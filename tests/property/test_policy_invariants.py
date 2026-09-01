"""Property-based proof that `PolicyEngine.decide` upholds the safety invariants for ANY
well-typed input — see docs/INVARIANTS.md. Hundreds of adversarial cases per property.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from hypothesis import given
from hypothesis import settings as hy_settings
from hypothesis import strategies as st

from mandatemend.config import settings
from mandatemend.policy.engine import PolicyEngine
from mandatemend.policy.rules import CHARGING_ACTIONS, DEAD_CAUSES, DEAD_MANDATE_STATES
from mandatemend.schemas import ActionType, FailureCause, TypedDiagnosis
from tests.property.strategies import (
    diagnoses,
    failure_events,
    intervention_advice,
    loop_states,
    retry_advice,
)

pytestmark = pytest.mark.property
ENGINE = PolicyEngine()
CASE = hy_settings(max_examples=150, deadline=None)

_decide = st.tuples(
    failure_events(), diagnoses, retry_advice, intervention_advice(), loop_states()
)


def _act(t):
    ev, dg, ra, ia, ls = t
    return ev, dg, ls, ENGINE.decide(ev, dg, ra, ia, ls)


@CASE
@given(_decide)
def test_always_returns_an_action_with_a_trace(t):
    _ev, _dg, _ls, a = _act(t)
    assert a.action_type in ActionType
    assert a.rule_trace, "I8: every Action carries a non-empty rule_trace"
    assert a.policy_version


@CASE
@given(_decide)
def test_low_confidence_never_moves_money(t):
    _ev, dg, _ls, a = _act(t)
    if dg.confidence < settings.low_confidence_threshold:
        assert a.action_type is ActionType.NO_ACTION  # I7
        assert a.requires_human is True


@CASE
@given(_decide)
def test_dead_mandate_is_never_charged(t):
    ev, dg, _ls, a = _act(t)
    if ev.mandate_state in DEAD_MANDATE_STATES or dg.cause in DEAD_CAUSES:
        assert a.action_type not in CHARGING_ACTIONS  # I3


@CASE
@given(_decide)
def test_npci_retry_cap_is_never_exceeded(t):
    _ev, _dg, ls, a = _act(t)
    if ls.retries_used >= settings.npci_max_retries:
        assert a.action_type not in CHARGING_ACTIONS  # I1


@CASE
@given(_decide)
def test_a_charge_stays_within_the_per_txn_cap(t):
    ev, _dg, _ls, a = _act(t)
    if a.action_type in CHARGING_ACTIONS:
        assert a.amount_paise is not None
        assert a.amount_paise <= ev.mandate_max_amount_paise  # I6


@CASE
@given(_decide)
def test_a_charge_implies_a_24h_predebit_notice_on_file(t):
    _ev, _dg, ls, a = _act(t)
    if a.action_type in CHARGING_ACTIONS:
        assert ls.last_notice_at is not None  # I2
        gap = a.scheduled_at - ls.last_notice_at
        assert gap >= timedelta(hours=settings.predebit_notice_hours)


@CASE
@given(_decide)
def test_a_notification_is_never_scheduled_in_quiet_hours(t):
    _ev, _dg, _ls, a = _act(t)
    if a.action_type is ActionType.SEND_NOTIFICATION:
        h = a.scheduled_at.hour  # I4
        assert not (h >= settings.quiet_hours_start or h < settings.quiet_hours_end)


@CASE
@given(_decide)
def test_two_in_session_hard_declines_at_budget_forces_escalation(t):
    _ev, dg, ls, a = _act(t)
    if dg.confidence >= settings.low_confidence_threshold and (
        ls.consecutive_hard_declines >= settings.npci_max_retries
    ):
        assert a.action_type is ActionType.STOP_AND_ESCALATE


class _Boom:
    """An advice object whose every attribute access raises — the engine must fail closed."""

    def __getattr__(self, _name):
        raise RuntimeError("boom")


# Diagnoses / loop-states guaranteed past the confidence + stopping gates, so the engine
# actually reaches (and chokes on) the hostile advice object.
_confident_diag = st.builds(
    TypedDiagnosis,
    cause=st.sampled_from(list(FailureCause)),
    confidence=st.floats(min_value=settings.low_confidence_threshold, max_value=1.0),
    rationale=st.just("x"),
    source=st.just("test"),
    injection_flagged=st.booleans(),
)


@st.composite
def _below_budget_state(draw):
    ls = draw(loop_states())
    ls.consecutive_hard_declines = draw(st.integers(0, settings.npci_max_retries - 1))
    return ls


@CASE
@given(failure_events(), _confident_diag, retry_advice, _below_budget_state())
def test_engine_fails_closed_on_a_hostile_advice_object(ev, dg, ra, ls):
    a = ENGINE.decide(ev, dg, ra, _Boom(), ls)  # I12
    assert a.action_type is ActionType.NO_ACTION
    assert a.requires_human is True
    assert any(rt.rule == "engine_fail_closed" for rt in a.rule_trace)
