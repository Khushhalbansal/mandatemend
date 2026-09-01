"""`mandatemend` CLI subcommands — smoke tests that each command runs and exits 0."""

import json

import pytest

from mandatemend.cli import main

pytestmark = pytest.mark.integration


def test_score_fast_no_log(capsys, tmp_path, monkeypatch):
    # keep the iteration log untouched
    from mandatemend import cli

    monkeypatch.setattr(cli.settings, "iter_log", tmp_path / "iterations.jsonl")
    rc = main(["score", "--fast", "--no-log", "--note", "pytest"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "MandateMend batch scorecard" in out
    assert "COMPLIANCE VIOLATIONS      0" in out  # STOP-THE-LINE gate


def test_demo_by_index(capsys):
    rc = main(["demo", "0"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Recovery timeline" not in out  # demo prints rounds, not the console heading
    assert "round 0:" in out
    assert "audit chain: chain OK" in out


def test_verify_audit(capsys):
    rc = main(["verify-audit"])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_train_writes_artifacts(tmp_path, monkeypatch, capsys):
    from mandatemend.models import retry_timing, train, uplift

    if not train.TRAIN_JSON.exists():
        pytest.skip("run `python data/generator.py` first (training set is not committed)")

    r_art = tmp_path / "retry_timing.joblib"
    u_art = tmp_path / "uplift.joblib"
    monkeypatch.setattr(retry_timing, "ARTIFACT", r_art)
    monkeypatch.setattr(uplift, "ARTIFACT", u_art)
    monkeypatch.setattr(train, "METRICS", tmp_path / "model_metrics.json")

    rc = main(["train"])
    assert rc == 0
    assert r_art.exists() and u_art.exists()

    metrics = json.loads((tmp_path / "model_metrics.json").read_text())
    assert "retry_timing" in metrics and "uplift" in metrics
    # the trained retry model must at least match the naive "+72h always" baseline on the oracle
    oracle = metrics["retry_timing"]["oracle"]
    assert oracle["model_picks_a_winning_delay"] >= oracle["naive_+72h_is_a_winning_delay"] - 0.05


def test_unknown_command_errors():
    with pytest.raises(SystemExit):
        main(["frobnicate"])
