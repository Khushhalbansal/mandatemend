"""Tamper-evident audit ledger (CLAUDE.md §6).

Every material event (diagnosis, policy decision, execution result, escalation) is written
here. Entries are chained: entry_hash = sha256(prev_hash + canonical_json(payload)).
No code path updates or deletes an existing row. `verify_chain()` recomputes the whole
chain and reports the first break, if any.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import select

from mandatemend.db.models import AuditEntry
from mandatemend.db.session import session_scope

GENESIS = "0" * 64

# In-process cache of the chain tip. Lets a single-process run skip a SELECT per append
# (the batch runner writes ~2k entries). `None` -> fall back to reading the DB. `verify_chain`
# always recomputes from the DB, so a stale cache can only slow things down, never corrupt.
_last_hash: str | None = None

# `append` is serialised: the executor's dedup path fires it from several webhook threads at
# once, and the chain (read tip -> hash -> insert) must be atomic or two entries collide on
# entry_hash. The system is single-process, so a lock is sufficient and cheap.
_lock = threading.RLock()


def reset_cache() -> None:
    global _last_hash, _buffer
    with _lock:
        _last_hash = None
        _buffer = None


# Optional write buffer: when active, `append` chains entries in memory and queues them; one
# `flush_buffer()` writes them all in a single transaction. Used by the batch runner (~2k
# entries/run) so audit stays ON without a session round-trip per entry. Chain order and
# hashes are identical to the unbuffered path.
_buffer: list[AuditEntry] | None = None


def begin_buffer() -> None:
    global _buffer
    with _lock:
        _buffer = []


def flush_buffer() -> int:
    global _buffer
    with _lock:
        if not _buffer:
            _buffer = None
            return 0
        n = len(_buffer)
        with session_scope() as s:
            s.add_all(_buffer)
        _buffer = None
        return n


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _hash(prev_hash: str, payload_json: str) -> str:
    return sha256(f"{prev_hash}{payload_json}".encode()).hexdigest()


def append(mandate_id: str, kind: str, payload: dict) -> str:
    """Append one entry; return its entry_hash. Serialised so concurrent callers can't
    build two entries off the same chain tip."""
    global _last_hash
    payload_json = _canonical(payload)

    with _lock:
        if _last_hash is None and _buffer is None:
            with session_scope() as s:
                last = s.execute(
                    select(AuditEntry).order_by(AuditEntry.id.desc()).limit(1)
                ).scalar_one_or_none()
                _last_hash = last.entry_hash if last else GENESIS
        prev_hash = _last_hash or GENESIS
        entry_hash = _hash(prev_hash, payload_json)
        row = AuditEntry(
            ts=datetime.now(UTC),
            mandate_id=mandate_id,
            kind=kind,
            payload_json=payload_json,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )
        if _buffer is not None:
            _buffer.append(row)
        else:
            with session_scope() as s:
                s.add(row)
        _last_hash = entry_hash
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
