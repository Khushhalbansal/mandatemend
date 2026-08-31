"""SQLAlchemy models.

`executed_action.idempotency_key` carries a DB-level UNIQUE constraint. That constraint —
not any application-level check — is what makes double execution impossible under concurrent
webhooks (CLAUDE.md §2/§6). The executor does `INSERT`; a duplicate raises `IntegrityError`
which the executor treats as "already done".

`audit_entry` is append-only and hash-chained: each row stores the SHA-256 of
(prev_hash + canonical payload). Any edit or deletion of a past row breaks the chain and is
detected by `mandatemend.audit.ledger.verify_chain` (CLAUDE.md §6 "tamper-evident").

Storage note (CHANGELOG 2026-09-01): Postgres is the real target (docker-compose). The unit
suite runs against SQLite for speed and zero external deps; the UNIQUE-constraint dedup
semantics used here hold identically on both. Integration tests re-run the idempotency proof
against Postgres when MANDATEMEND_DB_URL points at one.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ExecutedAction(Base):
    __tablename__ = "executed_action"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_executed_idem"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    mandate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gateway_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    recovered_amount_paise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)


class AuditEntry(Base):
    __tablename__ = "audit_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mandate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
