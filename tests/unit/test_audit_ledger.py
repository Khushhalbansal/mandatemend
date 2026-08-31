from mandatemend.audit import ledger
from mandatemend.db.models import AuditEntry
from mandatemend.db.session import session_scope


def test_chain_appends_and_verifies(db):
    ledger.append("m1", "diagnosis", {"cause": "INSUFFICIENT_FUNDS"})
    ledger.append("m1", "policy.decision", {"action": "RETRY"})
    ledger.append("m2", "resolution", {"recovered": True})
    ok, msg = ledger.verify_chain()
    assert ok, msg
    assert "3 entries" in msg


def test_tamper_is_detected(db):
    ledger.append("m1", "a", {"v": 1})
    ledger.append("m1", "b", {"v": 2})
    ledger.append("m1", "c", {"v": 3})
    with session_scope() as s:
        row = s.query(AuditEntry).order_by(AuditEntry.id.asc()).first()
        row.payload_json = row.payload_json.replace('"v":1', '"v":999')
    ok, msg = ledger.verify_chain()
    assert ok is False
    assert "altered" in msg or "mismatch" in msg


def test_buffered_matches_unbuffered(db):
    ledger.append("m1", "x", {"n": 1})
    unbuffered_tip = ledger.append("m1", "x", {"n": 2})

    ledger.reset_cache()
    with session_scope() as s:
        s.query(AuditEntry).delete()

    ledger.begin_buffer()
    ledger.append("m1", "x", {"n": 1})
    buffered_tip = ledger.append("m1", "x", {"n": 2})
    n = ledger.flush_buffer()
    assert n == 2
    assert buffered_tip == unbuffered_tip  # same chain, same hashes
    ok, _ = ledger.verify_chain()
    assert ok


def test_entries_for_filters_by_mandate(db):
    ledger.append("m1", "a", {})
    ledger.append("m2", "a", {})
    ledger.append("m1", "b", {})
    assert len(ledger.entries_for("m1")) == 2
    assert len(ledger.entries_for("m2")) == 1
