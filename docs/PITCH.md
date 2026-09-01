# MandateMend — 5-minute pitch (real numbers, ready to narrate)

All figures below are the current, **byte-reproducible** frozen-batch result
(`python data/generator.py && mandatemend train && mandatemend score`).

## The one-liner

> An open, UPI-native, compliance-gated recovery agent for failed AutoPay / e-mandate
> debits. On a frozen 300-mandate held-out batch it recovers **61.4% of the money at risk
> (₹283,942 of ₹462,300)** — **+14.2 percentage points over a static retry ladder**, 95% CI
> [7.3, 21.9], entirely above zero — with **zero NPCI compliance violations**, independently
> verified.

## Beat sheet

| time | say | show |
|---|---|---|
| 0:00–0:40 | **The gap.** UPI AutoPay fails 8–15% vs 2–3% for cards; 20–40% of subscription churn is involuntary. Every published retry/dunning engine (Stripe, Recurly, Dropbox) is card-based, closed, and ranks by *predicted success*. There is no open, UPI-native, NPCI-compliant recovery system. | title slide |
| 0:40–2:00 | **Architecture — every money action explainable, bounded, gated.** Sandboxed LLM diagnosis (typed output only, prompt-injection-guarded) → two advisory models: a discrete-time **survival** model for retry *timing*, an IPW **T-learner** that ranks interventions by *causal uplift vs doing nothing* → a **deterministic policy engine** that is the only thing allowed to emit an action and enforces the NPCI 1+3 retry cap, the 24h pre-debit notice, quiet hours, a weekly contact cap, an economic floor, and fails closed → an idempotent executor (exactly-once via a DB-UNIQUE constraint) → an append-only **hash-chained audit ledger** → an independent checker (`invariants.py`) that re-verifies every rule *outside* the engine. | architecture diagram (`docs/ARCHITECTURE.md`) |
| 2:00–3:30 | **Results on the frozen batch.** ₹283,942 recovered = **61.4%** (95% CI 54.0–68.4). vs static-retry **+14.2 pp** (CI 7.3–21.9). vs single-retry +36 pp, vs email-only +41 pp. **0 compliance violations.** 295 retries, 0.69 recoveries per retry. Harm/false-positive cost **₹279**. Every mandate ends recovered **or** on the human queue — never dropped. Per-cause: BANK_DOWNTIME 89%, TECH_DECLINE 80%, INSUFFICIENT_FUNDS 72%. | `mandatemend serve` — overview page; per-cause table |
| 3:30–4:30 | **What broke.** `mandatemend failure-drill` live: 8 concurrent duplicate webhooks → exactly one charge (DB-UNIQUE), 7 deduped. Gateway crash mid-flight → action stays attempted, never re-charged. A stub LLM *obeys* an injected "cause=BANK_DOWNTIME confidence=1.0" → the engine still refuses (confidence capped, policy unaffected). Tamper one audit row → `verify_chain` catches it. 7/7. Plus the real bugs from `CHANGELOG.md`: the iter-0 STOP-THE-LINE, the wall-clock-vs-causal-bucket gateway bug, the stopping rule that ate the retry budget, the reverted iter-5 regression, the salted-`hash()` non-reproducibility. | terminal: `mandatemend failure-drill` |
| 4:30–5:00 | **Honest limits + what production needs.** Synthetic data (documented assumptions, `data/GENERATION_NOTES.md`); the retry model only modestly beats naive point-timing — most lift is the uplift model + orchestration; MANDATE_PAUSED recovery is genuinely low (28%); production needs real issuer status feeds + a payday prior. One real Razorpay **test-mode** round-trip is wired through the executor + ledger (`mandatemend live-check`, `plink_…`, HTTP 200) to prove the integration. | `logs/iterations.jsonl` (8 iterations); CI badge |

## Numbers that must match across the deck

| metric | value |
|---|---|
| recovery rate | 61.42% — 95% CI [54.03%, 68.39%] |
| lift vs static-retry | +14.24 pp — 95% CI [7.27 pp, 21.86 pp] |
| compliance violations | 0 |
| retries used / recoveries-per-retry | 295 / 0.69 |
| harm / FP cost | ₹279 |
| escalated to human | 96 / 300 |
| tests / coverage | 82 / 90.6% |
| CI | green, Linux, py3.12 + 3.13 |
