"""Retry-timing (survival) + uplift (T-learner) models: shape, save/load, sanity."""

from pathlib import Path

import pytest

from mandatemend.models.retry_timing import RetryTimingModel
from mandatemend.models.uplift import ARMS, UpliftModel
from mandatemend.schemas import FailureCause, TypedDiagnosis
from mandatemend.simulation import DELAY_BUCKETS_H
from tests.conftest import make_event

TRAIN_JSON = Path(__file__).resolve().parents[2] / "data" / "training_set.json"


@pytest.fixture(scope="module")
def models():
    if not TRAIN_JSON.exists():
        pytest.skip("run `python data/generator.py` to create the training set")
    rt, rt_metrics = RetryTimingModel.train(TRAIN_JSON)
    up, up_metrics = UpliftModel.train(TRAIN_JSON)
    return rt, rt_metrics, up, up_metrics


def _diag(cause=FailureCause.INSUFFICIENT_FUNDS):
    return TypedDiagnosis(cause=cause, confidence=0.9, rationale="x", source="t")


def test_retry_curve_shape_and_range(models):
    rt, *_ = models
    curve = rt.curve(make_event(), _diag())
    assert [d for d, _ in curve] == list(DELAY_BUCKETS_H)
    assert all(0.0 <= p <= 1.0 for _, p in curve)
    delay, p = rt.best_delay(make_event(), _diag())
    assert delay in DELAY_BUCKETS_H and 0.0 <= p <= 1.0


def test_retry_val_auc_is_reported_and_beats_coin_flip(models):
    _rt, rt_metrics, *_ = models
    assert rt_metrics["val_auc"] >= 0.5


def test_retry_time_aware_metrics_shape(models):
    _rt, rt_metrics, *_ = models
    assert rt_metrics["integrated_brier_score"] is not None
    assert 0.0 <= rt_metrics["integrated_brier_score"] <= 1.0
    pb = rt_metrics["per_bucket"]
    # one entry per delay bucket that appears in the logging data, keyed by bucket hours
    assert set(pb) <= {str(d) for d in DELAY_BUCKETS_H}
    assert all(v["n"] >= 1 for v in pb.values())


def test_retry_hazard_survival_recovery_are_consistent(models):
    rt, *_ = models
    ev, dg = make_event(), _diag()
    hz = rt.hazard_curve(ev, dg)
    assert hz == rt.curve(ev, dg)  # legacy alias unchanged
    surv = rt.survival_curve(ev, dg)
    rec = rt.recovery_curve(ev, dg)
    s = 1.0
    for (d, h), (ds, sv), (dr, rv) in zip(hz, surv, rec, strict=True):
        assert d == ds == dr
        s *= 1.0 - h
        assert sv == pytest.approx(s, abs=1e-9)
        assert rv == pytest.approx(1.0 - s, abs=1e-9)
    # survival is non-increasing, recovery non-decreasing
    svals = [s for _, s in surv]
    assert all(a >= b - 1e-12 for a, b in zip(svals, svals[1:], strict=False))
    assert [r for _, r in rec] == sorted(r for _, r in rec)


def test_expected_recovery_for_schedule_composes_the_hazards(models):
    rt, *_ = models
    ev, dg = make_event(), _diag()
    hz = dict(rt.hazard_curve(ev, dg))
    sched = [24.0, 72.0, 168.0]
    expect = 1.0 - (1 - hz[24.0]) * (1 - hz[72.0]) * (1 - hz[168.0])
    assert rt.expected_recovery_for_schedule(ev, dg, sched) == pytest.approx(expect, abs=1e-9)
    # a longer schedule can only help; a single-bucket schedule == that bucket's hazard
    assert rt.expected_recovery_for_schedule(ev, dg, [24.0]) == pytest.approx(hz[24.0], abs=1e-9)
    assert rt.expected_recovery_for_schedule(ev, dg, sched) >= hz[24.0] - 1e-12


def test_retry_save_load_roundtrip(models, tmp_path):
    rt, *_ = models
    p = rt.save(tmp_path / "rt.joblib")
    reloaded = RetryTimingModel.load(p)
    a = reloaded.curve(make_event(), _diag())
    b = rt.curve(make_event(), _diag())
    assert [d for d, _ in a] == [d for d, _ in b]
    assert [pytest.approx(p, abs=1e-9) for _, p in a] == [p for _, p in b]


def test_uplift_ranks_all_arms_by_uplift(models):
    *_, up, _um = models
    ranked = up.rank(make_event(), _diag())
    assert {a for a, _p, _u in ranked} == set(ARMS)
    uplifts = [u for _a, _p, u in ranked]
    assert uplifts == sorted(uplifts, reverse=True)  # descending by uplift
    assert all(0.0 <= p <= 1.0 for _a, p, _u in ranked)


def test_uplift_models_every_arm_with_enough_data(models):
    *_, _up, um = models
    # the full training set should give a real model for (nearly) every arm, not just the
    # weak prior. SMS_REMINDER / GRACE_48H / NO_OP sit near the 40-row / 2-class threshold,
    # so allow one to fall back.
    modelled = set(um["arms_modelled"])
    assert len(modelled) >= len(ARMS) - 1, modelled
    assert {"RETRY_ONLY", "WHATSAPP_UPI_LINK", "METHOD_SWITCH"} <= modelled


def test_uplift_save_load_roundtrip(models, tmp_path):
    *_, up, _ = models
    p = up.save(tmp_path / "up.joblib")
    reloaded = UpliftModel.load(p)
    assert reloaded.rank(make_event(), _diag()) == up.rank(make_event(), _diag())
    assert reloaded.feature_baseline == up.feature_baseline


def test_uplift_local_attribution_is_signed_and_ranked(models):
    *_, up, _ = models
    ev, dg = make_event(), _diag()
    top_arm = up.rank(ev, dg)[0][0]
    contribs = up.explain(ev, dg, top_arm, top=5)
    assert 1 <= len(contribs) <= 5
    # sorted by |delta| desc; each names a real feature and a value
    mags = [abs(c["delta"]) for c in contribs]
    assert mags == sorted(mags, reverse=True)
    assert all(c["feature"] in up.feature_names for c in contribs)


def test_global_importance_is_reported_for_both_models(models):
    _rt, rt_metrics, _up, up_metrics = models
    rt_gi = rt_metrics["global_importance"]
    assert rt_gi and all(0.0 <= abs(r["importance"]) for r in rt_gi)
    assert any(r["feature"] == "delay_hours" for r in rt_gi)  # timing dominates, as expected
    up_gi = up_metrics["global_importance"]
    assert "RETRY_ONLY" in up_gi and len(up_gi["RETRY_ONLY"]) <= 8
