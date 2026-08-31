"""The typed contract every component speaks.

Design rules (CLAUDE.md §2, §6):
  * The LLM produces `TypedDiagnosis` and nothing else. It is schema-validated on the way in;
    anything out-of-schema -> caller falls back to NO_ACTION.
  * Only the policy engine constructs an `Action`. `Action` carries a full `rule_trace` so an
    operator can see *why* every money move happened.
  * Money is integer paise everywhere. No floats for currency.
"""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrEnum(str, enum.Enum):
    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


class PaymentMethod(StrEnum):
    UPI_AUTOPAY = "UPI_AUTOPAY"
    CARD_EMANDATE = "CARD_EMANDATE"


class MandateState(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class FailureCause(StrEnum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    BANK_DOWNTIME = "BANK_DOWNTIME"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    MANDATE_PAUSED = "MANDATE_PAUSED"
    MANDATE_EXPIRED = "MANDATE_EXPIRED"
    TECH_DECLINE = "TECH_DECLINE"
    SUSPECTED_CHURN = "SUSPECTED_CHURN"
    UNKNOWN = "UNKNOWN"


class InterventionType(StrEnum):
    """What the uplift model ranks. Advisory only — the policy engine may veto any of these."""

    NO_OP = "NO_OP"
    RETRY_ONLY = "RETRY_ONLY"
    WHATSAPP_UPI_LINK = "WHATSAPP_UPI_LINK"
    SMS_REMINDER = "SMS_REMINDER"
    GRACE_48H = "GRACE_48H"
    PARTIAL_CHARGE = "PARTIAL_CHARGE"
    METHOD_SWITCH = "METHOD_SWITCH"


class ActionType(StrEnum):
    """What the executor can physically do. Emitted only by the policy engine."""

    RETRY = "RETRY"
    SEND_NOTIFICATION = "SEND_NOTIFICATION"  # includes WhatsApp/SMS pre-debit notice
    OFFER_ALTERNATE_METHOD = "OFFER_ALTERNATE_METHOD"
    GRACE_EXTEND = "GRACE_EXTEND"
    PARTIAL_CHARGE = "PARTIAL_CHARGE"
    STOP_AND_ESCALATE = "STOP_AND_ESCALATE"
    NO_ACTION = "NO_ACTION"


# --------------------------------------------------------------------------------------
# Ingest
# --------------------------------------------------------------------------------------
class MandateHistory(BaseModel):
    """Compact history the diagnoser and models are allowed to see."""

    model_config = ConfigDict(frozen=True)

    prior_attempts: int = Field(ge=0)
    prior_successes: int = Field(ge=0)
    prior_hard_declines: int = Field(ge=0)
    consecutive_failures: int = Field(ge=0)
    days_since_last_success: int | None = Field(default=None, ge=0)
    contacts_this_week: int = Field(default=0, ge=0)
    grace_used: bool = False
    tenure_months: int = Field(ge=0)


class FailureEvent(BaseModel):
    """Canonical, normalized failure. Every ingestion path must produce exactly this."""

    model_config = ConfigDict(frozen=True)

    mandate_id: str = Field(min_length=1, max_length=64)
    customer_id: str = Field(min_length=1, max_length=64)
    method: PaymentMethod
    issuer: str = Field(min_length=1, max_length=32)  # e.g. HDFC, SBIN, ICIC, PYTM
    amount_paise: int = Field(gt=0)
    currency: str = "INR"
    err_code: str = Field(min_length=1, max_length=48)  # raw gateway/bank code
    raw_err_text: str = Field(default="", max_length=2000)  # UNTRUSTED free text (see sanitize.py)
    occurred_at: datetime
    attempt_no: int = Field(ge=0)  # 0 = original scheduled debit, 1..3 = retries
    mandate_state: MandateState
    mandate_valid_until: datetime | None = None
    mandate_max_amount_paise: int = Field(gt=0)
    history: MandateHistory

    @field_validator("issuer", "err_code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("currency")
    @classmethod
    def _inr_only(cls, v: str) -> str:
        if v != "INR":
            raise ValueError("MandateMend handles INR mandates only")
        return v


# --------------------------------------------------------------------------------------
# Diagnosis (LLM output — sandboxed, no authority)
# --------------------------------------------------------------------------------------
class TypedDiagnosis(BaseModel):
    model_config = ConfigDict(frozen=True)

    cause: FailureCause
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=600)
    source: str = Field(default="unknown")  # "llm:<model>" | "heuristic"
    injection_flagged: bool = False  # sanitizer tripped on the raw_err_text

    @field_validator("rationale")
    @classmethod
    def _no_control_chars(cls, v: str) -> str:
        return "".join(ch for ch in v if ch == "\n" or ch >= " ").strip()


# --------------------------------------------------------------------------------------
# Model advice (advisory only)
# --------------------------------------------------------------------------------------
class RetryTimingAdvice(BaseModel):
    model_config = ConfigDict(frozen=True)

    delay_hours: float = Field(ge=0.0, le=24 * 14)
    p_success: float = Field(ge=0.0, le=1.0)
    model_source: str = "survival"


class InterventionAdvice(BaseModel):
    model_config = ConfigDict(frozen=True)

    intervention: InterventionType
    uplift: float  # estimated P(recover | intervention) - P(recover | control)
    p_recover: float = Field(ge=0.0, le=1.0)
    ranked: list[tuple[InterventionType, float]] = Field(default_factory=list)
    model_source: str = "t-learner"


# --------------------------------------------------------------------------------------
# Policy output (the only executable thing)
# --------------------------------------------------------------------------------------
class RuleEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule: str
    passed: bool
    detail: str = ""


class Action(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_type: ActionType
    mandate_id: str
    idempotency_key: str = Field(min_length=8, max_length=128)
    scheduled_at: datetime
    amount_paise: int | None = Field(default=None, gt=0)  # set for RETRY / PARTIAL_CHARGE
    channel: str | None = None  # "whatsapp" | "sms" for SEND_NOTIFICATION
    alt_method: PaymentMethod | None = None
    reason: str = Field(min_length=1, max_length=400)
    rule_trace: list[RuleEvaluation]
    policy_version: str
    diagnosis: TypedDiagnosis
    requires_human: bool = False

    @field_validator("rule_trace")
    @classmethod
    def _non_empty_trace(cls, v: list[RuleEvaluation]) -> list[RuleEvaluation]:
        if not v:
            raise ValueError("an Action must carry a non-empty rule_trace (CLAUDE.md §2)")
        return v


# --------------------------------------------------------------------------------------
# Execution result + batch outcome
# --------------------------------------------------------------------------------------
class ExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: Action
    executed: bool  # False if idempotency-deduplicated or NO_ACTION
    dedup_hit: bool = False
    gateway_success: bool | None = None  # None for non-charging actions
    recovered_amount_paise: int = 0
    detail: str = ""


class MandateResolution(BaseModel):
    """End state for one mandate after the recovery loop finishes."""

    model_config = ConfigDict(frozen=True)

    mandate_id: str
    amount_at_risk_paise: int
    recovered: bool
    recovered_amount_paise: int
    retries_used: int
    contacts_made: int
    terminal_action: ActionType
    escalated_to_human: bool
    timeline: list[ExecutionResult]


class Scorecard(BaseModel):
    """Written to logs/iterations.jsonl, one line per iteration (CLAUDE.md §1.1)."""

    iteration: int
    ts: datetime
    git_sha: str | None = None
    note: str = ""

    tests_passed: int = 0
    tests_total: int = 0
    lint_errors: int = 0
    type_errors: int = 0

    batch_size: int = 0
    amount_at_risk_paise: int = 0
    recovered_paise: int = 0
    batch_recovery_rate: float = 0.0

    baseline_static_recovery_rate: float = 0.0
    baseline_email_only_recovery_rate: float = 0.0
    baseline_single_retry_recovery_rate: float = 0.0
    baseline_lift: float = 0.0  # agent - static-retry

    retries_used_total: int = 0
    recoveries_per_retry: float = 0.0
    unnecessary_contacts: int = 0
    escalated_count: int = 0

    compliance_violations: int = 0  # MUST be 0 (CLAUDE.md §3.1 stop-the-line)
