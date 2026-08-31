from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mandatemend.audit import ledger
from mandatemend.db.session import init_engine
from mandatemend.schemas import (
    FailureEvent,
    MandateHistory,
    MandateState,
    PaymentMethod,
)


@pytest.fixture
def db(tmp_path):
    """Fresh SQLite DB per test + reset the audit chain cache."""
    url = f"sqlite:///{(tmp_path / 'test.sqlite').as_posix()}"
    init_engine(url, create=True)
    ledger.reset_cache()
    yield url


def make_event(**over) -> FailureEvent:
    base = dict(
        mandate_id="mnd_test_0001",
        customer_id="cust_test_0001",
        method=PaymentMethod.UPI_AUTOPAY,
        issuer="HDFC",
        amount_paise=49900,
        err_code="U30",
        raw_err_text="Account balance is insufficient.",
        occurred_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        attempt_no=0,
        mandate_state=MandateState.ACTIVE,
        mandate_valid_until=datetime(2027, 1, 1, tzinfo=UTC),
        mandate_max_amount_paise=1_500_000,
        history=MandateHistory(
            prior_attempts=6,
            prior_successes=5,
            prior_hard_declines=1,
            consecutive_failures=1,
            days_since_last_success=30,
            contacts_this_week=0,
            grace_used=False,
            tenure_months=6,
        ),
    )
    base.update(over)
    return FailureEvent(**base)
