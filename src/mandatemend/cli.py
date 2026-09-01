"""`mandatemend` command line.

    mandatemend gen-data [--n-train N]     regenerate the training set (never the frozen batch)
    mandatemend train                      train the survival + uplift models
    mandatemend score [--note "..."]       run the frozen-batch scorecard, append to the loop log
    mandatemend demo <mandate_id|index>    trace one mandate end to end
    mandatemend serve [--port 8000]        operator console
    mandatemend verify-audit               replay + verify the last scoring run's audit chain
    mandatemend live-check [--mandate ID]  one REAL Razorpay test-mode round-trip (needs keys)
    mandatemend failure-drill              run the adversarial / failure-injection scenarios
    mandatemend redteam                    the wider adversarial battery (injection corpus, fuzzing, ...)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from mandatemend.config import settings


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


def _count_tests() -> tuple[int, int]:
    """Run pytest -q and parse 'N passed[, M failed]'."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header"],
        capture_output=True,
        text=True,
    )
    out = r.stdout + r.stderr
    m_pass = re.search(r"(\d+) passed", out)
    m_fail = re.search(r"(\d+) failed", out)
    passed = int(m_pass.group(1)) if m_pass else 0
    failed = int(m_fail.group(1)) if m_fail else 0
    return passed, passed + failed


def _count_lint() -> int:
    r = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "src/", "data/", "tests/", "-q"],
        capture_output=True,
        text=True,
    )
    m = re.search(r"Found (\d+) error", r.stdout + r.stderr)
    return int(m.group(1)) if m else (0 if r.returncode == 0 else 1)


def _count_types() -> int:
    r = subprocess.run([sys.executable, "-m", "mypy"], capture_output=True, text=True)
    m = re.search(r"Found (\d+) error", r.stdout + r.stderr)
    return int(m.group(1)) if m else (0 if r.returncode == 0 else 1)


def cmd_gen_data(args: argparse.Namespace) -> int:
    from mandatemend.config import REPO_ROOT

    gen = REPO_ROOT / "data" / "generator.py"
    return subprocess.run(
        [sys.executable, str(gen), "--n-train", str(args.n_train)]
    ).returncode


def cmd_train(_args: argparse.Namespace) -> int:
    from mandatemend.models import train

    train.main()
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    from mandatemend.batch.run_batch import format_scorecard, run

    log = Path(settings.iter_log)
    iteration = 0
    if log.exists():
        lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        iteration = len(lines)

    sc = run(iteration=iteration, note=args.note, git_sha=_git_sha())
    if not args.fast:
        sc.tests_passed, sc.tests_total = _count_tests()
        sc.lint_errors = _count_lint()
        sc.type_errors = _count_types()

    print(format_scorecard(sc))
    print(
        f"  tests {sc.tests_passed}/{sc.tests_total}   lint_errors {sc.lint_errors}   "
        f"type_errors {sc.type_errors}"
    )

    if not args.no_log:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(sc.model_dump_json() + "\n")
        print(f"  -> appended iteration {iteration} to {log}")

    if sc.compliance_violations:
        print("STOP-THE-LINE: compliance_violations > 0 (CLAUDE.md §3.1)")
        return 2
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from mandatemend.agent import Agent
    from mandatemend.audit import ledger
    from mandatemend.batch.run_batch import _load_frozen
    from mandatemend.db.session import init_engine
    from mandatemend.executor.gateway import SimulatedGateway
    from mandatemend.schemas import FailureEvent

    events, labels = _load_frozen()
    ev: FailureEvent | None
    if args.target.isdigit() and int(args.target) < len(events):
        ev = events[int(args.target)]
    else:
        ev = next((e for e in events if e.mandate_id == args.target), None)
    if ev is None:
        print(f"no such mandate: {args.target}")
        return 1

    init_engine("sqlite://", create=True)
    ledger.reset_cache()
    agent = Agent.default(gateway=SimulatedGateway(labels), audit_enabled=True)
    res = agent.recover(ev)

    lab = labels[ev.mandate_id]
    print(f"mandate {ev.mandate_id}  true_cause={lab['true_cause']}  "
          f"churn={lab['true_churn_intent']}  amount=Rs {ev.amount_paise / 100:,.0f}")
    for i, step in enumerate(res.timeline):
        a = step.action
        print(
            f"  round {i}: {a.action_type.value:20s} "
            f"exec={step.executed!s:5} ok={step.gateway_success!s:5}  {a.reason}"
        )
        for rt in a.rule_trace:
            mark = "ok " if rt.passed else "BLOCK"
            print(f"          [{mark}] {rt.rule}: {rt.detail}")
    print(
        f"  => recovered={res.recovered}  amount=Rs {res.recovered_amount_paise / 100:,.0f}  "
        f"retries={res.retries_used}  contacts={res.contacts_made}  "
        f"terminal={res.terminal_action.value}"
    )
    ok, msg = ledger.verify_chain()
    print(f"  audit chain: {msg}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("mandatemend.console.app:app", host="127.0.0.1", port=args.port, reload=False)
    return 0


def cmd_live_check(args: argparse.Namespace) -> int:
    from mandatemend.live import run_live_check

    try:
        out = run_live_check(args.mandate)
    except RuntimeError as exc:  # missing keys
        print(f"live-check unavailable: {exc}")
        print("set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in .env")
        return 1

    print(f"mandate           {out['mandate_id']}  (Rs {out['amount_paise'] / 100:,.0f})")
    print(f"gateway           {out['gateway']}")
    print(f"HTTP              {out['http']}")
    print(f"payment_link_id   {out['payment_link_id']}")
    print(f"short_url         {out['short_url']}")
    print(f"link status       {out['status']}")
    print(f"executor.executed {out['executed']}   detail: {out['detail']}")
    print(f"audit chain       {out['audit_chain']}")
    print(f"                  {out['note']}")
    print("  -> sidecar written; console overview will show this round-trip")
    return 0 if out["http"] == 200 else 2


def cmd_failure_drill(_a: argparse.Namespace) -> int:
    from mandatemend.drills import format_results, run_all

    results = run_all()
    print(format_results(results))
    return 0 if all(r.held for r in results) else 1


def cmd_redteam(_a: argparse.Namespace) -> int:
    from mandatemend.redteam import format_results, run_all

    results = run_all()
    print(format_results(results))
    return 0 if all(r.held for r in results) else 1


def cmd_verify_audit(_a: argparse.Namespace) -> int:
    from mandatemend.audit import ledger
    from mandatemend.batch.run_batch import run

    run(iteration=0, note="verify-audit")
    ok, msg = ledger.verify_chain()
    print(("OK  " if ok else "BROKEN  ") + msg)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mandatemend", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gen-data")
    g.add_argument("--n-train", type=int, default=8000)
    g.set_defaults(fn=cmd_gen_data)

    sub.add_parser("train").set_defaults(fn=cmd_train)

    s = sub.add_parser("score")
    s.add_argument("--note", default="")
    s.add_argument("--fast", action="store_true", help="skip pytest/ruff/mypy")
    s.add_argument("--no-log", action="store_true", help="do not append to iterations.jsonl")
    s.set_defaults(fn=cmd_score)

    d = sub.add_parser("demo")
    d.add_argument("target", help="mandate_id or 0-based index into the frozen batch")
    d.set_defaults(fn=cmd_demo)

    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(fn=cmd_serve)

    lc = sub.add_parser("live-check")
    lc.add_argument("--mandate", default=None, help="mandate_id from the frozen batch (default: first)")
    lc.set_defaults(fn=cmd_live_check)

    sub.add_parser("failure-drill").set_defaults(fn=cmd_failure_drill)
    sub.add_parser("redteam").set_defaults(fn=cmd_redteam)
    sub.add_parser("verify-audit").set_defaults(fn=cmd_verify_audit)

    args = p.parse_args(argv)
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
