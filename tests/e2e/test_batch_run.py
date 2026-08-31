"""One true end-to-end run over the FROZEN held-out batch (CLAUDE.md §8 DoD)."""

import pytest

from mandatemend.batch.run_batch import run

pytestmark = pytest.mark.e2e


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
