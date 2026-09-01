"""Bounded, honest mutation check on the pure compliance layer.

Run:  python scripts/mutcheck.py

mutmut 3.x has no native-Windows support and 2.5.1 runs but is noisy here (its survivor set
is dominated by non-behavioural mutants on imports, docstrings and the `detail=` / `reason=`
f-strings that only populate the human-readable rule trace). So this applies a hand-picked
set of *semantically meaningful* mutations — every comparison operator and boolean
connective in the compliance predicates (`policy/rules.py`) and in the independent checker
(`invariants.py`) — and asserts the fast unit + full property suites catch each one.

See docs/INVARIANTS.md for the reported result.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable

# (file, original snippet, mutated snippet, invariant it would break)
MUTATIONS = [
    # --- policy/rules.py ----------------------------------------------------------------
    ("src/mandatemend/policy/rules.py",
     "ok = diag.confidence >= settings.low_confidence_threshold",
     "ok = diag.confidence <= settings.low_confidence_threshold",
     "I7 confidence-gate direction"),
    ("src/mandatemend/policy/rules.py",
     "ok = state.retries_used < settings.npci_max_retries",
     "ok = state.retries_used <= settings.npci_max_retries",
     "I1 off-by-one on the NPCI retry cap"),
    ("src/mandatemend/policy/rules.py",
     "dead = event.mandate_state in DEAD_MANDATE_STATES or diag.cause in DEAD_CAUSES",
     "dead = event.mandate_state in DEAD_MANDATE_STATES and diag.cause in DEAD_CAUSES",
     "I3 dead-mandate detection weakened (or -> and)"),
    ("src/mandatemend/policy/rules.py",
     "ok = gap >= timedelta(hours=settings.predebit_notice_hours)",
     "ok = gap <= timedelta(hours=settings.predebit_notice_hours)",
     "I2 pre-debit-notice window inverted"),
    ("src/mandatemend/policy/rules.py",
     "in_quiet = hour >= qs or hour < qe",
     "in_quiet = hour >= qs and hour < qe",
     "I4 quiet-hours window broken (or -> and)"),
    ("src/mandatemend/policy/rules.py",
     "ok = state.contacts_this_week < settings.max_contacts_per_week",
     "ok = state.contacts_this_week > settings.max_contacts_per_week",
     "I5 contact-cap comparison flipped"),
    ("src/mandatemend/policy/rules.py",
     "ok = amount_paise <= event.mandate_max_amount_paise",
     "ok = amount_paise >= event.mandate_max_amount_paise",
     "I6 amount-cap comparison flipped"),
    ("src/mandatemend/policy/rules.py",
     "ok = expected >= floor",
     "ok = expected <= floor",
     "outreach economic floor inverted"),
    ("src/mandatemend/policy/rules.py",
     "ok = state.consecutive_hard_declines < limit",
     "ok = state.consecutive_hard_declines <= limit",
     "stopping-rule off-by-one"),
    # --- invariants.py (the independent checker) --------------------------------------
    ("src/mandatemend/invariants.py",
     "if len(charges) > settings.npci_max_retries:",
     "if len(charges) >= settings.npci_max_retries:",
     "checker I1 boundary"),
    ("src/mandatemend/invariants.py",
     "<= c.action.scheduled_at - timedelta(hours=settings.predebit_notice_hours)",
     ">= c.action.scheduled_at - timedelta(hours=settings.predebit_notice_hours)",
     "checker I2 notice-window direction"),
    ("src/mandatemend/invariants.py",
     "if h >= settings.quiet_hours_start or h < settings.quiet_hours_end:",
     "if h >= settings.quiet_hours_start and h < settings.quiet_hours_end:",
     "checker I4 quiet-hours window"),
    ("src/mandatemend/invariants.py",
     "if session_contacts > remaining_budget:",
     "if session_contacts < remaining_budget:",
     "checker I5 contact-frequency direction"),
    ("src/mandatemend/invariants.py",
     "if amt > event.mandate_max_amount_paise:",
     "if amt >= event.mandate_max_amount_paise:",
     "checker I6 amount-cap boundary"),
]

_BASE = [PY, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider"]
# Two invocations: the unit predicate/engine/checker tests (no marker filter), then the
# property suite (which is opt-in behind the `property` marker). A mutation is "killed" if
# EITHER run goes red.
UNIT_RUN = [
    *_BASE, "-m", "not live and not property",
    "tests/unit/test_policy_rules.py", "tests/unit/test_policy_engine.py",
    "tests/unit/test_invariants.py", "tests/unit/test_diagnosers.py",
]
PROP_RUN = [*_BASE, "-m", "property", "tests/property"]


def run_suite() -> bool:
    for cmd in (UNIT_RUN, PROP_RUN):
        if subprocess.run(cmd, cwd=REPO, capture_output=True, text=True).returncode != 0:
            return False
    return True


def main() -> int:
    if not run_suite():
        print("baseline suite is not green - fix that before mutation-checking")
        return 2
    killed = 0
    survivors: list[str] = []
    for rel, old, new, desc in MUTATIONS:
        p = REPO / rel
        src = p.read_text(encoding="utf-8")
        if old not in src:
            print(f"  SKIP (snippet moved)  {desc}")
            continue
        p.write_text(src.replace(old, new, 1), encoding="utf-8")
        try:
            ok = run_suite()
        finally:
            p.write_text(src, encoding="utf-8")
        if ok:
            survivors.append(desc)
            print(f"  SURVIVED  {desc}")
        else:
            killed += 1
            print(f"  killed    {desc}")
    total = killed + len(survivors)
    print(f"\n{killed}/{total} logic mutations caught ({killed / total:.0%})")
    for s in survivors:
        print(f"  survivor: {s}")
    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
