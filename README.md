# MandateMend

**A compliance-gated recovery agent for failed UPI AutoPay / e-mandate debits.**
Razorpay AI Buildathon 2026 — Track 03 (AI Revenue Recovery), sub-angle 3A.

UPI AutoPay fails at **8–15%** vs 2–3% for card mandates; ~10% of recurring payments fail on
the first attempt and **20–40% of subscription churn is involuntary**. Every published
retry/dunning system (Stripe Smart Retries, Recurly, Dropbox) is card-based, closed, and
ranks actions by predicted success. MandateMend is an open, UPI-native recovery agent that
(1) diagnoses the failure, (2) times the retry with a **discrete-time survival model**,
(3) picks the dunning intervention by **causal uplift** against a do-nothing control,
(4) runs every money move through a **deterministic policy engine** that enforces the NPCI
retry cap and 24h pre-debit-notice rule, and (5) writes a **hash-chained audit ledger**.

## Headline result (frozen 300-mandate held-out batch)

| metric | value |
|---|---|
| recovery rate | **62.1%** (₹286,916 of ₹462,300 at risk) |
| lift vs. static-retry baseline (24h/72h/168h) | **+14.9 pp** |
| lift vs. single-retry / email-only | +37 pp / +42 pp |
| NPCI compliance violations | **0** (independently checked, `invariants.py`) |
| retries used / recoveries-per-retry | 230 / 0.87 |
| terminal state | every mandate ends **recovered** or **on the human queue** — never dropped |

Full history in [`logs/iterations.jsonl`](logs/iterations.jsonl); design rationale in
[`docs/RESEARCH.md`](docs/RESEARCH.md).

## Architecture (trust boundary)

```
FailureEvent ─▶ Diagnosis (LLM, sandboxed: typed output only, injection-guarded)
                     │
                     ├─▶ Retry-timing model  (survival / discrete-time hazard)   ─┐  advisory
                     └─▶ Intervention model  (IPW T-learner, CATE vs NO_OP)      ─┤  only
                                                                                  ▼
                     POLICY ENGINE (deterministic — the ONLY thing that emits an Action)
                       hard rules: NPCI retry cap · 24h pre-debit notice · quiet hours ·
                       weekly contact cap · per-mandate economic floor · stopping rule ·
                       amount-within-cap · fail-closed on any error
                                                                                  ▼
                     EXECUTOR (idempotent: DB-UNIQUE reserve-then-execute)
                                                                                  ▼
                     APPEND-ONLY, HASH-CHAINED AUDIT LEDGER  ──▶  operator console
```

The LLM never has execution authority. The policy engine can veto or downgrade any model
recommendation. Compliance is re-verified **outside** the engine by `mandatemend/invariants.py`
so the engine can never mark its own homework.

## Quickstart

```bash
python -m venv .venv && . .venv/Scripts/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

python data/generator.py            # training set (the 300-mandate held-out batch is FROZEN in git)
mandatemend train                   # train survival + uplift models -> src/mandatemend/models/artifacts/
mandatemend score                   # run the frozen-batch scorecard + tests + lint + types
mandatemend demo 5                  # trace one mandate end-to-end with its rule trace
mandatemend serve                   # operator console at http://127.0.0.1:8000
mandatemend verify-audit            # replay + verify the audit hash chain
```

Runs entirely offline against synthetic data. Set `ANTHROPIC_API_KEY` to use the LLM
diagnoser (otherwise a real rule-based `HeuristicDiagnoser` is used); set `RAZORPAY_KEY_ID`
/ `RAZORPAY_KEY_SECRET` + `MANDATEMEND_EXECUTOR=razorpay_test` for one real test-mode
Payment-Link round-trip.

## Data

* `data/generator.py` builds a synthetic mandate-failure world with realistic **temporal and
  velocity structure** (bank-downtime failures cluster on 2 issuers in a shared window; churn
  shows as rising consecutive failures), a mildly-confounded logging policy for training, and
  a **potential-outcomes table** (realized once at generation) so every strategy — agent and
  baselines — is scored on the *same* outcomes. See [`data/GENERATION_NOTES.md`](data/GENERATION_NOTES.md).
* `data/heldout_batch.frozen.json` + `data/heldout_labels.frozen.json` are **read-only**
  (SHA-256 in `data/FROZEN_SHA256.txt`). The generator refuses to overwrite them.

## What broke / how we recovered

Documented honestly as it happened in [`CHANGELOG.md`](CHANGELOG.md). Highlights: an
iteration-0 STOP-THE-LINE (the engine rate-limited only `SEND_NOTIFICATION`, not
`OFFER_ALTERNATE_METHOD`, so a limit-exceeded mandate looped 6 identical contacts); a
gateway that keyed retry outcomes on wall-clock time instead of the model's causal delay
bucket, silently collapsing every late retry into one bucket; a stopping rule that counted
pre-session failure history and cut the retry budget to 2.

## Layout

```
src/mandatemend/
  schemas.py        typed contract (money in integer paise)
  diagnosis/        sanitize · heuristic_diagnoser · llm_diagnoser
  models/           retry_timing (survival) · uplift (T-learner) · advisors · train
  policy/           rules (unit-tested predicates) · engine (sole Action authority)
  executor/         gateway (Simulated / RazorpayTest) · executor (idempotent)
  audit/ledger.py   append-only hash chain
  invariants.py     independent compliance re-verification
  agent.py          the bounded per-mandate recovery loop
  batch/            baselines · run_batch (scorecard)
  console/          FastAPI + Jinja operator console
data/ · tests/ (unit · integration · e2e) · logs/iterations.jsonl
```
