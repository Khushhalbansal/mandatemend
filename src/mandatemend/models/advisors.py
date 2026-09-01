"""Advisor protocols + heuristic (baseline) and trained implementations.

The heuristic advisors are a real, defensible baseline (domain rules), not stubs. The
trained `SurvivalRetryAdvisor` / `TLearnerUpliftAdvisor` must *beat* them on the frozen
batch for the ML work to be worth keeping (CLAUDE.md §8 "evaluated against a naive baseline").

`advise(...)` takes optional round-awareness hints (`tried_delays`, `tried`) so the agent can
walk down the ranking across successive rounds instead of repeating one recommendation.
Advisors stay stateless; the agent owns the "already tried" sets.
"""

from __future__ import annotations

from typing import Protocol

from mandatemend.schemas import (
    FailureCause,
    FailureEvent,
    InterventionAdvice,
    InterventionType,
    RetryTimingAdvice,
    TypedDiagnosis,
)
from mandatemend.simulation import DELAY_BUCKETS_H

_EMPTY_DELAYS: frozenset[float] = frozenset()
_EMPTY_ARMS: frozenset[InterventionType] = frozenset()


class RetryAdvisor(Protocol):
    def advise(
        self, event: FailureEvent, diag: TypedDiagnosis, *, tried_delays: frozenset[float] = ...
    ) -> RetryTimingAdvice: ...


class InterventionAdvisor(Protocol):
    def advise(
        self,
        event: FailureEvent,
        diag: TypedDiagnosis,
        *,
        tried: frozenset[InterventionType] = ...,
    ) -> InterventionAdvice: ...


# --------------------------------------------------------------------------- heuristic
class HeuristicRetryAdvisor:
    """Domain-rule retry timing. Rough proxy for 'retry near payday / after downtime'."""

    model_source = "heuristic"

    def advise(
        self,
        event: FailureEvent,
        diag: TypedDiagnosis,
        *,
        tried_delays: frozenset[float] = _EMPTY_DELAYS,
    ) -> RetryTimingAdvice:
        c = diag.cause
        default = {
            FailureCause.BANK_DOWNTIME: (72.0, 0.6),
            FailureCause.INSUFFICIENT_FUNDS: (72.0, 0.4),
            FailureCause.SUSPECTED_CHURN: (72.0, 0.35),
            FailureCause.TECH_DECLINE: (6.0, 0.55),
            FailureCause.LIMIT_EXCEEDED: (24.0, 0.1),
        }.get(c, (48.0, 0.3))
        delay, p = default
        if delay in tried_delays:
            # step to the next untried bucket further out
            for d in DELAY_BUCKETS_H:
                if d > delay and d not in tried_delays:
                    delay, p = d, p * 0.8
                    break
        return RetryTimingAdvice(delay_hours=delay, p_success=p, model_source=self.model_source)


class HeuristicInterventionAdvisor:
    """Domain-rule intervention choice (the 'obvious' mapping)."""

    model_source = "heuristic"

    _TABLE: dict[FailureCause, tuple[InterventionType, float]] = {
        FailureCause.INSUFFICIENT_FUNDS: (InterventionType.WHATSAPP_UPI_LINK, 0.45),
        FailureCause.SUSPECTED_CHURN: (InterventionType.WHATSAPP_UPI_LINK, 0.2),
        FailureCause.BANK_DOWNTIME: (InterventionType.RETRY_ONLY, 0.55),
        FailureCause.TECH_DECLINE: (InterventionType.RETRY_ONLY, 0.55),
        FailureCause.LIMIT_EXCEEDED: (InterventionType.PARTIAL_CHARGE, 0.55),
        FailureCause.MANDATE_PAUSED: (InterventionType.WHATSAPP_UPI_LINK, 0.4),
        FailureCause.MANDATE_EXPIRED: (InterventionType.WHATSAPP_UPI_LINK, 0.4),
        FailureCause.UNKNOWN: (InterventionType.NO_OP, 0.05),
    }
    _FALLBACK_ORDER = (
        InterventionType.RETRY_ONLY,
        InterventionType.WHATSAPP_UPI_LINK,
        InterventionType.METHOD_SWITCH,
        InterventionType.PARTIAL_CHARGE,
        InterventionType.SMS_REMINDER,
        InterventionType.GRACE_48H,
    )

    def advise(
        self,
        event: FailureEvent,
        diag: TypedDiagnosis,
        *,
        tried: frozenset[InterventionType] = _EMPTY_ARMS,
    ) -> InterventionAdvice:
        interv, p = self._TABLE.get(diag.cause, (InterventionType.RETRY_ONLY, 0.3))
        order = [interv, *[x for x in self._FALLBACK_ORDER if x != interv]]
        chosen = next((x for x in order if x not in tried), InterventionType.NO_OP)
        pr = p if chosen is interv else 0.25
        return InterventionAdvice(
            intervention=chosen,
            uplift=max(0.0, pr - 0.06),
            p_recover=pr,
            ranked=[(x, 0.3) for x in order if x not in tried] or [(InterventionType.NO_OP, 0.0)],
            model_source=self.model_source,
        )


# --------------------------------------------------------------------------- trained
class SurvivalRetryAdvisor:
    """Trained discrete-time hazard model: picks the delay bucket with the highest P(success)."""

    model_source = "survival"

    def __init__(self, model=None):  # model: RetryTimingModel
        from mandatemend.models.retry_timing import RetryTimingModel

        self.model = model or RetryTimingModel.load()
        self._curve_cache: tuple[str, list[tuple[float, float]]] | None = None
        self._warm: dict[str, list[tuple[float, float]]] = {}

    def warm(self, rows: list[tuple[FailureEvent, TypedDiagnosis]]) -> None:
        """Batch-precompute every mandate's hazard curve in one model call (big speedup for
        a whole-batch run — HistGBM's per-call overhead dominates otherwise)."""
        for (ev, _dg), curve in zip(rows, self.model.curve_many(rows), strict=True):
            self._warm[ev.mandate_id] = curve

    def advise(
        self,
        event: FailureEvent,
        diag: TypedDiagnosis,
        *,
        tried_delays: frozenset[float] = _EMPTY_DELAYS,
    ) -> RetryTimingAdvice:
        # The hazard curve depends only on (event, diag), which are fixed for a mandate across
        # the recovery loop's rounds: use the warm batch cache, else a 1-entry memo.
        curve = self._warm.get(event.mandate_id)
        if curve is None:
            if self._curve_cache is None or self._curve_cache[0] != event.mandate_id:
                self._curve_cache = (event.mandate_id, self.model.curve(event, diag))
            curve = self._curve_cache[1]
        avail = [(d, p) for d, p in curve if d not in tried_delays] or curve
        d, p = max(avail, key=lambda t: t[1])
        return RetryTimingAdvice(delay_hours=d, p_success=p, model_source=self.model_source)


class TLearnerUpliftAdvisor:
    """Trained IPW T-learner: ranks intervention arms by causal uplift vs the NO_OP control."""

    model_source = "t-learner"

    def __init__(self, model=None):  # model: UpliftModel
        from mandatemend.models.uplift import UpliftModel

        self.model = model or UpliftModel.load()
        self._rank_cache: tuple[str, list] | None = None
        self._warm: dict[str, list] = {}

    def warm(self, rows: list[tuple[FailureEvent, TypedDiagnosis]]) -> None:
        """Batch-precompute every mandate's arm ranking in |arms| model calls total."""
        for (ev, _dg), ranked in zip(rows, self.model.rank_many(rows), strict=True):
            self._warm[ev.mandate_id] = ranked

    def advise(
        self,
        event: FailureEvent,
        diag: TypedDiagnosis,
        *,
        tried: frozenset[InterventionType] = _EMPTY_ARMS,
    ) -> InterventionAdvice:
        # The arm ranking is fixed per mandate; use the warm batch cache, else a 1-entry memo.
        ranked = self._warm.get(event.mandate_id)
        if ranked is None:
            if self._rank_cache is None or self._rank_cache[0] != event.mandate_id:
                self._rank_cache = (event.mandate_id, self.model.rank(event, diag))
            ranked = self._rank_cache[1]  # [(arm, p_recover, uplift)] desc by uplift
        avail = [t for t in ranked if t[0] not in tried] or ranked
        top_arm, top_p, top_uplift = avail[0]
        return InterventionAdvice(
            intervention=top_arm,
            uplift=top_uplift,
            p_recover=top_p,
            ranked=[(arm, uplift) for arm, _p, uplift in avail],
            model_source=self.model_source,
        )
