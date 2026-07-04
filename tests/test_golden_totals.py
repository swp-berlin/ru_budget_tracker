"""Golden characterization tests for the totals parser (xlsx report + csv law)."""

import json
from pathlib import Path

import pytest

from scripts.parsers import parse_totals_file

from tests.conftest import GOLDENS_DIR
from tests.golden_utils import TOTALS_FILES, golden_name, summarize_totals_parse

pytestmark = pytest.mark.golden


@pytest.mark.parametrize("source", TOTALS_FILES, ids=lambda p: p.stem)
def test_totals_parse_matches_golden(source: Path) -> None:
    golden_path = GOLDENS_DIR / golden_name(source)
    if not golden_path.exists():
        pytest.skip(f"no golden for {source.name} — unblessed, see quality report")
    with golden_path.open(encoding="utf-8") as f:
        golden = json.load(f)

    budgets, chapter_codes, expenses = parse_totals_file(source)
    summary = summarize_totals_parse(budgets, chapter_codes, expenses, source)

    for field in ["source_file", "budget_identifiers", "chapter_codes", "expense_count"]:
        assert summary[field] == golden[field], f"{source.stem}: {field} diverged from golden"

    # Compare per budget so a failure names the month/year that diverged.
    assert summary["values_by_budget"].keys() == golden["values_by_budget"].keys()
    for budget_identifier, values in golden["values_by_budget"].items():
        assert summary["values_by_budget"][budget_identifier] == values, (
            f"{source.stem}: values for {budget_identifier} diverged from golden"
        )
