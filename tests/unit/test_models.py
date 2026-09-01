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
