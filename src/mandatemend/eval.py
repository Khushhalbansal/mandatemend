"""`mandatemend eval` — model-strength diagnostics on the frozen held-out batch.

Three analyses, all *reporting only* — they read the frozen potential-outcomes table as an
oracle (same read-only use as `models/train.py`'s oracle checks) and never feed training:

  * sequencing   — expected recoveries when the retry model *orders* its 3 attempts vs the
                   fixed 24/72/168 ladder (B3).
  * calibration  — reliability + Expected Calibration Error for both models (B4).
  * ablation     — recovery rate / lift for retry-only, uplift-only, both, heuristic-only,
                   naive, on the primary 300-batch (B5). Shows where the +14 pp comes from.

Results are written to `logs/eval.json` and printed.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from mandatemend.agent import Agent
from mandatemend.audit import ledger
from mandatemend.batch.baselines import run_baseline
from mandatemend.batch.run_batch import _load_frozen
from mandatemend.config import settings
from mandatemend.db.session import init_engine
from mandatemend.diagnosis.base import get_diagnoser
from mandatemend.executor.executor import Executor
from mandatemend.executor.gateway import SimulatedGateway
from mandatemend.models.advisors import (
    HeuristicInterventionAdvisor,
    HeuristicRetryAdvisor,
    SurvivalRetryAdvisor,
    TLearnerUpliftAdvisor,
)
from mandatemend.models.retry_timing import RetryTimingModel
from mandatemend.models.uplift import ARMS, UpliftModel
from mandatemend.policy.engine import PolicyEngine
from mandatemend.schemas import ActionType, FailureCause, FailureEvent, InterventionType, TypedDiagnosis
from mandatemend.simulation import DELAY_BUCKETS_H, outcome_key

# One canonical realized-outcome key per uplift arm, so calibration compares the model's
# single-shot p_recover against a single realized execution (not "any variant ever wins",
# which would inflate the observed frequency and the ECE).
_ARM_CANONICAL_KEY: dict[InterventionType, str] = {
    InterventionType.RETRY_ONLY: outcome_key(ActionType.RETRY, 24.0),
    InterventionType.WHATSAPP_UPI_LINK: outcome_key(ActionType.SEND_NOTIFICATION, 24.0, channel="whatsapp"),
    InterventionType.SMS_REMINDER: outcome_key(ActionType.SEND_NOTIFICATION, 24.0, channel="sms"),
    InterventionType.GRACE_48H: outcome_key(ActionType.GRACE_EXTEND, 48.0),
    InterventionType.PARTIAL_CHARGE: outcome_key(ActionType.PARTIAL_CHARGE, 24.0),
    InterventionType.METHOD_SWITCH: outcome_key(ActionType.OFFER_ALTERNATE_METHOD, 0.0),
    InterventionType.NO_OP: outcome_key(ActionType.NO_ACTION, 0.0),
}

EVAL_JSON = Path(settings.iter_log).parent / "eval.json"
_FIXED_LADDER = [24.0, 72.0, 168.0]  # the classic dunning schedule (static_retry baseline)
_NPCI_RETRIES = 3


def _oracle_diag(cause: str) -> TypedDiagnosis:
    return TypedDiagnosis(
        cause=FailureCause(cause), confidence=1.0, rationale="oracle", source="oracle"
    )


# --------------------------------------------------------------------------- B3
def sequencing_eval(model: RetryTimingModel, events: list[FailureEvent], labels: dict) -> dict:
    """For each mandate that has *some* winning RETRY bucket in the realized table: does the
    model's top-3 ordered schedule capture a win? Compare to the fixed 24/72/168 ladder and
    to the model's single best pick. Adaptivity should compound -> top-3 >= ladder."""
    n = model_top3 = model_top1 = ladder = 0
    pred_top3: list[float] = []
    obs_top3: list[int] = []
    for ev in events:
        lab = labels[ev.mandate_id]
        realized = {
            d: lab["outcomes"].get(outcome_key(ActionType.RETRY, d), {}) for d in DELAY_BUCKETS_H
        }
        winners = {d for d, v in realized.items() if v.get("success")}
        if not winners:
            continue
        n += 1
        diag = _oracle_diag(lab["true_cause"])
        ranked = [d for d, _ in sorted(model.hazard_curve(ev, diag), key=lambda t: t[1], reverse=True)]
        model_sched = ranked[:_NPCI_RETRIES]
        model_top3 += any(d in winners for d in model_sched)
        model_top1 += ranked[0] in winners
        ladder += any(d in winners for d in _FIXED_LADDER)
        pred_top3.append(model.expected_recovery_for_schedule(ev, diag, model_sched))
        obs_top3.append(1 if any(d in winners for d in model_sched) else 0)
    return {
        "n_mandates_with_a_winning_retry": n,
        "model_top3_ordered_capture_rate": round(model_top3 / n, 4) if n else None,
        "fixed_ladder_24_72_168_capture_rate": round(ladder / n, 4) if n else None,
        "model_top1_only_capture_rate": round(model_top1 / n, 4) if n else None,
        "model_minus_ladder_pp": round((model_top3 - ladder) / n, 4) if n else None,
        "schedule_prob_calibration": {
            "mean_predicted_recovery": round(float(np.mean(pred_top3)), 4) if pred_top3 else None,
            "mean_observed_recovery": round(float(np.mean(obs_top3)), 4) if obs_top3 else None,
        },
    }


# --------------------------------------------------------------------------- B4
def _ece(pred: np.ndarray, obs: np.ndarray, bins: int = 10) -> dict:
    """Expected / maximum calibration error + the reliability table."""
    if len(pred) == 0:
        return {"ece": None, "mce": None, "n": 0, "reliability": []}
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(pred, edges[1:-1]), 0, bins - 1)
    rel = []
    ece = mce = 0.0
    n = len(pred)
    for b in range(bins):
        m = idx == b
        if not m.any():
            continue
        p_mean, o_mean, cnt = float(pred[m].mean()), float(obs[m].mean()), int(m.sum())
        gap = abs(p_mean - o_mean)
        ece += (cnt / n) * gap
        mce = max(mce, gap)
        rel.append(
            {
                "bin": [round(float(edges[b]), 2), round(float(edges[b + 1]), 2)],
                "n": cnt,
                "mean_predicted": round(p_mean, 4),
                "observed_frequency": round(o_mean, 4),
            }
        )
    return {"ece": round(ece, 4), "mce": round(mce, 4), "n": n, "reliability": rel}


def calibration_eval(
    retry_model: RetryTimingModel,
    uplift_model: UpliftModel,
    events: list[FailureEvent],
    labels: dict,
) -> dict:
    """Predicted probability vs realized frequency on the frozen batch, for both models."""
    r_pred: list[float] = []
    r_obs: list[int] = []
    u_pred: list[float] = []
    u_obs: list[int] = []
    for ev in events:
        lab = labels[ev.mandate_id]
        diag = _oracle_diag(lab["true_cause"])
        haz = dict(retry_model.hazard_curve(ev, diag))
        for d in DELAY_BUCKETS_H:
            entry = lab["outcomes"].get(outcome_key(ActionType.RETRY, d))
            if entry is not None:
                r_pred.append(haz[d])
                r_obs.append(1 if entry["success"] else 0)
        ranked = {arm: p for arm, p, _u in uplift_model.rank(ev, diag)}
        for arm in ARMS:
            entry = lab["outcomes"].get(_ARM_CANONICAL_KEY[arm])
            if entry is None:
                continue
            u_pred.append(ranked[arm])
            u_obs.append(1 if entry["success"] else 0)
    return {
        "retry_timing": _ece(np.array(r_pred), np.array(r_obs)),
        "uplift": _ece(np.array(u_pred), np.array(u_obs)),
    }


# --------------------------------------------------------------------------- B5
def _run_agent_config(
    retry_adv, interv_adv, events: list[FailureEvent], labels: dict
) -> tuple[int, int]:
    """Run the full agent loop with a specific advisor pair; return (recovered, at_risk) paise."""
    init_engine("sqlite://", create=True)
    ledger.reset_cache()
    agent = Agent(
        diagnoser=get_diagnoser(),
        retry_advisor=retry_adv,
        intervention_advisor=interv_adv,
        engine=PolicyEngine(),
        executor=Executor(SimulatedGateway(labels)),
        audit_enabled=False,
    )
    agent.warm(events)
    recovered = at_risk = 0
    for ev in events:
        res = agent.recover(ev)
        at_risk += res.amount_at_risk_paise
        if res.recovered:
            recovered += res.recovered_amount_paise
    return recovered, at_risk


def ablation_eval(events: list[FailureEvent], labels: dict) -> dict:
    """recovery rate + lift vs static-retry for each advisor combination + the naive baseline."""
    naive = run_baseline("static_retry", labels)
    naive_rate = naive["recovery_rate"]
    configs = {
        "heuristic_retry + heuristic_uplift": (HeuristicRetryAdvisor(), HeuristicInterventionAdvisor()),
        "survival_retry + heuristic_uplift": (SurvivalRetryAdvisor(), HeuristicInterventionAdvisor()),
        "heuristic_retry + t_learner_uplift": (HeuristicRetryAdvisor(), TLearnerUpliftAdvisor()),
        "survival_retry + t_learner_uplift (shipped)": (
            SurvivalRetryAdvisor(),
            TLearnerUpliftAdvisor(),
        ),
    }
    rows = [
        {
            "config": "naive static-retry ladder (no agent)",
            "recovery_rate": round(naive_rate, 4),
            "lift_vs_static_pp": 0.0,
        }
    ]
    for name, (ra, ia) in configs.items():
        rec, risk = _run_agent_config(ra, ia, events, labels)
        rate = rec / risk if risk else 0.0
        rows.append(
            {
                "config": name,
                "recovery_rate": round(rate, 4),
                "lift_vs_static_pp": round(rate - naive_rate, 4),
            }
        )
    return {"baseline_static_recovery_rate": round(naive_rate, 4), "table": rows}


# --------------------------------------------------------------------------- driver
def run_all(*, do_sequencing: bool = True, do_calibration: bool = True, do_ablation: bool = True) -> dict:
    events, labels = _load_frozen()
    retry_model = RetryTimingModel.load()
    uplift_model = UpliftModel.load()
    out: dict = {}
    if do_sequencing:
        out["sequencing"] = sequencing_eval(retry_model, events, labels)
    if do_calibration:
        out["calibration"] = calibration_eval(retry_model, uplift_model, events, labels)
    if do_ablation:
        out["ablation"] = ablation_eval(events, labels)
    return out


def format_report(out: dict) -> str:
    lines: list[str] = ["MandateMend model-strength evaluation", ""]
    if "sequencing" in out:
        s = out["sequencing"]
        lines += [
            "SEQUENCING  (does ordering the 3 retries beat the fixed ladder?)",
            f"  n mandates with a winning retry bucket   {s['n_mandates_with_a_winning_retry']}",
            f"  model top-3 ordered captures a win       {s['model_top3_ordered_capture_rate']}",
            f"  fixed 24/72/168 ladder captures a win    {s['fixed_ladder_24_72_168_capture_rate']}",
            f"  model single best pick captures a win    {s['model_top1_only_capture_rate']}",
            f"  model - ladder                           {s['model_minus_ladder_pp']:+.4f}",
            f"  schedule prob calibration  pred {s['schedule_prob_calibration']['mean_predicted_recovery']}"
            f"  obs {s['schedule_prob_calibration']['mean_observed_recovery']}",
            "",
        ]
    if "calibration" in out:
        for name in ("retry_timing", "uplift"):
            c = out["calibration"][name]
            lines += [
                f"CALIBRATION [{name}]   ECE {c['ece']}   MCE {c['mce']}   n {c['n']}",
                "  bin            n     pred    observed",
            ]
            for r in c["reliability"]:
                lines.append(
                    f"  [{r['bin'][0]:.2f},{r['bin'][1]:.2f}) {r['n']:6d}  "
                    f"{r['mean_predicted']:.3f}   {r['observed_frequency']:.3f}"
                )
            lines.append("")
    if "ablation" in out:
        lines += [
            "ABLATION  (frozen 300-batch, recovery rate / lift vs static-retry)",
            f"  {'config':<44s} {'recovery':>9s} {'lift pp':>9s}",
        ]
        for r in out["ablation"]["table"]:
            lines.append(
                f"  {r['config']:<44s} {r['recovery_rate'] * 100:8.2f}% {r['lift_vs_static_pp'] * 100:+8.2f}"
            )
        lines.append("")
    return "\n".join(lines)
