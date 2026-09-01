"""Exercises the REAL Razorpay test-mode round-trip (CLAUDE.md §8 DoD for step 1).

Marked `live` -> excluded from the default `pytest` run (`addopts = -m "not live"`); run with
`pytest -m live`. Skips if no key is configured. Hits the network.
"""

import os

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("RAZORPAY_KEY_ID"),
        reason="RAZORPAY_KEY_ID not set (add to .env for the live round-trip test)",
    ),
]


def test_live_roundtrip_creates_a_real_payment_link(tmp_path, monkeypatch):
    # keep the round-trip's persistent audit DB + sidecar out of the repo during the test
    from mandatemend import live

    monkeypatch.setattr(live, "LIVE_DB", tmp_path / "live_audit.sqlite")
    monkeypatch.setattr(live, "SIDECAR", tmp_path / "last_live_roundtrip.json")

    out = live.run_live_check()  # default: first mandate of the frozen batch

    assert out["http"] == 200
    assert str(out["payment_link_id"]).startswith("plink_")
    assert str(out["short_url"]).startswith("https://")
    assert out["gateway"] == "razorpay_test"
    assert out["executed"] is True  # went through Executor reserve/execute/finalize
    assert out["audit_chain_ok"] is True
    assert (tmp_path / "last_live_roundtrip.json").exists()
    # the round-trip must never claim a recovery (test mode can't force a debit result)
    assert "connectivity" in out["note"]


def test_live_check_is_isolated_from_scoring(tmp_path, monkeypatch):
    """A live round-trip must not change the frozen-batch scorecard or touch the frozen files."""
    import hashlib
    from pathlib import Path

    from mandatemend import live
    from mandatemend.config import settings

    before = {
        p.name: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        for p in (settings.heldout_batch, settings.heldout_labels)
    }
    monkeypatch.setattr(live, "LIVE_DB", tmp_path / "live_audit.sqlite")
    monkeypatch.setattr(live, "SIDECAR", tmp_path / "last_live_roundtrip.json")
    live.run_live_check()
    after = {
        p.name: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        for p in (settings.heldout_batch, settings.heldout_labels)
    }
    assert before == after, "live-check must not touch the frozen batch/labels"
