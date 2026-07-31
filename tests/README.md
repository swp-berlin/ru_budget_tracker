# Test suite

Characterization tests for the data-import pipeline: they pin **blessed** behavior
(validated against official sources) so that any change
to it fails loudly and deliberately. A failure on a blessed item means either a
regression, or an intentional change — in which case regenerate the affected
fixtures **in a commit whose message explains why the numbers changed**.

## Blessed vs unblessed data

Two kinds of checks, treated differently:

- **Source-anchored checks** apply to ALL data immediately, no blessing needed:
  the import itself fails on layout drift, unparseable values, and printed-total
  deviations ≥ 0.1% (deviations between 1 ₽ and 0.1% import fine but appear as
  WARNINGs in the quality report); `test_official_totals.py` validates every
  report file on disk against its own printed total.
- **Characterization fixtures** (goldens, frozen budget totals) protect blessed
  data only. New files/budgets without fixtures show up as pytest **skips** and
  in the quality report's `unblessed_items` — never as failures. A blessed item
  disappearing or changing IS a failure.

## Adding new data (standard workflow)

```bash
# 1. new file(s) into src/data/import_files/raw/..., then full rebuild:
make download-and-bootstrap-data     # or bootstrap-data — always a full rebuild
# (import fails loudly on real errors in new files; quality report runs at the end)

# 2. tests: blessed data must be green; new items appear as skips
make test

# 3. when you have time: read src/data/quality/report.md, then bless
uv run --group dev python tests/generate_goldens.py --only report_2027_06
make test-regen-frozen

# 4. rerun, review diffs, commit data + fixtures + report together
make test
git diff tests/fixtures/frozen_budget_totals.json src/data/quality/
```

## Interpreting outcomes

| Signal | Meaning | What to do |
|---|---|---|
| Import exits 1 with `ParseError` (layout / marker row / unparseable value) | The new file violates a structural assumption | Inspect the named file/row; either the file is broken or the format changed — adapt deliberately |
| Import exits 1: "N ERROR-severity data issue(s) … data was written" | e.g. unresolved dimension parents, printed total off by ≥ 0.1% | Read `src/data/quality/issues/<file>.json`; data is in the DB but do not bless until understood |
| `make test`: skips like "no golden for X — unblessed" | New data awaiting blessing | Expected; bless when the quality report looks good |
| `make test`: a BLESSED golden/fixture fails | Regression — parser, dependency, or data changed under you | Investigate before touching fixtures; `generate_goldens.py --dump-rows <stem>` diffs row level |
| Quality report WARNINGs (`law_detail_exceeds_total`, printed-total 1₽–0.1%, `unblessed_items`) | Source inconsistencies or pending blessings; import is fine | Review when convenient; documented in `.claude/findings-2026-07.md` |
| Quality report exit 1 (ERROR findings) | Structural DB problem (undimensioned LAW/REPORT expenses, dangling links) | Should never happen after a clean import — investigate immediately |

Background reading for a new contributor (or AI session): `.claude/data-guide.md` — the
data model, units, file quirks, and validation anchors in one place.

## Tiers

| Marker | What | Needs | Speed |
|---|---|---|---|
| *(none)* | Pure parser functions, synthetic inputs | nothing | < 1 s |
| `db` | Assertions against the locally built `src/data/budget.db` | the DB (not in git; skipped if absent) | seconds |
| `golden` | Parse all real law/report/totals files, compare to `tests/goldens/*.json` | data files | ~6 min |
| `e2e` | Real import of one report into a temporary DB | data files + alembic | ~1 min |
| `external` | Cross-validation vs third-party CSVs in `.claude/validation/` | untracked CSVs | skipped if absent |

## Running

```bash
make test-fast    # unit + db tiers, seconds — run on every change
make test         # everything except external, ~10 min — run before/after a refactor
uv run --group dev pytest -m golden -k report_2024_03   # one golden file
```

## Fixtures and how to regenerate them (deliberately!)

| Fixture | Pins | Regenerate with |
|---|---|---|
| `tests/goldens/*.json` | Parser output per data file (counts, sums, row hash) | `make test-regen-goldens` |
| `tests/fixtures/frozen_budget_totals.json` | Expense count + total for all 251 budgets in the DB | `make test-regen-frozen` |
| `src/scripts/fixtures/frozen_db_values.json` | 7 hand-picked dimension-join SQL checks | edit by hand |

When only a golden's `rows_sha256` differs (aggregates match but rows changed):

```bash
uv run --group dev python tests/generate_goldens.py --dump-rows report_2024_03
# dumps tests/goldens/.rowdumps/report_2024_03.txt (gitignored) from the current
# code; dump again on the old code (git stash / checkout) and diff the two files.
```

## Comparing against a prior database version

`budget.db` is not in git, so keep a copy of the old one *before* rebuilding:

```bash
cp src/data/budget.db /tmp/prior.db     # before `make download-and-bootstrap-data`
make test-compare-db prior=/tmp/prior.db
```

Reports per-budget expense count/total and per-chapter sum differences, exit 1 if any.

## Notes

- `tests/conftest.py` sets dummy `DEEPL_API_KEY` / `NEXTCLOUD_DOWNLOAD_LINK` env
  vars — importing `scripts.import` requires them (pydantic settings validate at
  import time); no test performs downloads or translations.
- Tests marked `# characterization: ...` pin a known quirk of the current code
  (e.g. silent value swallowing). If your refactor fixes the quirk on purpose,
  update the test and say so in the commit — the comment tells you where the
  quirk lives.
- Not covered (yet): `ppp_parser` (needs network), `gdp_parser` golden files
  (can be added with the same pattern), `translations.py` / `rename_dimensions.py`.
