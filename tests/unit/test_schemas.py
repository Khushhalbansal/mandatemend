import pytest
from pydantic import ValidationError

from mandatemend.schemas import (
    Action,
    ActionType,
    FailureCause,
    RuleEvaluation,
    TypedDiagnosis,
)
from tests.conftest import make_event

NOW = make_event().occurred_at


def _diag():
    return TypedDiagnosis(cause=FailureCause.TECH_DECLINE, confidence=0.8, rationale="x", source="t")


def test_action_requires_non_empty_rule_trace():
    with pytest.raises(ValidationError):
        Action(
            action_type=ActionType.RETRY,
            mandate_id="m1",
            idempotency_key="k" * 12,
            scheduled_at=NOW,
            reason="r",
            rule_trace=[],
            policy_version="p",
            diagnosis=_diag(),
        )


def test_action_ok_with_trace():
    a = Action(
        action_type=ActionType.NO_ACTION,
        mandate_id="m1",
        idempotency_key="k" * 12,
        scheduled_at=NOW,
        reason="r",
        rule_trace=[RuleEvaluation(rule="x", passed=True)],
        policy_version="p",
        diagnosis=_diag(),
    )
    assert a.rule_trace[0].rule == "x"


def test_failure_event_is_inr_only():
    with pytest.raises(ValidationError):
        make_event(currency="USD")


def test_failure_event_positive_amount():
    with pytest.raises(ValidationError):
        make_event(amount_paise=0)


def test_diagnosis_confidence_bounded():
    with pytest.raises(ValidationError):
        TypedDiagnosis(cause=FailureCause.UNKNOWN, confidence=1.5, rationale="x", source="t")
