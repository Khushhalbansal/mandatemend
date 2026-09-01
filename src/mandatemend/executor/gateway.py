"""Payment gateways.

`SimulatedGateway` is the scoring gateway. It reads the FROZEN potential-outcomes table and
returns exactly what was realized at generation time. It cannot invent a success that is not
in the label file (CLAUDE.md §1.3): an unknown outcome key -> failure with an explicit note.

`RazorpayTestGateway` is for the single real test-mode round-trip in the demo (verification
step 7). It is never used for batch scoring because test mode cannot force an outcome.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from mandatemend.config import settings
from mandatemend.schemas import Action, ActionType, FailureEvent
from mandatemend.simulation import outcome_key


class Gateway(Protocol):
    name: str

    def attempt(self, action: Action, event: FailureEvent) -> tuple[bool | None, int, str]:
        """Return (success, recovered_paise, detail). success=None -> outcome unknown."""
        ...


_NON_MONEY = {ActionType.NO_ACTION, ActionType.STOP_AND_ESCALATE}


class SimulatedGateway:
    name = "simulated"

    def __init__(self, labels: dict[str, dict]):
        self._labels = labels

    @classmethod
    def from_frozen(cls, path: Path | None = None) -> SimulatedGateway:
        p = path or settings.heldout_labels
        raw = json.loads(Path(p).read_text(encoding="utf-8"))
        return cls(raw["labels"])

    def _delay_hours(self, action: Action, event: FailureEvent) -> float:
        # Prefer the causal delay bucket the retry-timing model chose; fall back to wall-clock.
        if action.retry_delay_bucket is not None:
            return action.retry_delay_bucket
        return max(0.0, (action.scheduled_at - event.occurred_at).total_seconds() / 3600.0)

    def attempt(self, action: Action, event: FailureEvent) -> tuple[bool | None, int, str]:
        if action.action_type in _NON_MONEY:
            return None, 0, f"{action.action_type.value}: no money move"

        table = self._labels.get(event.mandate_id, {}).get("outcomes", {})
        if not table:
            return False, 0, "no potential-outcomes row for this mandate"

        delay = self._delay_hours(action, event)
        if action.action_type is ActionType.SEND_NOTIFICATION:
            key = outcome_key(action.action_type, delay, channel=action.channel or "whatsapp")
        elif action.action_type is ActionType.PARTIAL_CHARGE:
            key = outcome_key(action.action_type, delay, partial_ratio=None)
        else:
            key = outcome_key(action.action_type, delay)

        entry = table.get(key)
        if entry is None:
            return False, 0, f"no realized outcome for key '{key}' (cannot invent success)"
        return bool(entry["success"]), int(entry["amount_paise"]), f"key={key} p={entry['p']}"


class RazorpayTestGateway:
    """Minimal real test-mode round-trip. Creates a Payment Link and returns its short_url.

    Outcome is reported as unknown (success=None): test mode does not let us force a debit
    result, so this gateway is for demonstrating a real API call, not for scoring.
    """

    name = "razorpay_test"
    base = "https://api.razorpay.com/v1"

    def __init__(self, key_id: str | None = None, key_secret: str | None = None):
        import os

        self.key_id = key_id or os.environ.get("RAZORPAY_KEY_ID", "")
        self.key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET", "")
        if not (self.key_id and self.key_secret):
            raise RuntimeError("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set")

    #: filled in by attempt() on success, so callers can surface the real link
    last_response: dict | None = None

    @staticmethod
    def _reference_id(action: Action) -> str:
        # Razorpay reference_id: <= 40 chars, must be unique per link. Strip non-alnum from
        # the idempotency key and add a short time suffix so repeated live-checks don't 409.
        import re
        import time

        base = re.sub(r"[^A-Za-z0-9_-]", "-", action.idempotency_key)[:26]
        return f"{base}-{int(time.time()) % 100000}"

    def attempt(self, action: Action, event: FailureEvent) -> tuple[bool | None, int, str]:
        import httpx

        amount = action.amount_paise or event.amount_paise
        payload = {
            "amount": int(amount),
            "currency": "INR",
            "description": (
                f"MandateMend recovery {action.action_type.value} for {event.mandate_id}"
            )[:2048],
            "reference_id": self._reference_id(action),
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
        }
        try:
            r = httpx.post(
                f"{self.base}/payment_links",
                json=payload,
                auth=(self.key_id, self.key_secret),
                timeout=25.0,
            )
        except httpx.HTTPError as exc:  # network error -> fail closed, no exception into the loop
            return None, 0, f"razorpay test-mode network error: {type(exc).__name__}: {exc}"

        if r.status_code >= 300:
            self.last_response = {"http": r.status_code, "error": r.text[:300]}
            return None, 0, f"razorpay test-mode error {r.status_code}: {r.text[:200]}"

        body = r.json()
        self.last_response = {
            "http": r.status_code,
            "id": body.get("id"),
            "short_url": body.get("short_url"),
            "status": body.get("status"),
            "amount": body.get("amount"),
            "reference_id": body.get("reference_id"),
        }
        # Outcome is deliberately unknown: test mode cannot force a debit result, so this
        # proves connectivity, not recovery.
        return None, 0, f"created payment_link {body.get('id')} {body.get('short_url')}"


def get_gateway(labels: dict[str, dict] | None = None) -> Gateway:
    if settings.executor == "razorpay_test":
        return RazorpayTestGateway()
    if labels is not None:
        return SimulatedGateway(labels)
    return SimulatedGateway.from_frozen()
