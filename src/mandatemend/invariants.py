"""Independent compliance verification.

CLAUDE.md §1.3 / §3: compliance is checked here, *outside* the policy engine, by re-reading
the produced actions and their timeline. The engine can never mark its own homework. The
batch runner calls `check_resolution` on every mandate and the scorecard reports the total
`compliance_violations`, which must be 0 — a non-zero count is stop-the-line (§3.1).
"""

from __future__ import annotations

from datetime import timedelta

from mandatemend.config import settings
from mandatemend.schemas import (
    ActionType,
    FailureEvent,
    MandateResolution,
)

_CHARGING = {ActionType.RETRY, ActionType.PARTIAL_CHARGE}
_DEAD_STATES = {"PAUSED", "EXPIRED", "REVOKED"}


def check_resolution(event: FailureEvent, res: MandateResolution) -> list[str]:
    """Return a list of human-readable violation strings (empty == compliant)."""
    v: list[str] = []
    charges = [r for r in res.timeline if r.action.action_type in _CHARGING and r.executed]
    notices = [
        r
        for r in res.timeline
        if r.action.action_type is ActionType.SEND_NOTIFICATION and r.executed
    ]
    outbound_contacts = [
        r
        for r in res.timeline
        if r.executed
        and r.action.action_type
        in (
            ActionType.SEND_NOTIFICATION,
            ActionType.OFFER_ALTERNATE_METHOD,
            ActionType.REQUEST_REAUTH,
        )
    ]

    # 1. NPCI retry cap: at most `npci_max_retries` executed charge attempts.
    if len(charges) > settings.npci_max_retries:
        v.append(
            f"NPCI_RETRY_CAP: {len(charges)} executed charges > cap {settings.npci_max_retries}"
        )

    # 2. 24h pre-debit notice: every executed charge must be preceded by a notice at least
    #    24h earlier.
    for c in charges:
        prior_notice = [
            n
            for n in notices
            if n.action.scheduled_at
            <= c.action.scheduled_at - timedelta(hours=settings.predebit_notice_hours)
        ]
        if not prior_notice:
            v.append(
                f"PREDEBIT_NOTICE: charge at {c.action.scheduled_at.isoformat()} "
                f"has no notice >= {settings.predebit_notice_hours}h earlier"
            )

    # 3. Quiet hours: no executed outbound contact (notice, alternate-method offer, or
    #    re-auth request) in [quiet_start, quiet_end).
    for n in outbound_contacts:
        h = n.action.scheduled_at.hour
        if h >= settings.quiet_hours_start or h < settings.quiet_hours_end:
            v.append(
                f"QUIET_HOURS: {n.action.action_type.value} scheduled at hour {h}"
            )

    # 4. Contact frequency: the contacts the AGENT made this session must not exceed the
    #    remaining weekly budget. A mandate that arrives already at/over the cap is not the
    #    agent's doing — what matters is that it then adds nothing.
    session_contacts = len(outbound_contacts)
    remaining_budget = max(0, settings.max_contacts_per_week - event.history.contacts_this_week)
    if session_contacts > remaining_budget:
        v.append(
            f"CONTACT_FREQUENCY: agent made {session_contacts} contacts this session, "
            f"remaining weekly budget was {remaining_budget}"
        )

    # 5. No charge on a dead mandate.
    if event.mandate_state.value in _DEAD_STATES and charges:
        v.append(f"DEAD_MANDATE_CHARGE: {len(charges)} charge(s) on {event.mandate_state} mandate")

    # 6. Charge amount within the mandate's per-transaction cap.
    for c in charges:
        amt = c.action.amount_paise or 0
        if amt > event.mandate_max_amount_paise:
            v.append(f"AMOUNT_OVER_CAP: {amt}p > {event.mandate_max_amount_paise}p")

    # 6b. AFA (I13): a debit above the AFA-exemption ceiling requires a prior executed
    #     re-authorization request in the same session.
    ceiling = settings.afa_exemption_ceiling_paise
    reauths = [
        r
        for r in res.timeline
        if r.action.action_type is ActionType.REQUEST_REAUTH and r.executed
    ]
    for c in charges:
        if (c.action.amount_paise or 0) > ceiling:
            prior = [r for r in reauths if r.action.scheduled_at <= c.action.scheduled_at]
            if not prior:
                v.append(
                    f"AFA_EXEMPTION: charge {c.action.amount_paise}p > AFA ceiling {ceiling}p "
                    f"with no prior re-authorization"
                )

    # 7. Every executed action carries a non-empty rule trace.
    for r in res.timeline:
        if r.executed and not r.action.rule_trace:
            v.append(f"EMPTY_RULE_TRACE: {r.action.action_type} executed with no trace")

    return v
