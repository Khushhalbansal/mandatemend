# Figma / MCP integration rules for this repo

**Read this before using any `mcp__figma__*` tool against this codebase.**

## TL;DR — this is not a design-system codebase

MandateMend is a **Python backend + ML** project (a UPI-mandate payment-recovery agent for
the Razorpay AI Buildathon). It has essentially no frontend surface:

| you might expect | what actually exists here |
|---|---|
| React / Vue / Svelte | **none** — no `package.json`, no `node_modules`, no JS/TS files at all |
| a component library | **none** — 4 hand-written Jinja2 templates |
| design tokens (Style Dictionary, Tailwind config, `tokens.json`) | **none** — ~12 CSS custom properties in one 94-line file |
| a build system / bundler | **none** — templates are served as-is by FastAPI; CSS is a static file |
| Storybook / component docs | **none** |
| an icon system | **none** — the UI uses zero icons on purpose |
| CSS Modules / styled-components / CSS-in-JS | **none** — one global stylesheet |

The **only** UI is a deliberately minimal, server-rendered *operator console*
(`src/mandatemend/console/`). Its look is governed by `CLAUDE.md` §4, which explicitly
forbids the aesthetic most Figma comps bring:

> No purple/violet gradient backgrounds, no glassmorphism cards, no generic centered hero
> sections. No decorative emoji. Favor information density over whitespace-heavy "SaaS
> landing page" layouts. Color should be functional, not decorative … Avoid stock
> icon-library soup.

**Do not import a Figma design directly into this repo.** If a Figma frame is provided,
translate its *information* (what an operator needs to see and do next), not its styling.
A pixel-faithful port will violate `CLAUDE.md` §4 and should be rejected in review.

---

## 1. Token definitions

**Location:** `src/mandatemend/console/static/app.css`, `:root` block. That is the entire
token system — plain CSS custom properties, no transformation pipeline, no JSON source, no
dark mode.

```css
:root {
  --paper: #faf9f6;   /* page background            */
  --ink:   #1b1b1a;   /* body text                  */
  --muted: #6a6a66;   /* secondary text, captions   */
  --rule:  #d9d7cf;   /* hairline borders           */
  --accent:#1a4d7a;   /* links only                 */
  --ok:    #1f6f43;   /* state: recovered / pass    */
  --warn:  #8a5a00;   /* state: escalated / human   */
  --bad:   #a01b2b;   /* state: violation / blocked */
  --panel: #f2f1ec;   /* table hover, inset panels  */
}
```

**Rules if you add or map tokens from Figma:**
- Colour is **functional**. A new colour must encode a *state* (pass/fail, recovered/at-risk,
  compliant/violation), never a brand accent or decoration. If a Figma style doesn't map to
  a state, drop it.
- Keep the set tiny. If a mapping needs more than ~15 colours, the design is wrong for this
  tool — push back.
- No gradients, no shadows beyond a 1px `--rule` border, no border-radius above 2px
  (`.tag` uses `border-radius: 2px`; everything else is square).
- Typography is **two families, no scale system**: a serif for prose
  (`"Iowan Old Style", Georgia, serif`) and a monospace for every number, id, ledger row and
  rule-trace line (`"SF Mono", "JetBrains Mono", Menlo, Consolas, monospace`). Numeric cells
  use `font-variant-numeric: tabular-nums` and are right-aligned. Do not introduce a
  display face or a modular type scale.
- Spacing is ad-hoc (`padding: 4px 10px` on cells, `18px 22px` on `main`). There is no
  spacing token. Match the existing values; don't add a scale.

---

## 2. Component library

There is no component library and no component framework. "Components" are Jinja2 template
fragments and a handful of CSS classes. Inventory:

| pattern | class(es) | defined in | used for |
|---|---|---|---|
| page shell | `header`, `main`, `nav` | `templates/base.html` + css | every page |
| headline stat | `.headline .big` / `.sub`, `.lift-pos` / `.lift-neg` | `overview.html` | the recovered-₹ number and lift |
| KPI row | `.status-strip .cell b` / `span` | `overview.html` | recovered / escalated / retries / violations counters |
| data table | bare `table` / `th.num` / `td.num` | all pages | every list; numeric columns right-aligned, tabular figures |
| inline bar | `.bar` / `.bar.agent > span` | `overview.html` | agent-vs-baseline comparison |
| state chip | `.tag.ok` / `.tag.esc` / `.tag.bad` | `mandates.html`, `mandate.html` | recovered / human-queue / violation |
| rule-trace row | `.round` → `.hd` / `.trace .r.pass` / `.r.block` | `mandate.html` | per-round policy decision + why |
| filter strip | `.filters a` / `.filters a.on` | `mandates.html` | cause / outcome filters (plain links, no JS) |
| action button | `.btn` | `mandate.html` | "Download evidence pack" |
| audit block | `pre.audit` | `mandate.html` | hash-chained ledger dump |

```html
<!-- state chip — the canonical "component" here: three states, colour = meaning -->
{% if r.violations %}<span class="tag bad">violation</span>
{% elif r.resolution.recovered %}<span class="tag ok">recovered</span>
{% else %}<span class="tag esc">human queue</span>{% endif %}
```

```html
<!-- rule-trace row — every money decision shows its rule evaluations inline -->
<div class="r {{ 'pass' if rt.passed else 'block' }}">
  <span class="k">[{{ 'ok' if rt.passed else 'BLOCK' }}] {{ rt.rule }}</span>{{ rt.detail }}
</div>
```

**Rules:** new "components" are a template partial + one or two classes in `app.css`. No
per-component stylesheet, no JS behaviour, no client-side state. Every screen must answer
"what does the operator do next" — if a Figma component is purely decorative, don't build it.

---

## 3. Frameworks & libraries

| concern | choice | file |
|---|---|---|
| language | Python ≥ 3.11 | `pyproject.toml` |
| web server | **FastAPI** + Starlette | `src/mandatemend/console/app.py` |
| templating | **Jinja2** via `fastapi.templating.Jinja2Templates` | `console/app.py` |
| static files | `StarletteStaticFiles` mounted at `/static` | `console/app.py` |
| ASGI server | `uvicorn` | `mandatemend serve` → `cli.py` |
| CSS | one hand-written global stylesheet | `console/static/app.css` |
| JS | **none** | — |
| bundler / transpiler | **none** | — |
| ML / data (the actual project) | numpy, scikit-learn, SQLAlchemy, pydantic | `pyproject.toml` |

```python
# src/mandatemend/console/app.py — the whole rendering setup
templates = Jinja2Templates(directory=str(_HERE / "templates"))
templates.env.filters["rupees"] = lambda p: f"{(p or 0) / 100:,.0f}"
templates.env.filters["pct"]    = lambda x: f"{(x or 0) * 100:.1f}%"

app = FastAPI(title="MandateMend operator console")
app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

@app.get("/", response_class=HTMLResponse)
def overview(request: Request):
    v = service.view()
    return templates.TemplateResponse("overview.html", {"request": request, "v": v, "sc": v.scorecard})
```

**Rule:** do not add a frontend framework or a build step to render a Figma design. If a
design genuinely needs interactivity, first ask whether the operator task needs it at all;
if it does, a few lines of vanilla `<script>` in the template are the ceiling.

---

## 4. Asset management

There are **no image, video, or font assets** in the repo, and no CDN. The console ships
zero binary assets. Fonts are system stacks only (see §1). `.gitattributes` marks
`*.png`, `*.joblib`, `*.parquet` as `binary` for the day one is added, but none exist today.

**Rule:** if a Figma export produces raster assets, that is a signal the design is too
heavy for this tool. Prefer: no image at all → an inline `<div class="bar">` or a Unicode
glyph → last resort, a hand-authored inline `<svg>` checked into the template. Never a
sprite sheet, never an icon font, never a CDN link (`CLAUDE.md` also bars external
resources in the artifact context and the same discipline applies here).

---

## 5. Icon system

There is **no icon system, and that is intentional** (`CLAUDE.md` §4: "use icons sparingly
and only where they replace text, not next to every label" — the console currently uses
none). State is conveyed by the word plus a coloured border (`.tag`), not a glyph.

**Rule:** do not introduce `lucide`, `heroicons`, `@fortawesome`, an icon font, or an SVG
sprite. If a Figma frame is icon-dense, replace each icon with its label. If an icon truly
replaces text (e.g. a sort caret), inline a single `<svg>` (≤ 1 KB, `currentColor`,
`aria-hidden="true"`) directly in the template that uses it. No shared icon module.

---

## 6. Styling approach

- **Methodology:** one global stylesheet, plain class selectors (loosely BEM-ish:
  `.round > .hd`, `.trace .r.block`). No CSS Modules, no CSS-in-JS, no utility framework.
- **Global styles:** `app.css` sets `box-sizing: border-box`, body font/colour, and a
  `header` / `main` layout. Everything is global; there is no scoping mechanism.
- **Responsive:** minimal. `<meta name="viewport">` is set in `base.html`; `main` is
  `max-width: 1100px`. There are **no media queries** — the layout is a single dense column
  of tables that reflow naturally. Tables are not horizontally scroll-wrapped yet; if a
  Figma design adds wide content, wrap it in `overflow-x: auto` rather than adding
  breakpoints.
- **State styling pattern** (the one to follow):

```css
.tag       { font-size: 11px; padding: 1px 6px; border: 1px solid currentColor; border-radius: 2px; }
.tag.ok    { color: var(--ok);   }
.tag.esc   { color: var(--warn); }
.tag.bad   { color: var(--bad);  }
/* colour is set once on the element; border + text both inherit via currentColor */
```

**Rules:** keep all styling in `app.css`. Reuse the existing tokens and classes before
adding any. New rules should be a handful of lines. No `!important`, no deep nesting, no
animations/transitions (the tool is read-often, not demoed).

---

## 7. Project structure

```
src/mandatemend/
  schemas.py            typed contract shared by every layer (pydantic; money = int paise)
  config.py             env-driven settings (pydantic-settings)
  simulation.py         shared constants for the synthetic potential-outcomes model
  features.py           feature extraction for the ML models
  agent.py              the bounded per-mandate recovery loop
  invariants.py         independent compliance re-verification (outside the policy engine)
  cli.py                `mandatemend` entrypoint (gen-data / train / score / demo / serve / verify-audit)
  diagnosis/            sanitize.py · heuristic_diagnoser.py · llm_diagnoser.py · base.py (factory)
  models/               retry_timing.py (survival) · uplift.py (T-learner) · advisors.py · train.py · artifacts/
  policy/               rules.py (unit-tested predicates) · engine.py (sole Action authority)
  executor/             gateway.py (Simulated / RazorpayTest) · executor.py (idempotent, DB-UNIQUE)
  audit/ledger.py       append-only hash-chained ledger
  db/                   models.py (SQLAlchemy) · session.py
  batch/                baselines.py · run_batch.py (scorecard)
  console/              <-- the ONLY frontend
    app.py              FastAPI routes + Jinja setup + template filters
    service.py          runs one batch on startup, caches rows/scorecard/audit in memory
    templates/          base.html · overview.html · mandates.html · mandate.html
    static/app.css      the entire stylesheet
data/                   generator.py + FROZEN held-out batch (read-only, pinned -text)
tests/                  unit/ · integration/ · e2e/
docs/                   RESEARCH.md · FIGMA_INTEGRATION.md (this file)
logs/iterations.jsonl   append-only scorecard history
```

**Feature-organisation pattern:** by *pipeline stage* (diagnosis → models → policy →
executor → audit), not by UI feature. The console is a thin read-only view over
`console/service.py`, which itself just calls `batch/run_batch.py`. There is no routing
library, no state management, no feature-flag system.

---

## If you must bring a Figma frame in

1. Extract the **content model** only: which fields, which table columns, which
   next-actions. Ignore colours, spacing, shadows, imagery, icons.
2. Add one Jinja partial under `console/templates/` and, if unavoidable, ≤ ~10 lines in
   `app.css` reusing the existing `:root` tokens.
3. Numbers → monospace, right-aligned, `tabular-nums`. State → a `.tag` in `--ok` /
   `--warn` / `--bad`. Every view ends with "what does the operator do next".
4. Run `mandatemend serve` and eyeball it against `CLAUDE.md` §4. If it reads as a
   marketing page, a dashboard-for-its-own-sake, or "AI-generated UI", it is wrong.
5. There is no Storybook and no visual-regression setup — verification is `mandatemend
   serve` plus the existing `pytest` (which does not cover the console).
