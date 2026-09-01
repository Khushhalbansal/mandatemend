"""`mandatemend redteam` — the wider adversarial battery all holds.

Slower than `failure-drill` (it runs a 360-execution concurrent-load check), so it lives in
the integration tier and is a hard gate in CI. `run_all()` is expensive, so it runs once
per module and the assertions share the result.
"""

import pytest

from mandatemend.redteam import format_results, run_all

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def results():
    return run_all()


def test_every_redteam_group_holds(results):
    failed = [r.group for r in results if not r.held]
    assert not failed, f"red-team groups NOT held: {failed}\n{format_results(results)}"


def test_redteam_covers_the_expected_surface(results):
    names = {r.group for r in results}
    assert names >= {
        "prompt-injection",
        "hostile-webhooks",
        "clock-skew",
        "ledger-outage",
        "concurrent-load",
    }


def test_injection_corpus_is_fully_neutralised(results):
    pi = next(r for r in results if r.group == "prompt-injection")
    # the printed rate reads "N/N neutralised ..." — first and second numbers must match
    got, total = pi.rate.split()[0].split("/")
    assert got == total, f"injection detection not 100%: {pi.rate}"
