# MandateMend

[![CI](https://github.com/Khushhalbansal/mandatemend/actions/workflows/ci.yml/badge.svg)](https://github.com/Khushhalbansal/mandatemend/actions/workflows/ci.yml)
&nbsp;coverage ~90% &nbsp;·&nbsp; ruff + mypy clean &nbsp;·&nbsp; 112 tests + 10 Hypothesis property tests &nbsp;·&nbsp; `redteam` 5/5 &nbsp;·&nbsp; mutation check 17/17

**A compliance-gated recovery agent for failed UPI AutoPay / e-mandate debits.**
Razorpay AI Buildathon 2026 — Track 03 (AI Revenue Recovery), sub-angle 3A.

UPI AutoPay fails at **8–15%** vs 2–3% for card mandates; ~10% of recurring payments fail on
the first attempt and **20–40% of subscription churn is involuntary**. Every published
retry/dunning system (Stripe Smart Retries, Recurly, Dropbox) is card-based, closed, and
ranks actions by *predicted success*. MandateMend is an open, UPI-native recovery agent that

1. **diagnoses** the failure — LLM, sandboxed, injection-guarded, typed output only;
2. **times** the retry with a discrete-time **survival / hazard** model, within the NPCI
   1-original-+-3-retry budget;
3. **chooses** the dunning intervention by **causal uplift** against a do-nothing control
   (not by predicted success — see [`docs/MODELS.md`](docs/MODELS.md));
4. runs every money move through a **deterministic policy engine** — the only component that
   may emit an executable action — enforcing the NPCI retry cap, the 24h pre-debit-notice
   rule, quiet hours, a weekly contact cap, a per-mandate economic floor, a stopping rule,
   and fail-closed on any error;
5. writes an **append-only, hash-chained audit ledger**, re-verified for compliance by an
   independent checker (`invariants.py`) that lives *outside* the engine.

Every safety property is written out as a numbered, independently-checkable proposition in
[`docs/INVARIANTS.md`](docs/INVARIANTS.md) (I1–I13), and each is proven three ways: a
targeted unit test, a **Hypothesis property test** over hundreds of generated
`event × diagnosis × advice × state` combinations, and the `mandatemend redteam` adversarial
battery (30-payload prompt-injection corpus, hostile-webhook fuzzing, clock skew, mid-run
ledger outage, 16-thread concurrent double-charge check). The property suite found and fixed
two real safety holes this iteration — see *What broke*.

## Headline result — frozen 300-mandate held-out batch

| metric | value |
|---|---|
| **recovery rate** | **63.51 %** (₹293,588 of ₹462,300 at risk) — 95 % CI [56.28 %, 70.45 %] |
| **lift vs. static-retry** (24h / 72h / 168h ladder) | **+16.33 pp** — 95 % CI [9.94 pp, 23.81 pp], **entirely above zero** |
| lift vs. single-retry / email-only | +38 pp / +43 pp |
| **NPCI compliance violations** | **0** — independently re-checked by `invariants.py` |
| retries used / recoveries-per-retry | 287 / 0.72 |
| harm / false-positive cost | ₹288 (paid outreach on mandates that never recovered) |
| terminal state | every mandate ends **recovered** or **on the human queue** — never dropped |
| one real Razorpay **test-mode** round-trip | `plink_…` created, HTTP 200, wired through the executor + audit ledger (`mandatemend live-check`) |

**Cross-check on a disjoint 1000-mandate batch** (`mandatemend score --batch v2`): recovery
**63.45 %** (95 % CI [59.5 %, 67.3 %]) — the absolute number holds. Lift there is **+8.65 pp**,
lower only because that batch's static-retry baseline (54.8 %) is easier than the primary's
(47.2 %) — same agent, different baseline draw. **The stable, honest number is the absolute
recovery rate; lift is baseline-sensitive.** 0 compliance violations at 1000 mandates. See
[`docs/MODELS.md §4`](docs/MODELS.md).

Numbers are **byte-reproducible**: `data/generator.py` is fully deterministic (stable
`blake2b` seeds, not salted `hash()`), so `python data/generator.py && mandatemend train &&
mandatemend score` gives the same result on any machine. CIs are a seeded, mandate-resampled
2000× bootstrap. Full iteration history (incl. the STOP-THE-LINE at iter 0 and the reverted
regression at iter 5) is in [`logs/iterations.jsonl`](logs/iterations.jsonl).

Docs: **[ARCHITECTURE](docs/ARCHITECTURE.md)** · **[MODELS](docs/MODELS.md)** ·
**[INVARIANTS (I1–I13)](docs/INVARIANTS.md)** · **[NPCI rules](docs/NPCI.md)** ·
**[PITCH (5-min beat sheet)](docs/PITCH.md)** · **[RESEARCH / track choice](docs/RESEARCH.md)** ·
**[data generation](data/GENERATION_NOTES.md)** · **[CHANGELOG — what broke](CHANGELOG.md)**

## Architecture (trust boundary)

```
FailureEvent ─▶ Diagnosis (LLM, SANDBOXED: typed TypedDiagnosis only, injection-guarded)
                     │                         offline HeuristicDiagnoser is the default
                     ├─▶ retry-timing model   (discrete-time hazard)        ─┐  ADVICE ONLY —
                     └─▶ intervention model   (IPW T-learner, uplift vs NO_OP)┤  the engine may
                                                                             ▼  veto any of it
                     POLICY ENGINE  (deterministic — the ONLY constructor of an Action)
                       NPCI retry cap · 24h pre-debit notice · quiet hours · weekly
                       contact cap · per-mandate economic floor · stopping rule ·
                       amount-within-cap · fail closed → NO_ACTION + human queue
                                                                             ▼
                     EXECUTOR  (idempotent: DB-UNIQUE reserve → execute → finalize)
                       SimulatedGateway (frozen outcomes)  |  RazorpayTestGateway (real)
                                                                             ▼
                     APPEND-ONLY, HASH-CHAINED AUDIT LEDGER
                                                                             ▼
                     invariants.py  (re-verifies EVERY rule, outside the engine)  +  console
```

## Run it

**One command on a fresh checkout** (Unix / macOS / Git-Bash):

```bash
make demo        # venv + locked deps + generate data + train + score the frozen batch
make serve       # operator console at http://127.0.0.1:8000
```

**Manual / Windows:**

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-lock.txt      # exact validated set
.venv/Scripts/pip install -e . --no-deps

.venv/Scripts/python data/generator.py     # training set (the 300-mandate held-out batch is FROZEN in git)
mandatemend train                          # survival + uplift -> src/mandatemend/models/artifacts/  (committed)
mandatemend score                          # frozen-batch scorecard + pytest + ruff + mypy; appends to logs/iterations.jsonl
mandatemend demo 5                         # trace one mandate end-to-end with its full rule trace
mandatemend serve                          # operator console
mandatemend verify-audit                   # replay + verify the audit hash chain
mandatemend failure-drill                  # 7 adversarial scenarios, live: inject X -> invariant held
mandatemend redteam                        # wider adversarial battery: 30-payload injection corpus, webhook fuzzing, concurrency
mandatemend live-check                     # one REAL Razorpay test-mode round-trip (needs keys in .env)

pytest -m property tests/property          # Hypothesis safety proofs (opt-in marker; own CI step)
```

Runs entirely offline against synthetic data. Trained model artifacts are committed, so
`mandatemend score` works without `train`. Set `ANTHROPIC_API_KEY` to swap the offline
`HeuristicDiagnoser` for the LLM one; put `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` in `.env`
(gitignored) for `live-check`.

```
$ mandatemend score          # the iteration number increments per logged run
MandateMend batch scorecard  (v0.1.0, iteration 17)
  batch size                 300
  amount at risk             Rs 462,300
  recovered (agent)          Rs 293,588   63.51%   95% CI [56.28%, 70.45%]
  baseline static-retry      47.18%
  baseline single-retry      24.96%
  baseline email-only        19.99%
  LIFT vs static-retry       16.33%   95% CI [9.94%, 23.81%]
  retries used (total)       287
  recoveries / retry         0.7247
  contacts on non-recovered  192   harm cost Rs 288
  escalated to human         92
  COMPLIANCE VIOLATIONS      0
  per cause (rate with 95% Wilson CI):
    BANK_DOWNTIME        n=38   rec=34    89.47%  [75.87%, 95.83%]  esc=4
    INSUFFICIENT_FUNDS   n=134  rec=96    71.64%  [63.49%, 78.59%]  esc=38
    TECH_DECLINE         n=59   rec=51    86.44%  [75.46%, 92.97%]  esc=8
    ...
  tests 112/112   lint_errors 0   type_errors 0
```

## Data & scoring isolation (CLAUDE.md §1.3)

* `data/generator.py` builds a synthetic mandate-failure world with **temporal / velocity
  structure** (bank-downtime failures cluster on 2 issuers in a shared window; churn shows as
  rising consecutive failures), a mildly-confounded logging policy for training, and a
  **potential-outcomes table** realised once at generation — so the agent and every baseline
  are scored on the *same* outcomes ([`data/GENERATION_NOTES.md`](data/GENERATION_NOTES.md)).
* `data/heldout_batch.frozen.json` + `data/heldout_labels.frozen.json` are **read-only**
  (`-text` in `.gitattributes`, SHA-256 in `data/FROZEN_SHA256.txt`; the generator refuses to
  overwrite them and CI re-checks the hash).
* The scored run uses an **in-memory** DB; the DB-UNIQUE idempotency guarantee is identical
  in memory, and the concurrent-webhook / gateway-crash proofs are in
  `tests/integration/test_executor_idempotency.py` against a file DB.
* The real Razorpay call is **additive** — a separate module, a separate DB, never inside the
  scored run.

## What broke / how we recovered

Honest running log in [`CHANGELOG.md`](CHANGELOG.md):

* **iter 0 — STOP-THE-LINE:** the engine rate-limited only `SEND_NOTIFICATION`, not
  `OFFER_ALTERNATE_METHOD`, so a limit-exceeded mandate looped 6 identical contacts. Paused,
  root-caused, fixed the contact-cap definition + added a stall-breaker.
* **the gateway keyed retry outcomes on wall-clock time**, not the model's causal delay
  bucket — `state.now` advances across rounds, so retries 2 and 3 silently collapsed into one
  bucket and re-failed. Fix: the chosen bucket travels on `Action.retry_delay_bucket`.
* **the stopping rule counted pre-session failure history**, so a mandate with 2 prior
  failures escalated after a single retry and never spent its NPCI budget. Fix: in-session
  declines only.
* **iter 5 regression, reverted per §3.2:** letting the mandate's standing notice cover
  retries within 72h *removed* the spacing the notice delay was implicitly enforcing —
  recovery fell to 59.5 %. Reverted; iter 4 stands.
* **iter 8 — two safety holes the Hypothesis property tests found:** (1) a paid-outreach
  economic-floor fallback in `engine.py` could emit a `RETRY` on a PAUSED/EXPIRED mandate
  because it only re-checked the notice, not liveness / the NPCI cap / the amount cap —
  now it re-checks *all* charging preconditions; (2) the independent `CONTACT_FREQUENCY`
  check counted a mandate's *pre-session* contacts against the cap, so a mandate arriving
  already over the weekly limit was mis-flagged — now it bounds the agent's *own* session
  contacts by the *remaining* budget. Both fixed, both with new tests.
* **iter 9 — the ablation caught a real bug.** `mandatemend eval --ablation` swaps each
  advisor pair into the agent; the first run showed the shipped `survival + T-learner` at
  61.42 %, *behind* `survival + heuristic` by 3.8 pp. Root cause:
  `_prefer_retry_when_competitive` exempted `PARTIAL_CHARGE` alongside `RETRY_ONLY` for
  retry-first causes, but a partial charge consumes an NPCI attempt *and* marks its delay
  bucket tried — poisoning the `RETRY@24h` bucket a transient `TECH_DECLINE` wins on. The
  T-learner ranks `PARTIAL_CHARGE` top for `TECH_DECLINE`; the heuristic never does. Fix:
  only `RETRY_ONLY` passes the override. **61.42 → 63.51 %**, `TECH_DECLINE` recovery
  79.7 → 86.4 %, retries *down*, 0 violations. A 1.7 pp gap to `survival + heuristic`
  remains (thin buckets); the shipped default decision is deferred to the 1000-mandate v2
  batch.

## Layout

```
src/mandatemend/
  schemas.py         typed contract (money = integer paise; Action can't exist without a rule_trace)
  diagnosis/         sanitize · heuristic_diagnoser · llm_diagnoser
  models/            retry_timing (hazard) · uplift (T-learner) · advisors (round-aware) · train
  policy/            rules (individually unit-tested predicates) · engine (sole Action authority)
  executor/          gateway (Simulated | RazorpayTest) · executor (idempotent, DB-UNIQUE)
  audit/ledger.py    append-only hash chain
  invariants.py      independent compliance re-verification
  redteam.py         wider adversarial battery (mandatemend redteam)
  agent.py           the bounded per-mandate recovery loop (warm() batches model inference)
  batch/             baselines · run_batch (scorecard + bootstrap CIs)
  live.py            one real Razorpay test-mode round-trip
  console/           FastAPI + Jinja operator console (dense, server-rendered, no build step)
docs/INVARIANTS.md   I1–I13 · enforcing code + independent check + tests, per invariant
data/ · tests/ (unit · integration · e2e · property · live) · logs/iterations.jsonl · .github/workflows/ci.yml
```

MIT licensed.
