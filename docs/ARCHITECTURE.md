# MandateMend — architecture

Track 03 bar: *"Don't just identify the problem. Show measured money recovered across a
batch, with compliant escalation, stopping rules, and an audit trail."* This document maps
that sentence onto the code.

## 1. The trust boundary

```
 ┌─ ingest ────────────────────────────────────────────────────────────────────┐
 │ Razorpay test-mode webhook  /  frozen synthetic batch                       │
 │        └─> normalize -> FailureEvent   (schemas.py, frozen, INR paise)      │
 └───────────────────────────────┬────────────────────────────────────────────┘
                                 v
 ┌─ diagnosis  (LLM, SANDBOXED — zero execution authority) ────────────────────┐
 │ diagnosis/llm_diagnoser.py   raw_err_text -> sanitize.scan() -> fenced      │
 │   -> Anthropic -> strict JSON -> TypedDiagnosis  (schema-validated)         │
 │   any parse/schema failure or injection flag -> confidence capped / UNKNOWN │
 │ diagnosis/heuristic_diagnoser.py  offline rule classifier (the default;     │
 │   never reads raw_err_text, so injection-immune by construction)            │
 └───────────────────────────────┬────────────────────────────────────────────┘
                                 v
 ┌─ advisory models  (ADVICE ONLY — the engine may veto or downgrade any of it)┐
 │ models/retry_timing.py  discrete-time hazard: P(retry succeeds | x, bucket) │
 │ models/uplift.py        IPW T-learner: argmax  P_arm(recover|x) - P_NO_OP   │
 │ models/advisors.py      round-aware wrappers (walk the ranking, skip tried) │
 └───────────────────────────────┬────────────────────────────────────────────┘
                                 v
 ┌─ POLICY ENGINE  (deterministic — the ONLY component that constructs an Action)
 │ policy/rules.py   small, individually unit-tested predicates:              │
 │   confidence_gate · mandate_live_for_charge · npci_retry_cap ·            │
 │   predebit_notice_24h · quiet_hours · contact_frequency ·                 │
 │   outreach_economics · stopping_rule · amount_within_cap                  │
 │ policy/engine.py  composes them; every branch appends a RuleEvaluation to  │
 │   the Action's rule_trace; unexpected error -> NO_ACTION + human queue     │
 └───────────────────────────────┬────────────────────────────────────────────┘
                                 v
 ┌─ EXECUTOR  (idempotent) ───────────────────────────────────────────────────┐
 │ executor/executor.py  RESERVE (INSERT idempotency_key, COMMIT) -> EXECUTE  │
 │   (gateway) -> FINALIZE (write outcome + audit entry).  Exactly-once is a  │
 │   DB UNIQUE constraint, not application logic. Crash after RESERVE ->      │
 │   action stays "attempted", never retried (fail closed).                   │
 │ executor/gateway.py  SimulatedGateway (frozen potential-outcomes table)    │
 │   | RazorpayTestGateway (real POST /v1/payment_links, test mode)           │
 └───────────────────────────────┬────────────────────────────────────────────┘
                                 v
 ┌─ AUDIT LEDGER  (append-only, hash-chained) ───────────────────────────────┐
 │ audit/ledger.py  entry_hash = sha256(prev_hash + canonical_json(payload))  │
 │   verify_chain() recomputes the whole chain; any edit/delete breaks it     │
 └───────────────────────────────┬────────────────────────────────────────────┘
                                 v
 ┌─ independent compliance re-check  +  operator console ─────────────────────┐
 │ invariants.py  re-reads the produced timeline and re-verifies EVERY rule   │
 │   OUTSIDE the engine (the engine can never mark its own homework)          │
 │ console/       dense server-rendered views over the cached batch           │
 └──────────────────────────────────────────────────────────────────────────┘
```

## 2. "Every money action explainable, bounded and gated" → code

| requirement | where |
|---|---|
| the LLM has no execution authority | `TypedDiagnosis` is the only thing `llm_diagnoser` returns; `engine.decide` is the only constructor of `Action` |
| every action is explainable | `Action.rule_trace` (non-empty by a `schemas.py` validator); rendered per-round in `console/templates/mandate.html` and `mandatemend demo` |
| NPCI retry cap (1 + max 3) | `rules.rule_npci_retry_cap`; re-checked in `invariants` (`NPCI_RETRY_CAP`) |
| 24h pre-debit notice before a charge | `rules.rule_predebit_notice`; re-checked in `invariants` (`PREDEBIT_NOTICE`) |
| quiet hours (21:00–08:00) | `rules.rule_quiet_hours` + `clamp_out_of_quiet`; re-checked (`QUIET_HOURS`) |
| weekly contact cap | `rules.rule_contact_frequency` over `CONTACT_ACTIONS`; re-checked (`CONTACT_FREQUENCY`) |
| never charge a dead mandate | `rules.rule_mandate_live_for_charge`; re-checked (`DEAD_MANDATE_CHARGE`) |
| never charge above the per-txn cap | `rules.rule_amount_within_cap`; re-checked (`AMOUNT_OVER_CAP`) |
| AFA: a debit above ₹15k needs a re-auth first, not a bare notice (I13) | `rules.rule_afa_exemption`; engine `afa_substitution` → `REQUEST_REAUTH`; re-checked (`AFA_EXEMPTION`). See `docs/NPCI.md` |
| dead-mandate recovery is a re-auth request, not a debit | `REQUEST_REAUTH` (an outbound *contact*: contact-cap + quiet hours; never a charge). Demonstrated on the v2 batch — see `docs/MODELS.md §4e` |
| low-confidence diagnosis → NO_ACTION + human | `rules.rule_confidence_gate` (`low_confidence_threshold = 0.55`) |
| stopping rule | `rules.rule_stopping` (in-session hard declines ≥ retry budget) + the agent's contact/round-budget guards |
| fail closed | `engine.decide` try/except → NO_ACTION + `requires_human`; `executor` gateway-exception path |
| audit trail | `audit/ledger.py`; `verify_chain` asserted by `run_batch`, the e2e test, and `mandatemend verify-audit` |
| measured money recovered across a batch | `batch/run_batch.py` → `Scorecard` (money-weighted rate + 95% bootstrap CI, lift vs 3 baselines, per-cause, harm cost) |

## 3. The per-mandate loop (`agent.py`)

`diagnose once` → up to `_MAX_ROUNDS` (10) of `advisors → engine.decide → executor.execute →
update LoopState`. Round-awareness: the agent tracks `tried_delays` / `tried_interventions`
and passes them to the advisors so it walks down the ranking instead of repeating a
recommendation. A **stall-breaker** escalates if the same non-charging action is chosen
twice running. **Termination invariant:** every mandate ends `recovered` **or**
`STOP_AND_ESCALATE` (human queue) — never silently dropped; a post-loop guard enforces it.

## 4. Data & scoring isolation (CLAUDE.md §1.3)

- `data/heldout_batch.frozen.json` + `data/heldout_labels.frozen.json` are read-only
  (`-text` in `.gitattributes`, SHA-256 in `data/FROZEN_SHA256.txt`, generator refuses to
  overwrite, CI re-checks the hash).
- The scored run uses an **in-memory** SQLite DB (no fsync). The DB-UNIQUE idempotency
  guarantee is identical in memory; the concurrent-webhook proof lives in
  `tests/integration/test_executor_idempotency.py` against a file DB.
- The real Razorpay call (`mandatemend live-check`) is **additive** — a separate module
  (`live.py`), a separate persistent DB (`logs/live_audit.sqlite`), never inside `run_batch`.

## 5. Failure handling on record (`CHANGELOG.md`)

The iter-0 STOP-THE-LINE (contact-cap applied to only one action type), the gateway
wall-clock-vs-causal-bucket bug that silently collapsed late retries, the stopping rule that
counted pre-session history and ate the retry budget, and the reverted iter-5 regression are
all documented as real "what broke" material, not smoothed over.
