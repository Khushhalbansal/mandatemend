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

## 4. Known limitations

- Synthetic training data cannot perfectly preserve real behavioural patterns (arXiv
  2604.13125). Mitigated with explicit temporal/velocity structure + a latent churn process,
  not IID rows — but the absolute numbers should be read **relative to the baselines on the
  same data**, not as a production forecast.
- The retry model has no payday feature (the event doesn't carry one); a production version
  would join issuer-level salary-cycle priors.
- The T-learner's control arm (`NO_OP`) has the fewest rows; its estimate is the noisiest
  part of every uplift figure.
