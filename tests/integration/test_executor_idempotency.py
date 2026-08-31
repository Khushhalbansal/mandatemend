"""Exactly-once execution under concurrent webhooks (CLAUDE.md §8 DoD, §5 adversarial pass).

The guarantee comes from the DB UNIQUE constraint on executed_action.idempotency_key, not
from application logic.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from mandatemend.db.models import ExecutedAction
from mandatemend.db.session import session_scope
from mandatemend.executor.executor import Executor
from mandatemend.schemas import Action, ActionType, RuleEvaluation, TypedDiagnosis
from tests.conftest import make_event

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _diag():
    from mandatemend.schemas import FailureCause

    return TypedDiagnosis(cause=FailureCause.TECH_DECLINE, confidence=0.9, rationale="x", source="t")


def _action(key="mnd_test_0001|r0|RETRY|20260902T12"):
    return Action(
        action_type=ActionType.RETRY,
        mandate_id="mnd_test_0001",
        idempotency_key=key,
        scheduled_at=NOW,
        amount_paise=49900,
        retry_delay_bucket=24.0,
        reason="retry",
        rule_trace=[RuleEvaluation(rule="x", passed=True)],
        policy_version="p",
        diagnosis=_diag(),
    )


class _AlwaysOKGateway:
    name = "test-ok"

    def attempt(self, action, event):
        return True, action.amount_paise, "ok"


class _RaisingGateway:
    name = "test-raise"

    def attempt(self, action, event):
        raise RuntimeError("gateway exploded mid-flight")


def test_duplicate_webhook_executes_once(db):
    ex = Executor(_AlwaysOKGateway())
    ev = make_event()
    act = _action()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: ex.execute(act, ev), range(8)))

    executed = [r for r in results if r.executed and not r.dedup_hit]
    dedup = [r for r in results if r.dedup_hit]
    assert len(executed) == 1
    assert len(dedup) == 7

    with session_scope() as s:
        rows = s.query(ExecutedAction).filter_by(idempotency_key=act.idempotency_key).all()
        assert len(rows) == 1  # DB UNIQUE held


def test_gateway_crash_leaves_action_reserved_not_retried(db):
    ex = Executor(_RaisingGateway())
    ev = make_event()
    act = _action(key="mnd_test_0001|r0|RETRY|crashcase")

    r1 = ex.execute(act, ev)
    assert r1.executed is True and r1.gateway_success is False

    # a re-fire of the same key must NOT run the gateway again (no double charge)
    r2 = ex.execute(act, ev)
    assert r2.dedup_hit is True

    with session_scope() as s:
        rows = s.query(ExecutedAction).filter_by(idempotency_key=act.idempotency_key).all()
        assert len(rows) == 1


def test_no_action_writes_no_executed_row(db):
    ex = Executor(_AlwaysOKGateway())
    act = _action().model_copy(update={"action_type": ActionType.NO_ACTION, "amount_paise": None})
    r = ex.execute(act, make_event())
    assert r.executed is False and r.dedup_hit is False
    with session_scope() as s:
        assert s.query(ExecutedAction).count() == 0
