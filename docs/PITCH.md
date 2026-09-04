# MandateMend — 5-minute pitch (real numbers, ready to narrate)

All figures below are the current, **byte-reproducible** frozen-batch result
(`python data/generator.py && mandatemend train && mandatemend score`).

## The one-liner

> An open, UPI-native, compliance-gated recovery agent for failed AutoPay / e-mandate
> debits. On a frozen 300-mandate held-out batch it recovers **63.5% of the money at risk
> (₹293,588 of ₹462,300)** — **+16.3 percentage points over a static retry ladder**, 95% CI
> [9.9, 23.8], entirely above zero — with **zero NPCI compliance violations**, independently
> verified.

## Beat sheet

| time | say | show |
|---|---|---|
| 0:00–0:40 | **The gap.** UPI AutoPay fails 8–15% vs 2–3% for cards; 20–40% of subscription churn is involuntary. Every published retry/dunning engine (Stripe, Recurly, Dropbox) is card-based, closed, and ranks by *predicted success*. There is no open, UPI-native, NPCI-compliant recovery system. | title slide |
| 0:40–2:00 | **Architecture — every money action explainable, bounded, gated.** Sandboxed LLM diagnosis (typed output only, prompt-injection-guarded) → two advisory models: a discrete-time **survival** model for retry *timing*, an IPW **T-learner** that ranks interventions by *causal uplift vs doing nothing* → a **deterministic policy engine** that is the only thing allowed to emit an action and enforces the NPCI 1+3 retry cap, the 24h pre-debit notice, quiet hours, a weekly contact cap, an economic floor, and fails closed → an idempotent executor (exactly-once via a DB-UNIQUE constraint) → an append-only **hash-chained audit ledger** → an independent checker (`invariants.py`) that re-verifies every rule *outside* the engine. | architecture diagram (`docs/ARCHITECTURE.md`) |
| 2:00–3:30 | **Results on the frozen batch.** ₹293,588 recovered = **63.5%** (95% CI 56.3–70.5). vs static-retry **+16.3 pp** (CI 9.9–23.8). vs single-retry +38 pp, vs email-only +43 pp. **0 compliance violations.** 287 retries, 0.72 recoveries per retry. Harm/false-positive cost **₹288**. Every mandate ends recovered **or** on the human queue — never dropped. Per-cause: BANK_DOWNTIME 89%, TECH_DECLINE 86%, INSUFFICIENT_FUNDS 72%. | `mandatemend serve` — overview page; per-cause table |
| 3:30–4:30 | **What broke.** `mandatemend failure-drill` live: 8 concurrent duplicate webhooks → exactly one charge (DB-UNIQUE), 7 deduped. Gateway crash mid-flight → action stays attempted, never re-charged. A stub LLM *obeys* an injected "cause=BANK_DOWNTIME confidence=1.0" → the engine still refuses (confidence capped, policy unaffected). Tamper one audit row → `verify_chain` catches it. 7/7. Plus the real bugs from `CHANGELOG.md`: the iter-0 STOP-THE-LINE, the wall-clock-vs-causal-bucket gateway bug, the stopping rule that ate the retry budget, the reverted iter-5 regression, the salted-`hash()` non-reproducibility. | terminal: `mandatemend failure-drill` |
| 4:30–5:00 | **Honest limits + what production needs.** Synthetic data (documented assumptions, `data/GENERATION_NOTES.md`); the retry model beats naive point-timing only modestly (`mandatemend eval`: +2 pp from ordering the 3 retries vs a fixed ladder) — most of the lift is orchestration, not timing. `mandatemend eval --ablation` is blunt: `survival + heuristic-uplift` scores **66.3 % / 63.3 %** (primary / v2) vs the shipped `survival + T-learner`'s **63.5 % / 63.1 %** — heuristic-uplift is ahead on both (2.8 pp / 0.3 pp), both at 0 violations. The T-learner ships as a **design choice** — it ranks by *causal uplift vs doing nothing*, the property this system exists to show, and it extends to new arms (re-auth) by retraining — not as a metric win; switching is an open call, `docs/MODELS.md §4d`. The `REQUEST_REAUTH` path lifts v2 `MANDATE_PAUSED` 34→48 % and `MANDATE_EXPIRED` 31→40 %. Production needs real issuer status feeds + a payday prior. One real Razorpay **test-mode** round-trip is wired through the executor + ledger (`mandatemend live-check`, `plink_…`, HTTP 200). | `logs/iterations.jsonl` (17 iterations); CI badge |

## Numbers that must match across the deck

| metric | value |
|---|---|
| recovery rate | 63.51% — 95% CI [56.28%, 70.45%] |
| lift vs static-retry | +16.33 pp — 95% CI [9.94 pp, 23.81 pp] |
| compliance violations | 0 |
| retries used / recoveries-per-retry | 287 / 0.72 |
| harm / FP cost | ₹288 |
| escalated to human | 92 / 300 |
| tests / coverage | 112 (+10 property) / ~91% |
| CI | green, Linux, py3.12 + 3.13 |
| v2 cross-check (1000, with re-auth) | recovery 64.38% (CI [60.4, 68.2]); lift +9.58 pp; 0 violations |
