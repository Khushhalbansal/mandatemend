"""`mandatemend eval` — sequencing / calibration / ablation diagnostics.

Reporting-only: reads the frozen potential-outcomes table as an oracle, never trains on it.
Integration-tier because it runs the full agent loop five times for the ablation.
"""

import pytest

from mandatemend import eval as ev
from mandatemend.models.retry_timing import ARTIFACT as RETRY_ARTIFACT
from mandatemend.models.uplift import ARTIFACT as UPLIFT_ARTIFACT

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def out():
    if not (RETRY_ARTIFACT.exists() and UPLIFT_ARTIFACT.exists()):
        pytest.skip("model artifacts missing; run `mandatemend train`")
    return ev.run_all()


def test_sequencing_reports_model_and_ladder_capture_rates(out):
    s = out["sequencing"]
    assert s["n_mandates_with_a_winning_retry"] > 0
    for k in ("model_top3_ordered_capture_rate", "fixed_ladder_24_72_168_capture_rate"):
        assert 0.0 <= s[k] <= 1.0
    # ordering the 3 retries can only help vs a fixed subset of the same buckets
    assert s["model_top3_ordered_capture_rate"] >= s["model_top1_only_capture_rate"]


def test_calibration_reports_ece_in_range_for_both_models(out):
    for name in ("retry_timing", "uplift"):
        c = out["calibration"][name]
        assert 0.0 <= c["ece"] <= 1.0
        assert 0.0 <= c["mce"] <= 1.0
        assert c["n"] > 0
        assert sum(r["n"] for r in c["reliability"]) == c["n"]


def test_ablation_shipped_config_matches_the_scorecard(out):
    tbl = {r["config"]: r for r in out["ablation"]["table"]}
    shipped = next(r for k, r in tbl.items() if "shipped" in k)
    # the shipped survival+t-learner row must reproduce the ~61% headline (same harness)
    assert 0.58 <= shipped["recovery_rate"] <= 0.64
    # every agent config must beat the naive ladder
    naive = tbl["naive static-retry ladder (no agent)"]["recovery_rate"]
    agent_rows = [r for k, r in tbl.items() if "no agent" not in k]
    assert all(r["recovery_rate"] > naive for r in agent_rows)
