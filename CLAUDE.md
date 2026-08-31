# CLAUDE.md — MandateMend Build Instructions

Project: UPI AutoPay / e-mandate failure-recovery agent (Razorpay AI Buildathon, Track 03, Angle 3A).
This file governs how Claude Code should operate in **auto mode** for this repo. Read it fully before writing any code, and re-read it at the start of every new session.

---

## 1. The build loop (how to iterate to convergence)

Do not treat "no more improvement" as a vague feeling. Every iteration must produce a **scorecard**, and the loop only stops on scorecard evidence.

### 1.1 Scorecard — compute this after every iteration, no exceptions
Run an actual command that outputs a JSON/log line with:
- `tests_passed` / `tests_total` (pytest, run for real — not mentally simulated)
- `batch_recovery_rate` — ₹ recovered / ₹ at risk on the **frozen** held-out 300-mandate batch (see §2)
- `baseline_lift` — recovery rate minus the static-retry baseline, same batch
- `compliance_violations` — count of NPCI-cap / 24h-notice / quiet-hour violations detected by the invariant checks (§3) — must always be 0, not just "low"
- `lint_errors`, `type_errors`

Write each iteration's scorecard to `logs/iterations.jsonl` (append-only, one line per iteration) so there's a full audit trail of the loop, the same way the product itself keeps an audit ledger. Never overwrite or edit past entries.

### 1.2 Stopping condition
- Compare `batch_recovery_rate` and `tests_passed/tests_total` against the **previous two** iterations, not just one.
- Stop auto-looping on a feature only when the delta across both of the last two iterations is below threshold (e.g. <0.5% recovery-rate change, no new test failures) — a single flat iteration can be a stall, not convergence.
- Regardless of convergence, **hard-cap at 8 iterations per feature area** and stop for human review. Pure "score stopped improving" is not sufficient justification to keep looping or to declare a feature done — a plateau can mean "stuck" as easily as "finished."

### 1.3 Anti-gaming guardrails — the loop must not be easy to satisfy dishonestly
This is the most important section. An agent under pressure to show score improvement will find the path of least resistance, which is often to weaken the test rather than fix the code. Prevent that explicitly:
- **The held-out 300-mandate batch and its ground-truth labels are frozen at creation and read-only.** Do not regenerate, resample, or "fix" this file to improve a score. If you believe the batch itself is flawed, stop and flag it to the user instead of editing it.
- **Never edit a test to make it pass.** If a test fails, the default assumption is the code is wrong, not the test. If you genuinely believe a test is incorrect, say so explicitly in the iteration log and leave it failing rather than silently loosening the assertion.
- **No silent scope-narrowing.** If a feature is hard to implement fully, do not quietly implement a stub, mock, or hardcoded-success path and report it as passing. Report it as incomplete.
- **No swallowed exceptions.** Don't wrap failing code in try/except-pass to make a test suite go green. A hidden failure is worse than a visible one.
- **Compliance checks (NPCI cap, 24h notice, idempotency) run as independent invariant assertions, not as part of the feature code being tested** — the code under test should never be able to mark its own compliance homework.
- Every iteration's diff should be small and reviewable. If a single iteration touches more than ~5 files, split it into smaller iterations instead.

---

## 2. Non-negotiable invariants (do not relax these, ever, under auto mode)
- The LLM diagnosis module never has execution authority. It outputs a typed, schema-validated diagnosis only.
- The deterministic policy engine is the only component allowed to emit an executable Action.
- Every executed action carries an idempotency key enforced by a DB-level unique constraint (not just application logic).
- NPCI retry cap (max 3 retries) and the 24h pre-debit notice rule are enforced in the policy engine, never bypassable by a confident LLM output or a high-uplift-score recommendation.
- Low-confidence diagnosis → NO_ACTION + human queue. Never guess when uncertain on a money-moving decision.

## 3. Checkpoints — hard stops vs. log-and-proceed

### 3.1 Hard stops — pause and wait for the user, no exceptions, even under "Yes, use auto mode"
These protect the integrity of the whole submission. If any of these gets silently overridden, the build looks done but is lying about it, which is worse than being honestly incomplete. Waiting hours here is the correct trade-off:
- A change would touch the frozen held-out batch or its labels.
- A test is about to be deleted, skipped, or have an assertion weakened.
- The scorecard shows `compliance_violations > 0` at any point — this is stop-the-line, not "keep looping."
- The idempotency mechanism itself, or the database/storage engine backing it, is about to change.

### 3.2 Log-and-proceed — do not stall the session on these, but leave a clear trail
- **Minor architectural/implementation decisions** not spelled out in the plan (library choice, schema field names, folder structure, exact hyperparameters): pick the most conservative, reversible, well-documented option, write the decision and one-line reasoning to `CHANGELOG.md`, and continue. Flag these for review in the morning rather than waiting on them.
- **A single iteration scoring worse than the previous one**: automatically revert to the last known-good state, log why in `logs/iterations.jsonl`, and move to the next task. Only escalate to a hard stop if the *same module* regresses twice in a row — that's a signal something structural is wrong, not just a bad iteration.

## 4. Design principles (the console must not look AI-generated)
This is an operator console for a fintech audit tool, not a marketing landing page. Avoid the default look of generated UIs:
- No purple/violet gradient backgrounds, no glassmorphism cards, no generic centered hero sections.
- No decorative emoji in headers or buttons.
- Favor information density over whitespace-heavy "SaaS landing page" layouts — this is a tool operators will stare at daily, not a pitch page (save the polish for the actual pitch deck, not the console).
- Use a real typographic hierarchy: one serif or distinctive display face for headers is optional, but body/data should be a plain, highly legible sans or monospace for numeric/ledger data specifically (tabular figures, right-aligned).
- Color should be functional, not decorative: a restrained palette where color encodes state (e.g., compliance pass/fail, recovered/at-risk) rather than branding.
- Avoid stock icon-library soup — use icons sparingly and only where they replace text, not next to every label.
- Every screen should answer "what does an operator do next" — action-oriented, not dashboard-for-dashboard's-sake.

## 5. Agentic reasoning protocol — how to think, not just what to build
Don't go straight from reading a task to writing code. For every non-trivial feature (policy engine, executor, retry-timing model — not tiny fixes), run this four-step loop explicitly, and show the intermediate steps in your reasoning/output rather than skipping to the answer:

1. **Plan before executing.** State what you're about to build, the two or three real implementation options, and why you're picking one. If a choice has a security or compliance implication, say so explicitly here, not after the fact.
2. **Execute in small units.** One reviewable change at a time (per §1.3 — no giant diffs).
3. **Self-critique before marking done.** After implementing, deliberately re-read your own code as if reviewing someone else's PR: What did I skip? What edge case did I not handle? Did I make the test pass in a way that would embarrass me if a panel read the diff? Write this critique down, even if brief — don't silently decide it's fine.
4. **Adversarial pass, specifically for money-handling and security-relevant code.** Actively try to think like someone trying to break this: What happens on a duplicate webhook fired twice in the same millisecond? What if the LLM diagnosis output is malformed or contains injected instructions? What if a retry is attempted after a mandate was revoked mid-flight? What if the batch file is tampered with? Write down at least one attack/failure scenario per money-moving component and either handle it or explicitly log it as a known gap in `CHANGELOG.md` — never leave it silently unconsidered.

This four-step loop is what separates "code that runs" from "code that survives a panel of Razorpay engineers asking pointed questions about it." Depth of reasoning here matters more than speed of output — a fast wrong answer costs more time than a slightly slower correct one.

**Bound the adversarial pass**: 2 attack/failure scenarios per component is enough — don't keep generating more. Depth beats breadth here; pick the most realistic scenarios, not the longest list.

**Diminishing-returns fallback for noisy metrics** (mainly the ML model): if 3 consecutive iterations on the same feature don't beat the *best* scorecard seen so far (not just the previous one — model training scores bounce around), stop iterating on that feature, keep the best version seen, log it as "converged with residual noise" in `logs/iterations.jsonl`, and move to the next module. Don't keep spending the iteration budget chasing a number that isn't reliably moving.

## 6. Security hardening checklist
Treat every item below as a requirement, not a nice-to-have, given this handles money-adjacent data even in test mode:
- **LLM input sanitization**: the diagnosis module's free-text inputs (failure context, error messages) must be treated as untrusted. Strip/escape anything that looks like an attempt to inject instructions ("ignore previous instructions", role-play framing, etc.) before it reaches the prompt, and validate the LLM's output against a strict schema — reject and fall back to NO_ACTION on any malformed or out-of-schema response.
- **No secrets in code or commits.** Razorpay test-mode API keys, DB credentials, etc. go in environment variables / a `.env` file that is gitignored from the first commit — check this before the first commit, not after.
- **Idempotency is enforced at the database layer** (unique constraint), never solely in application logic — application-level checks can race under concurrency; DB constraints can't.
- **Least privilege**: the executor's DB/API credentials should only have the permissions the executor actually needs (e.g., no ability to read unrelated tables, no admin-level API scopes).
- **Input validation on every external boundary**: webhook payloads, API responses, and the synthetic batch file should all be schema-validated on ingestion, not trusted implicitly.
- **Dependency hygiene**: pin dependency versions, avoid pulling in unmaintained packages for core money-handling logic.
- **Audit log is append-only and tamper-evident** — no code path should be able to update or delete a past audit entry, including "cleanup" scripts.
- **Fail closed, not open**: on any unexpected error in the policy engine or executor, the default behavior is to do nothing and escalate to a human queue — never default to "retry anyway" or "assume success."

## 7. Engineering discipline
- Small, atomic commits with real messages describing *why*, not just *what*.
- Testing pyramid: unit tests on policy-engine rules (fast, many), integration tests on the executor against Razorpay test-mode APIs (fewer), one true end-to-end batch run test (slowest, run less often).
- Keep a running `CHANGELOG.md` — this becomes part of your "what broke and how I recovered" material for the pitch, so document real failures honestly as they happen, don't retroactively clean the story up.
- Budget awareness: if a single feature is consuming disproportionate iterations/tokens without scorecard movement, stop and flag rather than continuing to spend.

## 8. Definition of done, per module
- **Data generator**: produces the 2,000-mandate training set + frozen 300-mandate held-out batch with temporal/velocity structure (not IID rows), documented generation assumptions.
- **Policy engine**: all hard rules unit-tested individually, including the deliberately-injected violation case.
- **Retry-timing model**: trained, evaluated against a naive baseline, metrics logged — not just "runs without error."
- **Executor**: idempotency proven under concurrent-webhook and duplicate-retry failure-injection tests, not just claimed.
- **Console**: an operator can read the headline recovery number, drill into a single mandate's rule-trace, and export an evidence pack, without needing to read the code.

---

**When in doubt: prefer a smaller, honestly-scoped feature that passes all invariants over a larger feature that "mostly works." A gamed scorecard is worse than a slow one.**
