"""`ledger.append` under concurrent callers — the chain stays valid.

The executor's dedup path fires `append` from several webhook threads at once; two entries
built off the same chain tip would collide on `entry_hash`. `append` is serialised with a
lock (single-process system), so this must hold.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from mandatemend.audit import ledger

pytestmark = pytest.mark.integration


def test_concurrent_appends_produce_one_valid_chain(db):
    ledger.reset_cache()

    def one(i: int) -> str:
        # identical payloads on purpose — the collision case
        return ledger.append("m", "concurrent", {"k": "same"})

    with ThreadPoolExecutor(max_workers=16) as pool:
        hashes = list(pool.map(one, range(64)))

    assert len(set(hashes)) == 64, "every entry_hash must be unique"
    ok, msg = ledger.verify_chain()
    assert ok, msg
    assert "64 entries" in msg
