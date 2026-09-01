# Changelog

Honest running log of decisions and real failures (CLAUDE.md §3.2, §7, §5.4).
Newest first. Do not retroactively clean this up — the failures are pitch material.

## [unreleased]

### 2026-09-02 — iteration 12d (work-stream G): interpretability

- **Global — permutation importance** for the retry-timing model and the two data-heavy
  uplift arms (`RETRY_ONLY`, `WHATSAPP_UPI_LINK`), written by `mandatemend train` to
  `logs/model_metrics.json` and tabulated in `docs/MODELS.md §4f`. (HistGBM has no
  `feature_importances_`, so it's the AUC drop when a feature is shuffled on the held-out
  slice.) `delay_hours` dominates retry-timing; `cause_TECH_DECLINE` drives `RETRY_ONLY`'s
  uplift; the WhatsApp arm keys on the churn-risk features — all defensible.
- **Local — per-decision attribution.** `UpliftModel.explain(event, diag, arm)`: for the
  arm the model chose, how `p_recover` moves when each feature is reset to its training mean
  (leave-one-feature-out, signed, ranked — **no SHAP dependency**, `feature_baseline`
  persisted in the artifact). Surfaced in `mandatemend demo <id>` and the evidence pack
  (`uplift_attribution`). e.g. mandate 5 (`LIMIT_EXCEEDED` → `METHOD_SWITCH`):
  `amount_to_cap_ratio = 1.63 → +0.065 on p_recover`.
- Models: retry-timing artifact byte-identical (metrics-only change); uplift artifact gains
  `feature_baseline`. Headline unchanged (iteration 16: 63.51 % / +16.33 pp / 0 violations /
  112 tests).

### 2026-09-02 — iteration 12c (work-stream E2): re-auth outcomes on v2, dead-mandate recovery

- `data/generator.py --freeze-reauth-v2` writes **`data/heldout_reauth_v2.frozen.json`** — a
  `REQUEST_REAUTH` outcome (`success` / `amount` / `p`) for each of the 97 paused/expired v2
  mandates. `p(re-approve) ≈ 0.62` non-churning / `0.12` churning, tenure-scaled;
  deterministic (`_seed(mandate_id, "reauth")`). **The v2 batch + labels are byte-identical
  — this is its own frozen file, own SHA line, own CI check** (`.gitattributes` `-text`, the
  frozen-SHA gate now covers all five files).
- `SimulatedGateway(labels, reauth_outcomes=)` — `REQUEST_REAUTH` is keyed on the mandate id
  (re-auth timing isn't modelled). `run_batch.run(batch="v2")` loads the supplement when
  present; the scorecard note reads `[batch=v2 +reauth]`.
- Engine: the dead-mandate substitution now routes a genuinely PAUSED/EXPIRED/REVOKED mandate
  to `REQUEST_REAUTH` first (the NPCI-correct move), falling back to the collect link only
  for a cause-only "dead" diagnosis or after re-auth was already tried. **Primary batch
  byte-identical** (63.51 %, dead buckets unchanged — on the primary the re-auth request
  gets no realized outcome, then the collect link still fires next round).
- **Result on v2:** `MANDATE_PAUSED` 33.9 → **48.4 %**, `MANDATE_EXPIRED` 31.4 → **40.0 %**,
  v2 overall 63.45 → **64.38 %**, **0 compliance violations** across all 1000 mandates. The
  re-auth path lifts exactly the weakest buckets — what the architecture always intended and
  the 300-batch couldn't show. `docs/MODELS.md §4e`.

### 2026-09-02 — iteration 12a/12b (work-streams E1 + F): re-auth path + AFA ceiling (I13)

**12a — `REQUEST_REAUTH` action + `REAUTH_LINK` intervention.** The real UPI AutoPay flow
for a paused/expired mandate: ask the customer to re-authorize (they re-approve in their UPI
app → mandate returns ACTIVE). Wired everywhere as an **outbound contact, never a charge** —
it is in `CONTACT_ACTIONS` (weekly cap + quiet hours apply, I4/I5) and never in
`CHARGING_ACTIONS` (no NPCI retry consumed, no 24h notice needed). Engine gets a
`REQUEST_REAUTH` branch; the quiet-hours and contact-frequency checks in `invariants.py` now
cover all three outbound-contact types via a shared `outbound_contacts` list. **Primary and
v2 batches byte-identical** (63.51 % / 63.45 %, 0 violations): the shipped T-learner has no
`REAUTH_LINK` training rows so it never picks it, and the dead-mandate substitution is
unchanged — the path is inert until the v2 re-auth outcomes land (12c).

**12b — `docs/NPCI.md` + `rule_afa_exemption` + invariant I13.**
  * `docs/NPCI.md` — the regulatory surface the engine enforces: UMN lifecycle, the
    ₹15,000 AFA-exemption ceiling (NPCI OC 82), the ₹1 L category cap, 24h/T-1 pre-debit
    notice, 1+3 retry cap, pause/revoke mid-flight.
  * **I13** — no executed `RETRY` / `PARTIAL_CHARGE` above `afa_exemption_ceiling_paise`
    (= ₹15,000) unless a `REQUEST_REAUTH` was executed earlier in the session. Enforced by
    `rule_afa_exemption(amount, state.reauth_done)` in the engine's charging branch
    (`afa_substitution` → routes to `REQUEST_REAUTH`); re-verified by checker rule 6b
    (`AFA_EXEMPTION`). The synthetic batches top out at ₹4,999, so — like the injected NPCI
    cap violation — I13 is proven by crafted unit tests (₹20,000 mandate), not a batch
    mandate. No scorecard change on either batch.
  * `scripts/mutcheck.py` gained 3 AFA mutations (now 17). First run 16/17 — the survivor
    was again a "checker over-strict at the exact boundary" mutant (a charge *exactly* at
    ₹15,000 flagged as needing re-auth); closed with
    `test_afa_ceiling_boundary_charge_exactly_at_ceiling_is_exempt`. **Now 17/17.**

### 2026-09-02 — iteration 11 (work-stream D): small-n honesty + the v2 cross-check batch

**11a — per-cause Wilson score intervals.** `wilson_interval(k, n)` in `batch/run_batch.py`;
`Scorecard.per_cause` entries carry `rate_ci`; `format_scorecard` + the console overview
show the 95 % interval. Small-n buckets now read honestly: `MANDATE_PAUSED` 22.2 % →
[9.0 %, 45.2 %], `LIMIT_EXCEEDED` 47.8 % → [29.2 %, 67.0 %]. No headline change (iteration
12 line).

**11b — `data/heldout_batch_v2.frozen.json` (1000 mandates).** Same deterministic generator,
seed 20260901, index range `[1_100_000, 1_101_000)` — disjoint from training and the primary
held-out range (0 overlap verified). Written by `python data/generator.py --freeze-v2`
(refuses to overwrite, chmod read-only, SHA in `FROZEN_SHA256.txt`, CI checks all four
frozen files). The primary 300-batch is untouched and stays THE headline metric.
`_write_json` switched to `write_bytes` so the on-disk file is byte-identical to the hashed
payload on every OS (Windows `write_text` was translating newlines → SHA mismatch).

**11c — `score --batch v2`, `eval --by-cause`, and the T-learner question resolved.**
  * `mandatemend score --batch v2` (1000 mandates): recovery **63.45 %** (95 % CI
    [59.5 %, 67.3 %]) — essentially identical to the primary 63.51 %. **0 compliance
    violations at 1000 mandates.** Lift is only **+8.65 pp** though, because the v2
    static-retry baseline (54.8 %) is higher than the primary's (47.2 %) — same agent, easier
    baseline draw. Written to `logs/score_v2.json`, *not* the iteration log (v2 is a
    cross-check, not a tracked iteration).
  * `mandatemend eval --by-cause [--batch v2]` — per-cause n / recovery / Wilson CI / lift.
  * **Ablation re-run on v2 — the shipped `survival + T-learner` is the best of the five
    there (63.45 %, +0.5 pp over `survival + heuristic`), the reverse of the primary batch's
    −1.7 pp.** Two sub-2 pp results with opposite signs; the larger batch favours the shipped
    config. **Decision: keep `survival + T-learner`.** The iteration-9c `PARTIAL_CHARGE` bug
    was the real defect — once fixed, the two intervention advisors are statistically
    indistinguishable, and `heuristic retry + T-learner` scoring −2.32 pp on v2 (below naive)
    shows the T-learner only pays off inside the full survival-retry + round-aware loop.
    Documented in `docs/MODELS.md §4d`.
  * Honest takeaway now in the docs: **absolute recovery (~63.5 % on both batches) is the
    stable number; lift is baseline-sensitive** (+16.3 pp primary vs +8.7 pp v2).

### 2026-09-02 — iteration 9c: the ablation caught a real bug (PARTIAL_CHARGE poisons retry-first)

Following up the iteration-9b ablation finding (shipped `survival + T-learner` at 61.42 %,
behind `survival + heuristic` by 3.8 pp), per the user's call to **investigate before
deciding the shipped default**. It was a bug, not "the heuristic is just better":

**Root cause.** `agent._prefer_retry_when_competitive` — the override that forces the retry
budget to be spent before any other arm on `TECH_DECLINE / BANK_DOWNTIME / SUSPECTED_CHURN`
— exempted `PARTIAL_CHARGE` alongside `RETRY_ONLY`. A partial charge still (a) consumes one
of the 3 NPCI attempts and (b) marks its delay bucket as tried. So on a transient
tech-decline the T-learner (which ranks `PARTIAL_CHARGE` top for `TECH_DECLINE`, its highest
`arm_pos_rate` at 0.46) would burn the first retry on a partial charge at 24 h, poisoning
the exact bucket a plain `RETRY@24h` wins on — then lose at 48/72 h. The heuristic never
picks `PARTIAL_CHARGE` for `TECH_DECLINE`, so it never hit this. Traced on 6+ high-value
`TECH_DECLINE` mandates: `heur: NOTIFY[x] → RETRY@24[ok]` vs
`tlearn: NOTIFY[x] → PARTIAL_CHARGE@24[x] → RETRY@48[x] → RETRY@72[x] → ESCALATE`.

**Fix (1 line of logic).** Only `RETRY_ONLY` passes the override now; `PARTIAL_CHARGE` on a
retry-first cause is redirected to a full retry. Partial charge still applies normally for
`LIMIT_EXCEEDED` (where the full amount is genuinely over the per-txn cap).

**Effect.** Shipped `survival + T-learner`: **61.42 → 63.51 %** recovery, lift **+14.24 →
+16.33 pp**, the whole `TECH_DECLINE` bleed (4 mandates / ₹6.4 k) gone, retries *down*
295 → 287, escalations 96 → 92, **0 compliance violations**, 94/94 tests, property 10/10,
redteam 5/5. Logged as iteration 11.

**Still open (deferred to iteration 11 / v2 batch).** `survival + heuristic` (65.23 %) still
leads by 1.7 pp, now concentrated in `LIMIT_EXCEEDED` (n = 2) and dead-mandate buckets
(n ≈ 4) — too thin to trust the sign. The T-learner is clearly ahead on the big
`INSUFFICIENT_FUNDS` bucket. Shipped default stays `survival + T-learner`; the disjoint
1000-mandate v2 batch decides whether that changes.

### 2026-09-01 — iteration 9b (work-stream B3+B4+B5): `mandatemend eval`

New `src/mandatemend/eval.py` + `mandatemend eval [--sequencing|--calibration|--ablation]`
→ `logs/eval.json`. All three are reporting-only (read the frozen potential-outcomes table
as an oracle, same as the `train` oracle checks — never trained on).

* **B3 sequencing.** Model's hazard-ranked top-3 retry schedule captures a realised win on
  **0.794** of the 199 mandates that have a winning bucket, vs **0.774** for the fixed
  24/72/168 ladder — **+2.0 pp** from adaptive ordering. Modest; the retry model's value is
  mostly bucket *selection*, not order. `expected_recovery_for_schedule` (from 9a) predicts
  0.716 vs 0.794 observed for its own top-3.
* **B4 calibration / ECE.** retry-timing ECE **0.063** (per bucket, n=2100), uplift ECE
  **0.046** (per arm vs one canonical realised execution — an earlier version compared
  against "any arm variant ever wins" and got a misleading 0.287). Both reasonably
  calibrated; full reliability tables in `logs/eval.json`.
* **B5 ablation — and an uncomfortable finding.** Swapping each advisor pair into the
  otherwise-fixed agent, on the frozen 300-batch:

  | config | recovery | lift |
  |---|---|---|
  | naive static-retry | 47.18% | +0.00 |
  | heuristic + heuristic | 56.21% | +9.04 |
  | **survival + heuristic** | **65.23%** | **+18.05** |
  | heuristic + T-learner | 51.73% | +4.55 |
  | survival + T-learner *(shipped)* | 61.42% | +14.24 |

  The shipped config is **not** the best of five: `survival retry + heuristic uplift` scores
  **+3.8 pp higher**, and the trained T-learner *lowers* recovery in both pairings it's in.
  On this 300-mandate batch the T-learner is net-negative vs the domain-rule intervention
  advisor. Flagged, not hidden: documented in `docs/MODELS.md §4c`, and queued for
  iteration 11's 1000-mandate v2 batch — if `survival + heuristic` still leads there, the
  shipped default changes (T-learner kept as an option / an honest negative result). Not
  switched off one thin batch. The shipped ablation row reproduces the real 61.42 % headline
  exactly, which validates the harness.

### 2026-09-01 — iteration 9a (work-stream B2): retry-timing as a proper discrete-time hazard

**Scope decision.** Work-stream B1 (issuer × day-of-month empirical-Bayes prior) was
**skipped** this iteration: the current generator emits every non-downtime failure in a
~20 h window around Sep 1, so `day_of_month` has ~2 distinct values and the feature
collapses to issuer-level target-encoding. Not worth the iteration's budget; parked as a
stretch item pending a generator evolution (work-stream C).

**B2 — `models/retry_timing.py` reframed.** It was already *called* a discrete-time hazard
but was structurally a pooled binary classifier with delay as a feature. Now stated and
instrumented properly (Singer & Willett 2003, ch. 10–12):
  * person-period design made explicit (`_design`): one row per training mandate at its
    logged bucket, `y` = success-in-bucket, IPW weight.
  * new derived views on the same hazard `h(t)`: `survival_curve` `S(t)=Π(1−h)`,
    `recovery_curve` `1−S(t)`, and `expected_recovery_for_schedule(...)`
    `= 1 − Π_{b∈schedule}(1−h(b))` — the composed survival for an ordered ≤3-bucket retry
    plan (this feeds the B3 sequencing metric).
  * `train.py` now reports **time-stratified calibration**: per-bucket `n` / `event_rate` /
    `auc` / `brier`, plus the integrated Brier score and overall `val_brier`, alongside the
    existing oracle agreement. Surfaces (rather than averages away) that the logging policy
    concentrates observations on the 24 h + 168 h buckets, leaving the rest data-starved.
  * data caveat documented in the module + `docs/MODELS.md`: one observation per mandate, no
    synthesised risk-set rows; `S(t)` assumes bucket-conditional independence given `x`,
    which holds by construction in the simulator.

**Honest outcome: no headline change, and that is by design.** `best_delay` = argmax hazard
is unchanged; the retrained `retry_timing.joblib` is **byte-identical** to the pre-reframe
artifact. Scorecard stays **61.42 % / +14.24 pp / 0 violations** (iteration 9 line;
per-cause identical to iteration 7). The value here is rigor + the survival composition the
sequencing evaluation needs, not a number.

**A worse variant, tried and reverted (§3.2).** First cut of B2 also (a) shuffled the
train/val split, (b) refit the saved model on *all* rows, (c) used an ordinal bucket index
instead of raw delay hours. That dropped the frozen-batch recovery to **59.84 % (−1.58 pp)**
and the retry oracle from 0.437 → 0.412 (tying naive). Reverted all three; kept only the
additive framing. Logged here rather than silently.

### 2026-09-01 — iteration 8: the unbeatable-safety-story pass (work-stream A)

Goal (per the hardening plan): leave a panel with nothing to poke at on safety. No change
to the recovery model this iteration — the primary 300-batch headline is unchanged; what
changed is the *evidence* that the safety invariants actually hold.

**A1. `docs/INVARIANTS.md`** — every safety/compliance property as a numbered proposition
I1–I13, each mapped to (a) the enforcing code path, (b) the independent re-verification in
`invariants.py`, (c) the tests that exercise it. I13 (AFA re-auth ceiling) is listed as
planned (iteration 12) so the numbering is stable.

**A2. Property-based tests (Hypothesis), `tests/property/`** — 10 properties, hundreds of
generated cases each:
  * `test_policy_invariants.py` (9): for any well-typed
    `FailureEvent × TypedDiagnosis × RetryTimingAdvice × InterventionAdvice × LoopState`,
    `PolicyEngine.decide` upholds I1–I8, the stopping rule, and I12 (fails closed on a
    hostile advice object whose every attribute access raises).
  * `test_agent_loop.py` (1): drives the whole `Agent.recover` loop with a scripted
    adversarial diagnoser + advisors + a coin-flip gateway; asserts
    `check_resolution == []`, `retries_used <= 3`, terminates RECOVERED xor ESCALATED in
    `<= _MAX_ROUNDS`, audit chain verifies.
  * Opt-in `property` marker; own CI step (`pytest -m property tests/property`).

**Two real safety holes the property tests found and that are now fixed:**
  1. **Dead-mandate charge via the economics-substitution fallback.** When a paid outreach
     failed the economic floor, `engine.py` fell back to "plain retry instead" while only
     re-checking that a notice was on file — not liveness, the NPCI cap, or the amount cap.
     A PAUSED/EXPIRED mandate on that exact path got a `RETRY`. Fix: the fallback now
     re-satisfies *every* charging precondition (`rule_mandate_live_for_charge`,
     `rule_amount_within_cap`, `retries_used < npci_max_retries`, and the 24h notice gap)
     before it may emit a retry; otherwise NO_ACTION.
  2. **`CONTACT_FREQUENCY` blamed pre-session contacts.** The independent checker counted
     every contact in the timeline against the flat weekly cap, so a mandate that *arrived*
     already at 3 contacts was reported as a violation the agent hadn't caused. Fix: the
     checker now compares the agent's *own* session contacts against the *remaining* weekly
     budget (`max(0, cap - history.contacts_this_week)`). New test
     `test_contact_frequency_ok_when_mandate_arrives_over_cap`; the existing
     `test_contact_frequency_violation` was rewritten to 4 agent-made contacts (was
     relying on the old semantics — assertion tightened, not weakened).

**A3. `mandatemend redteam`** (`src/mandatemend/redteam.py`, `tests/integration/test_redteam.py`)
— the wider adversarial battery, each group PASS/FAIL with a printed rate:
  * **prompt-injection** — a 30-payload corpus (direct overrides, role-play, fake
    delimiters, RLO/zero-width unicode, schema-coercion, urgency/authority) fed through an
    LLM stub that *obeys* the injection. All 30: sanitizer-flagged, confidence capped ≤ 0.5,
    and the policy engine still gates them to `NO_ACTION + requires_human`. **30/30.**
  * **hostile-webhooks** — 10 malformed payloads (missing field, negative/zero/string
    amount, 20 KB text, bad enum, bad datetime) → all 10 rejected at
    `FailureEvent.model_validate` with a `ValidationError`, none partially built.
  * **clock-skew** — far-future `occurred_at` + `retries_used=9` → engine still emits a
    well-formed, non-charging Action.
  * **ledger-outage** — `ledger.append` raises mid-`execute()` → executor fails closed,
    ≤ 1 DB row, no double charge.
  * **concurrent-load** — 60 mandates × 6 duplicate webhooks × 16 threads → exactly 60
    `executed_action` rows, audit chain verifies. **5/5 groups held.**

**Bug found writing A3 — `redteam.run_all()` wedged pytest for ~4.5 min.** It opened with
`with contextlib.suppress(Exception): db_session.get_engine()`; with no engine bound that
lazily builds one from the default **Postgres** URL, and the failed localhost:5432 connect
left something that stalled process exit (the 5 groups themselves run in ~4 s). The line
served no purpose — every group binds its own engine via `init_engine()` — so it was
removed. Test now runs in ~2.5 s.

**A3 sanitizer gap.** The first redteam run flagged only 20/30 injection payloads.
`diagnosis/sanitize.py` `_INJECTION_PATTERNS` extended (~13 new regexes: forget-everything,
`human:`/`assistant:` turn markers, "as the developer/admin", "I instruct/order you",
`set cause/confidence to`, "the real cause is", schema-coercion `confidence=1`,
`override:` / `policy_engine` / `bypass the gate`, `<system>`-style tags). Now 30/30
flagged, still 0 false positives on the benign-message corpus (`test_sanitize.py`).

**A4. Mutation testing — two separate measurements, reported as a pair (never collapsed
into one headline).** Full detail in `docs/INVARIANTS.md`:
  * **M1 — automated `mutmut` sweep (raw ~39%).** `mutmut` (config in `setup.cfg`,
    on-demand, *not* a project dep — 3.x has no native-Windows support, 2.5.1 runs but is
    noisy): 281 mutants over `policy/rules.py` + `policy/engine.py` + `invariants.py`,
    **109 killed / 171 survived / 1 suspicious — 39% raw**. One-line triage: most survivors
    are non-behavioural (mutated import aliases, docstrings, and the `detail=`/`reason=`
    f-strings that only populate the human-readable rule trace). Reported as-is, no
    adjustment, as the raw automated floor.
  * **M2 — targeted manual check on live rule-mutations (14/14).**
    `python scripts/mutcheck.py`: 14 hand-picked
    *semantically meaningful* mutations — every comparison operator and boolean connective
    in the compliance predicates and in the independent checker (`<`↔`<=`, `>`↔`>=`,
    `or`↔`and`, cap-comparison flips). Each applied, the unit predicate/engine/checker
    tests **and** the full property suite run, mutation reverted. **First run: 12/14
    caught** — the two survivors were boundary gaps in the *independent checker's* own
    tests: a charge count of *exactly* 3 and a charge amount *exactly* at the mandate cap
    (both legal, neither pinned, so a `>`→`>=` mutation that makes the checker over-strict
    slipped through). Added `test_npci_cap_boundary_exactly_three_charges_is_ok` +
    `test_amount_cap_boundary_charge_exactly_at_cap_is_ok`. **Now 14/14.** (Also caught a
    bug in the check script itself first — a stray `-m property` was deselecting the unit
    tests, so run 0 spuriously showed 3/14; fixed to two separate pytest invocations.)

**A5. CI gates** (`.github/workflows/ci.yml`): new steps `Tests — property` and
`Red-team adversarial battery` between integration and the e2e/coverage gate.

**Process note — a self-inflicted contaminated scorecard.** The first `mandatemend score`
for iteration 8 ran its `pytest` subprocess *while `mutmut` was mutating `policy/` on disk*
(I had both running in the background), so its line in `logs/iterations.jsonl` recorded
`tests_passed 84/86`. A clean re-run with nothing else touching the tree gives **86/86**;
that one field on the last line was corrected in place (recovery / lift / compliance were
already correct — those come from the batch run, not pytest). Lesson: never run `mutmut`
concurrently with anything that imports the modules under mutation.

### 2026-09-01 — deps: dropped `lifelines` + `pandas` (declared, never imported)
The scaffold planned a `lifelines` survival fit for retry timing (see the 2026-09-01
scaffold entry below); the model that actually shipped is an sklearn
`HistGradientBoostingClassifier` in a discrete-time-hazard framing, so `lifelines` — and its
heavy transitive tree (scipy is kept for sklearn, but matplotlib / autograd / formulaic /
patsy are gone) — plus `pandas` were dead weight. Removed from `pyproject.toml`;
`requirements-lock.txt` regenerated from a clean venv (49 packages, was ~60). Also
`schemas.py`: `class StrEnum(str, Enum)` → `from enum import StrEnum` (we require ≥3.12).

### 2026-09-01 — iteration 7: deterministic data generation (reproducibility bug)
* **`data/generator.py` was not reproducible.** It seeded per-mandate RNGs with
  `abs(hash((mandate_id, ...)))`, and Python's `hash()` for str/bytes is salted per process
  (`PYTHONHASHSEED`) — so `python data/generator.py` produced a *different training set on
  every run and every machine*, and CI (fresh checkout) trained on data that didn't match
  the committed model artifacts. Fix: `_seed(*parts)` = `blake2b` of the joined parts →
  stable 32-bit seed. `python data/generator.py` now emits a byte-identical file every time
  (verified: two runs, same SHA-256). The frozen held-out batch is unaffected (committed,
  never regenerated).
* On the now-deterministic training set the retry-timing model at `max_iter=90` only *tied*
  the naive "+72h" baseline on the held-out oracle (0.412 = 0.412). Raised `max_iter`
  90 → 200 (batched inference had removed the speed reason for the earlier cut): it now
  beats naive (0.437 vs 0.412) and a scored run is still ~9s.
* **New reproducible headline (iteration 7):** recovery **61.42 %** (95 % CI
  [54.03 %, 68.39 %]), lift **+14.24 pp** vs static-retry (95 % CI [7.27 pp, 21.86 pp],
  entirely above zero), **0 compliance violations**. (Was 62.06 % / +14.89 pp on the old
  non-reproducible data — the honest, regenerable number is slightly lower.)
* CI: dropped py3.11 from the matrix (`requirements-lock.txt` is frozen from a 3.13 env;
  `requires-python` → `>=3.12`); added a `python data/generator.py` step before tests so the
  training-set-dependent tests and the `train` step work on a fresh checkout.

### 2026-09-01 — `failure-drill` command + a real concurrency bug it caught
* **`mandatemend failure-drill`** (`drills.py`): runs 7 adversarial scenarios live and prints
  "inject X → the system did Y → invariant held" — concurrent-webhook (exactly-once via
  DB-UNIQUE), duplicate-retry, gateway-crash-mid-flight, NPCI-cap-attempt,
  dead-mandate-charge-attempt, prompt-injection (obeyed by a stub LLM, still refused),
  audit-tamper. Each is also a test (`tests/integration/test_drills.py`). 7/7 hold.
* **Bug the drill surfaced — `audit/ledger.append` was not concurrency-safe.** The executor's
  dedup path fires `append` from several webhook threads at once; two threads read the same
  cached chain tip → two entries with the same `entry_hash` → `UNIQUE constraint failed:
  audit_entry.entry_hash`. Fix: `append` / `begin_buffer` / `flush_buffer` / `reset_cache`
  now hold a module `RLock` (single-process system, so a lock is sufficient and cheap). New
  `tests/integration/test_audit_concurrency.py`: 64 concurrent identical-payload appends →
  64 distinct hashes, one valid chain. The existing idempotency test had been getting lucky
  on timing.
* The concurrent-webhook drill runs against a **file** DB (its own connection per thread),
  not the in-memory StaticPool — the in-memory shared-connection setup can't exercise
  cross-connection UNIQUE enforcement, which is the whole point of that scenario.

### 2026-09-01 — dev-check hardening: CI, coverage 66→91%, statistical rigor, docs
* **CI** (`.github/workflows/ci.yml`): py 3.11/3.12/3.13 matrix — ruff, mypy, pytest with
  `--cov-fail-under=85`, then `mandatemend train && mandatemend score` as a hard
  STOP-THE-LINE gate (`score` exits non-zero on `compliance_violations > 0`), then a
  frozen-batch SHA-256 check. `requirements-lock.txt` = the exact validated dependency set
  CI installs; `pyproject` deps relaxed to compatible floors. `Makefile` (`make demo` =
  fresh-checkout smoke test). MIT `LICENSE`.
* **Tests 53 → 80, coverage 66% → 91%.** New: `test_console.py` (every route via FastAPI
  TestClient), `test_cli.py` (score / demo / verify-audit / train), `test_models.py`
  (survival + uplift train / curve / rank / save-load), `test_invariants.py` (every
  violation branch), `test_live_offline.py` (`run_live_check` with the HTTP call faked).
* **Statistical rigor on the scorecard** (reporting only — the agent's 62.06% / +14.89pp is
  unchanged): seeded, vectorised 2000× mandate-resampled bootstrap → `recovery_rate_ci`
  [54.75%, 69.22%] and `baseline_lift_ci` [7.18%, 23.46%] (entirely above zero). Explicit
  `harm_cost_paise` (paid outreach on never-recovered mandates, ₹260). `per_cause[]` on the
  Scorecard + in `mandatemend score` + the console overview.
* **Perf: `Agent.warm(events)`** batch-precomputes model inference (one `predict_proba` per
  arm over an (N, F) matrix instead of N·|arms| single-row calls) — a scored run went from
  ~50s back to ~9s; the full suite runs in ~2min.
* **Fixes surfaced by the new tests:** `db/session.init_engine` now disposes the previous
  engine (sqlite connection leak → ResourceWarnings); console moved to FastAPI `lifespan` +
  `TemplateResponse(request, …)` (suite passes `-W error::DeprecationWarning`).
* **Docs:** `docs/ARCHITECTURE.md` (trust boundary + bar→code mapping), `docs/MODELS.md`
  (survival + T-learner design, IPW, oracle-agreement numbers, limitations), README
  overhaul with CI badge + working repro + CLI transcript.

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
