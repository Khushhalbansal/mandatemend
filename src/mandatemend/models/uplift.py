"""Intervention selection — IPW-weighted T-learner (CATE per arm).

For each intervention arm we fit a separate outcome model P(recover | x, arm) on the logging
rows assigned to that arm, weighting each row by 1/propensity (clipped) to undo the logging
policy's bias. uplift(arm | x) = P_arm(recover | x) - P_control(recover | x), control = NO_OP.
The advisor returns the arms ranked by uplift; the agent walks that ranking across rounds,
skipping arms already tried (round-awareness without a stateful model).

Industry retry/dunning engines rank actions by predicted success; ranking by *causal uplift*
against a control is the step up this brings (research file: arXiv 2412.09232, 2505.08343).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from mandatemend.features import FEATURE_NAMES, feature_row
from mandatemend.schemas import (
    FailureCause,
    FailureEvent,
    InterventionType,
    TypedDiagnosis,
)

ARTIFACT = Path(__file__).resolve().parent / "artifacts" / "uplift.joblib"
_IPW_CLIP = 10.0
CONTROL = InterventionType.NO_OP

# logging-policy key prefix -> intervention arm
_KEY_TO_ARM: dict[str, InterventionType] = {
    "RETRY": InterventionType.RETRY_ONLY,
    "PARTIAL_CHARGE": InterventionType.PARTIAL_CHARGE,
    "GRACE_EXTEND": InterventionType.GRACE_48H,
    "OFFER_ALTERNATE_METHOD": InterventionType.METHOD_SWITCH,
    "NO_ACTION": InterventionType.NO_OP,
}


def _arm_from_key(key: str) -> InterventionType | None:
    parts = key.split("|")
    head = parts[0]
    if head == "SEND_NOTIFICATION":
        ch = parts[2] if len(parts) > 2 else "whatsapp"
        return (
            InterventionType.WHATSAPP_UPI_LINK
            if ch == "whatsapp"
            else InterventionType.SMS_REMINDER
        )
    return _KEY_TO_ARM.get(head)


ARMS: list[InterventionType] = [
    InterventionType.RETRY_ONLY,
    InterventionType.WHATSAPP_UPI_LINK,
    InterventionType.SMS_REMINDER,
    InterventionType.GRACE_48H,
    InterventionType.PARTIAL_CHARGE,
    InterventionType.METHOD_SWITCH,
    InterventionType.NO_OP,
]


@dataclass
class UpliftModel:
    arm_models: dict[str, HistGradientBoostingClassifier]
    feature_names: list[str]

    @classmethod
    def train(cls, training_json: Path) -> tuple[UpliftModel, dict]:
        raw = json.loads(Path(training_json).read_text(encoding="utf-8"))
        buckets: dict[str, list[tuple[list[float], int, float]]] = {a.value: [] for a in ARMS}
        for row in raw["rows"]:
            arm = _arm_from_key(row["logged_action_key"])
            if arm is None:
                continue
            ev = FailureEvent.model_validate(row["failure_event"])
            diag = TypedDiagnosis(
                cause=FailureCause(row["true_cause"]),
                confidence=1.0,
                rationale="train",
                source="train",
            )
            feats = feature_row(ev, diag)
            x = [feats[n] for n in FEATURE_NAMES]
            y = 1 if row["observed_success"] else 0
            w = min(_IPW_CLIP, 1.0 / max(row["propensity"], 1e-3))
            buckets[arm.value].append((x, y, w))

        arm_models: dict[str, HistGradientBoostingClassifier] = {}
        counts: dict[str, int] = {}
        pos_rate: dict[str, float] = {}
        for arm_key, rows in buckets.items():
            counts[arm_key] = len(rows)
            if len(rows) < 40 or len({r[1] for r in rows}) < 2:
                continue  # too few / single-class -> fall back to a prior at inference
            xm = np.array([r[0] for r in rows], dtype=float)
            ym = np.array([r[1] for r in rows], dtype=int)
            wm = np.array([r[2] for r in rows], dtype=float)
            pos_rate[arm_key] = float(ym.mean())
            clf = HistGradientBoostingClassifier(
                max_depth=3,
                learning_rate=0.08,
                max_iter=60,
                l2_regularization=1.0,
                random_state=0,
            )
            clf.fit(xm, ym, sample_weight=wm)
            arm_models[arm_key] = clf

        model = cls(arm_models=arm_models, feature_names=list(FEATURE_NAMES))
        metrics = {
            "arm_counts": counts,
            "arm_pos_rate": {k: round(v, 3) for k, v in pos_rate.items()},
            "arms_modelled": sorted(arm_models),
        }
        return model, metrics

    # ---- inference ---------------------------------------------------
    def _p(self, arm: str, x: np.ndarray) -> float:
        clf = self.arm_models.get(arm)
        if clf is None:
            return 0.05  # weak prior for an unmodelled arm
        return float(clf.predict_proba(x)[:, 1][0])

    def rank(
        self, event: FailureEvent, diag: TypedDiagnosis
    ) -> list[tuple[InterventionType, float, float]]:
        """Return [(arm, p_recover, uplift_vs_control)] sorted by uplift desc."""
        feats = feature_row(event, diag)
        x = np.array([[feats[n] for n in FEATURE_NAMES]], float)
        p_ctrl = self._p(CONTROL.value, x)
        out = []
        for arm in ARMS:
            p = self._p(arm.value, x)
            out.append((arm, p, p - p_ctrl))
        out.sort(key=lambda t: t[2], reverse=True)
        return out

    # ---- persistence ----------------------------------------------
    def save(self, path: Path | None = None) -> Path:
        import joblib

        p = path or ARTIFACT
        p.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"arm_models": self.arm_models, "feature_names": self.feature_names}, p)
        return p

    @classmethod
    def load(cls, path: Path | None = None) -> UpliftModel:
        import joblib

        d = joblib.load(path or ARTIFACT)
        return cls(arm_models=d["arm_models"], feature_names=d["feature_names"])
