"""Retry-timing model — discrete-time hazard / survival formulation.

The decision is *when* to retry within the NPCI 3-attempt budget, not *if*. We model the
per-bucket success hazard: pooled logistic / gradient-boosted estimate of
`P(retry succeeds | features, delay_bucket)`, one row per (sample, observed bucket) from the
logging policy. Scoring a candidate delay = evaluating that hazard at the bucket; the
advisor picks the bucket with the highest predicted success. (Discrete-time hazard via
pooled classification is the standard Singer & Willett estimator; survival framing for
soft-collection timing follows Witzany & Kozina 2022 — see the research file.)

Trained only on `logged_action_key` rows that are RETRY / PARTIAL_CHARGE, inverse-propensity
weighted so the biased logging policy does not skew the estimate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from mandatemend.features import FEATURE_NAMES, feature_row
from mandatemend.schemas import FailureCause, FailureEvent, TypedDiagnosis
from mandatemend.simulation import DELAY_BUCKETS_H

ARTIFACT = Path(__file__).resolve().parent / "artifacts" / "retry_timing.joblib"
_IPW_CLIP = 10.0


def _delay_from_key(key: str) -> float | None:
    parts = key.split("|")
    if parts[0] not in ("RETRY", "PARTIAL_CHARGE"):
        return None
    try:
        return float(parts[1])
    except (IndexError, ValueError):
        return None


@dataclass
class RetryTimingModel:
    clf: HistGradientBoostingClassifier
    feature_names: list[str]

    # ---- training -----------------------------------------------------------
    @classmethod
    def train(cls, training_json: Path) -> tuple[RetryTimingModel, dict]:
        raw = json.loads(Path(training_json).read_text(encoding="utf-8"))
        X, y, w = [], [], []
        for row in raw["rows"]:
            delay = _delay_from_key(row["logged_action_key"])
            if delay is None:
                continue
            ev = FailureEvent.model_validate(row["failure_event"])
            # Train on the *true* cause so timing is learned cleanly; at inference the
            # diagnosis stands in for it. (Cause is one input among many.)
            diag = TypedDiagnosis(
                cause=FailureCause(row["true_cause"]),
                confidence=1.0,
                rationale="train",
                source="train",
            )
            feats = feature_row(ev, diag)
            X.append([feats[n] for n in FEATURE_NAMES] + [delay])
            y.append(1 if row["observed_success"] else 0)
            w.append(min(_IPW_CLIP, 1.0 / max(row["propensity"], 1e-3)))

        X_arr, y_arr, w_arr = np.array(X, float), np.array(y, int), np.array(w, float)
        n = len(y_arr)
        cut = int(n * 0.8)
        clf = HistGradientBoostingClassifier(
            max_depth=4,
            learning_rate=0.08,
            max_iter=90,
            l2_regularization=1.0,
            random_state=0,
        )
        clf.fit(X_arr[:cut], y_arr[:cut], sample_weight=w_arr[:cut])

        model = cls(clf=clf, feature_names=[*FEATURE_NAMES, "delay_hours"])
        if len(np.unique(y_arr[cut:])) < 2:
            val_auc = float("nan")
        else:
            val_auc = float(roc_auc_score(y_arr[cut:], clf.predict_proba(X_arr[cut:])[:, 1]))
        return model, {"val_auc": round(val_auc, 4), "n_train_rows": int(cut)}

    # ---- inference --------------------------------------------------------
    def best_delay(self, event: FailureEvent, diag: TypedDiagnosis) -> tuple[float, float]:
        feats = feature_row(event, diag)
        base = [feats[n] for n in FEATURE_NAMES]
        rows = np.array([[*base, d] for d in DELAY_BUCKETS_H], float)
        p = self.clf.predict_proba(rows)[:, 1]
        i = int(np.argmax(p))
        return float(DELAY_BUCKETS_H[i]), float(p[i])

    def curve(self, event: FailureEvent, diag: TypedDiagnosis) -> list[tuple[float, float]]:
        return self.curve_many([(event, diag)])[0]

    def curve_many(
        self, rows: list[tuple[FailureEvent, TypedDiagnosis]]
    ) -> list[list[tuple[float, float]]]:
        """Batched `curve`: one predict_proba over the (N*buckets, F+1) matrix."""
        if not rows:
            return []
        nb = len(DELAY_BUCKETS_H)
        mat = np.array(
            [
                [*(feature_row(ev, dg)[n] for n in FEATURE_NAMES), d]
                for ev, dg in rows
                for d in DELAY_BUCKETS_H
            ],
            dtype=float,
        )
        p = self.clf.predict_proba(mat)[:, 1].reshape(len(rows), nb)
        return [
            [(float(d), float(pi)) for d, pi in zip(DELAY_BUCKETS_H, p[i], strict=True)]
            for i in range(len(rows))
        ]

    # ---- persistence ---------------------------------------------------
    def save(self, path: Path | None = None) -> Path:
        import joblib

        p = path or ARTIFACT
        p.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"clf": self.clf, "feature_names": self.feature_names}, p)
        return p

    @classmethod
    def load(cls, path: Path | None = None) -> RetryTimingModel:
        import joblib

        d = joblib.load(path or ARTIFACT)
        return cls(clf=d["clf"], feature_names=d["feature_names"])
