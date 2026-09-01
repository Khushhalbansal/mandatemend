"""Property-based proof over the WHOLE `Agent.recover` loop: for an arbitrary mandate, an
arbitrary (adversarial) diagnoser, arbitrary advisors, and an arbitrary gateway outcome
script, every compliance invariant still holds over the full timeline and the loop always
terminates RECOVERED or ESCALATED. See docs/INVARIANTS.md (I1-I11).
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import settings as hy_settings
from hypothesis import strategies as st

from mandatemend.agent import _MAX_ROUNDS, Agent
from mandatemend.audit import ledger
from mandatemend.config import settings
from mandatemend.db.session import init_engine
from mandatemend.executor.executor import Executor
from mandatemend.invariants import check_resolution
from mandatemend.policy.engine import PolicyEngine
from mandatemend.schemas import Action, ActionType, FailureEvent
from tests.property.strategies import (
    diagnoses,
    failure_events,
    intervention_advice,
    retry_advice,
)

pytestmark = pytest.mark.property
CASE = hy_settings(max_examples=150, deadline=None)


class _ScriptedDiagnoser:
    def __init__(self, diag):
        self._diag = diag

    def diagnose(self, _event):
        return self._diag


class _ScriptedRetryAdvisor:
    def __init__(self, adv):
        self._adv = adv

    def advise(self, _e, _d, *, tried_delays=frozenset()):  # noqa: ARG002
        return self._adv


class _ScriptedInterventionAdvisor:
    def __init__(self, seq):
        self._seq = seq

    def advise(self, _e, _d, *, tried=frozenset()):  # noqa: ARG002
        return self._seq


def _outcome_key(action: Action) -> str:
    return f"{action.action_type.value}:{int(action.retry_delay_bucket or 0)}:{action.channel or ''}"


class _CoinGateway:
    """Returns a drawn boolean per (action_type, delay-bucket, channel) key; stable per run."""

    name = "coin"

    def __init__(self, outcomes: dict[str, bool]):
        self._o = outcomes

    def attempt(self, action: Action, event: FailureEvent):
        if action.action_type in (ActionType.NO_ACTION, ActionType.STOP_AND_ESCALATE):
            return None, 0, "noop"
        ok = self._o.get(_outcome_key(action), False)
        return ok, (action.amount_paise or event.amount_paise) if ok else 0, _outcome_key(action)


_outcomes = st.dictionaries(
    st.builds(
        lambda a, d, c: f"{a}:{d}:{c}",
        st.sampled_from(
            ["RETRY", "PARTIAL_CHARGE", "SEND_NOTIFICATION", "GRACE_EXTEND", "OFFER_ALTERNATE_METHOD"]
        ),
        st.sampled_from([0, 6, 24, 48, 72, 120, 168]),
        st.sampled_from(["", "whatsapp", "sms"]),
    ),
    st.booleans(),
    max_size=25,
)


@CASE
@given(failure_events(), diagnoses, retry_advice, intervention_advice(), _outcomes)
def test_full_loop_never_violates_an_invariant(ev, dg, ra, ia, outcomes):
    init_engine("sqlite://", create=True)  # fresh in-memory DB per example
    ledger.reset_cache()
    agent = Agent(
        diagnoser=_ScriptedDiagnoser(dg),
        retry_advisor=_ScriptedRetryAdvisor(ra),
        intervention_advisor=_ScriptedInterventionAdvisor(ia),
        engine=PolicyEngine(),
        executor=Executor(_CoinGateway(outcomes)),
        audit_enabled=True,
    )

    res = agent.recover(ev)

    assert check_resolution(ev, res) == [], "compliance invariants I1-I8 over the timeline"
    assert res.retries_used <= settings.npci_max_retries  # I1
    assert res.recovered or res.escalated_to_human, "I10: never dropped"
    assert not (res.recovered and res.escalated_to_human)
    assert len(res.timeline) <= _MAX_ROUNDS, "loop terminates"
    ok, msg = ledger.verify_chain()
    assert ok, f"I9: {msg}"
