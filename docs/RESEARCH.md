# Razorpay AI Buildathon 2026 — Deep Research & Track Strategy

**Prepared for:** aitools@synthsports.co · **Date:** 2026-09-01 · **Deadline:** applications close **5 September 2026**
**Builder profile (from you):** balanced across ML / backend / full-stack · solo · 3–4+ weeks · want primary + fallback both worked out

---

## Context — why this document exists

You want to be selected in the Razorpay AI Buildathon. This is **not a prize hackathon** — it is a **hiring funnel**. Selected builders get a 6- or 12-month **AI Builder Internship** in Bangalore at ₹75,000/month. Round 1 = pick a track + build a working project. Round 2 = public GitHub repo + 5-min pitch video + architecture doc + "what broke and how you recovered". Round 3 = panel review (no aptitude test, no GD). "Your code speaks louder than your resume."

That framing changes the winning strategy. You are not being ranked on a leaderboard against a public gallery — submissions are **private applications**, so the real field is invisible. You are being judged by **Razorpay engineers deciding whether they want to hire you onto a specific team**. The winning move is therefore: **pick the track whose "bar" is the most objectively demonstrable, whose problem maps directly to a Razorpay product line an intern would actually join, and attack a sub-angle that the obvious competitors are not taking.**

This file gives you: (1) a scored comparison of all 5 tracks, (2) a **primary** recommendation (Track 03) and a **fallback** (Track 02), each fully worked out, (3) the academic literature (2022+) for each, (4) the GitHub prior art and the exact gaps to exploit, (5) a 3–4 week build plan, (6) a verification plan.

---

## Part A — Track selection

### A.1 Scoring model

Six criteria, weighted for "get hired via a defensible working build, solo, in ~4 weeks":

| Criterion | Weight | Why it matters here |
|---|---|---|
| Strategic fit with a Razorpay product line | 25% | Panel is hiring for a team. Fit = "we want this person on Optimizer / RiskOps / X". |
| Objectivity of "the bar" | 20% | A single defensible number beats a slick demo in a panel review. |
| Low competition / differentiability | 20% | You flagged this as a plus. Fewer credible entries + a sub-angle nobody else takes. |
| Solo-achievable depth in 4 weeks | 15% | Must ship working + measured, not a prototype. |
| "What broke / how I recovered" richness | 10% | Explicitly asked for in submission. Money-handling bugs make great stories. |
| Synthetic-data realism achievable | 10% | Every track needs a convincing held-out batch; some are far easier to fake well. |

### A.2 Scores (1–5, higher = better)

| Track | Fit (25) | Bar objectivity (20) | Low competition (20) | Solo depth (15) | Failure stories (10) | Data realism (10) | **Weighted** |
|---|---|---|---|---|---|---|---|
| **01 AI Growth & Agentic Commerce** | 5 | 2 | 1 | 2 | 3 | 3 | **2.75** |
| **02 AI Risk Manager** | 4 | 5 | 4 | 4 | 3 | 3 | **4.00** |
| **03 AI Revenue Recovery** | 5 | 5 | 3 | 4 | 5 | 4 | **4.35** |
| **04 AI Finance Controller** | 3 | 5 | 4 | 3 | 3 | 3 | **3.60** |
| **05 Open** | 2 | 2 | 2 | 3 | 3 | 3 | **2.35** |

### A.3 Verdict

- **Primary: Track 03 — AI Revenue Recovery.** Highest weighted score. It is Razorpay's *literal core business* (Optimizer / Smart Router / Smart Retry / Subscriptions), its bar is the single most objective of all five ("**measured money recovered across a batch**, with compliant escalation, stopping rules and an audit trail" — you put one number on screen), and it produces the richest money-handling failure stories (idempotency, double-charge, retry storms). Competition is real but **beatable and visible** (see §C), and there is a clean low-competition sub-angle inside it.
- **Fallback: Track 02 — AI Risk Manager.** Razorpay itself says this track "surfaces the risk and ML-minded builders the others miss" — i.e. **they are telling you it is under-subscribed**. The bar is pure and objective (precision/recall + false-positive cost on a held-out set). Risk: mediocre metrics are visible; needs a genuinely defensible dataset. Take this only if you want the thinnest field and are confident in your ML.
- **Rejected: Track 01** (highest hype → most crowded, shallow chatbot demos, hard to show real money in test mode, half-baked ACP/AP2/x402 integrations); **Track 04** (good bar, low competition, but weaker "intern joins this team" story and less demo wow); **Track 05** (no rubric anchor, hard to stand out).

### A.4 Five advantages of Track 03 over the other tracks

1. **Unambiguous scoring.** The bar is "money recovered across a batch". You can show `₹X recovered / ₹Y at risk = Z% recovery rate` on a held-out batch of N failures. No other track lets you win the panel with a single defensible number the way this one does. Track 01's bar ("every money action explainable, bounded, gated") is qualitative; Track 04's is a match rate but on an unsexy task.
2. **Direct product-line fit → highest hire probability.** Razorpay Optimizer already does ML routing on 150–300 parameters / 600M+ data points for ~+10% success rate, and Smart Retry recovers 15–20% of failed transactions (+3–5pp to success rate). An intern who builds a credible recovery agent is *immediately* useful to that team. Risk (Track 02) is a cost centre with a mature in-house team; Finance Controller (Track 04) maps to RazorpayX but is a narrower org.
3. **Best "what broke / how I recovered" material.** The submission explicitly demands a failure story. Money movement gives you real ones: exactly-once execution under concurrent webhooks, stale mandate reservations, duplicate retries during a gateway flap, NPCI retry-cap violations. These are exactly the war stories a payments panel wants to hear.
4. **Synthetic data is both easy and legitimate.** The buildathon expects synthetic/test-mode data. Payment-failure logs (error codes, timestamps, amount, method, issuer, retry outcomes) are simple to generate convincingly and Razorpay test-mode APIs (Orders, Payments, Payment Links, Subscriptions, Refunds) let you make the loop real. Track 02's synthetic fraud data is notoriously hard to make behaviourally realistic (see arXiv 2604.13125 — "synthetic tabular generators fail to preserve behavioural fraud patterns").
5. **It rewards a balanced builder, which is you.** Track 03 done well is genuinely tri-disciplinary: an ML retry/uplift model + an agentic orchestrator + a deterministic policy/audit layer + an operator UI. Track 02 is ML-dominant (your breadth is wasted); Track 01 is frontend/integration-dominant; Track 04 is backend/rules-dominant. Track 03 is where "balanced across all three" is a competitive edge rather than a lack of specialisation.

### A.5 The differentiation problem inside Track 03 (important)

The **obvious** Track 03 build — "detect failed card payment → LLM diagnoses → deterministic policy engine picks RETRY / ALT_METHOD / ESCALATE → audit log" — **already exists publicly and is done well** (see §C.1, `srikrishna0603/razorpay-buildathon` "Revenue Resilience AI"). If you build that, you are compared head-to-head with an existing strong repo and several competent competitors doing the same.

**Do not build the generic card-retry agent.** Pick one of the two under-served sub-angles below. Both keep the strong Track-03 bar; both have near-zero direct prior art.

- **Angle 3A (RECOMMENDED): UPI AutoPay / e-Mandate failed-subscription recovery sequencer.**
  - **Why it's open:** UPI AutoPay failure rate is **8–15%** vs 2–3% for card mandates. ~10% of recurring payments fail on the first attempt; **20–40% of all subscription churn is involuntary**. Renewal success drops ~85% (month 1) → ~70% (month 6). NPCI caps retries at **1 original + max 3**, and mandates a pre-debit notification **≥24h before** each charge. There is **no peer-reviewed paper** on UPI-specific retry-timing (all prior work is card-based vendor blogs — Stripe Smart Retries, Recurly, Dropbox), and **no GitHub repo** targets this. It is uniquely Indian, ties to NPCI's UAP (which Razorpay cites in Track 01's "why now"), and Razorpay ships a UPI AutoPay product.
  - **What you build:** an agent that, for a batch of failed/at-risk mandates, (1) classifies the failure (insufficient funds vs bank downtime vs expired/paused mandate vs limit hit), (2) an ML model picks the **retry timing** within the 3-attempt budget (e.g. payday proximity, historical issuer-hour success, balance-recovery patterns), (3) an **uplift/CATE model** picks the **channel & offer** (WhatsApp + UPI collect link > email; grace period; partial charge), (4) a policy engine enforces the NPCI retry cap, the 24h pre-debit notice, quiet hours, and per-debtor stopping rules, (5) every action is logged to an immutable audit trail with a money-recovered ledger.
  - **Headline metric:** "Recovered ₹X of ₹Y at-risk MRR across N=300 failed mandates = Z% vs 47.6% industry median / vs a static 3-retry baseline we also ran."

- **Angle 3B: Payment-degradation → root-cause → recovery (the "why now" example direction).** Detect a *degradation* (issuer/method/BIN-level success-rate drop) from a transaction stream, do genuine **root-cause analysis** (which issuer / method / gateway / BIN cohort), then choose a bounded recovery action (route away from the degraded gateway, pause and re-attempt, notify affected users). This is closer to what Optimizer does and demonstrates streaming + RCA + routing. Slightly more competition than 3A because it's the first-listed example direction. Prior art: arXiv 2510.21710 (business-impact failure detection in instant payment systems), general RCA-via-ML literature — but nothing packaged as an agent with a recovery loop.

**Pick 3A.** It has the thinnest field, the clearest Indian/NPCI story, and the same objective bar.

---

## Part B — Academic literature review (2022 onward)

Searched: Google Scholar, arXiv, IEEE Xplore, ScienceDirect / Springer, ACL Anthology, dblp. Grouped by relevance to the recommended build. **No single paper solves the target problem end-to-end** — the closest works are card-based, or detection-only, or negotiation-only. That gap is your contribution.

### B.1 Directly relevant to Track 03 / Angle 3A (recurring-payment recovery)

| # | Paper (year, venue) | What it does | Gap you exploit |
|---|---|---|---|
| 1 | **Debt Collection Negotiations with LLMs: An Evaluation System and Optimizing Decision Making with Multi-Agent (MADeN)** — arXiv 2502.18228, 2025 | 13-metric eval across 4 dims (conversational, recovery, efficiency, debtor health); Planning-Agent + Judging-Agent multi-agent loop (+~10% CCI); **975 synthetic debt records via CTGAN**; GPT-4o hits 95.76% recovery but harms debtor health; DPO post-training helps. | Negotiation-only, no *payment-rail execution*, no retry-timing model, no compliance gating. Their own limitations: "simplified debtor financial modelling", "need stricter planning + integration with existing decision models", "manual validation with real debtors". **You add the execution loop, the NPCI compliance layer, and a real money-recovered ledger; reuse their CTGAN + eval-framework idea for your held-out batch.** |
| 2 | **An Identifiable Cost-Aware Causal Decision-Making Framework Using Counterfactual Reasoning** — arXiv 2505.08343, 2025 | Counterfactual, cost-aware framework for choosing an intervention when actions have asymmetric costs. | Not applied to payments. **Use it as the theoretical backbone for "which recovery action, given retry has a network cost and a churn risk".** |
| 3 | **Uplift Modeling with Continuous Treatments: A Predict-then-Optimize Approach** — arXiv 2412.09232, 2024 | CATE/uplift with continuous treatment + budget/operational constraints baked into policy selection. | Marketing framing. **Directly transplantable to "which channel/offer/grace lifts recovery probability most, subject to a per-batch outreach budget and NPCI limits".** Industry retry engines (Stripe/Recurly/Dropbox) do *ranking*, not *uplift* — bringing causal uplift is a genuine methodological step up you can defend to the panel. |
| 4 | **A Feature Engineering Approach for Business Impact-Oriented Failure Detection in Distributed Instant Payment Systems** — arXiv 2510.21710, 2025 | Feature engineering for detecting *business-impacting* failures in SEPA-Instant / TARGET-style instant rails; stresses interpretability. | EU rails, detection-only, no recovery. **Adapt the "business-impact-oriented feature" idea to UPI failure classification; cite as the instant-payments analogue of UPI.** |
| 5 | **Predicting Account Receivables with Machine Learning** — arXiv 2008.07363 (pre-2022, foundational) + **Intelligent decision support for debt collection using predictive learning and multi-criteria optimization** — ScienceDirect S3050700626000381, 2026 | P2P (promise-to-pay) probability estimation; multi-criteria optimisation of collection actions. | B2B receivables framing; not payment-rail, not Indian. Useful for the "promise-to-pay tracker" scoring sub-component if you add one. |
| 6 | **Witzany & Kozina (2022)** — survival analysis for soft-collection processes | Survival models beat logistic regression for time-to-pay in soft collections. | **Use a survival / hazard model for "when will this mandate succeed if retried at time t" instead of a plain classifier — a defensible modelling choice.** |
| 7 | Industry (not peer-reviewed, cite as practice baseline): **Stripe "How we built Smart Retries"**, **Recurly Intelligent Retries**, **Dropbox "Optimizing payments with ML"** (gradient-boosted ranking model over failure-type / usage / payment-type features), **Slicker 2025 Failed-Payment Recovery Benchmarks (47.6% median)**. | ML retry-*timing* on card rails; ranking not causal. | **This is the state of the art and it is entirely industrial and card-based. A rigorous, open, UPI-specific, uplift-based, compliance-gated version does not exist in the literature. That sentence is your paper's/pitch's thesis.** |

### B.2 Relevant to Track 03 / Angle 3B (degradation → RCA → recovery)

- **MetaRCA: A Generalizable Root Cause Analysis Framework for Cloud-Native Systems Powered by Meta Causal Knowledge** — arXiv 2603.02032, 2026. RCA via meta causal knowledge; transplant to payment cohorts (issuer × method × gateway × BIN).
- **Root Cause Analysis of Network Failures Using ML and Summarization** — IEEE Xplore 8030498. Classic ML-RCA + summarisation; the summarisation step maps to "explain the degradation to an operator".
- **A big data-driven root cause analysis system: ML in quality problem solving** — ScienceDirect S0360835221004848. General RCA methodology.
- **Real-Time Fraud Detection Under Concept Drift: A Streaming ML Approach for Instant Payment Systems** — 2025. The streaming/drift machinery here is what you need to detect a *degradation* online rather than in batch.

### B.3 Relevant to the fallback (Track 02)

| # | Paper (year) | Relevance |
|---|---|---|
| 1 | **PromoGuardian: Detecting Promotion Abuse Fraud with Multi-Relation Fused GNNs** — arXiv 2510.12652, 2024/25 (Meituan) | Group-based promo abuse; **precision 0.9315**, 37,517 fraudsters/day, 72,734 tx/day blocked. Benchmark to beat for an "abuse-ring sentinel". |
| 2 | **Voucher Abuse Detection with Prompt-based Fine-tuning on GNNs** — arXiv 2308.10028, CIKM'23 | Prompt-tuned GNN for voucher/coupon abuse. Directly relevant to Razorpay's promo/coupon surface. |
| 3 | **Collusion Detection with Graph Neural Networks** — arXiv 2410.07091, 2024 | Collusion-ring detection method. |
| 4 | **LEX-GNN: Label-Exploring GNN for Accurate Fraud Detection** — 2024 | Handles referral fraud (one actor, many new accounts); message-passing that separates fraud vs benign neighbours. |
| 5 | **Universal Ring-of-Abusers Detection via Multi-Modal Heterogeneous Graph Learning** — Amazon Science, 2024 | Multi-modal (numeric + text + image) + graph for abuser rings. |
| 6 | **Returnformer: A Graph Transformer for Predicting Product Returns in E-Commerce** — Entropy 28(1):72, 2026 | Pre-payment return-risk prediction via bipartite user–product graph; beats 4 ML baselines. Benchmark for a "return-risk scorer". |
| 7 | **Understanding and predicting online product return behavior: an interpretable ML approach** — Int. J. Production Economics, Dec 2024 (ScienceDirect S0925527324003566) | Interpretable return prediction + return-reason; tested on real large e-commerce data. |
| 8 | **"Early bird catches the worm: predicting returns even before purchase in fashion e-commerce"** + **"Proactive return prediction using heterogeneous GNNs" (2024)** | Pre-purchase return prediction — the hardest, most valuable version. |
| 9 | **Towards Waste Reduction in E-Commerce: ML Algorithms + Optimisation for Garment Returns Prediction** — SN Computer Science, 2025 | Feature-importance-driven returns prediction; comparative algorithm study. |
| 10 | **Real-Time Fraud Detection Under Concept Drift: Streaming ML for Instant Payment Systems** — 2025; **Detecting Concept Drift in Financial Fraud Using Temporal GNNs** — 2024/25; **Joint Detection of Fraud and Concept Drift with LLM-Assisted Judgment** — arXiv 2505.07852, 2025 | The "fraud-spike detector" direction = drift/anomaly detection. These are the current methods + the adversarial-drift framing. |
| 11 | **SAGE: An LLM-driven Self-Reflective Agentic Framework for Fraud Detection** — arXiv 2606.08146, 2026; **Understanding Structured Financial Data with LLMs: A Case Study on Fraud Detection** — arXiv 2512.13040, 2025 | LLM-agentic fraud detection framing — how to combine an LLM reasoner with a classifier without letting the LLM be the classifier. |
| 12 | **Explainable ML for Real-Time Payment Fraud Detection** — Springer, 2024; **Evaluating Fairness in Transaction Fraud Models** — arXiv 2409.04373, 2024 | The "honest metrics including false-positive cost" bar = explainability + fairness/bias auditing. Cite these to show you understand FP cost. |
| 13 | **E-Commerce Fraud Detection Based on ML: Systematic Literature Review** — Big Data Mining & Analytics, 2023 (SCOPUS/ScienceDirect + IEEE screened) | The survey to anchor your related-work section; notes the field's core problem is *lack of real labelled data*. |
| 14 | **AI in Chargeback / Compelling Evidence 3.0 / VAMP** context (industry, 2024–25): automated dispute responses cut chargeback cases ~33%; Visa CE 3.0 (2024) lets merchants submit historical device/IP evidence; Visa VAMP consolidation (1 Apr 2025) reshaped thresholds. | For a "chargeback evidence responder": the *rules changed recently*, so pre-2024 tooling is stale — a fresh, CE-3.0-aware, reason-code-aware evidence assembler is a real gap. No peer-reviewed paper exists; it is all vendor blogs (Riskified, Chargebacks911, Stripe Smart Disputes). |

### B.4 Cross-cutting / methodology

- **Synthetic Tabular Generators Fail to Preserve Behavioral Fraud Patterns: A Benchmark on Temporal, Velocity, and Multi-Account Signals** — arXiv 2604.13125, 2026. **Critical caveat for any synthetic held-out set.** Read before you generate data; cite it to show you know the pitfalls and explain how you mitigated (inject realistic temporal/velocity structure, not IID rows).
- **Large Language Model Agents in Finance: A Survey** — ACL Findings EMNLP 2025 (2025.findings-emnlp.972). Positioning / related-work for any agentic finance build.
- **Finance Agent Benchmark: Benchmarking LLMs on Real-world Financial Research Tasks** — arXiv 2508.00828, 2025. If you want an external yardstick for the agent's reasoning quality.
- **Scalable Invoice Reconciliation for SMEs: Edge-Deployed LLMs in Multi-Agent Systems** — ResearchGate 392226522, Mar 2025 (relevant only if you pivot to Track 04).

**Literature bottom line:** the recovery/collections problem is covered *in pieces* — retry timing (industry, card-only), collections negotiation (MADeN, no execution), uplift/causal intervention selection (marketing, not payments), instant-payment failure detection (EU, detection-only). **Nobody has published an open, UPI/e-mandate-specific, compliance-gated, uplift-driven recovery agent with a measured money-recovered batch result.** That is a defensible novel contribution for a student project and an obvious pitch thesis.

---

## Part C — GitHub / prior-art scan (competition intel)

There is **no public submission gallery** (applications are private), so the visible field = repos people chose to make public + demo links. Found so far:

### C.1 Track 03 prior art — the ones to beat

| Repo / link | What it is | Strengths | Gaps → your edge |
|---|---|---|---|
| **`srikrishna0603/razorpay-buildathon` — "Revenue Resilience AI"** | The strongest known competitor. "Deterministic policy engine gated by a typed diagnostic simulator." LLM is **sandboxed with zero execution authority** → outputs a *typed diagnosis only*; a **Policy Engine** maps diagnosis → `RETRY / OFFER_ALTERNATE_METHOD / STOP_AND_ESCALATE / NO_ACTION` under economic thresholds + confidence checks + idempotency; **SQLite WAL** for exactly-once; **failure-injection tests** (concurrent webhooks, stale reservation, duplicate executor); React operator console (R3F/Framer). Locally reproducible. | Clean trust-boundary architecture; real idempotency; real failure tests; documented invariants; polished console. **This is now the baseline pattern — assume 5–15 other entrants build something similar.** | (1) **Card/generic only — no UPI AutoPay, no NPCI retry cap, no 24h pre-debit notice, no e-mandate lifecycle.** (2) **No ML** — retry decision is threshold rules, not a learned timing/uplift model. (3) Thresholds hardcoded (`< 100 INR`), no merchant-specific or dynamic economics. (4) No adversarial prompt-injection guardrail on the diagnosis input. (5) SQLite admits it "cannot support strict durable WAL-locking… at scale". (6) No held-out **batch** metric — the buildathon bar is "money recovered *across a batch*"; a single-transaction console doesn't prove that. **Your build: UPI-mandate-specific + learned retry-timing (survival model) + uplift-based channel/offer selection + NPCI compliance layer + a 300-mandate held-out batch with a money-recovered number and a static-retry baseline for comparison.** |
| **`recovery-agent-eight.vercel.app` ("Recovery Agent · Razorpay Buildathon")** | A deployed Track-03 demo. Public content minimal; could not extract architecture or metrics. | Shipped a hosted demo. | Unknown depth; no visible metrics or audit trail. Treat as "someone else is in this lane" — reinforces: don't do the generic version. |
| **`recurso-dev/recurso`** | OSS billing engine: subscriptions, invoicing, multi-currency (Stripe **+ Razorpay**), **India GST**, **smart dunning** with off-session saved-card retries + recovery deep-links, double-entry ledger. | Production-grade dunning + a real ledger you could learn from / cite. | It's a billing engine, not an agent; dunning is rules + deep-links, no ML, no UPI-mandate-aware sequencing, no LLM diagnosis, no uplift. Good source of realistic data schemas + the double-entry ledger pattern for your audit trail. |
| **`UniBee`** (OSS billing, self-hostable) | Smart-dunning features to reduce churn. | Reference for dunning UX. | Same as recurso — not agentic, not ML, not UPI-mandate-specific. |
| **WorkAid Dunning**, FlyCode, Slicker, Recover Payments, Butter, Gravy (commercial) | Failed-payment recovery SaaS; some AI-driven retry timing. | Prove the problem is real and monetisable. | Closed; card-centric; US/EU; nothing UPI-AutoPay-native. |

### C.2 Track 02 prior art

| Repo | What it is | Note |
|---|---|---|
| **`amazon-science/fraud-dataset-benchmark`** | Standard multi-dataset fraud benchmark harness (IEEE-CIS, Sparkov, etc.). | **Use this** to get honest, comparable precision/recall for a Track-02 entry. |
| **`elangovana/PaySim-Synthetic-Dataset-Fraud-Detection`** | PaySim EDA + models. | Reference implementation for PaySim. |
| PromoGuardian / voucher-abuse / collusion-GNN papers | Have partial code or are reproducible. | For abuse-ring / promo-abuse direction. |
| No dedicated OSS **chargeback-representment LLM agent** found | Market is all commercial (Stripe Smart Disputes, Zamp, ChatFin, Chargebacks911). | A clean OSS CE-3.0-aware evidence assembler is a genuine gap. |

### C.3 Track 04 prior art (fallback-of-fallback, for completeness)

`Manu6259/financial-reconciliation-agent` (RAG categorization +46% lift, deterministic reconciliation, human-review queue), `Alexi5000/ClawKeeper` (110 TS finance agents, approval-gated execution), `pavitsu/pavit-bank-reconciliation`, `johnsonhk88/AI-Bank-Statement-Document-Automation`. Track 04 is **more crowded with OSS prior art than Track 03's UPI sub-angle** — another reason 3A wins.

### C.4 Other buildathon submissions seen

- Priyanshu Singh — "AI-Driven GitHub Authenticity Engine" (Open track, YouTube pitch). Not a competitor to 02/03.

**Prior-art bottom line:** the generic Track-03 card-retry agent is taken and done well. The **UPI AutoPay / e-mandate recovery sequencer with a learned timing model + uplift-based intervention + NPCI compliance gating + batch money-recovered metric** has **no public repo and no paper**. Build that.

---

## Part D — Recommended build (Primary: Track 03, Angle 3A)

### D.1 One-liner

**"MandateMend"** (name it what you like) — an agent that works a batch of failed / at-risk UPI AutoPay & card e-mandates, diagnoses each failure, schedules the *right retry at the right time* within the NPCI 3-attempt budget, picks the *right dunning intervention* (channel / grace / partial charge) via an uplift model, enforces every compliance rule, executes via Razorpay test-mode APIs, and reports **money recovered across the batch** with a full audit trail.

### D.2 Architecture (defensible trust boundary — improves on the known baseline)

```
                 ┌─────────────────────────────────────────────────────────┐
   Failed /      │  1. INGEST & NORMALIZE                                   │
   at-risk  ───► │     Razorpay test-mode webhooks + synthetic backfill     │
   mandates      │     → canonical FailureEvent{mandate_id, amount, method, │
                 │       issuer, err_code, ts, attempt_no, mandate_state}   │
                 └───────────────┬─────────────────────────────────────────┘
                                 ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │  2. DIAGNOSIS (LLM, SANDBOXED — no execution authority)             │
   │     input: failure event + recent history + issuer status feed     │
   │     output: TypedDiagnosis{cause ∈ {INSUFFICIENT_FUNDS,            │
   │       BANK_DOWNTIME, LIMIT_EXCEEDED, MANDATE_PAUSED,               │
   │       MANDATE_EXPIRED, TECH_DECLINE, SUSPECTED_CHURN},             │
   │       confidence, rationale}                                       │
   │     guardrail: input sanitised; schema-validated; low-confidence   │
   │       → NO_ACTION + human queue                                    │
   └───────────────┬───────────────────────────────────────────────────┘
                   ▼
   ┌───────────────────────────────┐   ┌───────────────────────────────┐
   │  3a. RETRY-TIMING MODEL (ML)  │   │  3b. INTERVENTION UPLIFT MODEL│
   │  survival / hazard model:     │   │  CATE over {no-op, WhatsApp+   │
   │  P(success | retry at t)      │   │  UPI link, SMS, grace 48h,     │
   │  features: payday proximity,  │   │  partial charge, method switch}│
   │  issuer-hour history, balance │   │  picks argmax uplift s.t.      │
   │  recovery pattern, err_code   │   │  outreach budget + NPCI limits │
   └───────────────┬──────────────┘   └──────────────┬────────────────┘
                   └──────────────┬──────────────────┘
                                  ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │  4. POLICY ENGINE (DETERMINISTIC — absolute authority)             │
   │   HARD RULES (cannot be overridden by ML or LLM):                 │
   │    • attempts_used < 3  (NPCI cap: 1 original + max 3 retries)    │
   │    • pre-debit notification sent ≥ 24h before scheduled retry     │
   │    • quiet hours / max N contacts per debtor per week            │
   │    • per-mandate economic floor (retry cost vs expected recovery) │
   │    • stopping rule: 2 consecutive hard declines → STOP_ESCALATE   │
   │    • mandate must be ACTIVE (not paused/expired/revoked)         │
   │   → emits a single typed Action + idempotency key                 │
   └───────────────┬───────────────────────────────────────────────────┘
                   ▼
   ┌───────────────────────────────┐   ┌───────────────────────────────┐
   │  5. EXECUTOR                   │   │  6. AUDIT + LEDGER            │
   │  Razorpay test-mode:          │   │  append-only event log +      │
   │  Subscriptions / Orders /     │   │  double-entry money-recovered │
   │  Payment Links / Refunds;     │   │  ledger; every action carries │
   │  exactly-once via idem key +  │   │  {who/what/why/rule-trace};   │
   │  DB unique constraint         │   │  exportable evidence pack     │
   └───────────────────────────────┘   └───────────────────────────────┘
                   ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │  7. OPERATOR CONSOLE  — batch view, per-mandate timeline,         │
   │  policy-rejection reasons, "recovered ₹X / ₹Y = Z%" headline,     │
   │  baseline-vs-agent comparison chart, one-click evidence export.   │
   └───────────────────────────────────────────────────────────────────┘
```

Why this beats the known baseline: (a) **UPI-mandate domain model + NPCI compliance layer** nobody else has; (b) **two learned models** (timing + uplift) where the baseline has only thresholds — and *uplift/causal* rather than the *ranking* that even Stripe/Recurly use; (c) **batch-first** design that directly answers the bar; (d) explicit **baseline comparison** (static 3-retry, and "email-only" dunning) so your number is meaningful; (e) same rigorous trust boundary + idempotency the baseline has, so you don't lose on safety.

### D.3 Data plan

- **Synthetic mandate-failure generator** (your own, ~2 days). Produce ~2,000 mandates over a simulated 6 months with realistic structure: issuer mix, per-issuer downtime windows, payday-correlated balance recovery, mandate pause/expiry events, err-code distribution matching the 8–15% UPI failure rate, and a latent "true churn intent" for a subset. **Inject temporal + velocity + multi-attempt structure** (heed arXiv 2604.13125 — do not generate IID rows). Consider CTGAN for the tabular marginals (as MADeN did) then overlay the temporal process.
- **Held-out test batch:** N = 300 failed mandates, frozen, never seen in training. This is what you score on.
- **Ground truth for "recovered":** in simulation you know whether a given (action, time) would have succeeded, so you can compute realised recovery and counterfactual baselines exactly.
- **Razorpay test-mode:** wire the executor to real test API calls (Subscriptions/Orders/Payment Links) for a subset so the demo shows real API round-trips, not just a simulator.

### D.4 Modelling choices you can defend to a panel

- **Retry timing = discrete-time survival model** (e.g. gradient-boosted hazard, or a simple neural hazard) for `P(success | first retry at hour h, features)` — cite Witzany & Kozina 2022. Beats a plain classifier because the decision is *when*, not *if*.
- **Intervention = uplift / CATE** (T-learner or causal forest) over the discrete action set with a per-batch outreach budget — cite arXiv 2412.09232 + 2505.08343. Beats industry "ranking" approaches.
- **LLM = diagnosis + explanation only**, schema-constrained, never touches money — matches the safety bar and the known-baseline pattern, with an added prompt-injection sanitiser on the free-text failure context.
- **Policy engine = deterministic, hard rules, full rule-trace in the audit log.**

### D.5 Metrics to report (hit every clause of "the bar")

1. **Money recovered across the batch:** `₹ recovered / ₹ at risk` on N=300, with 95% CI (bootstrap).
2. **Lift vs baselines:** vs static "retry at +1d/+3d/+7d", vs "email-only dunning", vs "single immediate retry". Show the delta is the agent's contribution.
3. **Retry efficiency:** recoveries per retry attempt (respecting the 3-cap) — proves you're not just spamming.
4. **False-positive / harm cost:** unnecessary contacts, retries on truly-dead mandates, over-charging — report the cost explicitly.
5. **Compliance:** 100% of actions within NPCI cap + 24h notice + quiet hours (assert in tests; show the one violation you deliberately injected being blocked).
6. **Graceful failure:** one end-to-end failure handled live (gateway flap during retry → idempotency prevents double charge → policy escalates). This is your "what broke" story.
7. **Exception list:** mandates the agent could not resolve and why — honest, not hidden.

### D.6 4-week solo timeline

| Week | Deliverable |
|---|---|
| **1** | Repo skeleton; canonical schemas; synthetic generator (with temporal/velocity structure); Razorpay test-mode integration (Subscriptions/Orders/Payment Links/webhooks); append-only audit log + double-entry ledger. |
| **2** | LLM diagnosis module (schema-constrained + injection guard); deterministic policy engine with all hard rules + rule-trace; executor with idempotency (DB unique constraint, not just SQLite WAL — use Postgres or document the limitation like the baseline did but go one better). Failure-injection test suite. |
| **3** | Retry-timing survival model + intervention uplift model; wire into the loop; run the N=300 held-out batch; implement all baselines for comparison; compute metrics + CIs. |
| **4** | Operator console (batch view, per-mandate timeline, policy-rejection reasons, headline recovery number, baseline-vs-agent chart, evidence export); architecture doc; record the 5-min pitch (lead with the recovered-₹ number and the NPCI-compliance angle; show the live gateway-flap recovery); README with repro steps + honest limitations. |

### D.7 Pitch framing (5-min video)

1. **0:00–0:40** — The gap: UPI AutoPay fails 8–15% (vs 2–3% cards), 20–40% of subscription churn is involuntary, and *there is no open, UPI-native, compliance-aware recovery system* — industry retry engines are all card-based, closed, and use ranking not causal uplift.
2. **0:40–2:00** — Architecture walkthrough: sandboxed LLM diagnosis → two learned models → deterministic policy engine → idempotent executor → audit ledger. Emphasise the trust boundary and the NPCI compliance layer.
3. **2:00–3:30** — Results on the frozen 300-mandate batch: **₹X recovered = Z%**, +Δ vs static retry, retry-efficiency, false-positive cost, 100% compliance. Show the baseline-vs-agent chart.
4. **3:30–4:30** — "What broke": live gateway-flap during a retry → idempotency key + DB constraint prevent the double charge → policy engine escalates → audit trail shows the whole thing.
5. **4:30–5:00** — Honest exception list + what production would need (real issuer status feeds, Postgres, merchant-specific economics).

---

## Part E — Fallback build (Track 02: AI Risk Manager)

Take this if you want the thinnest field (Razorpay says this track is under-subscribed) and you're confident in ML rigor.

### E.1 Best sub-angle: **Return-Risk Scorer for Indian D2C / COD** (not fraud — less crowded than fraud, and returns "quietly eat margin" per the track text)

- **Why:** fraud-spike detection is the crowded Track-02 pick (everyone reaches for IEEE-CIS). Returns are explicitly named in the track, are a real Razorpay Magic/COD pain, and the pre-purchase-return-prediction literature (Returnformer 2026, IJPE Dec 2024, "Early bird…", proactive-return GNNs 2024) is fresh and beatable.
- **Build:** a pre-/at-checkout model that scores `P(return | cart, customer history, address, method, category)` and a *bounded responder* that picks an intervention (require prepaid, offer size guidance, hold COD, add a return-fee nudge) — with measured precision/recall **and false-positive cost** (blocking a good customer) on a held-out set.
- **Data:** no clean Indian public set → synthesize (heed arXiv 2604.13125) or adapt the Kaggle "e-commerce returns" + Olist Brazilian e-commerce sets, and be explicit about the transfer.
- **Metrics bar:** precision / recall / PR-AUC on held-out; **cost curve** (margin saved vs good-customer friction) at each threshold; ablation vs a logistic baseline; SHAP for explainability (cite Springer 2024 explainable-fraud + arXiv 2409.04373 fairness).
- **Defense-only:** trivially satisfied — it's a scorer + policy, nothing offense-capable.

### E.2 Alternative Track-02 sub-angle: **CE-3.0-aware Chargeback Evidence Responder**

- **Why:** Visa Compelling Evidence 3.0 (2024) + VAMP consolidation (Apr 2025) made pre-2024 tooling stale; **no OSS LLM representment agent exists**; first-party ("friendly") fraud is now 36% of all fraud (up from 15% in 2023).
- **Build:** ingest dispute notice → classify reason code → determine CE-3.0 evidence threshold → assemble evidence pack from (synthetic) order/CRM/logistics records → draft rebuttal → **measured win-rate on a held-out set of disputes** with a false-submission cost.
- **Risk:** harder to get a convincing held-out "did we win" label without real dispute outcomes; more prompt-engineering than ML.

### E.3 Track-02 timeline (solo, 4 wk)

W1 data + schema + baseline model; W2 main model + calibration + cost curve + fairness audit; W3 bounded responder/policy + held-out eval + ablations; W4 console + honest FP-cost reporting + exception list + pitch.

### E.4 Track-02 metrics bar checklist

Held-out precision/recall/PR-AUC · explicit false-positive cost curve · ablation vs simple baseline · calibration plot · fairness/bias slice · exception list · **strictly defense-only** (state it).

---

## Part F — Summary tables

### F.1 Track comparison

| Track | Strategic fit | Bar (objectivity) | Competition | Solo-4wk depth | Key risk | Verdict |
|---|---|---|---|---|---|---|
| 01 Agentic Commerce | Very high | Low (qualitative) | **Highest** (hype) | Low (integration-heavy, shallow demos) | Look like everyone else; no real money in test mode | Avoid |
| **03 Revenue Recovery** | **Very high** (Optimizer/Retry/Subscriptions) | **Highest** ("money recovered / batch") | Medium, **visible & beatable** | High (ML + agent + policy + UI) | Generic version is taken → must pick UPI sub-angle | **PRIMARY** |
| 02 Risk Manager | High (RiskOps) | **Highest** (P/R + FP cost) | **Low** (Razorpay says so) | High (ML-dominant) | Mediocre metrics are visible; data realism | **FALLBACK** |
| 04 Finance Controller | Medium (RazorpayX) | High (match rate / 50+ batch) | Low, but **more OSS prior art** | Medium | Weaker "join this team" story; less wow | Skip |
| 05 Open | Low | Low (no anchor) | Medium | Medium | No rubric to win on | Skip |

### F.2 Recommended build at a glance

| Field | Value |
|---|---|
| **Track** | 03 — AI Revenue Recovery |
| **Sub-angle** | UPI AutoPay / e-mandate failed-subscription recovery sequencer (Angle 3A) |
| **Why this angle** | 8–15% UPI mandate failure vs 2–3% cards; 20–40% involuntary churn; **no paper, no GitHub repo** targets UPI-native recovery; ties to NPCI UAP; Razorpay ships the product |
| **Core novelty** | UPI/NPCI compliance layer + **learned retry-timing (survival model)** + **uplift/CATE intervention selection** (industry uses ranking) + batch-first money-recovered metric with baseline comparison |
| **Headline metric** | ₹ recovered / ₹ at-risk on frozen N=300 batch, + lift vs static-retry & email-only baselines |
| **Safety pattern** | Sandboxed LLM (diagnosis only) → deterministic policy engine (absolute authority) → idempotent executor → append-only audit ledger (matches best-known competitor, plus injection guard + Postgres idempotency) |
| **Main competitor to beat** | `srikrishna0603/razorpay-buildathon` ("Revenue Resilience AI") — strong architecture, but card-only, no ML, no UPI/NPCI, no batch metric |
| **Fallback** | Track 02, return-risk scorer for Indian D2C/COD (thinnest field; fresh 2024–26 literature) |

### F.3 Key numbers to quote in the pitch

| Fact | Source |
|---|---|
| UPI AutoPay failure 8–15% vs 2–3% card mandates | PhonePe / PayU / Razorpay subscription guides |
| NPCI retry cap: 1 original + max 3 retries; pre-debit notice ≥24h | NPCI UPI AutoPay rules / merchant guides |
| ~10% of recurring payments fail on first attempt; 20–40% of subscription churn is involuntary | Slicker / Recurly / industry |
| Median failed-payment recovery rate 47.6% (2025 SaaS benchmark) | Slicker 2025 benchmark |
| WhatsApp + UPI link ≈ 3× email recovery; 48h grace recovers 15–20% | India subscription-billing guides |
| Razorpay Optimizer: ML routing on 150–300 params / 600M+ data points → ~+10% success rate; Smart Retry recovers 15–20% of failed tx (+3–5pp) | Razorpay blog / docs |
| Stripe Smart Retries: +11% revenue vs static schedules; Adaptive Acceptance recovered $6B in 2024 | Stripe blog |
| Synthetic tabular generators fail to preserve behavioural fraud patterns | arXiv 2604.13125 (2026) |

### F.4 Reading list priority (start here)

1. `srikrishna0603/razorpay-buildathon` README — know exactly what you're beating.
2. MADeN — Debt Collection Negotiations with LLMs (arXiv 2502.18228) — eval framework + CTGAN synthetic data + multi-agent planning/judging.
3. Uplift Modeling with Continuous Treatments (arXiv 2412.09232) + Cost-Aware Causal Decision-Making (arXiv 2505.08343) — intervention selection backbone.
4. Feature Engineering for Failure Detection in Instant Payment Systems (arXiv 2510.21710) — UPI-analogue failure features.
5. Synthetic Tabular Generators Fail… (arXiv 2604.13125) — how not to build your held-out batch.
6. Stripe "How we built Smart Retries" + Dropbox "Optimizing payments with ML" — the industrial state of the art you're improving on.
7. `recurso-dev/recurso` — realistic billing/dunning schemas + double-entry ledger pattern for your audit trail.

---

## Part G — Verification plan (how you'll know the build is panel-ready)

1. **Bar compliance check:** produce the batch report — does it state (a) money recovered across N≥50 (you'll do 300), (b) compliant escalation, (c) stopping rules, (d) audit trail? If any clause is missing, it's not done.
2. **Baseline comparison exists:** static-retry and email-only baselines run on the *same* frozen batch; the agent's lift is reported with a CI. A number with no baseline is a red flag to a panel.
3. **Reproducibility:** `git clone && make demo` reproduces the batch result on a fresh machine (the known competitor advertises this — match it).
4. **Failure injection passes:** concurrent webhook / duplicate retry / gateway flap / NPCI-cap-violation attempt / paused-mandate — each is a test that asserts no double charge and correct policy response. Record one on video.
5. **LLM cannot move money:** a test that feeds an adversarial/prompt-injected failure context and asserts the executor still only acts on policy-engine output.
6. **Honest exception list:** the report names unresolved mandates and reasons; nothing swept under the rug.
7. **Razorpay test-mode round-trip:** at least one real test-mode Subscription/Order/Payment-Link call visible in logs + console, not only the simulator.
8. **Pitch dry-run:** 5:00 max, opens with the recovered-₹ number and the NPCI angle, shows the live failure recovery, ends with the exception list.

---

## Sources

- [Razorpay AI Buildathon — official](https://razorpay.com/buildathon/)
- [Velonx — Buildathon tracks/eligibility/selection](https://velonx.in/blog/razorpay-ai-buildathon-2026-tracks-eligibility-stipend-selection-process)
- [DEV — Dev Opportunity Radar #14](https://dev.to/devengers/dev-opportunity-radar-14-mlh-global-hack-week-40k-agents-for-humans-hackathon-razorpay-ai-2b9g)
- [GitHub — srikrishna0603/razorpay-buildathon ("Revenue Resilience AI")](https://github.com/srikrishna0603/razorpay-buildathon)
- [Recovery Agent · Razorpay Buildathon (demo)](https://recovery-agent-eight.vercel.app/)
- [GitHub — recurso-dev/recurso (OSS billing + smart dunning, Stripe+Razorpay, GST)](https://github.com/recurso-dev/recurso/releases)
- [GitHub — amazon-science/fraud-dataset-benchmark](https://github.com/amazon-science/fraud-dataset-benchmark)
- [GitHub — Manu6259/financial-reconciliation-agent](https://github.com/Manu6259/financial-reconciliation-agent)
- [GitHub — kennethleungty/Finance-LLMs (use-case compendium)](https://github.com/kennethleungty/finance-llms)
- [arXiv 2502.18228 — Debt Collection Negotiations with LLMs (MADeN)](https://arxiv.org/html/2502.18228v1)
- [arXiv 2412.09232 — Uplift Modeling with Continuous Treatments](https://arxiv.org/html/2412.09232v1)
- [arXiv 2505.08343 — Cost-Aware Causal Decision-Making with Counterfactual Reasoning](https://arxiv.org/pdf/2505.08343)
- [arXiv 2510.21710 — Feature Engineering for Failure Detection in Distributed Instant Payment Systems](https://arxiv.org/pdf/2510.21710)
- [arXiv 2604.13125 — Synthetic Tabular Generators Fail to Preserve Behavioral Fraud Patterns](https://arxiv.org/pdf/2604.13125)
- [arXiv 2510.12652 — PromoGuardian: Promotion Abuse Fraud with Multi-Relation Fused GNNs](https://arxiv.org/abs/2510.12652)
- [arXiv 2308.10028 — Voucher Abuse Detection with Prompt-based Fine-tuning on GNNs (CIKM'23)](https://arxiv.org/pdf/2308.10028)
- [arXiv 2410.07091 — Collusion Detection with Graph Neural Networks](https://arxiv.org/abs/2410.07091)
- [arXiv 2505.07852 — Joint Detection of Fraud and Concept Drift with LLM-Assisted Judgment](https://arxiv.org/pdf/2505.07852)
- [arXiv 2606.08146 — SAGE: LLM-driven Self-Reflective Agentic Framework for Fraud Detection](https://arxiv.org/pdf/2606.08146)
- [arXiv 2512.13040 — Understanding Structured Financial Data with LLMs: Fraud Detection](https://arxiv.org/pdf/2512.13040)
- [arXiv 2409.04373 — Evaluating Fairness in Transaction Fraud Models](https://arxiv.org/pdf/2409.04373)
- [arXiv 2603.02032 — MetaRCA: Root Cause Analysis for Cloud-Native Systems](https://arxiv.org/pdf/2603.02032)
- [arXiv 2508.00828 — Finance Agent Benchmark](https://arxiv.org/pdf/2508.00828)
- [Entropy 2026, 28(1):72 — Returnformer: Graph Transformer for Predicting Product Returns](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12839650/)
- [ScienceDirect S0925527324003566 — Interpretable ML for online product return behavior (IJPE, Dec 2024)](https://www.sciencedirect.com/science/article/abs/pii/S0925527324003566)
- [Springer — Improved Random Forest for E-commerce Seasonal Return Prediction](https://link.springer.com/chapter/10.1007/978-981-96-9248-4_16)
- [Springer — Waste Reduction in E-Commerce: ML + Optimisation for Garment Returns (SN Computer Science, 2025)](https://link.springer.com/article/10.1007/s42979-025-03944-z)
- [Big Data Mining & Analytics 2023 — E-Commerce Fraud Detection Based on ML: Systematic Literature Review](https://www.sciopen.com/article/10.26599/BDMA.2023.9020023)
- [Springer 2024 — Explainable ML for Real-Time Payment Fraud Detection](https://link.springer.com/chapter/10.1007/978-3-031-63717-9_1)
- [ACL Findings EMNLP 2025 — Large Language Model Agents in Finance: A Survey](https://aclanthology.org/2025.findings-emnlp.972.pdf)
- [ResearchGate 392226522 — Scalable Invoice Reconciliation for SMEs: Edge-Deployed LLMs in Multi-Agent Systems (Mar 2025)](https://www.researchgate.net/publication/392226522)
- [ScienceDirect S3050700626000381 — Intelligent decision support for debt collection](https://www.sciencedirect.com/science/article/pii/S3050700626000381)
- [arXiv 2008.07363 — Predicting Account Receivables with Machine Learning](https://arxiv.org/html/2008.07363v1)
- [ResearchGate 404376475 — Real-Time Fraud Detection Under Concept Drift: Streaming ML for Instant Payment Systems (2025)](https://www.researchgate.net/publication/404376475)
- [Razorpay Blog — Optimizer AI/ML routing (~+10% success rate)](https://razorpay.com/blog/boost-payments-success-rates-with-optimizers-ai-ml-routing/)
- [Razorpay Blog — Master Recurring Payments with UPI 2.0 AutoPay (2026)](https://razorpay.com/blog/master-recurring-payments-upi-autopay-guide/)
- [Razorpay Blog — UPI Autopay vs Card e-Mandates (2026)](https://razorpay.com/blog/upi-autopay-vs-card-e-mandates/)
- [Razorpay Docs — API Sandbox / Test Mode](https://razorpay.com/docs/api/sandbox-setup/)
- [Stripe — How we built Smart Retries](https://stripe.com/blog/how-we-built-it-smart-retries)
- [Dropbox Tech — Optimizing payments with machine learning](https://dropbox.tech/machine-learning/optimizing-payments-with-machine-learning)
- [Slicker — 2025 Failed-Payment Recovery Benchmarks (47.6% median)](https://www.slickerhq.com/resources/blog/2025-failed-payment-recovery-benchmarks-saas-median-47-percent)
- [PayU — UPI AutoPay Mandate setup guide for subscription merchants](https://payu.in/blog/upi-autopay-mandate-subscription-payments/)
- [PhonePe for Business — Understanding UPI Autopay Mandates](https://business.phonepe.com/articles/understanding-upi-autopay-mandates-everything-you-need-to-know)
- [Karo Zieminski — Agentic Commerce Protocols Explained: ACP, AP2, x402, MPP, UCP](https://karozieminski.substack.com/p/agentic-commerce-protocols-acp-ap2-x402-mpp-ucp)
- [Crossmint — Agentic payments protocols compared (MPP, ACP, AP2, x402)](https://www.crossmint.com/learn/agentic-payments-protocols-compared)
- [GitHub — agentic-commerce-protocol/agentic-commerce-protocol (OpenAI + Stripe)](https://github.com/agentic-commerce-protocol/agentic-commerce-protocol)
- [Riskified — Human + AI for automated chargeback dispute management](https://www.riskified.com/blog/automated-chargeback-dispute-management-software/)
- [Chargeflow — 100+ Chargeback Statistics for 2026](https://www.chargeflow.io/blog/chargeback-statistics-trends-costs-solutions)
- [Auto Interview AI — Vernacular/Hinglish Voice AI Agents in India (2026)](https://www.autointerviewai.com/blog/vernacular-ai-voice-agents-india-hinglish-code-switching-2026)
