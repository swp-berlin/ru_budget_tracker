"""Characterization unit tests for scripts.parsers.helpers.

Pure functions, synthetic pandas inputs, no data files or DB. Every pinned quirk
notes WHAT current behavior is captured and WHY, so a future refactorer can tell a
reintroduced bug from a deliberately-fixed quirk (then update the test).
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from models import Dimension
from scripts.parsers.issues import ParseError
from scripts.parsers.helpers import (
    MergedRow,
    clean_code_value,
    create_budget_from_metadata,
    deduplicate_dimensions,
    extract_budget_metadata_from_filename,
    extract_expense_type_name,
    find_header_row,
    get_column_mapping,
    merge_rows,
)

# Column mapping matching a full LAW header (name, ministry, chapter, subchapter,
# program, expense_type, value). value = expense_type + 1.
FULL_COLS = {
    "name": 0,
    "ministry": 1,
    "chapter": 2,
    "subchapter": 3,
    "program": 4,
    "expense_type": 5,
    "value": 6,
}

HEADER = ["Наименование", "Мин", "Рз", "ПР", "ЦСР", "ВР", "value"]


# =============================================================================
# extract_budget_metadata_from_filename
# =============================================================================


def test_metadata_law() -> None:
    assert extract_budget_metadata_from_filename(Path("law_2024.xlsx")) == {
        "original_identifier": "LAW-2024",
        "title": "Federal Budget Law",
        "year": 2024,
        "month": None,
        "type": "LAW",
        "scope": "YEARLY",
    }


def test_metadata_report_with_month() -> None:
    assert extract_budget_metadata_from_filename(Path("report_2024_03.xlsx")) == {
        "original_identifier": "REPORT-2024-03",
        "title": "Federal Budget Report",
        "year": 2024,
        "month": 3,
        "type": "REPORT",
        "scope": "QUARTERLY",
    }


def test_metadata_report_xls_extension() -> None:
    # .xls reports parse identically to .xlsx (extension is stripped by .stem).
    md = extract_budget_metadata_from_filename(Path("report_2023_03.xls"))
    assert md["original_identifier"] == "REPORT-2023-03"
    assert md["month"] == 3


def test_metadata_draft() -> None:
    md = extract_budget_metadata_from_filename(Path("draft_2024.xlsx"))
    assert md["type"] == "DRAFT"
    assert md["original_identifier"] == "DRAFT-2024"
    assert md["scope"] == "YEARLY"


def test_metadata_report_missing_month_current_behavior() -> None:
    # characterization: a report filename without a _MM segment yields month=None and a
    # month-less identifier rather than raising — helpers.py:72-81
    md = extract_budget_metadata_from_filename(Path("report_2024.xlsx"))
    assert md["month"] is None
    assert md["original_identifier"] == "REPORT-2024"


def test_metadata_type_is_case_insensitive() -> None:
    # filename is lowercased before prefix/year matching.
    md = extract_budget_metadata_from_filename(Path("LAW_2019.XLSX"))
    assert md["type"] == "LAW"
    assert md["year"] == 2019


def test_metadata_unknown_prefix_raises() -> None:
    with pytest.raises(ValueError, match="Unknown file type"):
        extract_budget_metadata_from_filename(Path("totals_2024.xlsx"))


def test_metadata_no_year_raises() -> None:
    with pytest.raises(ValueError, match="No year found"):
        extract_budget_metadata_from_filename(Path("law_abc.xlsx"))


# =============================================================================
# create_budget_from_metadata
# =============================================================================


def test_create_budget_report_month() -> None:
    md = extract_budget_metadata_from_filename(Path("report_2024_03.xlsx"))
    budget = create_budget_from_metadata(md)
    assert budget.published_at == date(2024, 3, 1)
    assert budget.description == "Federal Budget Report 2024-03"
    assert budget.type == "REPORT"


def test_create_budget_law_defaults_to_january() -> None:
    md = extract_budget_metadata_from_filename(Path("law_2024.xlsx"))
    budget = create_budget_from_metadata(md)
    assert budget.published_at == date(2024, 1, 1)
    assert budget.description == "Federal Budget Law 2024"
    assert budget.planned_at is None


# =============================================================================
# find_header_row
# =============================================================================


def test_find_header_row_min_variant() -> None:
    df = pd.DataFrame(
        [
            ["junk", None, None],
            ["Наименование", "Мин", "Рз"],
            ["data", "020", "01"],
        ]
    )
    assert find_header_row(df) == 1


def test_find_header_row_accepts_ukrainian_min_spelling() -> None:
    # header matches when it has "Наименование" and either "Мин" or "Мін".
    df = pd.DataFrame([["Наименование показателя", "Мін", "ВР"]])
    assert find_header_row(df) == 0


def test_find_header_row_raises_when_absent() -> None:
    with pytest.raises(ValueError, match="Could not find header row"):
        find_header_row(pd.DataFrame([["x", "y"], ["a", "b"]]))


# =============================================================================
# get_column_mapping
# =============================================================================


def test_get_column_mapping_full_header() -> None:
    mapping = get_column_mapping(pd.Series(HEADER))
    assert mapping == {
        "name": 0,
        "ministry": 1,
        "chapter": 2,
        "subchapter": 3,
        "program": 4,
        "expense_type": 5,
        "value": 6,
    }


def test_get_column_mapping_value_is_expense_type_plus_one() -> None:
    # value column is derived as expense_type index + 1, never read from the header.
    mapping = get_column_mapping(pd.Series([None, "Мин", float("nan"), "ВР"]))
    assert mapping["expense_type"] == 3
    assert mapping["value"] == 4


def test_get_column_mapping_without_vr_has_no_value_key() -> None:
    # characterization: no "ВР" column ⇒ no "value" key is added — helpers.py:150-151
    mapping = get_column_mapping(pd.Series(["Наименование", "Мін"]))
    assert mapping == {"name": 0, "ministry": 1}


# =============================================================================
# clean_code_value
# =============================================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        (float("nan"), None),
        (" 12 3 ", "123"),  # spaces stripped everywhere, not just edges
        ("nan", None),
        ("NaN", None),
        ("", None),
        ("  ", None),
        (100, "100"),
        (100.0, "100.0"),  # float codes keep their ".0" — characterization: helpers.py:161
        ("х", "х"),  # Cyrillic placeholder is passed through untouched
    ],
)
def test_clean_code_value(raw: object, expected: str | None) -> None:
    assert clean_code_value(raw) == expected


# =============================================================================
# merge_rows
# =============================================================================


def _merged_tuple(row: MergedRow) -> tuple:
    return (
        row.name,
        row.ministry_code,
        row.chapter_code,
        row.subchapter_code,
        row.program_code,
        row.expense_type_code,
        row.value,
    )


def test_merge_rows_multiplier_and_totals_skip() -> None:
    # First data row containing "всего" is skipped; value is multiplied.
    df = pd.DataFrame(
        [
            HEADER,
            ["ВСЕГО", None, None, None, None, None, 999],
            ["Ministry A", "020", None, None, None, None, None],
            ["Program X", "020", "01", "0102", "0110000000", "244", "5"],
        ]
    )
    rows = merge_rows(df, 0, FULL_COLS, multiplier=1000.0)
    assert [_merged_tuple(r) for r in rows] == [
        ("Ministry A", "020", None, None, None, None, None),
        ("Program X", "020", "01", "0102", "0110000000", "244", 5000.0),
    ]


def test_merge_rows_totals_skip_only_first_data_row() -> None:
    # characterization: the "всего" skip guard fires only for the FIRST data row; a later
    # row whose name contains "всего" is kept — helpers.py:194-197
    df = pd.DataFrame(
        [
            HEADER,
            ["First real", "020", "01", "0102", "0110000000", "244", "1"],
            ["ВСЕГО later", "030", "02", "0202", "0220000000", "244", "2"],
        ]
    )
    rows = merge_rows(df, 0, FULL_COLS)
    assert [r.name for r in rows] == ["First real", "ВСЕГО later"]


def test_merge_rows_accumulates_name_forward_when_no_codes() -> None:
    # code-less rows with no previous entry accumulate forward onto the next coded row.
    df = pd.DataFrame(
        [
            HEADER,
            ["Part one", None, None, None, None, None, None],
            ["Part two", None, None, None, None, None, None],
            ["Real", "020", None, None, None, None, None],
        ]
    )
    rows = merge_rows(df, 0, FULL_COLS)
    assert len(rows) == 1
    assert rows[0].name == "Part one Part two Real"


def test_merge_rows_appends_to_prev_when_prev_has_expense_type() -> None:
    # code-less continuation appends to previous row if that row has an expense_type
    # and its name does not already end with ")".
    df = pd.DataFrame(
        [
            HEADER,
            ["Expense name", "020", "01", "0102", "0110000000", "244", "5"],
            ["continuation", None, None, None, None, None, None],
        ]
    )
    rows = merge_rows(df, 0, FULL_COLS)
    assert len(rows) == 1
    assert rows[0].name == "Expense name continuation"


def test_merge_rows_appends_to_prev_when_name_ends_with_quote() -> None:
    # the other append rule: previous row lacks an expense_type and continuation ends '"'.
    df = pd.DataFrame(
        [
            HEADER,
            ["Ministry named", "020", None, None, None, None, None],
            ['tail"', None, None, None, None, None, None],
        ]
    )
    rows = merge_rows(df, 0, FULL_COLS)
    assert len(rows) == 1
    assert rows[0].name == 'Ministry named tail"'


def test_merge_rows_non_numeric_value_raises() -> None:
    # Fail-loud (Phase B, 2026-07-04): a value cell that can't be cast to float
    # used to be silently swallowed to None; it now raises ParseError. No such
    # cell exists in any real law file (verified via issue backfill).
    df = pd.DataFrame(
        [
            HEADER,
            ["Row", "020", "01", "0102", "0110000000", "244", "not-a-number"],
        ]
    )
    with pytest.raises(ParseError, match="not numeric"):
        merge_rows(df, 0, FULL_COLS)


# =============================================================================
# deduplicate_dimensions
# =============================================================================


def _dim(identifier: str, dim_type: str, name: str, parent_id: str | None = None) -> Dimension:
    return Dimension(
        original_identifier=identifier,
        type=dim_type,
        name=name,
        name_translated=None,
        parent_id=parent_id,
    )


def test_deduplicate_removes_exact_duplicates() -> None:
    dims = [
        _dim("01", "CHAPTER", "Name A"),
        _dim("01", "CHAPTER", "Name A"),
    ]
    assert len(deduplicate_dimensions(dims)) == 1


def test_deduplicate_keeps_both_names_for_same_identifier_current_behavior() -> None:
    # characterization: dedup key includes NAME, so two dims with same
    # (identifier, type, parent) but different names are BOTH kept (only a warning is
    # logged) — helpers.py:283-303
    dims = [
        _dim("01", "CHAPTER", "Name A"),
        _dim("01", "CHAPTER", "Name B"),
        _dim("01", "CHAPTER", "Name A"),  # exact dup of the first, dropped
    ]
    unique = deduplicate_dimensions(dims)
    assert len(unique) == 2
    assert [d.name for d in unique] == ["Name A", "Name B"]


# =============================================================================
# extract_expense_type_name
# =============================================================================


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Foo (bar)", "bar"),
        ("no parens", "no parens"),  # no ")" ⇒ full text returned
        ("a (x) b (y) c", "y"),  # last complete parenthesis pair wins
        ("outer (in (nested) here) tail", "in (nested) here"),  # balanced nesting
        ("trailing )", "trailing )"),  # ")" with no matching "(" ⇒ full text
    ],
)
def test_extract_expense_type_name(text: str, expected: str) -> None:
    assert extract_expense_type_name(text) == expected
