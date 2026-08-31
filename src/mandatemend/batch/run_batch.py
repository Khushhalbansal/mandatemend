"""Run the agent over the frozen held-out batch and build a Scorecard.

The held-out batch + labels are read-only inputs. This module never writes to them
(CLAUDE.md §1.3). It writes a throwaway SQLite DB under logs/ for the executor + audit
ledger, wiped at the start of every run so a run is reproducible.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from mandatemend import __version__
from mandatemend.agent import Agent
from mandatemend.audit import ledger
from mandatemend.batch.baselines import run_baseline
from mandatemend.config import settings
from mandatemend.db.session import init_engine
from mandatemend.executor.gateway import SimulatedGateway
from mandatemend.invariants import check_resolution
from mandatemend.schemas import FailureEvent, Scorecard

_RUN_DB = Path(settings.iter_log).parent / "run_batch.sqlite"


def _load_frozen() -> tuple[list[FailureEvent], dict]:
    batch = json.loads(Path(settings.heldout_batch).read_text(encoding="utf-8"))
    labels = json.loads(Path(settings.heldout_labels).read_text(encoding="utf-8"))
    events = [FailureEvent.model_validate(e) for e in batch["events"]]
    return events, labels["labels"]


def run(*, iteration: int = 0, note: str = "", git_sha: str | None = None) -> Scorecard:
    events, labels = _load_frozen()

    _RUN_DB.parent.mkdir(parents=True, exist_ok=True)
    if _RUN_DB.exists():
        _RUN_DB.unlink()
    init_engine(f"sqlite:///{_RUN_DB.as_posix()}", create=True)

    gateway = SimulatedGateway(labels)
    agent = Agent.default(gateway=gateway, audit_enabled=True)

    at_risk = recovered = n_recovered = retries_total = 0
    unnecessary_contacts = escalated = violations = 0

    for ev in events:
        res = agent.recover(ev)
        at_risk += res.amount_at_risk_paise
        retries_total += res.retries_used
        if res.recovered:
            recovered += res.recovered_amount_paise
            n_recovered += 1
        else:
            unnecessary_contacts += res.contacts_made
        if res.escalated_to_human:
            escalated += 1
        violations += len(check_resolution(ev, res))

    ok_chain, chain_msg = ledger.verify_chain()
    if not ok_chain:
        violations += 1  # a broken audit chain is a compliance failure

    base = {name: run_baseline(name, labels) for name in ("static_retry", "email_only", "single_retry")}
    agent_rate = recovered / at_risk if at_risk else 0.0

    sc = Scorecard(
        iteration=iteration,
        ts=datetime.now(UTC),
        git_sha=git_sha,
        note=(note + f" | audit_chain: {chain_msg}").strip(" |"),
        batch_size=len(events),
        amount_at_risk_paise=at_risk,
        recovered_paise=recovered,
        batch_recovery_rate=round(agent_rate, 4),
        baseline_static_recovery_rate=round(base["static_retry"]["recovery_rate"], 4),
        baseline_email_only_recovery_rate=round(base["email_only"]["recovery_rate"], 4),
        baseline_single_retry_recovery_rate=round(base["single_retry"]["recovery_rate"], 4),
        baseline_lift=round(agent_rate - base["static_retry"]["recovery_rate"], 4),
        retries_used_total=retries_total,
        recoveries_per_retry=round(n_recovered / retries_total, 4) if retries_total else 0.0,
        unnecessary_contacts=unnecessary_contacts,
        escalated_count=escalated,
        compliance_violations=violations,
    )
    return sc


def format_scorecard(sc: Scorecard) -> str:
    pct = lambda x: f"{x * 100:6.2f}%"  # noqa: E731
    rupees = lambda p: f"Rs {p / 100:,.0f}"  # noqa: E731
    lines = [
        f"MandateMend batch scorecard  (v{__version__}, iteration {sc.iteration})",
        f"  batch size                 {sc.batch_size}",
        f"  amount at risk             {rupees(sc.amount_at_risk_paise)}",
        f"  recovered (agent)          {rupees(sc.recovered_paise)}   {pct(sc.batch_recovery_rate)}",
        f"  baseline static-retry      {pct(sc.baseline_static_recovery_rate)}",
        f"  baseline single-retry      {pct(sc.baseline_single_retry_recovery_rate)}",
        f"  baseline email-only        {pct(sc.baseline_email_only_recovery_rate)}",
        f"  LIFT vs static-retry       {pct(sc.baseline_lift)}",
        f"  retries used (total)       {sc.retries_used_total}",
        f"  recoveries / retry         {sc.recoveries_per_retry}",
        f"  contacts on non-recovered  {sc.unnecessary_contacts}",
        f"  escalated to human         {sc.escalated_count}",
        f"  COMPLIANCE VIOLATIONS      {sc.compliance_violations}",
    ]
    if sc.compliance_violations:
        lines.append("  >>> STOP-THE-LINE: compliance_violations > 0 (CLAUDE.md §3.1) <<<")
    return "\n".join(lines)


if __name__ == "__main__":
    card = run()
    print(format_scorecard(card))
