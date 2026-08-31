"""Tamper-evident audit ledger (CLAUDE.md §6).

Every material event (diagnosis, policy decision, execution result, escalation) is written
here. Entries are chained: entry_hash = sha256(prev_hash + canonical_json(payload)).
No code path updates or deletes an existing row. `verify_chain()` recomputes the whole
chain and reports the first break, if any.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import select

from mandatemend.db.models import AuditEntry
from mandatemend.db.session import session_scope

GENESIS = "0" * 64


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _hash(prev_hash: str, payload_json: str) -> str:
    return sha256(f"{prev_hash}{payload_json}".encode()).hexdigest()


def append(mandate_id: str, kind: str, payload: dict) -> str:
    """Append one entry; return its entry_hash."""
    payload_json = _canonical(payload)
    with session_scope() as s:
        last = s.execute(
            select(AuditEntry).order_by(AuditEntry.id.desc()).limit(1)
        ).scalar_one_or_none()
        prev_hash = last.entry_hash if last else GENESIS
        entry_hash = _hash(prev_hash, payload_json)
        s.add(
            AuditEntry(
                ts=datetime.now(UTC),
                mandate_id=mandate_id,
                kind=kind,
                payload_json=payload_json,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
            )
        )
    return entry_hash


def verify_chain() -> tuple[bool, str]:
    """Recompute the chain. Return (ok, message)."""
    with session_scope() as s:
        rows = list(s.execute(select(AuditEntry).order_by(AuditEntry.id.asc())).scalars())
    prev = GENESIS
    for r in rows:
        expect = _hash(prev, r.payload_json)
        if r.prev_hash != prev:
            return False, f"entry {r.id}: prev_hash mismatch (chain broken before it)"
        if r.entry_hash != expect:
            return False, f"entry {r.id}: payload altered (hash mismatch)"
        prev = r.entry_hash
    return True, f"chain OK across {len(rows)} entries"


def entries_for(mandate_id: str) -> list[dict]:
    with session_scope() as s:
        rows = list(
            s.execute(
                select(AuditEntry)
                .where(AuditEntry.mandate_id == mandate_id)
                .order_by(AuditEntry.id.asc())
            ).scalars()
        )
    return [
        {
            "id": r.id,
            "ts": r.ts.isoformat(),
            "kind": r.kind,
            "payload": json.loads(r.payload_json),
            "entry_hash": r.entry_hash[:12],
        }
        for r in rows
    ]
