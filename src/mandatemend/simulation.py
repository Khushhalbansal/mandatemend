"""Shared vocabulary for the synthetic potential-outcomes model.

The generator writes an explicit potential-outcomes table per held-out mandate. The
SimulatedGateway and the batch runner *only read* that table, keyed through the helpers
here so the key format cannot drift between writer and readers (CLAUDE.md §1.3).

A potential-outcomes table entry answers: "if strategy applied <action> to this mandate
at <delay bucket> (with <channel>/<ratio>), would it have recovered, and how much?"
Outcomes are realized once at generation time (fixed booleans), so every strategy — the
agent and all baselines — is scored on the *same* realized outcomes. This is the
potential-outcomes / counterfactual design; no runtime randomness in the gateway.
"""

from __future__ import annotations

from mandatemend.schemas import ActionType, InterventionType

# Candidate retry delays (hours from the failure event). NPCI allows <= 3 retries, so a
# strategy selects at most 3 of these.
DELAY_BUCKETS_H: tuple[float, ...] = (0.0, 6.0, 24.0, 48.0, 72.0, 120.0, 168.0)

# Partial-charge ratio offered when a partial charge is attempted.
PARTIAL_RATIO: float = 0.6

# Intervention -> the concrete executable action the policy engine would emit for it.
INTERVENTION_TO_ACTION: dict[InterventionType, ActionType] = {
    InterventionType.NO_OP: ActionType.NO_ACTION,
    InterventionType.RETRY_ONLY: ActionType.RETRY,
    InterventionType.WHATSAPP_UPI_LINK: ActionType.SEND_NOTIFICATION,
    InterventionType.SMS_REMINDER: ActionType.SEND_NOTIFICATION,
    InterventionType.GRACE_48H: ActionType.GRACE_EXTEND,
    InterventionType.PARTIAL_CHARGE: ActionType.PARTIAL_CHARGE,
    InterventionType.METHOD_SWITCH: ActionType.OFFER_ALTERNATE_METHOD,
    InterventionType.REAUTH_LINK: ActionType.REQUEST_REAUTH,
}


def snap_delay(delay_hours: float) -> float:
    """Snap an arbitrary delay to the nearest defined bucket (round down, floor at 0)."""
    best = DELAY_BUCKETS_H[0]
    for b in DELAY_BUCKETS_H:
        if b <= delay_hours + 1e-9:
            best = b
    return best


def outcome_key(
    action_type: ActionType,
    delay_hours: float,
    *,
    channel: str | None = None,
    partial_ratio: float | None = None,
) -> str:
    """Canonical key into a mandate's potential-outcomes table."""
    parts: list[str] = [action_type.value, f"{snap_delay(delay_hours):g}"]
    if action_type is ActionType.SEND_NOTIFICATION:
        parts.append((channel or "whatsapp").lower())
    if action_type is ActionType.PARTIAL_CHARGE:
        parts.append(f"{partial_ratio if partial_ratio is not None else PARTIAL_RATIO:g}")
    return "|".join(parts)


ISSUERS: tuple[str, ...] = ("HDFC", "SBIN", "ICIC", "AXIS", "KKBK", "PYTM", "YESB", "UTIB")
