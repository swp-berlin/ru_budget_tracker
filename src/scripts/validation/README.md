# Cross-validation diagnostics

Standalone scripts that compare imported budgets in `src/data/budget.db` against the
independent third-party parses in `src/data/validation/` (see the README there for
the origin of the CSVs and their column semantics).

```bash
uv run python src/scripts/validation/compare_fedbud.py   # REPORT-2026-03 vs Fedbud.csv
uv run python src/scripts/validation/compare_fedlaw.py   # LAW-2025 vs Fedlaw.csv
```

Each exits 0 when the parsers agree and 1 on discrepancies, and prints the top
differing keys — which is the point of keeping them: they are for *investigating*
a mismatch, not for gating CI.

The asserting versions of these checks live in the test suite as
`tests/test_crossvalidation_external.py` (`pytest -m external`); the equivalent
check of every report file against its own printed grand total is
`tests/test_official_totals.py`. Run those to find out *whether* something is
wrong; run these scripts to find out *what*.
