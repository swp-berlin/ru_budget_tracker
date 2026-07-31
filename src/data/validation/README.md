# External cross-validation data

Independent third-party parses of two of our source files, provided 2026-07-03.
Both were produced from the same Excel files we import, by another person using a
different parser — so agreement between these CSVs and `budget.db` is evidence
that our importer reads the sources correctly.

| File | Parsed from | Values |
|---|---|---|
| `Fedbud.csv` | `import_files/clean/reports/report_2026_03.xlsx` | ₽ with kopecks (`Executed` column) |
| `Fedlaw.csv` | `import_files/clean/laws/law_2025.xlsx` | thousands ₽ (`Budget*` columns) |

## Column semantics

- **`Source`** — which section of the file the row came from:
  `1` = ведомственная структура (the section our importer reads),
  `2` = breakdown by раздел/подраздел, `3` = breakdown by госпрограмма.
  Only `Source=1` rows are comparable to our data; the others are alternative
  views of the same money and would double-count if mixed in.
- **`Agency` / `RZPR` / `ZSR` / `VR`** — ГРБС, раздел+подраздел, ЦСР, вид расходов.
  Comparison key is `(Agency, RZPR, ЦСР-stripped, VR)`.
- **`Executed`** (Fedbud) — исполнено, in ₽.
- **`Budget` / `Budget2` / `Budget3`** (Fedlaw) — planning years 2025 / 2026 / 2027,
  in **thousands ₽** (multiply by 1000 to compare). Our importer stores only the
  first planning year, so rows with an empty `Budget` (funded only in 2026/2027)
  are legitimately absent from the database.

## Used by

- `pytest -m external` (`tests/test_crossvalidation_external.py`) — asserting version,
  needs a built `src/data/budget.db`.
- `src/scripts/validation/compare_fedbud.py` / `compare_fedlaw.py` — diagnostic
  versions that print per-key differences.

Results as of 2026-07-03: report — 4,979 keys, zero mismatches, identical total;
law — all 3,156 database keys match with zero mismatches (108 keys exist only in
the CSV because they are funded only in the later planning years).
