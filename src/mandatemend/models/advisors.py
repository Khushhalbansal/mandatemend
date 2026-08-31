"""Advisor protocols + heuristic (untrained) implementations.

The heuristic advisors are a real, defensible baseline (domain rules), not stubs. The
trained `SurvivalRetryAdvisor` / `TLearnerUpliftAdvisor` must *beat* them on the frozen
batch for the ML work to be worth keeping (CLAUDE.md §8 "evaluated against a naive baseline").
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


class RetryAdvisor(Protocol):
    def advise(self, event: FailureEvent, diag: TypedDiagnosis) -> RetryTimingAdvice: ...


class InterventionAdvisor(Protocol):
    def advise(self, event: FailureEvent, diag: TypedDiagnosis) -> InterventionAdvice: ...


class HeuristicRetryAdvisor:
    """Domain-rule retry timing. Rough proxy for 'retry near payday / after downtime'."""

    model_source = "heuristic"

    def advise(self, event: FailureEvent, diag: TypedDiagnosis) -> RetryTimingAdvice:
        c = diag.cause
        if c is FailureCause.BANK_DOWNTIME:
            return RetryTimingAdvice(delay_hours=72.0, p_success=0.6, model_source=self.model_source)
        if c in (FailureCause.INSUFFICIENT_FUNDS, FailureCause.SUSPECTED_CHURN):
            # No payday signal in the event -> aim ~3 days out, a common salary-cycle guess.
            return RetryTimingAdvice(delay_hours=72.0, p_success=0.4, model_source=self.model_source)
        if c is FailureCause.TECH_DECLINE:
            return RetryTimingAdvice(delay_hours=6.0, p_success=0.55, model_source=self.model_source)
        if c is FailureCause.LIMIT_EXCEEDED:
            return RetryTimingAdvice(delay_hours=24.0, p_success=0.1, model_source=self.model_source)
        return RetryTimingAdvice(delay_hours=48.0, p_success=0.3, model_source=self.model_source)


class HeuristicInterventionAdvisor:
    """Domain-rule intervention choice (the 'obvious' mapping)."""

    model_source = "heuristic"

    def advise(self, event: FailureEvent, diag: TypedDiagnosis) -> InterventionAdvice:
        c = diag.cause
        table: dict[FailureCause, tuple[InterventionType, float]] = {
            FailureCause.INSUFFICIENT_FUNDS: (InterventionType.WHATSAPP_UPI_LINK, 0.45),
            FailureCause.SUSPECTED_CHURN: (InterventionType.WHATSAPP_UPI_LINK, 0.2),
            FailureCause.BANK_DOWNTIME: (InterventionType.RETRY_ONLY, 0.55),
            FailureCause.TECH_DECLINE: (InterventionType.RETRY_ONLY, 0.55),
            FailureCause.LIMIT_EXCEEDED: (InterventionType.PARTIAL_CHARGE, 0.55),
            FailureCause.MANDATE_PAUSED: (InterventionType.WHATSAPP_UPI_LINK, 0.4),
            FailureCause.MANDATE_EXPIRED: (InterventionType.WHATSAPP_UPI_LINK, 0.4),
            FailureCause.UNKNOWN: (InterventionType.NO_OP, 0.05),
        }
        interv, p = table.get(c, (InterventionType.RETRY_ONLY, 0.3))
        return InterventionAdvice(
            intervention=interv,
            uplift=max(0.0, p - 0.06),
            p_recover=p,
            ranked=[(interv, p)],
            model_source=self.model_source,
        )
