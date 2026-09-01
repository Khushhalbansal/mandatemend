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

**Formulation.** One row per `(sample, observed delay bucket)` from the logging policy;
target = did that retry succeed. A gradient-boosted classifier estimates the per-bucket
success hazard `P(retry succeeds | features, delay_bucket)`. Scoring a candidate delay =
evaluating the hazard at that bucket; the advisor returns the whole curve over the 7 buckets
`{0, 6, 24, 48, 72, 120, 168}h` and the agent walks it across successive retries (skipping
buckets already tried). Pooled classification over `(features, time)` is the standard
discrete-time hazard estimator (Singer & Willett); survival framing for soft-collection
timing follows Witzany & Kozina (2022).

**Debiasing.** The logging policy is mildly confounded (it favours payday-adjacent retries
for insufficient-funds). Rows are inverse-propensity weighted (`w = 1/π`, clipped at 10)
using the propensity stored at generation time.

**Estimator.** `HistGradientBoostingClassifier(max_depth=4, learning_rate=0.08, max_iter=90,
l2_regularization=1.0)`. `max_iter` was cut from 250 → 90 during iteration 4: the smaller
model **generalises better here** (see below) and a whole-batch scored run is ~5× faster.

**Held-out oracle check** (reporting only — never feeds training). On the frozen batch, for
every mandate that has *some* winning RETRY bucket, does the model's argmax bucket land on a
winning one?

| | value |
|---|---|
| model picks a winning delay | **~0.45** |
| naive "+72h always" picks a winning delay | ~0.41 |

The model beats the naive fixed-schedule baseline (CLAUDE.md §8 "evaluated against a naive
baseline"). It is not a strong classifier in absolute terms (`val_auc ~0.73`) — and that is
honest: the failure event does not expose the customer's payday, so timing has to be inferred
from `day_of_month × issuer × amount × history`, exactly as a real system would.

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
| model top arm is a winning arm | **~0.82** |
| (iteration 2, 2k training rows) | ~0.78 |

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
