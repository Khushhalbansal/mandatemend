# Changelog

Honest running log of decisions and real failures (CLAUDE.md §3.2, §7, §5.4).
Newest first. Do not retroactively clean this up — the failures are pitch material.

## [unreleased]

### 2026-09-01 — step 1: real Razorpay test-mode round-trip (additive, isolated from scoring)
* `RazorpayTestGateway` hardened: sanitised `reference_id` (alnum + time suffix, `<= 40`,
  no `|`), `httpx.HTTPError` caught -> fail closed, and it now records `last_response`
  (http status, `plink_` id, `short_url`, link status) for callers to surface.
* New `mandatemend/live.py` + `mandatemend live-check [--mandate ID]`: takes one real
  mandate from the frozen batch (read-only), synthesises a single RETRY `Action`, and runs
  it through the **real** `Executor` -> `RazorpayTestGateway` path (reserve / execute /
  finalize + a hash-chained `execution` audit entry) against a persistent
  `logs/live_audit.sqlite`. Writes `logs/last_live_roundtrip.json`; both gitignored.
* `config.py` now calls `load_dotenv(REPO_ROOT/".env", override=False)` — pydantic-settings
  only parses `.env` for `MANDATEMEND_*` fields, so the non-prefixed `RAZORPAY_*` /
  `ANTHROPIC_*` keys that `RazorpayTestGateway` reads from `os.environ` were previously
  invisible. `.env` stays gitignored (line 2); never committed in any commit (full-history
  scan clean).
* Operator console overview surfaces the last live round-trip (mandate, HTTP status, link
  id + `short_url`, `executor.executed`, audit-chain status) from the sidecar.
* Test: `tests/integration/test_razorpay_live.py`, marked `live` (excluded from the default
  suite via `addopts = -m "not live"`; run with `pytest -m live`; skips with no key).
  Asserts HTTP 200 + a `plink_` id + `executed is True` + audit chain OK, and that a live
  round-trip does **not** change the frozen batch/labels SHA-256.

**Evidence (real test-mode calls, no keys logged):**
`mandatemend live-check` -> HTTP 200, payment link `plink_TWdntO2ORgY7Eh`
(`https://rzp.io/rzp/43uYvEwc`, status `created`), `executor.executed=True`,
audit chain OK across 2 entries. `pytest -m live` -> 2 passed.

**Isolation confirmed:** default `pytest` 53 passed / 2 deselected; `mandatemend score`
unchanged at 62.06% recovery / +14.89pp lift / 0 compliance violations; frozen batch +
labels SHA-256 unchanged (match `data/FROZEN_SHA256.txt`).

### 2026-09-01 — iteration 4: trained advisors wired in; batch scoring 3.5min -> 9s
* **Trained models replace heuristics in the agent.** `SurvivalRetryAdvisor` (discrete-time
  hazard) + `TLearnerUpliftAdvisor` (IPW T-learner, CATE vs a NO_OP control) become the
  default when artifacts exist. Round-aware: the agent walks the advisor's ranking across
  rounds, skipping already-tried delay buckets / arms; `_prefer_retry_when_competitive`
  routes TECH_DECLINE / BANK_DOWNTIME / SUSPECTED_CHURN to a retry before an arm (those
  three lost to a plain retry ladder at iteration 2 because the uplift model over-favoured
  flashy arms).
* **Two real bugs found via the per-cause breakdown and fixed** (this is what moved lift
  from +1.7% to +14.9%):
  1. `SimulatedGateway` keyed retry outcomes on `scheduled_at - occurred_at` (wall-clock).
     Because `state.now` advances across rounds, retries 2 and 3 both collapsed into delay
     bucket 24 and re-failed. Fix: the model's chosen bucket now travels on
     `Action.retry_delay_bucket` and the gateway keys on that; wall-clock scheduling (for
     the pre-debit-notice gap and quiet hours) stays separate.
  2. `rule_stopping` counted **pre-session** `history.consecutive_failures`, so a mandate
     with 2 prior failures escalated after a single retry — the agent never spent its
     3-retry NPCI budget. Fix: in-session declines only; threshold = `npci_max_retries`.
* **Training data scaled** 2,000 -> 7,700 rows (held-out ids excluded); held-out draw moved
  to a fixed high index range so `n_train` can grow without ever overlapping the frozen
  batch. Model `max_iter` cut (uplift 200->60, retry 250->90) — smaller models generalise
  *better* here (retry oracle-agreement 37%->45% vs naive 41%; uplift top-arm-is-a-winner
  78%->82%) and, with per-mandate memoisation of model inference + an in-memory scoring DB,
  a full 300-mandate scored run dropped from ~3m30s to ~9s.
* Added: `mandatemend` CLI (`gen-data` / `train` / `score` / `demo` / `serve` /
  `verify-audit`), the operator console (FastAPI + Jinja, dense server-rendered), the test
  suite (53 tests: unit rules/engine/sanitize/diagnosers/schemas/ledger, integration
  idempotency + gateway-crash, e2e frozen-batch), `data/GENERATION_NOTES.md`, this repo's
  copy of the research doc at `docs/RESEARCH.md`.
* **Scorecard iteration 4**: recovery 62.06%, lift +14.89% vs static-retry, compliance
  violations 0, tests 53/53, lint 0. (Recorded `type_errors 1` was a stale mypy finding in
  `cli.py` fixed immediately after; the append-only log keeps the honest history.)

### 2026-09-01 — iterations 2–3 (exploratory, only the landing states logged)
* iter 2: trained survival + IPW T-learner advisors first wired in, round-aware arm/delay
  selection. recovery 48.9%, lift +1.7%. Per-cause diagnosis showed the agent *losing* to
  static-retry on BANK_DOWNTIME (−16pp) and TECH_DECLINE (−22pp) — traced to the two bugs
  fixed in iteration 4.
* iter 3 attempts: a blanket "prefer retry when competitive" rule regressed lift to +0.9%
  (reverted per §3.2); the targeted 3-cause version landed at +2.7%.

### 2026-09-01 — iteration 1: cleared the iteration-0 STOP-THE-LINE (compliance_violations 5 -> 0)
**Root cause (one bug class).** All 5 iteration-0 violations were `CONTACT_FREQUENCY: 6 > cap 3`
on `U67` (limit-exceeded) mandates whose amount exceeds even the partial-charge cap. Two
defects combined:
  1. `rule_contact_frequency` was applied only to `SEND_NOTIFICATION`. But
     `OFFER_ALTERNATE_METHOD` is also an outbound customer contact, and `invariants.py`
     counts it as one — so the engine's and the checker's definitions of "a contact"
     disagreed. The engine happily emitted `OFFER_ALTERNATE_METHOD` every round.
  2. The agent loop had no stall-breaker: an advisor that returns the same non-charging
     recommendation each round made the loop repeat an identical action until `_MAX_ROUNDS`.

**Fix (3 files, no test/label changes).**
  * `policy/rules.py`: added `CONTACT_ACTIONS` (= SEND_NOTIFICATION + OFFER_ALTERNATE_METHOD)
    and `NON_CHARGING_LOOP_ACTIONS`.
  * `policy/engine.py`: the method-switch branch now runs `rule_contact_frequency`; on cap it
    returns `STOP_AND_ESCALATE`.
  * `agent.py`: stall-breaker — the same non-charging `action_type` in two consecutive rounds
    -> `STOP_AND_ESCALATE` + audit `escalation` entry. Also the old `NO_ACTION`x2 path now
    escalates instead of a silent `break`. New stated invariant: **every mandate terminates
    RECOVERED or STOP_AND_ESCALATE, never dropped** (post-loop guard enforces it).

**Known, expected consequence to fix next (NOT stop-the-line).** With the untrained heuristic
advisors, recovery fell 47.08% -> 40.83% and escalations rose to 178/300, because the
heuristic intervention advisor recommends the same thing every round for the largest cause
bucket (INSUFFICIENT_FUNDS -> WHATSAPP_UPI_LINK), which the stall-breaker now correctly
stops. The heuristic advisor is only a baseline; the round-aware strategy + trained
retry-timing (survival) and uplift models are what turn this into positive lift. That is the
next work item, tracked as iteration 2+.

### 2026-09-01 — scaffold + stack decisions (log-and-proceed, CLAUDE.md §3.2)
- **Language: Python 3.11+** (local machine has 3.13.0). ML + FastAPI ecosystem, matches CLAUDE.md's pytest references.
- **DB: PostgreSQL 16 via docker-compose**, not SQLite. Reasoning: CLAUDE.md §2 requires idempotency enforced by a
  DB-level unique constraint that holds under concurrent webhooks; §3.1 makes the storage engine a hard-stop to change
  later, so it must be right on the first commit. SQLite's UNIQUE constraint is atomic but its single-writer locking is
  the exact limitation the closest competitor repo concedes. Postgres removes that objection.
- **Web: FastAPI + Jinja2 + HTMX**, server-rendered, not a React SPA. Reasoning: CLAUDE.md §4 explicitly warns against
  the generated-SPA look and asks for information density for an operator who stares at this daily. Server-rendered dense
  tables fit that better and remove a build toolchain.
- **Retry-timing model: discrete-time survival analysis (`lifelines`)**, not a plain classifier. Reasoning: the decision
  is *when* to retry within the NPCI 3-attempt budget, not *if* — a hazard/survival formulation matches the problem and
  is defensible (Witzany & Kozina 2022, survival analysis for soft-collection).
- **Uplift model: hand-rolled T-learner** over the discrete intervention set. Reasoning: CLAUDE.md §6 dependency hygiene —
  avoid pulling `econml`/`causalml` (heavy, transitive deps) into money-adjacent code for a two-arm-per-treatment CATE
  estimate we can implement transparently in ~40 lines on top of scikit-learn.
- **Diagnosis: `HeuristicDiagnoser` (offline, real rule-based) + `LLMDiagnoser` (Anthropic)**, selected by env. The
  heuristic path is a genuine classifier over error codes / mandate state, NOT a stub that reports fake success
  (CLAUDE.md §1.3). Tests run offline against the heuristic path; the `llm` marker gates the online path.
- **Gateway: `SimulatedGateway` + `RazorpayTestGateway`**, selected by env. The simulator replays the frozen batch's
  ground-truth labels; it cannot invent a success not present in the label file (CLAUDE.md §1.3).
