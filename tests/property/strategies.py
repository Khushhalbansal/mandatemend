"""Hypothesis strategies for the MandateMend domain types.

Kept deliberately wide: the point is that the policy engine's invariants hold for *any*
well-typed input, including combinations the generator would never produce.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import strategies as st

from mandatemend.policy.rules import LoopState
from mandatemend.schemas import (
    FailureCause,
    FailureEvent,
    InterventionAdvice,
    InterventionType,
    MandateHistory,
    MandateState,
    PaymentMethod,
    RetryTimingAdvice,
    TypedDiagnosis,
)
from mandatemend.simulation import ISSUERS

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
_paise = st.integers(min_value=100, max_value=15_000_00)
_small = st.integers(min_value=0, max_value=20)


@st.composite
def datetimes(draw, *, lo_h: int = -240, hi_h: int = 240) -> datetime:
    return _EPOCH + timedelta(hours=draw(st.integers(min_value=lo_h, max_value=hi_h)))


histories = st.builds(
    MandateHistory,
    prior_attempts=_small,
    prior_successes=_small,
    prior_hard_declines=_small,
    consecutive_failures=_small,
    days_since_last_success=st.one_of(st.none(), st.integers(min_value=0, max_value=400)),
    contacts_this_week=st.integers(min_value=0, max_value=8),
    grace_used=st.booleans(),
    tenure_months=st.integers(min_value=0, max_value=60),
)


@st.composite
def failure_events(draw) -> FailureEvent:
    amount = draw(_paise)
    cap = draw(st.integers(min_value=100, max_value=15_000_00))
    return FailureEvent(
        mandate_id="mnd_" + draw(st.text("abcdef0123456789", min_size=6, max_size=12)),
        customer_id="cust_" + draw(st.text("abcdef0123456789", min_size=6, max_size=12)),
        method=draw(st.sampled_from(list(PaymentMethod))),
        issuer=draw(st.sampled_from([*ISSUERS, "OTHR"])),
        amount_paise=amount,
        err_code=draw(st.sampled_from(["U30", "U69", "U67", "U91", "UMN_PAUSED", "ZZZ", "BT"])),
        raw_err_text=draw(st.text(max_size=300)),
        occurred_at=draw(datetimes()),
        attempt_no=draw(st.integers(min_value=0, max_value=5)),
        mandate_state=draw(st.sampled_from(list(MandateState))),
        mandate_valid_until=draw(st.one_of(st.none(), datetimes(lo_h=-1000, hi_h=10000))),
        mandate_max_amount_paise=cap,
        history=draw(histories),
    )


diagnoses = st.builds(
    TypedDiagnosis,
    cause=st.sampled_from(list(FailureCause)),
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    rationale=st.text(min_size=1, max_size=200).filter(lambda s: s.strip() != ""),
    source=st.sampled_from(["heuristic", "llm:test", "oracle"]),
    injection_flagged=st.booleans(),
)

retry_advice = st.builds(
    RetryTimingAdvice,
    delay_hours=st.floats(min_value=0.0, max_value=336.0, allow_nan=False),
    p_success=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    model_source=st.just("hypothesis"),
)


@st.composite
def intervention_advice(draw) -> InterventionAdvice:
    arm = draw(st.sampled_from(list(InterventionType)))
    p = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    return InterventionAdvice(
        intervention=arm,
        uplift=draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False)),
        p_recover=p,
        ranked=[(arm, p)],
        model_source="hypothesis",
    )


@st.composite
def loop_states(draw) -> LoopState:
    now = draw(datetimes())
    return LoopState(
        now=now,
        round_no=draw(st.integers(min_value=0, max_value=9)),
        retries_used=draw(st.integers(min_value=0, max_value=5)),
        contacts_this_week=draw(st.integers(min_value=0, max_value=8)),
        consecutive_hard_declines=draw(st.integers(min_value=0, max_value=5)),
        grace_used=draw(st.booleans()),
        last_notice_at=draw(st.one_of(st.none(), datetimes(lo_h=-400, hi_h=0))),
    )
