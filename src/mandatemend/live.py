"""One real Razorpay **test-mode** round-trip, wired through the executor + audit ledger.

This is additive and isolated from batch scoring (CLAUDE.md §1.3): `run_batch` never touches
the network and always uses the SimulatedGateway against the frozen batch. `run_live_check`
takes one real mandate from the frozen batch (read-only), synthesises a single RETRY action,
and runs it through the *real* `Executor` -> `RazorpayTestGateway` path so the proof covers
the executor's reserve/execute/finalize + the hash-chained audit entry, not just an HTTP
call. Test mode cannot force a debit result, so the outcome is "connectivity proven", not
"recovered".

Artifacts (both gitignored):
  logs/live_audit.sqlite         persistent audit DB for the round-trip
  logs/last_live_roundtrip.json  sidecar the operator console surfaces
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from mandatemend import POLICY_VERSION
from mandatemend.audit import ledger
from mandatemend.batch.run_batch import _load_frozen
from mandatemend.config import REPO_ROOT
from mandatemend.db.session import init_engine
from mandatemend.diagnosis.base import get_diagnoser
from mandatemend.executor.executor import Executor
from mandatemend.executor.gateway import RazorpayTestGateway
from mandatemend.schemas import Action, ActionType, RuleEvaluation

LIVE_DB = REPO_ROOT / "logs" / "live_audit.sqlite"
SIDECAR = REPO_ROOT / "logs" / "last_live_roundtrip.json"


def run_live_check(mandate_id: str | None = None) -> dict:
    events, _labels = _load_frozen()
    ev = (
        events[0]
        if mandate_id is None
        else next((e for e in events if e.mandate_id == mandate_id), None)
    )
    if ev is None:
        raise SystemExit(f"no such mandate in the frozen batch: {mandate_id}")

    LIVE_DB.parent.mkdir(parents=True, exist_ok=True)
    init_engine(f"sqlite:///{LIVE_DB.as_posix()}", create=True)
    ledger.reset_cache()

    diag = get_diagnoser().diagnose(ev)  # offline heuristic
    ledger.append(ev.mandate_id, "diagnosis", diag.model_dump())

    gw = RazorpayTestGateway()
    now = datetime.now(UTC)
    action = Action(
        action_type=ActionType.RETRY,
        mandate_id=ev.mandate_id,
        idempotency_key=f"live-{ev.mandate_id}-{int(time.time())}",
        scheduled_at=now,
        amount_paise=ev.amount_paise,
        retry_delay_bucket=24.0,
        reason="live Razorpay test-mode connectivity round-trip (not scored)",
        rule_trace=[
            RuleEvaluation(
                rule="live_check",
                passed=True,
                detail="manual round-trip; not a policy decision, not part of the frozen-batch score",
            )
        ],
        policy_version=POLICY_VERSION,
        diagnosis=diag,
    )

    result = Executor(gw).execute(action, ev)  # real POST /v1/payment_links + audit entry
    ok_chain, chain_msg = ledger.verify_chain()
    resp = gw.last_response or {}

    out = {
        "ts": now.isoformat(),
        "mandate_id": ev.mandate_id,
        "action": action.action_type.value,
        "amount_paise": action.amount_paise,
        "gateway": gw.name,
        "http": resp.get("http"),
        "payment_link_id": resp.get("id"),
        "short_url": resp.get("short_url"),
        "status": resp.get("status"),
        "executed": result.executed,
        "detail": result.detail,
        "audit_chain": chain_msg,
        "audit_chain_ok": ok_chain,
        "note": "test mode cannot force a debit outcome; this proves connectivity, not recovery",
    }
    SIDECAR.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def load_last() -> dict | None:
    try:
        return json.loads(SIDECAR.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
