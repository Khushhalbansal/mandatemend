"""The REQUEST_REAUTH recovery path (E1/E2): a paused/expired mandate is recovered through
a re-authorization request when the gateway has a realized re-auth outcome, and every
compliance invariant still holds.
"""

import json

import pytest

from mandatemend.agent import Agent
from mandatemend.audit import ledger
from mandatemend.batch.run_batch import _load_frozen, run
from mandatemend.config import settings
from mandatemend.db.session import init_engine
from mandatemend.executor.gateway import SimulatedGateway
from mandatemend.invariants import check_resolution
from mandatemend.schemas import ActionType, MandateState
from tests.conftest import make_event

pytestmark = pytest.mark.integration


def _agent(labels, reauth):
    init_engine("sqlite://", create=True)
    ledger.reset_cache()
    return Agent.default(
        gateway=SimulatedGateway(labels, reauth_outcomes=reauth), audit_enabled=False
    )


def test_paused_mandate_recovers_via_reauth_when_the_customer_re_approves():
    ev = make_event(mandate_state=MandateState.PAUSED, err_code="UMN_PAUSED")
    reauth = {ev.mandate_id: {"success": True, "amount_paise": ev.amount_paise, "p": 0.7}}
    res = _agent({}, reauth).recover(ev)
    assert res.recovered
    assert any(s.action.action_type is ActionType.REQUEST_REAUTH for s in res.timeline)
    # no charge was ever attempted on the dead mandate, and no invariant is broken
    assert not any(
        s.action.action_type in (ActionType.RETRY, ActionType.PARTIAL_CHARGE)
        for s in res.timeline
    )
    assert check_resolution(ev, res) == []


def test_paused_mandate_without_a_reauth_outcome_falls_back_and_stays_compliant():
    ev = make_event(mandate_state=MandateState.EXPIRED, err_code="UMN_EXPIRED")
    res = _agent({}, {}).recover(ev)  # no realized re-auth outcome
    # re-auth was tried, then the loop fell back to a collect link; still terminates cleanly
    assert res.recovered or res.escalated_to_human
    assert check_resolution(ev, res) == []


def test_v2_reauth_supplement_is_only_for_dead_mandates_and_lifts_their_recovery():
    p = settings.heldout_reauth_v2
    if not p.exists():
        pytest.skip("run `python data/generator.py --freeze-reauth-v2`")
    reauth = json.loads(p.read_text(encoding="utf-8"))["reauth"]
    events, labels = _load_frozen("v2")
    dead_ids = {
        e.mandate_id for e in events if e.mandate_state in (MandateState.PAUSED, MandateState.EXPIRED)
    }
    assert set(reauth) <= dead_ids, "re-auth outcomes must exist only for paused/expired mandates"

    sc = run(iteration=-1, note="pytest v2 reauth", batch="v2")
    assert "+reauth" in sc.note
    assert sc.compliance_violations == 0
    dead = {c["cause"]: c for c in sc.per_cause if c["cause"].startswith("MANDATE_")}
    # with the re-auth path the dead-mandate buckets recover materially better than the
    # ~0.22-0.34 they sit at without it
    assert dead["MANDATE_PAUSED"]["rate"] >= 0.42
    assert dead["MANDATE_EXPIRED"]["rate"] >= 0.36
