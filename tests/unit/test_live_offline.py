"""`mandatemend/live.py` without the network — the Razorpay POST is faked.

The real-network version is `tests/integration/test_razorpay_live.py` (marker `live`).
"""

import json

from mandatemend import live
from mandatemend.schemas import Action, FailureEvent


def _fake_attempt(self, action: Action, event: FailureEvent):
    self.last_response = {
        "http": 200,
        "id": "plink_FAKE123",
        "short_url": "https://rzp.io/rzp/fake",
        "status": "created",
        "amount": action.amount_paise,
        "reference_id": "fake-ref",
    }
    return None, 0, "created payment_link plink_FAKE123 https://rzp.io/rzp/fake"


def test_run_live_check_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake-secret")
    monkeypatch.setattr(live, "LIVE_DB", tmp_path / "live_audit.sqlite")
    monkeypatch.setattr(live, "SIDECAR", tmp_path / "last_live_roundtrip.json")
    monkeypatch.setattr(
        "mandatemend.executor.gateway.RazorpayTestGateway.attempt", _fake_attempt
    )

    out = live.run_live_check()
    assert out["http"] == 200
    assert out["payment_link_id"] == "plink_FAKE123"
    assert out["executed"] is True
    assert out["audit_chain_ok"] is True
    assert "connectivity" in out["note"]

    # sidecar written and reloadable
    assert live.load_last()["payment_link_id"] == "plink_FAKE123"
    assert json.loads((tmp_path / "last_live_roundtrip.json").read_text())["gateway"] == "razorpay_test"


def test_run_live_check_unknown_mandate(tmp_path, monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake-secret")
    monkeypatch.setattr(live, "LIVE_DB", tmp_path / "a.sqlite")
    monkeypatch.setattr(live, "SIDECAR", tmp_path / "b.json")
    try:
        live.run_live_check("mnd_does_not_exist")
        raise AssertionError("expected SystemExit")
    except SystemExit:
        pass


def test_load_last_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "SIDECAR", tmp_path / "nope.json")
    assert live.load_last() is None
