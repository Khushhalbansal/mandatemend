"""Operator console — every route, via FastAPI's TestClient (no network, no live server)."""

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client():
    from mandatemend.console import service
    from mandatemend.console.app import app

    service.build()  # one batch, cached in the module
    with TestClient(app) as c:
        yield c


def test_overview_renders_headline_and_sections(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    for token in (
        "recovery rate",
        "lift vs static-retry",
        "Agent vs. baselines",
        "By failure cause",
        "compliance violations",
        "Audit chain: chain OK",
    ):
        assert token in body, token
    assert "Traceback" not in body and "UndefinedError" not in body


def test_mandates_list_and_filters(client):
    assert "300 shown" in client.get("/mandates").text
    rec = client.get("/mandates?outcome=recovered").text
    esc = client.get("/mandates?outcome=escalated").text
    n_rec = int(rec.split(" shown")[0].split(">")[-1].split("(")[-1])
    n_esc = int(esc.split(" shown")[0].split(">")[-1].split("(")[-1])
    assert n_rec + n_esc == 300  # termination invariant: recovered xor escalated
    assert "0 shown" in client.get("/mandates?outcome=violation").text  # iter-4 build is clean
    assert " shown" in client.get("/mandates?cause=TECH_DECLINE").text


def test_mandate_detail_has_rule_trace_and_audit(client):
    mid = _first_mandate_id(client)
    r = client.get(f"/mandate/{mid}")
    assert r.status_code == 200
    for token in ("Recovery timeline", "Audit trail", "Download evidence pack", "[ok]"):
        assert token in r.text, token


def test_mandate_404(client):
    assert client.get("/mandate/nope_not_real").status_code == 404


def test_evidence_pack_download(client):
    mid = _first_mandate_id(client)
    r = client.get(f"/evidence/{mid}.json")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    pack = r.json()
    assert set(pack) >= {
        "mandate_id",
        "failure_event",
        "resolution",
        "compliance_violations",
        "audit_trail",
    }
    assert pack["mandate_id"] == mid
    assert len(pack["audit_trail"]) >= 3  # diagnosis + >=1 decision + resolution


def test_rebuild(client):
    assert client.post("/rebuild").json() == {"ok": True}


def _first_mandate_id(client) -> str:
    import re

    m = re.search(r"mnd_[A-Za-z0-9_]+", client.get("/mandates").text)
    assert m
    return m.group(0)
