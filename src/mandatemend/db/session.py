from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from mandatemend.config import settings
from mandatemend.db.models import Base

_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def _make_engine(url: str) -> Engine:
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    eng = create_engine(url, future=True, connect_args=connect_args)
    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _fk_and_wal(dbapi_conn, _rec):  # pragma: no cover - driver glue
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    return eng


def init_engine(url: str | None = None, *, create: bool = True) -> Engine:
    global _engine, _Session
    _engine = _make_engine(url or settings.db_url)
    _Session = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    if create:
        Base.metadata.create_all(_engine)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    if _Session is None:
        init_engine()
    assert _Session is not None
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
