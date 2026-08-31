"""Feature extraction shared by the retry-timing model and the uplift model.

One function, `feature_row`, so training and inference cannot drift. Output is an ordered
dict; `FEATURE_NAMES` is the canonical column order.
"""

from __future__ import annotations

from mandatemend.schemas import FailureCause, FailureEvent, PaymentMethod, TypedDiagnosis
from mandatemend.simulation import ISSUERS

_CAUSES = [c.value for c in FailureCause]

FEATURE_NAMES: list[str] = (
    [
        "amount_paise_log",
        "amount_to_cap_ratio",
        "attempt_no",
        "consecutive_failures",
        "prior_success_rate",
        "days_since_last_success",
        "tenure_months",
        "contacts_this_week",
        "grace_used",
        "is_upi_autopay",
        "hour_of_day",
        "day_of_month",
        "diag_confidence",
        "injection_flagged",
    ]
    + [f"issuer_{i}" for i in ISSUERS]
    + [f"cause_{c}" for c in _CAUSES]
)


def feature_row(event: FailureEvent, diag: TypedDiagnosis) -> dict[str, float]:
    import math

    h = event.history
    prior_rate = (h.prior_successes / h.prior_attempts) if h.prior_attempts else 0.0
    row: dict[str, float] = {
        "amount_paise_log": math.log10(max(event.amount_paise, 1)),
        "amount_to_cap_ratio": event.amount_paise / max(event.mandate_max_amount_paise, 1),
        "attempt_no": float(event.attempt_no),
        "consecutive_failures": float(h.consecutive_failures),
        "prior_success_rate": float(prior_rate),
        "days_since_last_success": float(h.days_since_last_success or 0),
        "tenure_months": float(h.tenure_months),
        "contacts_this_week": float(h.contacts_this_week),
        "grace_used": 1.0 if h.grace_used else 0.0,
        "is_upi_autopay": 1.0 if event.method is PaymentMethod.UPI_AUTOPAY else 0.0,
        "hour_of_day": float(event.occurred_at.hour),
        "day_of_month": float(event.occurred_at.day),
        "diag_confidence": float(diag.confidence),
        "injection_flagged": 1.0 if diag.injection_flagged else 0.0,
    }
    for i in ISSUERS:
        row[f"issuer_{i}"] = 1.0 if event.issuer == i else 0.0
    for c in _CAUSES:
        row[f"cause_{c}"] = 1.0 if diag.cause.value == c else 0.0
    return row


def feature_vector(event: FailureEvent, diag: TypedDiagnosis) -> list[float]:
    row = feature_row(event, diag)
    return [row[name] for name in FEATURE_NAMES]
