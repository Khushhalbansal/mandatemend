# MandateMend — safety & compliance invariants

This is the formal specification of every safety property MandateMend guarantees. Each
invariant is a numbered, independently-checkable proposition mapped to:

- **(a) Enforced by** — the code path in the deterministic policy engine / executor that
  makes it hold.
- **(b) Re-verified by** — the *independent* check that confirms it after the fact, without
  the engine being able to mark its own homework (CLAUDE.md §1.3 / §3).
- **(c) Proven by** — the tests (unit, property-based, red-team) that exercise it.

`settings.*` values are from `src/mandatemend/config.py`. "The engine" = `PolicyEngine`
in `src/mandatemend/policy/engine.py`; "the checker" = `check_resolution` in
`src/mandatemend/invariants.py`.

The batch runner calls the checker on **every** mandate in the frozen held-out batch and
the scorecard reports `compliance_violations`, which must be **0** — a non-zero count is
stop-the-line (CLAUDE.md §3.1).

---

## I1 — NPCI retry cap

**At most `settings.npci_max_retries` (= 3) executed charge attempts per mandate per
recovery session.**

- **Enforced by** `rule_npci_retry_cap(state)` — the engine checks
  `state.retries_used < 3` before every charging action (`engine.py:135`); on failure the
  action is substituted with a final `SEND_NOTIFICATION`.
- **Re-verified by** checker rule 1 (`invariants.py:34`): counts executed `RETRY` /
  `PARTIAL_CHARGE` timeline steps, flags `NPCI_RETRY_CAP` if `> 3`.
- **Proven by** `tests/unit/test_invariants.py::test_npci_cap_violation`,
  `tests/unit/test_policy_engine.py` (cap-reached substitution),
  `tests/property/test_policy_invariants.py` (holds for every generated `LoopState`),
  `tests/property/test_agent_loop.py` (`res.retries_used <= 3` over the full loop).

## I2 — 24h pre-debit notice

**Every executed charge is preceded by a `SEND_NOTIFICATION` at least
`settings.predebit_notice_hours` (= 24) hours earlier.**

- **Enforced by** `rule_predebit_notice(state, scheduled_at)` (`engine.py:186`): a charge
  with no `state.last_notice_at`, or a notice→debit gap `< 24h`, is downgraded to
  `SEND_NOTIFICATION`. The economics-substitution fallback path (`engine.py:242`) re-checks
  the same 24h gap before it is allowed to emit a plain retry.
- **Re-verified by** checker rule 2 (`invariants.py:42`): for each executed charge, requires
  a prior executed notice `<= charge_time - 24h`.
- **Proven by** `test_invariants.py::test_predebit_notice_violation`, the property tests
  (no `PREDEBIT_NOTICE` string ever appears), and the iteration-8a property test that
  originally caught a dead-mandate charge slipping past this fallback (fixed).

## I3 — No charge on a dead mandate

**No `RETRY` / `PARTIAL_CHARGE` is executed when `mandate_state ∈ {PAUSED, EXPIRED,
REVOKED}` or the diagnosis cause ∈ {MANDATE_PAUSED, MANDATE_EXPIRED}.**

- **Enforced by** `rule_mandate_live_for_charge(event, diag)` (`engine.py:120`): a
  non-live mandate forces `action_type` off the charging branch to a WhatsApp UPI collect
  link. The economics fallback re-checks liveness before emitting a retry.
- **Re-verified by** checker rule 5 (`invariants.py:76`): flags `DEAD_MANDATE_CHARGE` if
  any charge executed against a dead `mandate_state`.
- **Proven by** `test_invariants.py::test_dead_mandate_charge_violation`,
  `tests/property/test_policy_invariants.py::test_dead_mandate_is_never_charged`.

## I4 — No outbound contact in quiet hours

**No executed `SEND_NOTIFICATION` / `OFFER_ALTERNATE_METHOD` / `REQUEST_REAUTH` is scheduled
in `[settings.quiet_hours_start, settings.quiet_hours_end)` = [21:00, 08:00) IST.**

- **Enforced by** `clamp_out_of_quiet(scheduled_at)` (`rules.py`), applied to every
  outbound-contact schedule before it is built; `rule_quiet_hours` records the check in the
  rule trace.
- **Re-verified by** checker rule 3 (`invariants.py`): flags `QUIET_HOURS` for any of the
  three outbound-contact action types scheduled at an hour `>= 21` or `< 8`.
- **Proven by** `test_invariants.py::test_quiet_hours_violation`, property tests.

## I5 — Weekly contact cap

**The agent makes at most `settings.max_contacts_per_week` (= 3) outbound contacts, and
never more than the mandate's *remaining* weekly budget on arrival.**
Contact actions = `SEND_NOTIFICATION` + `OFFER_ALTERNATE_METHOD` + `REQUEST_REAUTH`
(`policy.rules.CONTACT_ACTIONS`). `REQUEST_REAUTH` — a mandate re-authorization request link
(iteration 12a) — is an outbound contact: it counts here and against quiet hours (I4), but
is **not** a charge, so it never touches the NPCI retry budget (I1) and needs no pre-debit
notice (I2).

- **Enforced by** `rule_contact_frequency(state)` (`engine.py`, notification /
  alternate-method / re-auth branches): checks `state.contacts_this_week < 3` before any
  contact action; on failure, holds for an already-scheduled retry window or escalates to a
  human.
- **Re-verified by** checker rule 4 (`invariants.py`): `session_contacts >
  max(0, 3 - event.history.contacts_this_week)` → `CONTACT_FREQUENCY`, where
  `session_contacts` counts every executed `SEND_NOTIFICATION` / `OFFER_ALTERNATE_METHOD` /
  `REQUEST_REAUTH`. A mandate that arrives already at/over the cap is not the agent's fault
  — what is checked is that the agent then adds nothing.
- **Proven by** `test_invariants.py::test_contact_frequency_violation`,
  `::test_contact_frequency_ok_when_mandate_arrives_over_cap`, property tests.

## I6 — Charge within the per-transaction mandate cap

**No executed charge exceeds `event.mandate_max_amount_paise`.**

- **Enforced by** `rule_amount_within_cap(amount, event)` (`engine.py:153`): a full amount
  over cap is stepped down to a partial charge, or — if even the partial is over cap — to
  an alternate-method offer.
- **Re-verified by** checker rule 6 (`invariants.py:79`): flags `AMOUNT_OVER_CAP` for any
  executed charge `amount_paise > mandate_max_amount_paise`.
- **Proven by** `test_invariants.py::test_amount_over_cap_violation`, property tests.

## I7 — LLM diagnosis has no execution authority

**A `TypedDiagnosis` never becomes an executable `Action` unless it passes
`rule_confidence_gate` (`confidence >= settings.low_confidence_threshold` = 0.55). A
sanitizer-flagged diagnosis has `confidence` capped at 0.5 and so can never pass.**

- **Enforced by** `rule_confidence_gate(diag)` as the *first* gate in `_decide`
  (`engine.py:93`); `LLMDiagnoser` caps `confidence <= 0.5` on any sanitizer hit
  (`llm_diagnoser.py:61`) and `<= 0.6` on a structured-fact contradiction. The engine is
  the only place an `Action` is constructed (`_build` / `_terminal`).
- **Re-verified by** the red-team prompt-injection group: a stubbed LLM that *obeys* an
  injection is still gated to `NO_ACTION + requires_human` for all 30 payloads.
- **Proven by** `src/mandatemend/redteam.py::_group_prompt_injection`,
  `tests/integration/test_redteam.py`, `tests/property/test_policy_invariants.py`
  (arbitrary low-confidence diagnosis ⇒ `NO_ACTION`).

## I8 — Every executed action carries a non-empty rule trace

- **Enforced by** `_build` / `_terminal` always passing the accumulated `trace` list, which
  is never empty (the confidence gate appends the first entry unconditionally).
- **Re-verified by** checker rule 7 (`invariants.py:86`): flags `EMPTY_RULE_TRACE`.
- **Proven by** `test_invariants.py::test_clean_timeline_has_no_violations`, property tests
  (`assert action.rule_trace` on every generated case).

## I9 — The audit chain verifies

**`ledger.verify_chain()` returns OK after every run: `entry_hash[i] = sha256(entry_hash[i-1]
+ canonical_json(entry[i]))`, append-only, no gaps.**

- **Enforced by** `src/mandatemend/audit/ledger.py` — no code path updates or deletes a
  past row; every executor step appends.
- **Re-verified by** `verify_chain()` recomputing the hash chain from row 0; the batch
  runner and `mandatemend verify-audit` both call it.
- **Proven by** `tests/unit/test_audit_ledger.py`, `redteam.py::_group_concurrent_load`
  (chain still verifies after 360 concurrent executions),
  `redteam.py::_group_ledger_outage`.

## I10 — Every mandate terminates RECOVERED or ESCALATED — never dropped

- **Enforced by** the agent loop (`agent.py`, `_MAX_ROUNDS = 10`): the loop exits either on
  a successful charge (`recovered`) or by emitting `STOP_AND_ESCALATE` /
  `NO_ACTION + requires_human` (`escalated_to_human`). The stall-breaker escalates on a
  repeated non-charging action rather than idling.
- **Re-verified by** `tests/property/test_agent_loop.py`:
  `assert res.recovered or res.escalated_to_human` and
  `not (res.recovered and res.escalated_to_human)` for every generated case; also
  `len(res.timeline) <= _MAX_ROUNDS`.
- **Proven by** the property loop test (150 examples/run) + the batch run (300 mandates,
  0 dropped).

## I11 — Exactly one execution per idempotency key

**The `executed_action.idempotency_key` column has a DB-level `UNIQUE` constraint. A
duplicate INSERT raises `IntegrityError`; the executor returns the prior outcome with
`dedup_hit=True`. The reserve commits *before* the gateway call (fail closed: a mid-flight
crash never risks a second charge).**

- **Enforced by** `Executor.execute` RESERVE-then-EXECUTE (`executor/executor.py:53`) +
  the `UNIQUE` constraint in `db/models.py` (not application logic).
- **Re-verified by** `redteam.py::_group_concurrent_load`: 60 mandates × 6 duplicate
  webhooks × 16 threads ⇒ exactly 60 `executed_action` rows.
- **Proven by** `tests/integration/test_executor_idempotency.py` (concurrent-webhook +
  duplicate-retry failure injection), `tests/integration/test_redteam.py`.

## I12 — Any engine exception ⇒ NO_ACTION + human queue (fail closed)

- **Enforced by** the `try/except` wrapper around `_decide` (`engine.py:63`): any
  unexpected exception returns a `_terminal(NO_ACTION, human=True)` with an
  `engine_fail_closed` rule-trace entry. The executor's gateway call is likewise wrapped
  (`executor.py:75`) and never re-raises into the loop.
- **Re-verified by** `redteam.py::_group_clock_skew` (hostile inputs still yield a
  well-formed non-charging action) and `_group_ledger_outage` (ledger failure ⇒ ≤ 1 DB
  row, no double charge).
- **Proven by** `tests/property/test_policy_invariants.py` (a hostile advice object never
  produces a charge), `tests/integration/test_redteam.py`.

## I13 — AFA re-authorization ceiling  *(iteration 12b)*

**No executed `RETRY` / `PARTIAL_CHARGE` for more than `settings.afa_exemption_ceiling_paise`
(= ₹15,000) unless a `REQUEST_REAUTH` was executed earlier in the same session.** Above the
UPI-AutoPay AFA-exemption ceiling a debit needs a fresh Additional Factor of Authentication
(a re-authorization), not a bare 24h pre-debit notice (NPCI OC 82 — see `docs/NPCI.md §2`).

- **Enforced by** `rule_afa_exemption(amount_paise, state.reauth_done)` (`rules.py`), checked
  in the engine's charging branch after the per-txn cap check (`engine.py`,
  `afa_substitution`): an over-ceiling charge with `reauth_done == False` is replaced by
  `REQUEST_REAUTH`. `state.reauth_done` is set by the agent after an executed `REQUEST_REAUTH`.
- **Re-verified by** checker rule 6b (`invariants.py`): for each executed charge with
  `amount_paise > ceiling`, requires a prior executed `REQUEST_REAUTH` in the timeline;
  flags `AFA_EXEMPTION` otherwise.
- **Proven by** `test_policy_rules.py::test_afa_exemption`,
  `test_policy_engine.py::test_high_value_charge_needs_reauth_first`,
  `test_invariants.py::test_afa_exemption_violation` (crafted ₹20,000 mandate — the synthetic
  batches top out at ₹4,999, so like the injected-violation case for I1, this invariant is
  proven by a crafted test rather than a batch mandate).

---

## Mutation testing

The goal is to prove the tests *catch a broken rule*, not merely execute it. There are
**two separate measurements** here. They answer different questions and are deliberately
**not** collapsed into a single headline number:

| # | measurement | scope | score | what it tells you |
|---|---|---|---|---|
| **M1** | automated `mutmut` sweep | *every* mutable token in `policy/rules.py` + `policy/engine.py` + `invariants.py` (281 mutants) | **109 killed / 171 survived — ~39% raw** | broad but noisy; most survivors triaged as non-behavioural (mutated imports, docstrings, and `detail=`/`reason=` rule-trace strings that change no decision) |
| **M2** | targeted manual check (`scripts/mutcheck.py`) | 17 hand-picked *live rule-mutations* — every comparison operator / boolean connective in the compliance predicates and the independent checker | **17 / 17 killed — 100%** | the decision-changing mutations are all caught by a unit test or a property |

M1 is the honest raw floor; M2 is the targeted proof on the mutations that actually matter.
Read them as a pair.

### M1 — automated `mutmut` sweep (raw: ~39%)

`mutmut` (config in `setup.cfg`) over `policy/rules.py` + `policy/engine.py` +
`invariants.py`: **281 mutants, 109 killed, 171 survived, 1 suspicious — 39% raw kill
rate.** One-line triage of the 171 survivors: **the large majority are non-behavioural** —
mutated import aliases, docstring text, and the `detail=` / `reason=` f-strings that only
populate the human-readable `rule_trace` (e.g. `"confidence=%.2f vs threshold"` →
`"XXconfidence"` changes no decision, so no test fails, correctly). Notes:

- `mutmut` 3.x has no native-Windows support; 2.5.1 runs but is pinned only for this
  analysis and is **not** a project dependency.
- The survivor list has not been individually annotated mutant-by-mutant; the 39% is
  reported as-is, without adjustment, as the raw automated floor.
- The mutations that *would* change a decision are enumerated and checked directly in M2.

### M2 — targeted manual check on live rule-mutations (17/17)

`python scripts/mutcheck.py` applies 17 hand-picked **decision-changing** mutations — every
comparison operator and boolean connective in the compliance predicates (`policy/rules.py`)
and in the independent checker (`invariants.py`): `<`↔`<=`, `>`↔`>=`, `or`↔`and`,
cap-comparison flips, the NPCI off-by-one. For each: apply, run the unit
predicate/engine/checker tests **and** the full property suite, revert. A mutant is killed
if either run goes red.

**Result: 17 / 17 caught (100%).** The mutation set grows with the rule set — iteration 12b
added 3 for the AFA ceiling (I13). Each time, a "checker over-strict at the exact boundary"
mutant has survived first (a charge count of *exactly* 3, an amount *exactly* at the mandate
cap, an amount *exactly* at the AFA ceiling — all legal, none pinned by a test), and each was
closed by adding a boundary test to `tests/unit/test_invariants.py`
(`test_*_boundary_*_is_ok`).

| # | mutation | invariant | killed by |
|---|---|---|---|
| 1 | `confidence >= thr` → `<=` | I7 | `test_policy_rules::test_confidence_gate` + property |
| 2 | `retries_used < cap` → `<=` | I1 | `test_policy_rules::test_npci_retry_cap` |
| 3 | dead-mandate `or` → `and` | I3 | `test_policy_rules::test_mandate_live_for_charge` |
| 4 | notice gap `>=` → `<=` | I2 | `test_policy_rules::test_predebit_notice_requires_24h_gap` |
| 5 | quiet-hours `or` → `and` | I4 | `test_policy_rules::test_quiet_hours` |
| 6 | contact-cap `<` → `>` | I5 | `test_policy_rules::test_contact_frequency` + property |
| 7 | amount-cap `<=` → `>=` | I6 | `test_policy_rules::test_amount_within_cap` |
| 8 | economic floor `>=` → `<=` | econ | `test_policy_rules::test_outreach_economics` |
| 9 | stopping `<` → `<=` | stop | `test_policy_rules::test_stopping_rule_uses_retry_budget` |
| 10 | checker NPCI `>` → `>=` | I1 | `test_invariants::test_npci_cap_boundary_exactly_three_charges_is_ok` (added) |
| 11 | checker notice `<=` → `>=` | I2 | `test_invariants::test_predebit_notice_violation` |
| 12 | checker quiet-hours `or` → `and` | I4 | `test_invariants::test_quiet_hours_violation` |
| 13 | checker contact-freq `>` → `<` | I5 | `test_invariants::test_contact_frequency_violation` |
| 14 | checker amount-cap `>` → `>=` | I6 | `test_invariants::test_amount_cap_boundary_charge_exactly_at_cap_is_ok` (added) |
| 15 | AFA ceiling `>` → `>=` | I13 | `test_policy_rules::test_afa_exemption` |
| 16 | AFA exemption `or` → `and` | I13 | `test_policy_rules::test_afa_exemption` + `test_policy_engine::test_high_value_charge_needs_reauth_first` |
| 17 | checker AFA ceiling `>` → `>=` | I13 | `test_invariants::test_afa_ceiling_boundary_charge_exactly_at_ceiling_is_exempt` (added) |

Re-run both M1 and M2 whenever `policy/` or `invariants.py` changes materially, and keep
reporting them as two separate numbers.
