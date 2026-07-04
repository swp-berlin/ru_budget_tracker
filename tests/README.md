# Test suite

Characterization tests for the data-import pipeline: they pin **current** behavior
(validated against official sources on 2026-07-03, see `.claude/learnings.md`) so
that any refactor which changes behavior fails loudly and deliberately. A failure
means either a regression, or an intentional change — in which case regenerate the
affected fixtures **in a commit whose message explains why the numbers changed**.

## Tiers

| Marker | What | Needs | Speed |
|---|---|---|---|
| *(none)* | Pure parser functions, synthetic inputs | nothing | < 1 s |
| `db` | Assertions against the checked-in `src/data/budget.db` | the DB | seconds |
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

```bash
git show <rev>:src/data/budget.db > /tmp/prior.db
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
