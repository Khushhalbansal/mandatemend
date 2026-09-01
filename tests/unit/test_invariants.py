"""Independent compliance checker — each violation branch fires on a crafted timeline."""

from datetime import UTC, datetime, timedelta

from mandatemend.invariants import check_resolution
from mandatemend.schemas import (
    Action,
    ActionType,
    ExecutionResult,
    MandateResolution,
    RuleEvaluation,
    TypedDiagnosis,
)
from tests.conftest import make_event

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _diag():
    from mandatemend.schemas import FailureCause

    return TypedDiagnosis(cause=FailureCause.INSUFFICIENT_FUNDS, confidence=0.9, rationale="x", source="t")


def _act(kind: ActionType, *, at: datetime, amount: int | None = None, channel: str | None = None) -> Action:
    return Action(
        action_type=kind,
        mandate_id="mnd_test_0001",
        idempotency_key=f"k-{kind.value}-{at:%Y%m%d%H%M%S}",
        scheduled_at=at,
        amount_paise=amount,
        channel=channel,
        reason="crafted",
        rule_trace=[RuleEvaluation(rule="x", passed=True)],
        policy_version="p",
        diagnosis=_diag(),
    )


def _res(*steps: ExecutionResult, contacts: int = 0) -> MandateResolution:
    return MandateResolution(
        mandate_id="mnd_test_0001",
        amount_at_risk_paise=49900,
        recovered=False,
        recovered_amount_paise=0,
        retries_used=sum(1 for s in steps if s.action.action_type is ActionType.RETRY),
        contacts_made=contacts,
        terminal_action=ActionType.STOP_AND_ESCALATE,
        escalated_to_human=True,
        timeline=list(steps),
    )


def _ok(a: Action, success: bool = False) -> ExecutionResult:
    return ExecutionResult(action=a, executed=True, gateway_success=success, recovered_amount_paise=0)


def test_clean_timeline_has_no_violations():
    ev = make_event()
    notice = _ok(_act(ActionType.SEND_NOTIFICATION, at=NOW, channel="whatsapp"))
    retry = _ok(_act(ActionType.RETRY, at=NOW + timedelta(hours=25), amount=ev.amount_paise))
    assert check_resolution(ev, _res(notice, retry, contacts=1)) == []


def test_npci_cap_violation():
    ev = make_event()
    notice = _ok(_act(ActionType.SEND_NOTIFICATION, at=NOW))
    retries = [
        _ok(_act(ActionType.RETRY, at=NOW + timedelta(hours=25 + i), amount=ev.amount_paise))
        for i in range(4)
    ]
    v = check_resolution(ev, _res(notice, *retries, contacts=1))
    assert any("NPCI_RETRY_CAP" in x for x in v)


def test_npci_cap_boundary_exactly_three_charges_is_ok():
    # exactly npci_max_retries (3) executed charges, each with a >=24h notice, is COMPLIANT —
    # the checker must not flag the boundary (guards `>` vs `>=` in invariants.py rule 1).
    ev = make_event()
    notice = _ok(_act(ActionType.SEND_NOTIFICATION, at=NOW))
    retries = [
        _ok(_act(ActionType.RETRY, at=NOW + timedelta(hours=25 + i), amount=ev.amount_paise))
        for i in range(3)
    ]
    v = check_resolution(ev, _res(notice, *retries, contacts=1))
    assert not any("NPCI_RETRY_CAP" in x for x in v), v


def test_amount_cap_boundary_charge_exactly_at_cap_is_ok():
    # a charge for exactly the per-txn mandate cap is COMPLIANT (guards `>` vs `>=` in
    # invariants.py rule 6).
    ev = make_event(amount_paise=150_000, mandate_max_amount_paise=150_000)
    notice = _ok(_act(ActionType.SEND_NOTIFICATION, at=NOW))
    at_cap = _ok(_act(ActionType.RETRY, at=NOW + timedelta(hours=25), amount=150_000))
    v = check_resolution(ev, _res(notice, at_cap, contacts=1))
    assert not any("AMOUNT_OVER_CAP" in x for x in v), v


def test_reauth_request_counts_as_a_contact_never_as_a_charge():
    ev = make_event()
    # 3 re-auth requests this session, weekly budget 3, none succeed -> compliant (it's a
    # contact, not a charge: no NPCI_RETRY_CAP, no PREDEBIT_NOTICE)
    reauths = [_ok(_act(ActionType.REQUEST_REAUTH, at=NOW.replace(hour=9 + i))) for i in range(3)]
    v = check_resolution(ev, _res(*reauths, contacts=3))
    assert v == [], v
    # a 4th pushes it over the contact cap
    reauths.append(_ok(_act(ActionType.REQUEST_REAUTH, at=NOW.replace(hour=13))))
    v2 = check_resolution(ev, _res(*reauths, contacts=4))
    assert any("CONTACT_FREQUENCY" in x for x in v2)
    assert not any("NPCI_RETRY_CAP" in x for x in v2)


def test_reauth_request_in_quiet_hours_is_a_violation():
    ev = make_event()
    late = _ok(_act(ActionType.REQUEST_REAUTH, at=NOW.replace(hour=23)))
    v = check_resolution(ev, _res(late, contacts=1))
    assert any("QUIET_HOURS" in x and "REQUEST_REAUTH" in x for x in v)


def test_predebit_notice_violation():
    ev = make_event()
    retry = _ok(_act(ActionType.RETRY, at=NOW, amount=ev.amount_paise))  # no notice at all
    v = check_resolution(ev, _res(retry))
    assert any("PREDEBIT_NOTICE" in x for x in v)


def test_quiet_hours_violation():
    ev = make_event()
    late = _ok(_act(ActionType.SEND_NOTIFICATION, at=NOW.replace(hour=23), channel="sms"))
    v = check_resolution(ev, _res(late, contacts=1))
    assert any("QUIET_HOURS" in x for x in v)


def test_dead_mandate_charge_violation():
    from mandatemend.schemas import MandateState

    ev = make_event(mandate_state=MandateState.PAUSED, err_code="UMN_PAUSED")
    notice = _ok(_act(ActionType.SEND_NOTIFICATION, at=NOW))
    retry = _ok(_act(ActionType.RETRY, at=NOW + timedelta(hours=25), amount=ev.amount_paise))
    v = check_resolution(ev, _res(notice, retry, contacts=1))
    assert any("DEAD_MANDATE_CHARGE" in x for x in v)


def test_amount_over_cap_violation():
    ev = make_event(amount_paise=200_000, mandate_max_amount_paise=150_000)
    notice = _ok(_act(ActionType.SEND_NOTIFICATION, at=NOW))
    over = _ok(_act(ActionType.RETRY, at=NOW + timedelta(hours=25), amount=200_000))
    v = check_resolution(ev, _res(notice, over, contacts=1))
    assert any("AMOUNT_OVER_CAP" in x for x in v)


def test_contact_frequency_violation():
    # agent makes 4 outbound contacts this session; weekly budget was 3 (history starts at 0)
    ev = make_event()
    contacts = [
        _ok(_act(ActionType.SEND_NOTIFICATION, at=NOW.replace(hour=9 + i))) for i in range(4)
    ]
    v = check_resolution(ev, _res(*contacts, contacts=4))
    assert any("CONTACT_FREQUENCY" in x for x in v)


def test_contact_frequency_ok_when_mandate_arrives_over_cap():
    # mandate already at 4 contacts this week when it arrives; agent adds none -> not a violation
    ev = make_event(history=make_event().history.model_copy(update={"contacts_this_week": 4}))
    v = check_resolution(ev, _res(contacts=4))
    assert not any("CONTACT_FREQUENCY" in x for x in v)
