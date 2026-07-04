"""Characterization unit tests for scripts.parsers.totals_parser.

Synthetic pandas inputs, no data files. Pins comma-decimal parsing, the billions
multiplier, silent non-numeric swallowing, and the functional/RZ chapter maps.
"""

import datetime as dt

import pandas as pd
import pytest

from scripts.parsers import totals_parser as tp


# =============================================================================
# parse_budget_value
# =============================================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2757480200,00", 2757480200.0),  # comma decimal separator
        ("123.45", 123.45),
        (100, 100.0),
    ],
)
def test_parse_budget_value(raw: object, expected: float) -> None:
    assert tp.parse_budget_value(raw) == expected


@pytest.mark.parametrize("raw", [float("nan"), None])
def test_parse_budget_value_missing_becomes_zero_current_behavior(raw: object) -> None:
    # characterization: a missing value parses to 0.0, not None — totals_parser.py:321-322
    assert tp.parse_budget_value(raw) == 0.0


# =============================================================================
# parse_cell_value_billions
# =============================================================================


def test_parse_cell_value_billions_multiplies() -> None:
    df = pd.DataFrame([[None, None, "12.5"]])
    assert tp.parse_cell_value_billions(df, 0, 2) == 12_500_000_000.0


def test_parse_cell_value_billions_non_numeric_raises() -> None:
    # Fail-loud (Phase B, 2026-07-04): a non-numeric totals cell means the sheet
    # layout shifted — it now raises instead of silently dropping the value.
    df = pd.DataFrame([[None, None, "bad"]])
    with pytest.raises(tp.ParseError, match="not numeric"):
        tp.parse_cell_value_billions(df, 0, 2)


def test_parse_cell_value_billions_whitespace_only_is_empty() -> None:
    # Whitespace-only cells occur in real files (total_report_2026.xlsx row 22)
    # and mean "no value", same as an empty cell.
    df = pd.DataFrame([[None, None, " "]])
    assert tp.parse_cell_value_billions(df, 0, 2) is None


def test_parse_cell_value_billions_missing_becomes_none() -> None:
    df = pd.DataFrame([[None, None, None]])
    assert tp.parse_cell_value_billions(df, 0, 2) is None


# =============================================================================
# parse_column_dates
# =============================================================================


def test_parse_column_dates_text_and_datetime() -> None:
    # Header lives on row index 2; columns are scanned from index 2 onward.
    df = pd.DataFrame(
        [
            ["r0c0", "r0c1", "r0c2", "r0c3"],
            ["r1c0", "r1c1", "r1c2", "r1c3"],
            ["ind", "code", "янв.18", dt.datetime(2019, 3, 1)],
        ]
    )
    assert tp.parse_column_dates(df) == {
        2: dt.date(2018, 1, 1),  # "янв.18" ⇒ Jan 2018 (2000 + 18)
        3: dt.date(2019, 3, 1),  # a real datetime is taken as its date
    }


# =============================================================================
# FUNCTIONAL_TO_CHAPTER / RZ_TO_CHAPTER
# =============================================================================


def test_functional_to_chapter_has_14_entries() -> None:
    assert len(tp.FUNCTIONAL_TO_CHAPTER) == 14
    assert tp.FUNCTIONAL_TO_CHAPTER["2.1."] == "01"
    assert tp.FUNCTIONAL_TO_CHAPTER["2.14."] == "14"


def test_rz_to_chapter_has_14_entries() -> None:
    assert len(tp.RZ_TO_CHAPTER) == 14
    assert tp.RZ_TO_CHAPTER[1] == "01"
    assert tp.RZ_TO_CHAPTER[14] == "14"
    # keys are ints 1..14; chapter codes are zero-padded strings
    assert set(tp.RZ_TO_CHAPTER) == set(range(1, 15))
