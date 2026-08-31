"""Non-agent baselines, evaluated directly against the frozen potential-outcomes table.

These are the comparators the agent must beat (CLAUDE.md §1.1 `baseline_lift`). They read
the same realized outcomes the agent's gateway reads, so the comparison is apples-to-apples.
"""

from __future__ import annotations

from dataclasses import dataclass

from mandatemend.schemas import ActionType
from mandatemend.simulation import outcome_key


@dataclass
class BaselineResult:
    recovered: bool
    recovered_paise: int
    retries_used: int
    contacts: int


def _first_success(outcomes: dict, keys: list[str]) -> tuple[bool, int, int, int]:
    retries = contacts = 0
    for k in keys:
        entry = outcomes.get(k)
        if k.startswith(("RETRY", "PARTIAL_CHARGE")):
            retries += 1
        elif k.startswith("SEND_NOTIFICATION"):
            contacts += 1
        if entry and entry["success"]:
            return True, int(entry["amount_paise"]), retries, contacts
    return False, 0, retries, contacts


def static_retry(outcomes: dict, amount_at_risk: int) -> BaselineResult:
    """Fixed schedule: retry at +24h, +72h, +168h (the classic dunning ladder)."""
    keys = [
        outcome_key(ActionType.RETRY, 24.0),
        outcome_key(ActionType.RETRY, 72.0),
        outcome_key(ActionType.RETRY, 168.0),
    ]
    ok, amt, r, c = _first_success(outcomes, keys)
    return BaselineResult(ok, amt, r, c)


def single_retry(outcomes: dict, amount_at_risk: int) -> BaselineResult:
    keys = [outcome_key(ActionType.RETRY, 24.0)]
    ok, amt, r, c = _first_success(outcomes, keys)
    return BaselineResult(ok, amt, r, c)


def email_only(outcomes: dict, amount_at_risk: int) -> BaselineResult:
    """One weak-channel reminder (SMS/email proxy), no retry orchestration."""
    keys = [outcome_key(ActionType.SEND_NOTIFICATION, 24.0, channel="sms")]
    ok, amt, r, c = _first_success(outcomes, keys)
    return BaselineResult(ok, amt, r, c)


def no_action(outcomes: dict, amount_at_risk: int) -> BaselineResult:
    entry = outcomes.get(outcome_key(ActionType.NO_ACTION, 0.0))
    if entry and entry["success"]:
        return BaselineResult(True, int(entry["amount_paise"]), 0, 0)
    return BaselineResult(False, 0, 0, 0)


BASELINES = {
    "static_retry": static_retry,
    "single_retry": single_retry,
    "email_only": email_only,
    "no_action": no_action,
}


def run_baseline(name: str, labels: dict[str, dict]) -> dict:
    fn = BASELINES[name]
    at_risk = recovered = n_rec = retries = contacts = 0
    for lab in labels.values():
        amt = int(lab["amount_at_risk_paise"])
        at_risk += amt
        r = fn(lab["outcomes"], amt)
        if r.recovered:
            recovered += r.recovered_paise
            n_rec += 1
        retries += r.retries_used
        contacts += r.contacts
    return {
        "name": name,
        "recovered_paise": recovered,
        "amount_at_risk_paise": at_risk,
        "recovery_rate": recovered / at_risk if at_risk else 0.0,
        "n_recovered": n_rec,
        "retries_used": retries,
        "contacts": contacts,
    }
