"""Retry-timing model — discrete-time hazard / survival analysis.

The decision is *when* to retry within the NPCI 3-attempt budget, not *if*. We model the
**discrete-time hazard**

    h(t | x) = P(a retry first succeeds in delay-bucket t | it has not succeeded before t, x)

with a pooled gradient-boosted classifier over person-period rows `(x, bucket_index) ->
event_in_bucket`, inverse-propensity weighted so the biased logging policy does not skew the
estimate. This is the Singer & Willett estimator (Singer & Willett 2003, *Applied
Longitudinal Data Analysis*, ch. 10-12 — discrete-time hazard via pooled logistic
regression); the survival framing for soft-collection timing follows Witzany & Kozina 2022
(see `docs/RESEARCH.md`).

Data caveat, stated honestly: the logging policy tries exactly **one** delay per mandate, so
each mandate contributes a single person-period observation at its logged bucket — we do not
synthesise risk-set rows for un-tried earlier buckets. The pooled hazard is still the
Singer & Willett form, fit on a sparse person-period design. The survival composition
`S(t) = Π_{s≤t}(1 - h(s))` assumes bucket-conditional independence given `x`, which holds by
construction in the simulator (each `RETRY@d` potential outcome is realised by its own draw).

Derived quantities exposed for the policy engine and the sequencing evaluation:
  * `hazard_curve`      — h(t) per bucket (this is the legacy `curve`)
  * `survival_curve`    — S(t) = Π_{s≤t}(1 - h(s))
  * `recovery_curve`    — 1 - S(t), cumulative P(recovered by bucket t)
  * `expected_recovery_for_schedule` — 1 - Π(1 - h(b)) over an ordered set of ≤3 buckets
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, roc_auc_score

from mandatemend.features import FEATURE_NAMES, feature_row
from mandatemend.schemas import FailureCause, FailureEvent, TypedDiagnosis
from mandatemend.simulation import DELAY_BUCKETS_H

ARTIFACT = Path(__file__).resolve().parent / "artifacts" / "retry_timing.joblib"
_IPW_CLIP = 10.0
_VAL_SPLIT = 0.8  # first 80% train, last 20% for the reported metric (see train())

# Ordinal position of each delay bucket on the discrete-time clock t = 0, 1, 2, ...
# Used only to *stratify the reported metrics by bucket*; the model feature stays the raw
# delay in hours (a monotone transform, identical splits for the GBM, and it keeps the
# saved artifact byte-comparable to the pre-reframe model).
_BUCKET_INDEX: dict[float, int] = {d: i for i, d in enumerate(DELAY_BUCKETS_H)}


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
    def _design(cls, training_json: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Person-period design: one row per training mandate at its logged delay bucket.
        X = [features..., delay_hours], y = success-in-that-bucket, w = IPW. `t_arr` is the
        ordinal bucket index, carried separately for metric stratification only."""
        raw = json.loads(Path(training_json).read_text(encoding="utf-8"))
        X: list[list[float]] = []
        y: list[int] = []
        w: list[float] = []
        tcol: list[int] = []
        for row in raw["rows"]:
            delay = _delay_from_key(row["logged_action_key"])
            if delay is None or delay not in _BUCKET_INDEX:
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
            tcol.append(_BUCKET_INDEX[delay])
        return (
            np.array(X, float),
            np.array(y, int),
            np.array(w, float),
            np.array(tcol, int),
        )

    @classmethod
    def train(cls, training_json: Path) -> tuple[RetryTimingModel, dict]:
        X_arr, y_arr, w_arr, t_arr = cls._design(Path(training_json))
        n = len(y_arr)
        cut = int(n * _VAL_SPLIT)

        clf = HistGradientBoostingClassifier(
            max_depth=4,
            learning_rate=0.08,
            max_iter=200,
            l2_regularization=1.0,
            random_state=0,
        )
        clf.fit(X_arr[:cut], y_arr[:cut], sample_weight=w_arr[:cut])

        p_val = clf.predict_proba(X_arr[cut:])[:, 1]
        metrics = cls._time_aware_metrics(y_arr[cut:], p_val, t_arr[cut:])
        metrics["n_person_periods"] = int(n)
        metrics["n_train_rows"] = int(cut)

        model = cls(clf=clf, feature_names=[*FEATURE_NAMES, "delay_hours"])
        return model, metrics

    @staticmethod
    def _time_aware_metrics(y: np.ndarray, p: np.ndarray, t: np.ndarray) -> dict:
        """AUC + Brier overall, per discrete-time bucket, and the integrated Brier score."""
        overall_auc = (
            float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else float("nan")
        )
        per_bucket: dict[str, dict] = {}
        briers: list[float] = []
        for ti in sorted(np.unique(t)):
            m = t == ti
            yi, pi = y[m], p[m]
            b = float(brier_score_loss(yi, pi)) if len(yi) else float("nan")
            per_bucket[str(DELAY_BUCKETS_H[ti])] = {
                "n": int(m.sum()),
                "event_rate": round(float(yi.mean()), 4) if len(yi) else None,
                "auc": (
                    round(float(roc_auc_score(yi, pi)), 4)
                    if len(np.unique(yi)) == 2
                    else None
                ),
                "brier": round(b, 4) if b == b else None,  # b==b filters NaN
            }
            if b == b:
                briers.append(b)
        return {
            "val_auc": round(overall_auc, 4) if overall_auc == overall_auc else None,
            "val_brier": round(float(brier_score_loss(y, p)), 4) if len(y) else None,
            "integrated_brier_score": round(float(np.mean(briers)), 4) if briers else None,
            "per_bucket": per_bucket,
        }

    # ---- inference --------------------------------------------------------
    def hazard_curve(
        self, event: FailureEvent, diag: TypedDiagnosis
    ) -> list[tuple[float, float]]:
        """h(t) per bucket."""
        return self.curve_many([(event, diag)])[0]

    # legacy alias — advisors + existing tests call `.curve` / `.curve_many`
    def curve(self, event: FailureEvent, diag: TypedDiagnosis) -> list[tuple[float, float]]:
        return self.hazard_curve(event, diag)

    def curve_many(
        self, rows: list[tuple[FailureEvent, TypedDiagnosis]]
    ) -> list[list[tuple[float, float]]]:
        """Batched hazard curve: one predict_proba over the (N*buckets, F+1) matrix."""
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

    def best_delay(self, event: FailureEvent, diag: TypedDiagnosis) -> tuple[float, float]:
        """The single delay bucket with the highest hazard (one retry per NPCI round)."""
        hz = self.hazard_curve(event, diag)
        d, p = max(hz, key=lambda t: t[1])
        return float(d), float(p)

    def survival_curve(
        self, event: FailureEvent, diag: TypedDiagnosis
    ) -> list[tuple[float, float]]:
        """S(t) = Π_{s≤t}(1 - h(s)) — P(still unrecovered after bucket t)."""
        s = 1.0
        out: list[tuple[float, float]] = []
        for d, h in self.hazard_curve(event, diag):
            s *= 1.0 - h
            out.append((float(d), float(s)))
        return out

    def recovery_curve(
        self, event: FailureEvent, diag: TypedDiagnosis
    ) -> list[tuple[float, float]]:
        """1 - S(t) — cumulative P(recovered by bucket t) if every bucket were retried."""
        return [(d, 1.0 - s) for d, s in self.survival_curve(event, diag)]

    def expected_recovery_for_schedule(
        self,
        event: FailureEvent,
        diag: TypedDiagnosis,
        ordered_buckets: list[float],
    ) -> float:
        """P(recovered) = 1 - Π_{b in schedule}(1 - h(b)) — the composed survival for an
        ordered retry schedule of (typically) up to 3 buckets. Order does not change this
        product; it matters when a downstream cost/deadline truncates the schedule."""
        hz = dict(self.hazard_curve(event, diag))
        surv = 1.0
        for b in ordered_buckets:
            surv *= 1.0 - hz.get(float(b), 0.0)
        return float(1.0 - surv)

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
