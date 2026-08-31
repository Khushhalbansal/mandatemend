"""Policy engine: the invariants that protect money (CLAUDE.md §2/§8)."""

from datetime import UTC, datetime

from mandatemend.policy.engine import PolicyEngine
from mandatemend.policy.rules import LoopState
from mandatemend.schemas import (
    ActionType,
    FailureCause,
    InterventionAdvice,
    InterventionType,
    MandateState,
    RetryTimingAdvice,
    TypedDiagnosis,
)
from tests.conftest import make_event

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
ENGINE = PolicyEngine()


def _advice(interv=InterventionType.RETRY_ONLY, p=0.6):
    return (
        RetryTimingAdvice(delay_hours=24.0, p_success=0.6),
        InterventionAdvice(intervention=interv, uplift=0.2, p_recover=p, ranked=[(interv, p)]),
    )


def _diag(cause=FailureCause.INSUFFICIENT_FUNDS, conf=0.9):
    return TypedDiagnosis(cause=cause, confidence=conf, rationale="x", source="test")


def test_low_confidence_forces_no_action_and_human_queue():
    ra, ia = _advice()
    act = ENGINE.decide(make_event(), _diag(conf=0.2), ra, ia, LoopState(now=NOW))
    assert act.action_type is ActionType.NO_ACTION
    assert act.requires_human is True
    assert act.rule_trace  # never empty


def test_dead_mandate_never_charged():
    ra, ia = _advice(InterventionType.RETRY_ONLY)
    ev = make_event(mandate_state=MandateState.PAUSED, err_code="UMN_PAUSED")
    act = ENGINE.decide(ev, _diag(FailureCause.MANDATE_PAUSED), ra, ia, LoopState(now=NOW))
    assert act.action_type not in (ActionType.RETRY, ActionType.PARTIAL_CHARGE)


def test_npci_cap_blocks_a_4th_charge():
    ra, ia = _advice(InterventionType.RETRY_ONLY)
    st = LoopState(now=NOW, retries_used=3, last_notice_at=NOW.replace(hour=1))
    act = ENGINE.decide(make_event(), _diag(), ra, ia, st)
    assert act.action_type not in (ActionType.RETRY, ActionType.PARTIAL_CHARGE)


def test_first_retry_requires_a_pre_debit_notice_first():
    ra, ia = _advice(InterventionType.RETRY_ONLY)
    act = ENGINE.decide(make_event(), _diag(), ra, ia, LoopState(now=NOW, last_notice_at=None))
    # cannot go straight to a charge with no notice on file
    assert act.action_type is ActionType.SEND_NOTIFICATION
    assert any(rt.rule == "predebit_notice_24h" and not rt.passed for rt in act.rule_trace)


def test_offer_alternate_method_respects_contact_cap():
    ra, ia = _advice(InterventionType.METHOD_SWITCH)
    st = LoopState(now=NOW, contacts_this_week=3)
    act = ENGINE.decide(make_event(), _diag(FailureCause.BANK_DOWNTIME), ra, ia, st)
    assert act.action_type is ActionType.STOP_AND_ESCALATE


def test_limit_exceeded_amount_over_cap_downgrades_to_partial():
    ra, ia = _advice(InterventionType.RETRY_ONLY)
    ev = make_event(amount_paise=200_000, mandate_max_amount_paise=150_000, err_code="U67")
    st = LoopState(now=NOW, last_notice_at=NOW.replace(hour=1))
    act = ENGINE.decide(ev, _diag(FailureCause.LIMIT_EXCEEDED), ra, ia, st)
    assert act.action_type in (ActionType.PARTIAL_CHARGE, ActionType.OFFER_ALTERNATE_METHOD)
    if act.action_type is ActionType.PARTIAL_CHARGE:
        assert act.amount_paise <= ev.mandate_max_amount_paise


def test_every_action_carries_a_rule_trace():
    ra, ia = _advice()
    for cause in FailureCause:
        act = ENGINE.decide(make_event(), _diag(cause), ra, ia, LoopState(now=NOW))
        assert act.rule_trace, f"empty trace for {cause}"
        assert act.policy_version


def test_engine_fails_closed_on_bad_advice(monkeypatch):
    """A malformed advice object must not crash the loop; engine returns NO_ACTION + human."""
    ra = RetryTimingAdvice(delay_hours=24.0, p_success=0.5)

    class Boom:
        intervention = InterventionType.RETRY_ONLY

        def __getattr__(self, k):
            raise RuntimeError("boom")

    act = ENGINE.decide(make_event(), _diag(), ra, Boom(), LoopState(now=NOW))
    assert act.action_type is ActionType.NO_ACTION
    assert act.requires_human is True
    assert any(rt.rule == "engine_fail_closed" for rt in act.rule_trace)
