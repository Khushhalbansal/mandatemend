# Synthetic data — generation assumptions

`data/generator.py`. Seed `20260901`. Training rows = mandate indices `[0, n_train)`;
held-out = indices `[1_000_000, 1_000_000 + n_heldout)` — disjoint by construction, plus a
belt-and-suspenders filter that drops any training mandate_id present in the frozen batch.

## Failure world

* **Cause mix**: INSUFFICIENT_FUNDS 45%, TECH_DECLINE 18%, BANK_DOWNTIME 15%,
  LIMIT_EXCEEDED 8%, MANDATE_PAUSED 6%, MANDATE_EXPIRED 4%, SUSPECTED_CHURN 4%.
  Reflects reported UPI AutoPay failure composition (insufficient funds dominant; downtime
  and technical declines material).
* **Not IID**: BANK_DOWNTIME failures are assigned to 2 randomly-chosen "down" issuers and
  timestamped inside a shared 4–16h window (velocity / correlation structure). Churn intent
  shows as elevated `consecutive_failures`, `attempt_no`, and `days_since_last_success`.
* **Amounts**: mixture of common Indian subscription price points (₹149–₹4,999), capped at
  the ₹15,000 UPI AutoPay per-transaction ceiling. LIMIT_EXCEEDED mandates have a
  customer-lowered per-txn cap below the debit amount.
* A few (~3%) `raw_err_text` values carry a prompt-injection string, to exercise the
  sanitizer end-to-end.

## Potential-outcomes table (held-out only)

For each held-out mandate the generator realizes — once, with a per-mandate RNG — the
success/amount of every candidate `(action, delay-bucket, channel/ratio)`. Delay buckets:
0, 6, 24, 48, 72, 120, 168 h. Partial-charge ratio: 0.60.

The success probability model (before the single Bernoulli draw):

| cause | retry | notification (UPI link / SMS) | partial charge | method switch | grace 48h |
|---|---|---|---|---|---|
| INSUFFICIENT_FUNDS | rises toward payday; step up once payday passes | ~0.46 / ~0.27 × base, better after payday | 0.34–0.70 × base | 0.20 × base | 0.56 × base if payday ≤ 60h |
| BANK_DOWNTIME | ~0.9 × base once `delay ≥ downtime_remaining`, else ~0.03 | ~0 (link doesn't fix a bank outage) | gated on downtime | 0.60 × base (route away) | ~0 |
| LIMIT_EXCEEDED | ~0.08 × base (still over cap) | link/SMS as usual | 0.75 × base (60% under cap) | 0.60 × base | 0.12 × base |
| TECH_DECLINE | 0.58 × base if `delay ≤ 24h` else 0.42 (transient) | as usual | 0.40 × base | 0.60 × base | 0.12 × base |
| MANDATE_PAUSED / EXPIRED | 0 (dead mandate) | UPI collect link works without a live mandate | 0 | new-mandate flow, 0.32 × base | 0 |
| SUSPECTED_CHURN | INSUFFICIENT_FUNDS curve × churn penalty | × churn penalty | × churn penalty | × churn penalty | × churn penalty |

`base` ~ N(0.82, 0.08) for non-churn, ~ N(0.28, 0.08) for churn intent (clipped to
[0.05, 0.98]); churn penalty ≈ ×0.30–0.40. NO_ACTION carries a small organic self-heal
(~6% non-churn, ~2% otherwise) so it is a real baseline, not trivially zero.

Outcomes are **fixed at generation**, so the agent and every baseline are evaluated on the
same realized results — a potential-outcomes / counterfactual design, no runtime randomness
in the gateway.

## Known limitation

Synthetic tabular data cannot perfectly preserve real behavioural fraud/failure patterns
(cf. arXiv 2604.13125). We mitigate with explicit temporal/velocity structure and a latent
churn process rather than IID rows, but the absolute recovery numbers should be read as
*relative to the baselines on the same data*, not as a production forecast.
