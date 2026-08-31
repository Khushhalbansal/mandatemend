# Changelog

Honest running log of decisions and real failures (CLAUDE.md §3.2, §7, §5.4).
Newest first. Do not retroactively clean this up — the failures are pitch material.

## [unreleased]

### 2026-09-01 — scaffold + stack decisions (log-and-proceed, CLAUDE.md §3.2)
- **Language: Python 3.11+** (local machine has 3.13.0). ML + FastAPI ecosystem, matches CLAUDE.md's pytest references.
- **DB: PostgreSQL 16 via docker-compose**, not SQLite. Reasoning: CLAUDE.md §2 requires idempotency enforced by a
  DB-level unique constraint that holds under concurrent webhooks; §3.1 makes the storage engine a hard-stop to change
  later, so it must be right on the first commit. SQLite's UNIQUE constraint is atomic but its single-writer locking is
  the exact limitation the closest competitor repo concedes. Postgres removes that objection.
- **Web: FastAPI + Jinja2 + HTMX**, server-rendered, not a React SPA. Reasoning: CLAUDE.md §4 explicitly warns against
  the generated-SPA look and asks for information density for an operator who stares at this daily. Server-rendered dense
  tables fit that better and remove a build toolchain.
- **Retry-timing model: discrete-time survival analysis (`lifelines`)**, not a plain classifier. Reasoning: the decision
  is *when* to retry within the NPCI 3-attempt budget, not *if* — a hazard/survival formulation matches the problem and
  is defensible (Witzany & Kozina 2022, survival analysis for soft-collection).
- **Uplift model: hand-rolled T-learner** over the discrete intervention set. Reasoning: CLAUDE.md §6 dependency hygiene —
  avoid pulling `econml`/`causalml` (heavy, transitive deps) into money-adjacent code for a two-arm-per-treatment CATE
  estimate we can implement transparently in ~40 lines on top of scikit-learn.
- **Diagnosis: `HeuristicDiagnoser` (offline, real rule-based) + `LLMDiagnoser` (Anthropic)**, selected by env. The
  heuristic path is a genuine classifier over error codes / mandate state, NOT a stub that reports fake success
  (CLAUDE.md §1.3). Tests run offline against the heuristic path; the `llm` marker gates the online path.
- **Gateway: `SimulatedGateway` + `RazorpayTestGateway`**, selected by env. The simulator replays the frozen batch's
  ground-truth labels; it cannot invent a success not present in the label file (CLAUDE.md §1.3).
