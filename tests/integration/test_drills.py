"""`mandatemend failure-drill` — every injected failure is caught."""

import pytest

from mandatemend.drills import format_results, run_all

pytestmark = pytest.mark.integration


def test_all_invariants_hold():
    results = run_all()
    failed = [r.name for r in results if not r.held]
    assert not failed, f"invariants NOT held: {failed}\n{format_results(results)}"
    names = {r.name for r in results}
    assert names >= {
        "concurrent-webhook",
        "duplicate-retry",
        "gateway-crash",
        "npci-retry-cap",
        "dead-mandate-charge",
        "prompt-injection",
        "audit-tamper",
    }
