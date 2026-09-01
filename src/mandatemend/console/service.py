"""Runs one batch on startup, keeps results + audit entries in memory for the console."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from mandatemend.agent import Agent
from mandatemend.audit import ledger
from mandatemend.batch.baselines import run_baseline
from mandatemend.batch.run_batch import _load_frozen
from mandatemend.config import settings as _s
from mandatemend.db.session import init_engine
from mandatemend.executor.gateway import SimulatedGateway
from mandatemend.invariants import check_resolution
from mandatemend.schemas import FailureEvent, MandateResolution


@dataclass
class Row:
    event: FailureEvent
    resolution: MandateResolution
    true_cause: str
    true_churn: bool
    violations: list[str]


@dataclass
class BatchView:
    built_at: datetime
    rows: list[Row] = field(default_factory=list)
    scorecard: dict = field(default_factory=dict)
    per_cause: list[dict] = field(default_factory=list)
    audit_ok: bool = True
    audit_msg: str = ""
    live_roundtrip: dict | None = None  # last real Razorpay test-mode call (mandatemend live-check)

    def by_id(self, mandate_id: str) -> Row | None:
        return next((r for r in self.rows if r.event.mandate_id == mandate_id), None)


_VIEW: BatchView | None = None


def build() -> BatchView:
    global _VIEW
    events, labels = _load_frozen()
    init_engine("sqlite://", create=True)
    ledger.reset_cache()

    agent = Agent.default(gateway=SimulatedGateway(labels), audit_enabled=True)
    agent.warm(events)
    from mandatemend.batch.baselines import BASELINES
    from mandatemend.batch.run_batch import _bootstrap_ci, wilson_interval

    static_fn = BASELINES["static_retry"]
    rows: list[Row] = []
    at_risk = recovered = n_rec = retries = escalated = viol = harm = 0
    a_rec: list[int] = []
    s_rec: list[int] = []
    risk_v: list[int] = []
    pc: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "rec": 0, "amt_risk": 0, "amt_rec": 0, "esc": 0}
    )

    for ev in events:
        res = agent.recover(ev)
        lab = labels[ev.mandate_id]
        v = check_resolution(ev, res)
        rows.append(Row(ev, res, lab["true_cause"], bool(lab["true_churn_intent"]), v))

        at_risk += res.amount_at_risk_paise
        retries += res.retries_used
        viol += len(v)
        risk_v.append(res.amount_at_risk_paise)
        a_rec.append(res.recovered_amount_paise if res.recovered else 0)
        b = static_fn(lab["outcomes"], res.amount_at_risk_paise)
        s_rec.append(b.recovered_paise if b.recovered else 0)
        if res.recovered:
            recovered += res.recovered_amount_paise
            n_rec += 1
        else:
            harm += res.contacts_made * _s.outreach_cost_paise  # paid outreach on a lost mandate
        if res.escalated_to_human:
            escalated += 1
        d = pc[lab["true_cause"]]
        d["n"] += 1
        d["amt_risk"] += res.amount_at_risk_paise
        if res.recovered:
            d["rec"] += 1
            d["amt_rec"] += res.recovered_amount_paise
        if res.escalated_to_human:
            d["esc"] += 1

    ok, msg = ledger.verify_chain()
    base = {n: run_baseline(n, labels) for n in ("static_retry", "single_retry", "email_only")}
    rate = recovered / at_risk if at_risk else 0.0
    import numpy as np

    rate_ci, lift_ci = _bootstrap_ci(np.array(a_rec), np.array(s_rec), np.array(risk_v))

    _VIEW = BatchView(
        built_at=datetime.now(UTC),
        rows=rows,
        scorecard={
            "batch_size": len(events),
            "amount_at_risk_paise": at_risk,
            "recovered_paise": recovered,
            "recovery_rate": rate,
            "recovery_rate_ci": rate_ci,
            "lift_ci": lift_ci,
            "harm_cost_paise": harm,
            "n_recovered": n_rec,
            "retries_total": retries,
            "recoveries_per_retry": (n_rec / retries) if retries else 0.0,
            "escalated": escalated,
            "compliance_violations": viol + (0 if ok else 1),
            "baseline_static": base["static_retry"]["recovery_rate"],
            "baseline_single": base["single_retry"]["recovery_rate"],
            "baseline_email": base["email_only"]["recovery_rate"],
            "lift_vs_static": rate - base["static_retry"]["recovery_rate"],
        },
        per_cause=[
            {
                "cause": c,
                "n": d["n"],
                "recovered": d["rec"],
                "rate": d["rec"] / d["n"] if d["n"] else 0.0,
                "rate_ci": list(wilson_interval(d["rec"], d["n"])),
                "amt_risk": d["amt_risk"],
                "amt_rec": d["amt_rec"],
                "escalated": d["esc"],
            }
            for c, d in sorted(pc.items())
        ],
        audit_ok=ok,
        audit_msg=msg,
        live_roundtrip=_load_live(),
    )
    return _VIEW


def _load_live() -> dict | None:
    from mandatemend.live import load_last

    return load_last()


def view() -> BatchView:
    return _VIEW or build()


def evidence_pack(mandate_id: str) -> dict | None:
    r = (_VIEW or build()).by_id(mandate_id)
    if r is None:
        return None
    return {
        "mandate_id": mandate_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "failure_event": r.event.model_dump(mode="json"),
        "true_cause": r.true_cause,
        "resolution": r.resolution.model_dump(mode="json"),
        "compliance_violations": r.violations,
        "audit_trail": ledger.entries_for(mandate_id),
    }
