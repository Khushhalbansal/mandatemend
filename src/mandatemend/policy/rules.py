"""Individual hard-rule predicates.

Each function is small and independently unit-tested (CLAUDE.md §8). They are pure: given
inputs, return a `RuleEvaluation`. The engine composes them; the invariant checker
(`mandatemend.invariants`) re-verifies the *outcome* independently so the engine can never
mark its own compliance homework (CLAUDE.md §1.3/§3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from mandatemend.config import settings
from mandatemend.schemas import (
    ActionType,
    FailureCause,
    FailureEvent,
    MandateState,
    RuleEvaluation,
    TypedDiagnosis,
)

CHARGING_ACTIONS = frozenset({ActionType.RETRY, ActionType.PARTIAL_CHARGE})
# Every action that puts an outbound message in front of the customer counts against the
# weekly contact cap and the quiet-hours rule — not just SEND_NOTIFICATION. `invariants.py`
# counts them the same way, so the engine must too (this mismatch caused the iteration-0
# CONTACT_FREQUENCY violations). REQUEST_REAUTH is an outbound contact (a re-authorization
# request link), so it is in here — but it is NOT a charge, so it never touches the NPCI
# retry budget.
CONTACT_ACTIONS = frozenset(
    {
        ActionType.SEND_NOTIFICATION,
        ActionType.OFFER_ALTERNATE_METHOD,
        ActionType.REQUEST_REAUTH,
    }
)
NON_CHARGING_LOOP_ACTIONS = frozenset(
    {
        ActionType.SEND_NOTIFICATION,
        ActionType.OFFER_ALTERNATE_METHOD,
        ActionType.REQUEST_REAUTH,
        ActionType.GRACE_EXTEND,
        ActionType.NO_ACTION,
    }
)
DEAD_MANDATE_STATES = frozenset({MandateState.PAUSED, MandateState.EXPIRED, MandateState.REVOKED})
DEAD_CAUSES = frozenset({FailureCause.MANDATE_PAUSED, FailureCause.MANDATE_EXPIRED})


@dataclass
class LoopState:
    """Mutable per-mandate state the engine reads each round. Owned by the agent loop."""

    now: datetime
    round_no: int = 0
    retries_used: int = 0
    contacts_this_week: int = 0
    consecutive_hard_declines: int = 0
    grace_used: bool = False
    last_notice_at: datetime | None = None
    escalated: bool = False
    trace: list[RuleEvaluation] = field(default_factory=list)


def rule_confidence_gate(diag: TypedDiagnosis) -> RuleEvaluation:
    ok = diag.confidence >= settings.low_confidence_threshold
    return RuleEvaluation(
        rule="confidence_gate",
        passed=ok,
        detail=f"confidence={diag.confidence:.2f} vs threshold {settings.low_confidence_threshold}",
    )


def rule_mandate_live_for_charge(event: FailureEvent, diag: TypedDiagnosis) -> RuleEvaluation:
    dead = event.mandate_state in DEAD_MANDATE_STATES or diag.cause in DEAD_CAUSES
    return RuleEvaluation(
        rule="mandate_live_for_charge",
        passed=not dead,
        detail=f"mandate_state={event.mandate_state}, cause={diag.cause}",
    )


def rule_npci_retry_cap(state: LoopState) -> RuleEvaluation:
    ok = state.retries_used < settings.npci_max_retries
    return RuleEvaluation(
        rule="npci_retry_cap",
        passed=ok,
        detail=f"retries_used={state.retries_used} / cap {settings.npci_max_retries}",
    )


def rule_predebit_notice(state: LoopState, scheduled_at: datetime) -> RuleEvaluation:
    """A charging action needs a notice >= 24h before the scheduled debit."""
    if state.last_notice_at is None:
        return RuleEvaluation(
            rule="predebit_notice_24h", passed=False, detail="no pre-debit notice sent yet"
        )
    gap = scheduled_at - state.last_notice_at
    ok = gap >= timedelta(hours=settings.predebit_notice_hours)
    return RuleEvaluation(
        rule="predebit_notice_24h",
        passed=ok,
        detail=f"notice->debit gap = {gap.total_seconds() / 3600:.1f}h "
        f"(need >= {settings.predebit_notice_hours}h)",
    )


def rule_quiet_hours(scheduled_at: datetime) -> RuleEvaluation:
    """Outbound contact must not land in [quiet_start, quiet_end) local time."""
    hour = scheduled_at.hour
    qs, qe = settings.quiet_hours_start, settings.quiet_hours_end
    in_quiet = hour >= qs or hour < qe
    return RuleEvaluation(
        rule="quiet_hours",
        passed=not in_quiet,
        detail=f"scheduled hour={hour}, quiet window [{qs},{qe})",
    )


def rule_contact_frequency(state: LoopState) -> RuleEvaluation:
    ok = state.contacts_this_week < settings.max_contacts_per_week
    return RuleEvaluation(
        rule="contact_frequency",
        passed=ok,
        detail=f"contacts_this_week={state.contacts_this_week} / cap {settings.max_contacts_per_week}",
    )


def rule_outreach_economics(p_recover: float, amount_at_risk_paise: int) -> RuleEvaluation:
    expected = p_recover * amount_at_risk_paise
    floor = settings.outreach_cost_paise * settings.min_expected_value_ratio
    ok = expected >= floor
    return RuleEvaluation(
        rule="outreach_economics",
        passed=ok,
        detail=f"E[recovery]={expected:.0f}p vs floor {floor:.0f}p "
        f"(p_recover={p_recover:.2f}, at_risk={amount_at_risk_paise}p)",
    )


def rule_stopping(state: LoopState) -> RuleEvaluation:
    """Escalate once the NPCI retry budget is spent with in-session declines, or on a run of
    in-session hard declines that already equals the budget. Pre-session failure history is
    NOT counted here — it feeds the diagnosis/uplift models, not the stop decision — so the
    agent always gets to spend its retry budget before this rule bites."""
    limit = settings.npci_max_retries
    ok = state.consecutive_hard_declines < limit
    return RuleEvaluation(
        rule="stopping_rule",
        passed=ok,
        detail=f"in-session consecutive_hard_declines={state.consecutive_hard_declines} "
        f"(stop at {limit})",
    )


def rule_amount_within_cap(amount_paise: int, event: FailureEvent) -> RuleEvaluation:
    ok = amount_paise <= event.mandate_max_amount_paise
    return RuleEvaluation(
        rule="amount_within_cap",
        passed=ok,
        detail=f"amount={amount_paise}p vs mandate cap {event.mandate_max_amount_paise}p",
    )


def clamp_out_of_quiet(scheduled_at: datetime) -> datetime:
    """Push a timestamp forward to the next 08:00 if it falls in quiet hours."""
    qs, qe = settings.quiet_hours_start, settings.quiet_hours_end
    dt = scheduled_at
    if dt.hour >= qs:
        dt = (dt + timedelta(days=1)).replace(hour=qe, minute=0, second=0, microsecond=0)
    elif dt.hour < qe:
        dt = dt.replace(hour=qe, minute=0, second=0, microsecond=0)
    return dt
