# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Setup:**
```bash
uv sync
```

**Run dev server:**
```bash
cd src && uv run python app.py   # http://localhost:8050
```

**Docker (production-like, HTTPS on :8443):**
```bash
docker compose up --build
```

**Database migrations:**
```bash
make alembic-upgrade                              # apply migrations
make alembic-revision m="description" rev-id="0001"  # create migration
make alembic-downgrade                            # rollback latest
```

**Data import (run in order after migrations):**
```bash
make import-fix
make import-budget [years="2023 2024"]
make import-totals totals=<path>
make import-gdp
make import-ppp
make import-translations
```

**Tests** (see `docs/tests.md` for tiers, fixtures, and the data-blessing workflow):
```bash
make test-fast       # unit + DB tiers, seconds — run on every change
make test            # + golden/e2e tiers (~10 min) — run before/after touching the importer
make quality-report  # data-quality report → src/data/quality/report.md (tracked)
```

Fixtures (goldens, frozen totals) protect **blessed** data; new files show up as skips
and in the quality report until blessed deliberately (`make test-regen-goldens`,
`make test-regen-frozen`) in a commit whose message explains why the numbers changed.
Deep data documentation for AI sessions: `.claude/data-guide.md`.

**Lint / format / typecheck:**
```bash
uvx ruff check src/
uvx ruff format src/
uvx ty check
```

Pre-commit hooks (Ruff, ty, betterleaks) run automatically on commit.

## Architecture

This is a Dash (Plotly) multi-page dashboard for analyzing Russian government budgets. The app entry point is `src/app.py`; pages live in `src/pages/` (`treemap.py`, `timeseries.py`, `about.py`).

**Layer overview:**

| Layer | Location | Role |
|---|---|---|
| UI / callbacks | `src/pages/`, `src/layout.py`, `src/callbacks/` | Dash components and callback wiring |
| UI assets | `src/assets/` | Static CSS/fonts/icons auto-served by Dash; chart colors live separately in `src/utils/definitions.py` — see `docs/customization.md` |
| Data fetching | `src/utils/fetch_*.py` | Queries DB, warms cache on startup |
| Data transformation | `src/utils/transform_*.py`, `src/utils/calculate.py` | Shapes data for charts, unit conversions |
| Database | `src/database/`, `src/models/` | SQLAlchemy + SQLite, Alembic migrations |
| ETL / import | `src/scripts/` | Parses Excel/CSV, calls DeepL for translations |
| Config | `src/settings.py` | Pydantic settings, reads from env vars |

**Database:** SQLite with WAL mode and memory-mapped I/O pragmas. Core writable tables are `Budget`, `Dimension`, `Expense`, `ConversionRate`. Heavy read queries are backed by pre-computed SQL views (`LawClassifiedSpendingPerChapter`, `ReportClassifiedSpendingPerChapter`, etc.) — these are read-only SQLAlchemy models and should not be written to directly.

**Routing:** App URL base pathname is configured via `settings.py`. All Dash callback pathname guards must use `get_relative_path()` (from `dash`) — never hardcode strings like `"/timeseries"`. See `src/pages/` for examples.

**Caching:** Treemap and timeseries data is pre-warmed into an in-process cache on app startup (see `src/utils/fetch_*.py`). Cache population is triggered once at boot; keep cache keys stable when refactoring fetch functions.

**Translations:** Dimension names are translated via the DeepL API (`src/scripts/translations.py`). Requires `IMPORTER__DEEPL_API_KEY` in environment.

## Documentation Map

Check the relevant doc below before grepping the codebase cold — each covers one area in depth so you don't have to reconstruct it from source.

| Need to know about... | Read |
|---|---|
| Setup, folder structure, deployment overview | `README.md` |
| Operational handover notes (DB backup, deploy status, caching gotchas) | `HANDOVER.md` |
| Changing colors, fonts, toolbar layout | `docs/customization.md` |
| Callbacks architecture | `docs/callbacks.md` |
| Database schema / SQLAlchemy models | `docs/models.md`, `docs/database.md` |
| Data import pipeline, source file formats | `docs/data.md`, `docs/data-import-files.md`, `docs/scripts.md` |
| Migrations | `docs/alembic.md` |
| Static assets (CSS/icons) | `docs/assets.md`, `docs/assets-icons.md` |
| Adding a new page | `docs/adding-a-page.md` |
| Test tiers & blessed-data workflow | `docs/tests.md` |
| Standalone importer component | `docs/importer.md` |
| Deep data semantics for AI sessions | `.claude/data-guide.md` |

## Guidelines

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.
