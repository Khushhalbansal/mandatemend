"""Run the agent over the frozen held-out batch and build a Scorecard.

The held-out batch + labels are read-only inputs; this module never writes to them
(CLAUDE.md §1.3). The executor + audit ledger run against a fresh in-memory SQLite DB per
run (no fsync -> ~9s instead of minutes); the DB-UNIQUE idempotency guarantee is identical
in memory, and the concurrent-webhook proof lives in the integration test against a file DB.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from mandatemend import __version__
from mandatemend.agent import Agent
from mandatemend.audit import ledger
from mandatemend.batch.baselines import BASELINES, run_baseline
from mandatemend.config import settings
from mandatemend.db.session import init_engine
from mandatemend.executor.gateway import SimulatedGateway
from mandatemend.invariants import check_resolution
from mandatemend.schemas import FailureEvent, Scorecard

_BOOTSTRAP = 2000
_BOOTSTRAP_SEED = 20260901


def _batch_paths(batch: str = "primary") -> tuple[Path, Path]:
    if batch == "v2":
        return Path(settings.heldout_batch_v2), Path(settings.heldout_labels_v2)
    if batch == "primary":
        return Path(settings.heldout_batch), Path(settings.heldout_labels)
    raise ValueError(f"unknown batch {batch!r} (expected 'primary' or 'v2')")


def _load_frozen(batch: str = "primary") -> tuple[list[FailureEvent], dict]:
    b_path, l_path = _batch_paths(batch)
    batch_json = json.loads(b_path.read_text(encoding="utf-8"))
    labels = json.loads(l_path.read_text(encoding="utf-8"))
    events = [FailureEvent.model_validate(e) for e in batch_json["events"]]
    return events, labels["labels"]


def _bootstrap_ci(
    agent_rec: np.ndarray, base_rec: np.ndarray, at_risk: np.ndarray
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Mandate-resampled 95% CIs for the money-weighted agent recovery rate and the lift.

    Vectorised: one (B, n) index matrix, gather + sum along the mandate axis.
    """
    rng = np.random.default_rng(_BOOTSTRAP_SEED)
    n = len(at_risk)
    idx = rng.integers(0, n, size=(_BOOTSTRAP, n))
    risk = at_risk[idx].sum(axis=1)
    risk = np.where(risk == 0, 1, risk)
    rates = agent_rec[idx].sum(axis=1) / risk
    lifts = rates - base_rec[idx].sum(axis=1) / risk
    return (
        (round(float(np.percentile(rates, 2.5)), 4), round(float(np.percentile(rates, 97.5)), 4)),
        (round(float(np.percentile(lifts, 2.5)), 4), round(float(np.percentile(lifts, 97.5)), 4)),
    )


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion k/n. Unlike the normal
    approximation it stays inside [0, 1] and is sensible at small n — which is the point:
    the per-cause buckets (MANDATE_PAUSED n≈18, SUSPECTED_CHURN n≈14) must show honestly
    wide bounds, not a bare point estimate."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (round(max(0.0, center - half), 4), round(min(1.0, center + half), 4))


def _load_reauth(batch: str) -> dict[str, dict]:
    """v2 REQUEST_REAUTH outcomes, if the (separately-frozen) supplement is present."""
    if batch != "v2":
        return {}
    p = Path(settings.heldout_reauth_v2)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("reauth", {})


def run(
    *, iteration: int = 0, note: str = "", git_sha: str | None = None, batch: str = "primary"
) -> Scorecard:
    events, labels = _load_frozen(batch)
    reauth = _load_reauth(batch)
    if batch != "primary":
        note = f"[batch={batch}{' +reauth' if reauth else ''}] {note}".strip()

    init_engine("sqlite://", create=True)
    ledger.reset_cache()
    ledger.begin_buffer()

    agent = Agent.default(
        gateway=SimulatedGateway(labels, reauth_outcomes=reauth), audit_enabled=True
    )
    agent.warm(events)  # batch-precompute model inference

    n = len(events)
    at_risk = np.zeros(n, dtype=np.int64)
    agent_rec = np.zeros(n, dtype=np.int64)
    static_rec = np.zeros(n, dtype=np.int64)
    retries_total = n_recovered = escalated = violations = 0
    unnecessary_contacts = harm_cost = 0
    pc: dict[str, dict] = defaultdict(lambda: {"n": 0, "rec": 0, "amt_risk": 0, "amt_rec": 0, "esc": 0})

    static_fn = BASELINES["static_retry"]
    for i, ev in enumerate(events):
        res = agent.recover(ev)
        lab = labels[ev.mandate_id]
        at_risk[i] = res.amount_at_risk_paise
        retries_total += res.retries_used
        if res.recovered:
            agent_rec[i] = res.recovered_amount_paise
            n_recovered += 1
        else:
            # False-positive / harm cost: paid outreach spent on a mandate that never
            # recovered. (Over-cap charges are impossible — the policy engine blocks them,
            # proven by test_policy_engine; over-charging is therefore not in this total.)
            unnecessary_contacts += res.contacts_made
            harm_cost += res.contacts_made * settings.outreach_cost_paise
        if res.escalated_to_human:
            escalated += 1
        violations += len(check_resolution(ev, res))

        b = static_fn(lab["outcomes"], res.amount_at_risk_paise)
        if b.recovered:
            static_rec[i] = b.recovered_paise

        d = pc[lab["true_cause"]]
        d["n"] += 1
        d["amt_risk"] += res.amount_at_risk_paise
        if res.recovered:
            d["rec"] += 1
            d["amt_rec"] += res.recovered_amount_paise
        if res.escalated_to_human:
            d["esc"] += 1

    ledger.flush_buffer()
    ok_chain, chain_msg = ledger.verify_chain()
    if not ok_chain:
        violations += 1

    total_risk = int(at_risk.sum())
    total_agent = int(agent_rec.sum())
    agent_rate = total_agent / total_risk if total_risk else 0.0
    base = {b: run_baseline(b, labels) for b in ("static_retry", "email_only", "single_retry")}
    rate_ci, lift_ci = _bootstrap_ci(agent_rec, static_rec, at_risk)

    return Scorecard(
        iteration=iteration,
        ts=datetime.now(UTC),
        git_sha=git_sha,
        note=(note + f" | audit_chain: {chain_msg}").strip(" |"),
        batch_size=n,
        amount_at_risk_paise=total_risk,
        recovered_paise=total_agent,
        batch_recovery_rate=round(agent_rate, 4),
        recovery_rate_ci=rate_ci,
        baseline_lift_ci=lift_ci,
        baseline_static_recovery_rate=round(base["static_retry"]["recovery_rate"], 4),
        baseline_email_only_recovery_rate=round(base["email_only"]["recovery_rate"], 4),
        baseline_single_retry_recovery_rate=round(base["single_retry"]["recovery_rate"], 4),
        baseline_lift=round(agent_rate - base["static_retry"]["recovery_rate"], 4),
        retries_used_total=retries_total,
        recoveries_per_retry=round(n_recovered / retries_total, 4) if retries_total else 0.0,
        unnecessary_contacts=unnecessary_contacts,
        harm_cost_paise=int(harm_cost),
        escalated_count=escalated,
        compliance_violations=violations,
        per_cause=[
            {
                "cause": c,
                "n": v["n"],
                "recovered": v["rec"],
                "rate": round(v["rec"] / v["n"], 4) if v["n"] else 0.0,
                "rate_ci": list(wilson_interval(v["rec"], v["n"])),
                "amt_risk_paise": v["amt_risk"],
                "amt_recovered_paise": v["amt_rec"],
                "escalated": v["esc"],
            }
            for c, v in sorted(pc.items())
        ],
    )


def format_scorecard(sc: Scorecard) -> str:
    pct = lambda x: f"{x * 100:.2f}%"  # noqa: E731
    rupees = lambda p: f"Rs {p / 100:,.0f}"  # noqa: E731
    rl, rh = sc.recovery_rate_ci
    ll, lh = sc.baseline_lift_ci
    lines = [
        f"MandateMend batch scorecard  (v{__version__}, iteration {sc.iteration})",
        f"  batch size                 {sc.batch_size}",
        f"  amount at risk             {rupees(sc.amount_at_risk_paise)}",
        f"  recovered (agent)          {rupees(sc.recovered_paise)}   {pct(sc.batch_recovery_rate)}"
        f"   95% CI [{pct(rl)}, {pct(rh)}]",
        f"  baseline static-retry      {pct(sc.baseline_static_recovery_rate)}",
        f"  baseline single-retry      {pct(sc.baseline_single_retry_recovery_rate)}",
        f"  baseline email-only        {pct(sc.baseline_email_only_recovery_rate)}",
        f"  LIFT vs static-retry       {pct(sc.baseline_lift)}   95% CI [{pct(ll)}, {pct(lh)}]",
        f"  retries used (total)       {sc.retries_used_total}",
        f"  recoveries / retry         {sc.recoveries_per_retry}",
        f"  contacts on non-recovered  {sc.unnecessary_contacts}   harm cost {rupees(sc.harm_cost_paise)}",
        f"  escalated to human         {sc.escalated_count}",
        f"  COMPLIANCE VIOLATIONS      {sc.compliance_violations}",
    ]
    if sc.per_cause:
        lines.append("  per cause (rate with 95% Wilson CI):")
        for c in sc.per_cause:
            lo, hi = c.get("rate_ci", [c["rate"], c["rate"]])
            lines.append(
                f"    {c['cause']:<20} n={c['n']:<4} rec={c['recovered']:<4} "
                f"{pct(c['rate']):>7}  [{pct(lo)}, {pct(hi)}]  esc={c['escalated']}"
            )
    if sc.compliance_violations:
        lines.append("  >>> STOP-THE-LINE: compliance_violations > 0 (CLAUDE.md §3.1) <<<")
    return "\n".join(lines)


if __name__ == "__main__":
    card = run()
    print(format_scorecard(card))
