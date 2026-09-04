# MandateMend — the two advisory models

Both models are **advice to the policy engine**, never authority. The engine can veto or
downgrade any recommendation, and every action they influence still passes the full hard-rule
ladder. They are trained **only** on `data/training_set.json` (the logging-policy rows); the
frozen held-out batch is never seen in training.

Retrain + evaluate: `mandatemend train` → writes `src/mandatemend/models/artifacts/*.joblib`
and `logs/model_metrics.json`. `random_state=0` everywhere, so a retrain is deterministic.

---

## 1. Retry-timing model — discrete-time hazard  (`models/retry_timing.py`)

**Question:** *when* to retry, within the NPCI 1-original-+-3-retry budget — not *if*.

**Formulation (discrete-time hazard, Singer & Willett 2003, ch. 10–12).** Person-period
design: one row per training mandate at its logged delay bucket, target = did that retry
succeed. A pooled gradient-boosted classifier estimates the **discrete-time hazard**

    h(t | x) = P(a retry first succeeds in bucket t | not succeeded before t, x)

over the 7 buckets `{0, 6, 24, 48, 72, 120, 168}h`. From `h` the model exposes the
**survival** `S(t) = Π_{s≤t}(1 − h(s))`, the **cumulative recovery** `1 − S(t)`, and
`expected_recovery_for_schedule(...)` = `1 − Π_{b∈schedule}(1 − h(b))` — the composed
survival for an ordered ≤3-bucket retry plan (used by the sequencing evaluation). The
advisor returns the hazard curve and the agent walks it across successive retries, skipping
buckets already tried. Survival framing for soft-collection timing follows Witzany & Kozina
(2022).

*Honest scope of the reframe (iteration 9a):* the composition math and the time-stratified
metrics below are new; the single-pick behaviour (`best_delay` = argmax hazard) is
**unchanged** — the reframe formalises and instruments what the model already did, it does
not move the scorecard. Data caveat: the logging policy tries exactly one delay per mandate,
so each mandate is a single person-period observation; we do not synthesise risk-set rows
for un-tried earlier buckets. `S(t)` assumes bucket-conditional independence given `x`,
which holds by construction in the simulator (each `RETRY@d` outcome is its own draw).

**Debiasing.** The logging policy is mildly confounded (it favours payday-adjacent retries
for insufficient-funds). Rows are inverse-propensity weighted (`w = 1/π`, clipped at 10)
using the propensity stored at generation time.

**Estimator.** `HistGradientBoostingClassifier(max_depth=4, learning_rate=0.08, max_iter=200,
l2_regularization=1.0)`. `max_iter` was cut from 250 → 90 for speed in iteration 4, then
raised back to 200 in iteration 7 once batched inference (`Agent.warm`) removed the speed
pressure — at 90 the model only *tied* the naive baseline on the reproducible training set;
at 200 it beats it.

**Held-out oracle check** (reporting only — never feeds training). On the frozen batch, for
every mandate that has *some* winning RETRY bucket, does the model's argmax bucket land on a
winning one?

| | value |
|---|---|
| model picks a winning delay | **0.437** |
| naive "+72h always" picks a winning delay | 0.412 |

The model beats the naive fixed-schedule baseline (CLAUDE.md §8 "evaluated against a naive
baseline"), but only modestly. It is not a strong classifier in absolute terms
(`val_auc ~0.68`) — and that is honest: the failure event does not expose the customer's
payday, so timing has to be inferred from `day_of_month × issuer × amount × history`, exactly
as a real system would. Most of the system's lift comes from the uplift model + the
round-aware orchestration, not from point retry-timing.

**Time-stratified calibration** (`logs/model_metrics.json → retry_timing`, on the held-out
20% of person-periods). Reported per discrete-time bucket: `n`, observed `event_rate`,
`auc`, and `brier`; plus the **integrated Brier score** (mean Brier across buckets,
`IBS ≈ 0.17`) and the overall `val_brier`. Most buckets are data-starved — the logging
policy concentrates observations on the 24h and 168h buckets (n ≈ 380 / 250; the rest
n ≈ 30–90) — so per-bucket AUC ranges from ~0.54 in the dominant buckets to ~0.88 in the
sparse early ones. This is surfaced rather than averaged away; it is the honest picture of
what one biased logging policy can teach a timing model, and it motivates the ablation
(§ below) that shows how little of the +14 pp actually rides on retry timing.

---

## 2. Intervention model — IPW T-learner  (`models/uplift.py`)

**Question:** which intervention arm — `RETRY_ONLY`, `WHATSAPP_UPI_LINK`, `SMS_REMINDER`,
`GRACE_48H`, `PARTIAL_CHARGE`, `METHOD_SWITCH`, `NO_OP` — moves this mandate most, *relative
to doing nothing*.

**Formulation (T-learner).** One outcome model per arm, `P_arm(recover | x)`, trained on the
logging rows assigned to that arm, IPW-weighted. Then
`uplift(arm | x) = P_arm(recover | x) − P_control(recover | x)` with `control = NO_OP`. The
advisor ranks arms by uplift; the agent walks the ranking across rounds, skipping arms
already tried; if the ranking is exhausted it emits `NO_OP`, which the stall-breaker turns
into an escalation.

**Why uplift and not "predict success".** Every published retry/dunning engine (Stripe Smart
Retries, Recurly, Dropbox) ranks actions by predicted success. Ranking by **causal uplift
against a control** is the methodological step this brings (research file §B: arXiv
2412.09232 predict-then-optimize uplift; 2505.08343 cost-aware counterfactual decisions). It
stops the agent "recovering" mandates that would have self-healed anyway and keeps the
outreach budget on the mandates a touch actually changes.

**Estimator.** Per arm: `HistGradientBoostingClassifier(max_depth=3, learning_rate=0.08,
max_iter=60, l2_regularization=1.0)`. An arm with `< 40` rows or a single outcome class falls
back to a weak prior (`p = 0.05`) at inference; with the full 7.7k-row training set every arm
gets a real model.

**Held-out oracle check.** For every mandate with *some* winning arm, is the model's top-ranked
arm a winning one?

| | value |
|---|---|
| model top arm is a winning arm | **0.75** |
| (iteration 2, 2k training rows) | ~0.78 |

(The iter-2 figure was measured on a non-reproducible, salted-`hash()` training set; 0.75 is
the number on the deterministic set.)

---

## 3. Batched inference (`Agent.warm`)

HistGBM's per-call Python overhead dominates on single-row inputs. `Agent.warm(events)`
precomputes every mandate's hazard curve and arm ranking once — `|arms|` `predict_proba`
calls over an `(N, F)` matrix instead of `N × |arms|` single-row calls — cutting a
300-mandate scored run from ~50s to ~9s. `run_batch` and the console call it; `demo` /
`live-check` fall back to per-call memoised inference.

## 4. Model-strength evaluation — `mandatemend eval`  (iteration 9b)

Three reporting-only diagnostics on the frozen 300-batch (read-only oracle use, same as the
`train` oracle checks — never trained on). Written to `logs/eval.json`.

### 4a. Sequencing (B3) — does *ordering* the 3 retries beat the fixed ladder?

For every mandate with at least one realised winning RETRY bucket (n = 199): does the retry
model's hazard-ranked **top-3 schedule** capture a win, vs the classic fixed **24 / 72 /
168 h** ladder?

| schedule | captures a win |
|---|---|
| model top-3, ordered by hazard | **0.794** |
| fixed 24/72/168 ladder | 0.774 |
| model single best pick only | 0.437 |

**+2.0 pp** from adaptive sequencing over the fixed ladder — real but modest; most of the
retry model's value is picking *which* buckets, not the order. Schedule-probability
calibration: the model predicts 0.716 recovery for its own top-3 vs 0.794 observed (slight
under-confidence).

### 4b. Calibration / ECE (B4)

Predicted probability vs realised frequency on the frozen batch, 10 equal-width bins.
Uplift is compared arm-by-arm against a **single canonical realised execution** per arm (not
"any variant ever wins", which would inflate the observed frequency).

| model | ECE | MCE | n |
|---|---|---|---|
| retry-timing (per bucket) | **0.063** | 0.204 | 2100 |
| uplift (per arm) | **0.046** | 0.336 | 2100 |

Both are reasonably calibrated; MCE is driven by the sparse high-probability tail bins
(n ≈ 2–25). Full reliability tables in `logs/eval.json`.

### 4c. Ablation (B5) — where does the lift come from, and one bug it caught

Recovery rate on the frozen 300-batch with each advisor pair swapped in (all other
orchestration held fixed):

| config | recovery | lift vs static-retry |
|---|---:|---:|
| naive static-retry ladder (no agent) | 47.18 % | +0.00 |
| heuristic retry + heuristic uplift | 57.31 % | +10.14 |
| **survival retry + heuristic uplift** | **66.33 %** | **+19.15** |
| heuristic retry + T-learner uplift | 51.83 % | +4.66 |
| survival retry + T-learner uplift *(shipped)* | **63.51 %** | **+16.33** |

**The first run of this ablation showed the shipped config at 61.42 %, *behind*
`survival + heuristic` by 3.8 pp — and the investigation found a real bug** (not a "the
heuristic is just better" result):

`agent._prefer_retry_when_competitive` — the targeted override that spends the retry budget
before an arm on `TECH_DECLINE / BANK_DOWNTIME / SUSPECTED_CHURN` — was exempting
`PARTIAL_CHARGE` alongside `RETRY_ONLY`. But a partial charge **consumes one of the 3 NPCI
attempts** *and* marks its delay bucket as tried, so on a transient tech-decline it poisoned
the exact bucket (`RETRY@24h`) a plain full retry would have won on. The T-learner ranks
`PARTIAL_CHARGE` top for `TECH_DECLINE` (highest `arm_pos_rate`, 0.46), so it hit this on
every such mandate; the heuristic never picks `PARTIAL_CHARGE` for `TECH_DECLINE`, so it
didn't. Fix: only `RETRY_ONLY` passes the override now. Result: shipped **61.42 → 63.51 %**
(+2.1 pp), the entire `TECH_DECLINE` bleed (4 mandates / ₹6.4 k) gone, retries *down*
295 → 287, 0 compliance violations.

**Residual gap on the primary batch: 2.8 pp.** `survival + heuristic` (66.33 %) leads the
shipped `survival + T-learner` (63.51 %). What remains is concentrated in `LIMIT_EXCEEDED`
and the dead-mandate buckets (`MANDATE_PAUSED/EXPIRED`) — the T-learner steers to
`OFFER_ALTERNATE_METHOD` / `REQUEST_REAUTH` where the heuristic's WhatsApp-link path does
better on this small sample — while the T-learner is *ahead* on the big `INSUFFICIENT_FUNDS`
bucket. Iteration 12's re-auth work widened this gap from the 1.7 pp measured at iteration 9
(the dead-mandate substitution changed how both configs behave on paused/expired mandates).

### 4d. v2 cross-check — the T-learner question, still open

Same ablation on the disjoint **1000-mandate v2 batch** (3× the per-cause sample), current
numbers (`mandatemend eval --ablation --batch v2`; run without the re-auth supplement, so the
shipped row reads 63.06 % here vs 64.38 % from `score --batch v2`):

| config | v2 recovery | v2 lift | primary lift |
|---|---:|---:|---:|
| naive static-retry | 54.80 % | +0.00 | +0.00 |
| heuristic + heuristic | 57.09 % | +2.29 | +10.14 |
| survival + heuristic | **63.32 %** | **+8.52** | +19.15 |
| heuristic + T-learner | 52.09 % | **−2.71** | +4.66 |
| **survival + T-learner *(shipped)*** | 63.06 % | +8.26 | +16.33 |

**`survival + heuristic-uplift` now leads on *both* batches** — by 2.8 pp on the primary and
0.3 pp (a statistical tie) on v2. Iteration 11 first ran this and v2 put the T-learner
marginally *ahead* (+0.5 pp); that tiebreaker is what shipped it. Iteration 12's re-auth
work shifted the ablation and the tiebreaker is gone. Both configs hold **0 compliance
violations** on both batches.

**The T-learner stays the shipped default as a design choice, not a metric win:**
- it ranks interventions by **causal uplift against doing nothing** (`P_arm(recover|x) −
  P_NO_OP(recover|x)`), the property this whole system exists to demonstrate; the heuristic
  uplift is a fixed cause→arm lookup with no counterfactual reasoning;
- it extends to new arms (`REAUTH_LINK`) by retraining, where the heuristic needs a
  hand-written rule per arm;
- inside the full loop it is not net-negative — but note `heuristic retry + T-learner`
  scores **−2.71 pp on v2**, *below* the naive ladder, so the uplift ranking only pays off
  with the survival retry model and round-aware orchestration underneath it.

**This is a documented open call.** If the priority is the headline recovery number on the
frozen batch, `survival + heuristic-uplift` is 2.8 pp better on the primary and should be
shipped — the trade is losing the causal-uplift story. `mandatemend eval --ablation
[--batch v2]` reproduces both columns.

**Lift is baseline-sensitive; absolute recovery is not.** The agent recovers ~63.5–64.4 % on
*both* batches (primary 63.51 %, v2 64.38 % with re-auth / 95 % CI [60.4 %, 68.2 %]), but
v2's static-retry baseline is 54.8 % vs the primary's 47.2 %, so v2 lift is +9.58 pp vs
primary +16.33 pp. The stable, honest number is the **absolute recovery rate**; the lift
depends on which baseline draw the batch happens to contain.

### 4e. Re-authorization path on v2 (iteration 12c)

Paused / expired mandates can't be debited (**I3**) — the correct UPI AutoPay recovery is a
**re-authorization request** (`REQUEST_REAUTH`): the customer re-approves in their UPI app
and the mandate returns ACTIVE. The primary 300-batch has no re-auth potential outcomes, so
the agent there falls back to a one-off collect link. The v2 batch gets a **separately
frozen** supplement (`data/heldout_reauth_v2.frozen.json` — the v2 batch/labels themselves
are never modified) with a `REQUEST_REAUTH` outcome for each of its 97 paused/expired
mandates: `p(re-approve) ≈ 0.62` for a non-churning customer, `≈ 0.12` for a churning one,
scaled by tenure.

`mandatemend score --batch v2` (with the supplement present) vs without it:

| bucket | without re-auth | with re-auth |
|---|---:|---:|
| `MANDATE_PAUSED` (n = 62) | 33.9 % | **48.4 %** |
| `MANDATE_EXPIRED` (n = 35) | 31.4 % | **40.0 %** |
| v2 overall | 63.45 % | 64.38 % |

**0 compliance violations** with the re-auth path active — `REQUEST_REAUTH` is bound as an
outbound contact (I4 quiet hours, I5 weekly cap) and never as a charge (I1, I2), verified by
`check_resolution` on all 1000 v2 mandates. It lifts exactly the weakest buckets, which the
architecture always intended but the primary batch could not demonstrate.

### 4f. Interpretability (iteration 12d)

**Global — permutation importance** (`mandatemend train` → `logs/model_metrics.json`;
HistGBM has no `feature_importances_`, so this is the AUC drop when a feature is shuffled on
the held-out slice). Top drivers:

| retry-timing | ↓AUC | | uplift `RETRY_ONLY` | ↓AUC | | uplift `WHATSAPP_UPI_LINK` | ↓AUC |
|---|---:|---|---|---:|---|---|---:|
| `delay_hours` | .062 | | `cause_TECH_DECLINE` | .106 | | `days_since_last_success` | .081 |
| `cause_BANK_DOWNTIME` | .024 | | `consecutive_failures` | .046 | | `consecutive_failures` | .045 |
| `consecutive_failures` | .023 | | `cause_BANK_DOWNTIME` | .025 | | `hour_of_day` | .045 |
| `cause_INSUFFICIENT_FUNDS` | .018 | | `days_since_last_success` | .017 | | `tenure_months` | .031 |

Each is defensible: retry-timing rides on *when* (`delay_hours`) plus the cause and the
recency signals; `RETRY_ONLY`'s uplift is driven by `TECH_DECLINE` (transient → another
attempt works); the WhatsApp arm keys on the churn-risk features (`days_since_last_success`,
`consecutive_failures`, tenure) — it is the "reach a wavering customer" arm.

**Local — per-decision attribution.** `UpliftModel.explain(event, diag, arm)` reports, for
the arm the model chose, how `p_recover` moves when each feature is reset to its training
mean (leave-one-feature-out; signed, ranked; **no SHAP dependency**). Surfaced in
`mandatemend demo <id>` and in the evidence pack (`/evidence/<id>.json →
uplift_attribution`). Example (mandate 5, `LIMIT_EXCEEDED` → `METHOD_SWITCH`):
`amount_to_cap_ratio = 1.63 → +0.065 on p_recover` — the amount exceeds the mandate's own
cap, so switching payment method is the move.

## 5. Known limitations

- Synthetic training data cannot perfectly preserve real behavioural patterns (arXiv
  2604.13125). Mitigated with explicit temporal/velocity structure + a latent churn process,
  not IID rows — but the absolute numbers should be read **relative to the baselines on the
  same data**, not as a production forecast.
- The retry model has no payday feature (the event doesn't carry one); a production version
  would join issuer-level salary-cycle priors.
- The T-learner's control arm (`NO_OP`) has the fewest rows; its estimate is the noisiest
  part of every uplift figure.
