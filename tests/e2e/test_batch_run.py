"""One true end-to-end run over the FROZEN held-out batch (CLAUDE.md §8 DoD)."""

import pytest

from mandatemend.batch.run_batch import run, wilson_interval

pytestmark = pytest.mark.e2e


def test_wilson_interval_math():
    # n=0 -> degenerate
    assert wilson_interval(0, 0) == (0.0, 0.0)
    # symmetric-ish, brackets the point estimate, stays in [0,1]
    lo, hi = wilson_interval(5, 10)
    assert 0.0 <= lo < 0.5 < hi <= 1.0
    # small n -> wide; large n -> narrow, for the same proportion
    w_small = wilson_interval(4, 18)  # ~MANDATE_PAUSED bucket
    w_large = wilson_interval(400, 1800)
    assert (w_small[1] - w_small[0]) > (w_large[1] - w_large[0]) + 0.1
    # a 0-of-n bucket has lo == 0 but hi > 0 (never claims certainty)
    z_lo, z_hi = wilson_interval(0, 14)
    assert z_lo == 0.0 and z_hi > 0.0


def test_per_cause_carries_a_wilson_ci(scorecard):
    assert scorecard.per_cause
    for c in scorecard.per_cause:
        lo, hi = c["rate_ci"]
        assert 0.0 <= lo <= c["rate"] + 1e-4 and c["rate"] - 1e-4 <= hi <= 1.0


@pytest.fixture(scope="module")
def scorecard():
    return run(iteration=-1, note="pytest e2e")


def test_compliance_is_clean(scorecard):
    assert scorecard.compliance_violations == 0, (
        "STOP-THE-LINE: the frozen-batch run has compliance violations"
    )


def test_agent_beats_every_baseline(scorecard):
    assert scorecard.batch_recovery_rate > scorecard.baseline_static_recovery_rate
    assert scorecard.batch_recovery_rate > scorecard.baseline_single_retry_recovery_rate
    assert scorecard.batch_recovery_rate > scorecard.baseline_email_only_recovery_rate


def test_lift_is_materially_positive(scorecard):
    # guards against a silent regression; the working number is ~+15pp
    assert scorecard.baseline_lift >= 0.08


def test_batch_shape(scorecard):
    assert scorecard.batch_size == 300
    assert scorecard.amount_at_risk_paise > 0
    assert 0.0 < scorecard.batch_recovery_rate < 1.0
    # NPCI budget: total retries can never exceed 3x the batch
    assert scorecard.retries_used_total <= 3 * scorecard.batch_size


def test_audit_chain_verifies(scorecard):
    assert "chain OK" in scorecard.note
