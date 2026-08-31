"""Offline, rule-based diagnoser.

This is a *real* classifier over structured signals (error code, mandate state, attempt
history) — not a stub that reports fake success (CLAUDE.md §1.3). It is the default when no
ANTHROPIC_API_KEY is set, and it is what the test suite runs against so tests stay
deterministic and offline.

By construction it never reads `raw_err_text`, so it is immune to prompt injection; that is
a feature, and the LLM path must earn parity with it on safety.
"""

from __future__ import annotations

from mandatemend.schemas import FailureCause, FailureEvent, MandateState, TypedDiagnosis

# Normalized error-code fragments -> cause. Checked as substring, case-insensitive.
_CODE_MAP: tuple[tuple[str, FailureCause], ...] = (
    ("INSUFFICIENT", FailureCause.INSUFFICIENT_FUNDS),
    ("U30", FailureCause.INSUFFICIENT_FUNDS),
    ("ZM", FailureCause.INSUFFICIENT_FUNDS),
    ("NOT_AVAILABLE", FailureCause.BANK_DOWNTIME),
    ("U69", FailureCause.BANK_DOWNTIME),
    ("U16", FailureCause.BANK_DOWNTIME),
    ("DOWNTIME", FailureCause.BANK_DOWNTIME),
    ("LIMIT", FailureCause.LIMIT_EXCEEDED),
    ("U67", FailureCause.LIMIT_EXCEEDED),
    ("PAUSED", FailureCause.MANDATE_PAUSED),
    ("UMN_PAUSED", FailureCause.MANDATE_PAUSED),
    ("EXPIRED", FailureCause.MANDATE_EXPIRED),
    ("UMN_EXPIRED", FailureCause.MANDATE_EXPIRED),
    ("U91", FailureCause.TECH_DECLINE),
    ("BT", FailureCause.TECH_DECLINE),
    ("TECHNICAL", FailureCause.TECH_DECLINE),
)


class HeuristicDiagnoser:
    source = "heuristic"

    def diagnose(self, event: FailureEvent) -> TypedDiagnosis:  # noqa: C901 - explicit ladder
        code = event.err_code.upper()
        hist = event.history

        # 1. Mandate liveness overrides the code — a dead mandate cannot be charged.
        if event.mandate_state is MandateState.PAUSED:
            return self._d(FailureCause.MANDATE_PAUSED, 0.97, "mandate_state=PAUSED")
        if event.mandate_state is MandateState.EXPIRED:
            return self._d(FailureCause.MANDATE_EXPIRED, 0.97, "mandate_state=EXPIRED")
        if event.mandate_state is MandateState.REVOKED:
            return self._d(
                FailureCause.MANDATE_EXPIRED, 0.9, "mandate_state=REVOKED (treat as dead)"
            )

        # 2. Amount over the per-transaction mandate cap -> genuine limit breach.
        if event.amount_paise > event.mandate_max_amount_paise:
            return self._d(
                FailureCause.LIMIT_EXCEEDED,
                0.9,
                f"amount {event.amount_paise} > mandate cap {event.mandate_max_amount_paise}",
            )

        # 3. Error-code lookup.
        code_cause: FailureCause | None = None
        for frag, cause in _CODE_MAP:
            if frag in code:
                code_cause = cause
                break

        # 4. Churn signal: repeated insufficient-funds with a long dry spell.
        looks_insufficient = code_cause is FailureCause.INSUFFICIENT_FUNDS or code_cause is None
        if (
            looks_insufficient
            and hist.consecutive_failures >= 3
            and (hist.days_since_last_success or 0) >= 45
        ):
            conf = 0.6 + min(0.25, 0.05 * (hist.consecutive_failures - 3))
            return self._d(
                FailureCause.SUSPECTED_CHURN,
                round(conf, 2),
                f"consecutive_failures={hist.consecutive_failures}, "
                f"days_since_last_success={hist.days_since_last_success}",
            )

        if code_cause is not None:
            # Confidence: strong for unambiguous codes, softer for the noisy ones.
            strong = code_cause in (
                FailureCause.BANK_DOWNTIME,
                FailureCause.LIMIT_EXCEEDED,
            )
            conf = 0.88 if strong else 0.78
            if code_cause is FailureCause.INSUFFICIENT_FUNDS and hist.consecutive_failures >= 2:
                conf -= 0.06
            return self._d(code_cause, round(conf, 2), f"err_code~='{event.err_code}'")

        # 5. Nothing matched -> low confidence, force the human queue downstream.
        return self._d(
            FailureCause.UNKNOWN,
            0.3,
            f"unrecognized err_code '{event.err_code}' and no decisive history signal",
        )

    def _d(self, cause: FailureCause, confidence: float, rationale: str) -> TypedDiagnosis:
        return TypedDiagnosis(
            cause=cause,
            confidence=confidence,
            rationale=rationale,
            source=self.source,
            injection_flagged=False,
        )
