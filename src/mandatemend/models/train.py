"""Train the retry-timing (discrete-time hazard) and uplift (T-learner) models; report metrics.

Trains only on `data/training_set.json` (the logging-policy rows). Never touches the frozen
held-out batch. Writes artifacts to `src/mandatemend/models/artifacts/` and a metrics blob
to `logs/model_metrics.json` — including the retry model's time-stratified calibration
(per-bucket AUC / Brier, integrated Brier score) alongside the oracle agreement check.

An oracle check against the held-out potential-outcomes table is included for reporting only
(does the model's argmax delay / argmax arm agree with the realized best?) — it does not feed
training.
"""

from __future__ import annotations

import json
from pathlib import Path

from mandatemend.config import settings
from mandatemend.models.retry_timing import RetryTimingModel
from mandatemend.models.uplift import ARMS, UpliftModel
from mandatemend.schemas import ActionType, FailureCause, FailureEvent, TypedDiagnosis
from mandatemend.simulation import DELAY_BUCKETS_H, INTERVENTION_TO_ACTION, outcome_key

TRAIN_JSON = Path(__file__).resolve().parents[3] / "data" / "training_set.json"
METRICS = Path(settings.iter_log).parent / "model_metrics.json"


def _oracle_retry_agreement(model: RetryTimingModel) -> dict:
    """On the held-out batch: does the model's best delay match the realized best RETRY delay?"""
    batch = json.loads(Path(settings.heldout_batch).read_text(encoding="utf-8"))["events"]
    labels = json.loads(Path(settings.heldout_labels).read_text(encoding="utf-8"))["labels"]
    agree = naive_agree = considered = 0
    for e in batch:
        ev = FailureEvent.model_validate(e)
        lab = labels[ev.mandate_id]
        diag = TypedDiagnosis(
            cause=FailureCause(lab["true_cause"]),
            confidence=1.0,
            rationale="oracle",
            source="oracle",
        )
        realized = {
            d: labels[ev.mandate_id]["outcomes"].get(outcome_key(ActionType.RETRY, d), {})
            for d in DELAY_BUCKETS_H
        }
        succ = {d: v for d, v in realized.items() if v.get("success")}
        if not succ:
            continue
        considered += 1
        best_delay, _ = model.best_delay(ev, diag)
        if realized.get(best_delay, {}).get("success"):
            agree += 1
        if realized.get(72.0, {}).get("success"):  # naive "+72h" baseline
            naive_agree += 1
    return {
        "n_with_a_winning_retry": considered,
        "model_picks_a_winning_delay": round(agree / considered, 3) if considered else None,
        "naive_+72h_is_a_winning_delay": round(naive_agree / considered, 3) if considered else None,
    }


def _oracle_uplift_agreement(model: UpliftModel) -> dict:
    batch = json.loads(Path(settings.heldout_batch).read_text(encoding="utf-8"))["events"]
    labels = json.loads(Path(settings.heldout_labels).read_text(encoding="utf-8"))["labels"]
    agree = considered = 0
    for e in batch:
        ev = FailureEvent.model_validate(e)
        lab = labels[ev.mandate_id]
        diag = TypedDiagnosis(
            cause=FailureCause(lab["true_cause"]),
            confidence=1.0,
            rationale="oracle",
            source="oracle",
        )
        oc = lab["outcomes"]
        # realized: does *any* execution of this arm succeed in the table?
        arm_ok: dict = {}
        for arm in ARMS:
            at = INTERVENTION_TO_ACTION[arm]
            keys = [k for k in oc if k.split("|")[0] == at.value]
            arm_ok[arm] = any(oc[k]["success"] for k in keys)
        if not any(arm_ok.values()):
            continue
        considered += 1
        top_arm = model.rank(ev, diag)[0][0]
        if arm_ok.get(top_arm):
            agree += 1
    return {
        "n_with_a_winning_arm": considered,
        "model_top_arm_is_a_winning_arm": round(agree / considered, 3) if considered else None,
    }


def main() -> None:
    if not TRAIN_JSON.exists():
        raise SystemExit(f"missing {TRAIN_JSON}; run `python data/generator.py` first")

    retry_model, retry_metrics = RetryTimingModel.train(TRAIN_JSON)
    retry_model.save()
    uplift_model, uplift_metrics = UpliftModel.train(TRAIN_JSON)
    uplift_model.save()

    metrics = {
        "retry_timing": {**retry_metrics, "oracle": _oracle_retry_agreement(retry_model)},
        "uplift": {**uplift_metrics, "oracle": _oracle_uplift_agreement(uplift_model)},
    }
    METRICS.parent.mkdir(parents=True, exist_ok=True)
    METRICS.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
