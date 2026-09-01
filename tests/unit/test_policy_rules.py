"""Each hard-rule predicate, tested individually (CLAUDE.md §8)."""

from datetime import UTC, datetime, timedelta

import pytest

from mandatemend.config import settings
from mandatemend.policy import rules
from mandatemend.policy.rules import LoopState
from mandatemend.schemas import FailureCause, MandateState, TypedDiagnosis
from tests.conftest import make_event

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _diag(cause=FailureCause.INSUFFICIENT_FUNDS, conf=0.9):
    return TypedDiagnosis(cause=cause, confidence=conf, rationale="x", source="test")


def test_confidence_gate():
    assert rules.rule_confidence_gate(_diag(conf=0.9)).passed
    assert not rules.rule_confidence_gate(_diag(conf=settings.low_confidence_threshold - 0.01)).passed


@pytest.mark.parametrize(
    "state,cause,expect_pass",
    [
        (MandateState.ACTIVE, FailureCause.INSUFFICIENT_FUNDS, True),
        (MandateState.PAUSED, FailureCause.MANDATE_PAUSED, False),
        (MandateState.EXPIRED, FailureCause.MANDATE_EXPIRED, False),
        (MandateState.ACTIVE, FailureCause.MANDATE_PAUSED, False),  # cause alone kills it
    ],
)
def test_mandate_live_for_charge(state, cause, expect_pass):
    ev = make_event(mandate_state=state)
    assert rules.rule_mandate_live_for_charge(ev, _diag(cause)).passed is expect_pass


def test_npci_retry_cap():
    assert rules.rule_npci_retry_cap(LoopState(now=NOW, retries_used=2)).passed
    assert not rules.rule_npci_retry_cap(LoopState(now=NOW, retries_used=3)).passed


def test_predebit_notice_requires_24h_gap():
    st = LoopState(now=NOW, last_notice_at=None)
    assert not rules.rule_predebit_notice(st, NOW + timedelta(hours=48)).passed  # no notice at all

    st = LoopState(now=NOW, last_notice_at=NOW)
    assert not rules.rule_predebit_notice(st, NOW + timedelta(hours=23)).passed
    assert rules.rule_predebit_notice(st, NOW + timedelta(hours=25)).passed


def test_quiet_hours():
    assert rules.rule_quiet_hours(NOW.replace(hour=13)).passed
    assert not rules.rule_quiet_hours(NOW.replace(hour=22)).passed
    assert not rules.rule_quiet_hours(NOW.replace(hour=3)).passed


def test_contact_frequency():
    assert rules.rule_contact_frequency(LoopState(now=NOW, contacts_this_week=2)).passed
    assert not rules.rule_contact_frequency(LoopState(now=NOW, contacts_this_week=3)).passed


def test_outreach_economics():
    # E[recovery] = p * at_risk vs floor = outreach_cost * ratio
    assert rules.rule_outreach_economics(0.5, 100_000).passed
    assert not rules.rule_outreach_economics(0.0001, 100).passed


def test_stopping_rule_uses_retry_budget():
    limit = settings.npci_max_retries
    assert rules.rule_stopping(LoopState(now=NOW, consecutive_hard_declines=limit - 1)).passed
    assert not rules.rule_stopping(LoopState(now=NOW, consecutive_hard_declines=limit)).passed


def test_amount_within_cap():
    ev = make_event(amount_paise=200_000, mandate_max_amount_paise=150_000)
    assert not rules.rule_amount_within_cap(200_000, ev).passed
    assert rules.rule_amount_within_cap(90_000, ev).passed


def test_afa_exemption():
    ceiling = settings.afa_exemption_ceiling_paise
    assert rules.rule_afa_exemption(1_000_000, reauth_done=False).passed  # below ceiling
    assert rules.rule_afa_exemption(ceiling, reauth_done=False).passed  # exactly at ceiling is exempt
    assert not rules.rule_afa_exemption(ceiling + 1, reauth_done=False).passed  # over, no re-auth
    assert rules.rule_afa_exemption(ceiling + 1, reauth_done=True).passed  # over, but re-auth done


def test_clamp_out_of_quiet_pushes_to_0800():
    late = NOW.replace(hour=23)
    clamped = rules.clamp_out_of_quiet(late)
    assert clamped.hour == settings.quiet_hours_end
    assert clamped > late

    early = NOW.replace(hour=4)
    assert rules.clamp_out_of_quiet(early).hour == settings.quiet_hours_end


def test_deliberately_injected_violation_is_caught_by_the_rule():
    """A charge scheduled 1h after the only notice must FAIL the pre-debit rule."""
    st = LoopState(now=NOW, last_notice_at=NOW)
    ev = rules.rule_predebit_notice(st, NOW + timedelta(hours=1))
    assert ev.passed is False
    assert "24" in ev.detail
