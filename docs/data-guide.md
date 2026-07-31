# Data guide

**Everything a new contributor needs to know about this project's data: the data model,
units, file quirks, and validation anchors in one place. Written 2026-07-04, after the
test-hardening and import-refactor work. Companions: `tests/README.md` (test tiers and the
blessing workflow), `src/data/quality/report.md` (the current, generated state of the data),
`src/data/validation/` (external cross-check data).**

## What this project is

A Dash dashboard analyzing Russian federal budgets, with a central research interest in
**classified (secret) spending**, computed as: `official totals − sum of published detail`.
That subtraction is why the pipeline imports both detailed budget structures AND separate
official totals from independent sources — the *gap between them is the product*, so data
quality on both sides is everything.

## The five data sources

| Source | Files | Unit in file | Stored in DB | Notes |
|---|---|---|---|---|
| Budget laws (ved structure, budget.gov.ru, "приложение" of the law) | `clean/laws/law_YYYY.xlsx` | thousands ₽ | ₽ (×1000 at parse) | one per year, 2018–2026 |
| Execution reports (roskazna.gov.ru, quarterly) | `clean/reports/report_YYYY_MM.xls(x)` | ₽ with kopecks | ₽ as-is | 33 files; sheet **"2.1"** = ведомственная структура; column 8 = «Исполнено» |
| Report totals (MinFin monthly brief) | `raw/totals/total_report_YYYY.xlsx` | billions ₽ | ₽ (×1e9 at parse) | sheet **"месяц"**; chapter breakdown ONLY until 2021, later extrapolated by the app |
| Law totals (hand-transcribed from bgd PDF reports) | `raw/totals/total_law_YYYY.csv` | thousands ₽ | **raw thousands** (!) | the app multiplies ×1000 via `budget_config.law_total_value_multiplier` (src/utils/definitions.py); a view migration would be needed to change this |
| GDP (Rosstat quarterly + Minekonom forecast) / PPP (World Bank API) | `raw/conversion_tables/` | — | conversion_rates table | 81 gdp + 38 ppp rows |

Independent third-party parses for cross-validation live in `src/data/validation/`
(`Fedbud.csv` = report 2026-03, `Fedlaw.csv` = law 2025; ~20 MB, tracked so that
`pytest -m external` is reproducible).

## The row hierarchy (the single most important concept)

Law and report files are ONE flat sheet encoding a hierarchy. Every row carries a subset of
codes: Мин (ministry/ГРБС) → Рз (chapter) → ПР (subchapter) → ЦСР (program) → ВР (expense type).

```
Министерство финансов          092  —     —          —     10 218 467 809 067,68   ← ministry header (subtotal)
Общегосударственные вопросы    092  0100  —          —     284 087 407 018.22      ← chapter header (subtotal)
<program>                      092  0106  ЦСР        —     …                       ← program header (subtotal)
<expense>                      092  0106  ЦСР        244   1 234 567.89            ← LEAF → becomes an Expense
```

**Only leaf rows (detailed ВР code + value) become expenses.** Every header row's value
column is a printed roll-up of the leaves beneath it — importing both would double-count.
In report_2025_12: 7,430 leaves vs 4,513 header rows vs 4,014 aggregate-ВР rows (all
accounted per file in `src/data/quality/issues/*.json`, code `row_accounting`).

### ВР (expense type) levels — the historic double-counting bug

Report files carry spending at TWO ВР levels: aggregate `x00` codes (100, 200 … 800) and
detailed codes (121, 244, 612 …). From mid-2019, `x00` rows additionally repeat at multiple
ЦСР hierarchy levels, so summing aggregates double-counted up to **+643bn ₽** (22 of 33
files). Since 2026-07-03 the report parser keeps ONLY detailed rows; after that, all 33
files match their own printed grand total **to the cent**. LAW files carry ONLY `x00`
codes (verified — no detail level exists there), so law and report EXPENSE_TYPE dimensions
are at different granularity; ВР-level comparisons across the two don't align.

### Program hierarchy and codes

- ЦСР codes are 10 chars, structure 2+1+2+5; trailing all-zero segments are stripped
  (`parse_program_code`). Codes may contain Cyrillic/Latin lookalikes (В vs V) — never
  normalize them away.
- Program parent links are longest-prefix string matches. The law and report variants
  deliberately differ (law accepts 1-char prefixes, report requires ≥2) — pinned by tests,
  documented in the code; unifying would change all law goldens.
- PROGRAM dimensions for leaves get identifier `"{ЦСР}-{ВР}"`.

## File quirks (all verified, all handled)

- **Excel's 15-significant-digit limit**: any cell ≥ 10T ₽ with kopecks (16 digits) cannot
  be stored as an Excel number — the Treasury export writes it as TEXT
  (`'10 218 467 809 067,68'`, NBSP separators, comma decimal). Affects: grand-total rows
  in ALL report files (30–40T; the printed-total check uses a ru-number parser), and the
  Минфин ministry-header subtotal in year-end files 2024-12/2025-12 (only ГРБС above 10T).
  Both subtotals verified equal to the imported leaf sums to the kopeck. Expect more as
  budgets grow; harmless (recorded as INFO).
- **Leading all-empty column** in some report files: dropped before parsing; pandas LABELS
  keep original indices after dropna — always use `iloc` (the parser does).
- **Multi-line names** in law files: code-less rows continue neighbouring rows' names via
  two heuristics (previous expense row's name not ending `)`; continuation ending `"`) —
  named predicates in helpers.py.
- **law_2020** titles chapter 13 with parentheses where other years use «и» —
  `CHAPTER_NAME_REPLACEMENTS` remaps it, else the chapter splits into two dimensions.
- **Law printed «ВСЕГО» ≠ ved-structure leaf sum** (~445M ₽ / 0.0015% in law_2025) — a
  property of the source files (confirmed by independent parse), NOT a parser bug. Hence
  no printed-total hard check for laws (reports only).
- **Whitespace-only cells** in monthly totals = months not yet reported = legitimately
  empty.
- **TOTAL-* budget shape**: each totals budget = 1 undimensioned grand-total expense
  (+ 14 chapter-linked expenses where breakdown exists). Hence the by-design baseline of
  209 zero-dim / 798 one-dim expenses — NOT a bug.

## Pipeline architecture (post-refactor, branch refactor/import-pipeline)

```
src/scripts/
  import.py          CLI + orchestration; writes per-file issue JSON to <db>/quality/issues/
  db_writer.py       all DB writes (upserts); INSERT-ONLY for expenses ⇒ incremental
                     re-import DUPLICATES — full `make bootstrap-data` rebuild is the
                     standard workflow (deliberate design decision, do not "fix")
  quality_report.py  make quality-report → src/data/quality/report.{md,json} (TRACKED in
                     git, deterministic, no timestamps; exit 1 only on ERROR findings)
  parsers/issues.py  ParseIssue / IssueCollector / ParseError — the one issue concept
  parsers/*.py       law, report, totals, gdp, ppp parsers
```

Fail-loud rules (imports abort with file/row context): report header layout drift
(positional columns verified against expected Cyrillic header substrings), missing
column-number marker row, unparseable values on rows whose value is USED (expense leaves,
totals cells, CSV years — informational text on header rows is exempt and recorded INFO),
printed-total deviation ≥ 0.1% (1 ₽ … 0.1% = WARNING, import succeeds), ERROR-severity
issues (e.g. unresolved dimension parents) fail the run AFTER data + issue files are
written.

## Testing & blessing (see tests/README.md for the operator workflow)

Two-tier philosophy:
- **Source-anchored checks** apply to ALL data immediately (import-time checks above;
  `test_official_totals.py` per report file; cross-source detail-vs-totals in the quality
  report). A broken new file fails on day one, no fixtures needed.
- **Characterization fixtures** (44 goldens in tests/goldens/, frozen per-budget totals,
  frozen_db_values, conversion-rates hash) protect BLESSED data only. Unfixtured new
  items = pytest skips + `unblessed_items` in the quality report; a blessed item
  disappearing/changing = hard failure. Bless deliberately after reading the report:
  `tests/generate_goldens.py --only <stem>` + `make test-regen-frozen`, commit with
  explanation.

Validation anchors and what they prove (as of 2026-07-04, all green):
printed totals (33/33 to the cent), Fedbud row-level (4,979 keys exact), Fedlaw row-level
(3,156 keys exact), report-vs-monthly-totals cross-source (224 chapter-months clean),
full differential re-import (compare_dbs: 251 budgets, 1,386 chapter sums identical).

## Open data issues

The one substantive open item: **law chapter-years where the ved-structure detail exceeds
the PDF-transcribed chapter total** (up to ~+105bn ₽) → negative classified spending in the
app for those cells. They surface as the `law_detail_exceeds_total` WARNING; the current
list, per year and chapter, is in `src/data/quality/report.md`.

The parser is exonerated (LAW-2025 matches the independent Fedlaw parse on all 3,156 keys),
so the discrepancy is on the totals side. The affected cells cluster in **2018 and 2021**
— the largest being 2018 chapter 14 (+24.7bn) and 2021 chapter 14 Межбюджетные трансферты
(+105bn). Two candidate causes, both needing a human pass over the source PDFs in
`raw/totals/pdf_source_law_totals`: a transcription slip in the hand-made
`total_law_*.csv`, or a genuine edition mismatch (the ved-structure xlsx being the *amended*
law while the PDF appendix is the *original enacted* one — 2021 amendments were large).
