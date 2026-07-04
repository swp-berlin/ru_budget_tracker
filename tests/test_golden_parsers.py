"""Golden characterization tests: parse every real law/report file, compare to goldens.

Each golden in tests/goldens/ pins what the parser produced when the output was
last validated against official sources (see .claude/learnings.md). Any diff means
parser behavior changed: either a regression, or a deliberate change — in which
case regenerate via `make test-regen-goldens` and explain the change in the commit.
"""

import json
from pathlib import Path

import pytest

from scripts.parsers import parse_law_file, parse_report_file

from tests.conftest import GOLDENS_DIR
from tests.golden_utils import golden_name, law_files, report_files, summarize_parse

pytestmark = pytest.mark.golden

BUDGET_FILES = law_files() + report_files()

# Fields compared one by one so a failure names the field (and for the sum
# dictionaries, the specific ministry/chapter/expense-type) that diverged.
SUMMARY_FIELDS = [
    "source_file",
    "budget",
    "expense_count",
    "expense_total",
    "dimension_counts",
    "expense_dim_type_coverage",
    "sum_by_ministry",
    "sum_by_chapter",
    "sum_by_expense_type",
]


def load_golden(source: Path) -> dict:
    golden_path = GOLDENS_DIR / golden_name(source)
    if not golden_path.exists():
        # Unblessed file: imported data not yet frozen. Visible as a skip;
        # bless deliberately after reviewing the quality report:
        #   uv run --group dev python tests/generate_goldens.py --only <stem>
        pytest.skip(f"no golden for {source.name} — unblessed, see quality report")
    with golden_path.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("source", BUDGET_FILES, ids=lambda p: p.stem)
def test_parse_matches_golden(source: Path) -> None:
    golden = load_golden(source)
    parse = parse_law_file if source.stem.startswith("law") else parse_report_file
    budget, dimensions, expenses = parse(source)
    summary = summarize_parse(budget, dimensions, expenses, source)

    for field in SUMMARY_FIELDS:
        assert summary[field] == golden[field], f"{source.stem}: {field} diverged from golden"

    assert summary["rows_sha256"] == golden["rows_sha256"], (
        f"{source.stem}: aggregate fields match but the row set changed "
        f"(e.g. rows swapped values). To see which rows: "
        f"`uv run --group dev python tests/generate_goldens.py --dump-rows {source.stem}`, "
        f"then dump again on the old code and diff the two files in tests/goldens/.rowdumps/"
    )

    assert summary["dimensions_sha256"] == golden["dimensions_sha256"], (
        f"{source.stem}: expense rows match but the dimension set changed — "
        f"a parent link (program hierarchy) or a dimension name diverged"
    )


def test_every_golden_has_its_data_file() -> None:
    """One-directional: a blessed (goldened) file disappearing is a failure.

    Data files WITHOUT a golden are tolerated — they are unblessed new data,
    reported by the quality report and visible as skips above.
    """
    data_stems = {p.stem for p in BUDGET_FILES}
    golden_stems = {
        p.stem
        for p in GOLDENS_DIR.glob("*.json")
        if p.stem.startswith(("law_", "report_"))  # totals goldens are covered separately
    }
    assert golden_stems <= data_stems, (
        f"goldens whose data file disappeared: {sorted(golden_stems - data_stems)}"
    )
