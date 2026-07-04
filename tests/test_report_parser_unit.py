"""Characterization unit tests for scripts.parsers.report_parser.

Synthetic pandas rows / hand-built classification matrices, no data files. Pinned
quirks (row-6 fallback, silent value swallowing, x00 aggregate rejection) are named
and commented so a future refactor fails loudly and legibly.
"""

import pandas as pd
import pytest

from models import Dimension
from scripts.parsers import report_parser as rp

# Column indices used by report rows (0-indexed), mirroring REPORT_COLUMNS.
NAME, MINISTRY, CHAPTER_FULL, PROGRAM, EXPENSE_TYPE, VALUE_EXECUTED = 0, 2, 3, 4, 5, 8


def _row(
    ministry: object = None,
    chapter_full: object = None,
    program: object = None,
    expense_type: object = None,
    value_executed: object = None,
    name: object = "Some name",
) -> pd.Series:
    """Build a report-shaped Series (9 columns) with fields at their real indices."""
    series = pd.Series([None] * 9)
    series.iloc[NAME] = name
    series.iloc[MINISTRY] = ministry
    series.iloc[CHAPTER_FULL] = chapter_full
    series.iloc[PROGRAM] = program
    series.iloc[EXPENSE_TYPE] = expense_type
    series.iloc[VALUE_EXECUTED] = value_executed
    return series


def _expense_type_row(expense_type: object) -> pd.Series:
    series = pd.Series([None] * 9)
    series.iloc[EXPENSE_TYPE] = expense_type
    return series


# =============================================================================
# parse_chapter_code
# =============================================================================


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("0100", ("01", None)),  # ends in "00" ⇒ chapter only
        ("0110", ("01", "0110")),  # subchapter
        ("01", ("01", None)),  # exactly 2 chars ⇒ no subchapter
        ("0", ("0", None)),  # shorter than 2 chars returned verbatim
        ("0000", ("00", None)),
        ("010203", ("01", "010203")),  # longer than 4 ⇒ full code is the subchapter
    ],
)
def test_parse_chapter_code(code: str, expected: tuple[str, str | None]) -> None:
    assert rp.parse_chapter_code(code) == expected


# =============================================================================
# parse_program_code
# =============================================================================


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("0100000000", "01"),  # docstring example
        ("0110000000", "011"),  # docstring example
        ("0110400000", "01104"),  # docstring example
        ("0110490000", "0110490000"),  # docstring example: nothing to strip
        ("0000000000", None),  # all-zero ⇒ None
    ],
)
def test_parse_program_code_docstring_examples(code: str, expected: str | None) -> None:
    assert rp.parse_program_code(code) == expected


def test_parse_program_code_none_and_empty() -> None:
    # characterization: callers pass raw cell values, so None must stay accepted
    # even though the annotation says str — report_parser.py:218
    assert rp.parse_program_code(None) is None  # ty: ignore[invalid-argument-type]
    assert rp.parse_program_code("") is None


@pytest.mark.parametrize("code", ["12345", "245-abc", "011049000A"])
def test_parse_program_code_non_10_char_passthrough_current_behavior(code: str) -> None:
    # characterization: the segment-stripping logic assumes a 10-char code; anything else
    # (including 10-char codes with a non-digit) is returned unchanged — report_parser.py:240-241
    assert rp.parse_program_code(code) == code


# =============================================================================
# is_valid_row / is_expense_row
# =============================================================================


@pytest.mark.parametrize(
    ("expense_type", "valid", "expense"),
    [
        (None, True, False),  # empty ET: valid dimension row, not an expense
        (float("nan"), True, False),
        (100, False, False),  # x00 aggregates rejected (would double-count)
        (200, False, False),
        (800, False, False),
        (121, True, True),  # detailed codes accepted
        (244, True, True),
        (612, True, True),
        ("244", True, True),  # numeric strings parse the same
        ("200", False, False),
        (0, False, False),  # zero rejected (et_val > 0 guard)
        (-100, False, False),
    ],
)
def test_is_valid_and_expense_row(expense_type: object, valid: bool, expense: bool) -> None:
    row = _expense_type_row(expense_type)
    assert rp.is_valid_row(row) is valid
    assert rp.is_expense_row(row) is expense


def test_non_numeric_expense_type_valid_but_not_expense_current_behavior() -> None:
    # characterization: a non-numeric ВР is treated as empty — is_valid_row returns True
    # (row kept as a dimension row) but is_expense_row returns False (no Expense created)
    # — report_parser.py:161-166 and 183-188
    row = _expense_type_row("abc")
    assert rp.is_valid_row(row) is True
    assert rp.is_expense_row(row) is False


# =============================================================================
# find_data_start_row
# =============================================================================


def test_find_data_start_row_after_number_row() -> None:
    df = pd.DataFrame(
        [
            ["header"] * 3,
            [1, 2, 3],
            ["data", "x", "y"],
        ]
    )
    assert rp.find_data_start_row(df) == 2


def test_find_data_start_row_fallback_to_6_current_behavior() -> None:
    # characterization: when the "1 2 3 ..." column-number row is not found, the parser
    # silently falls back to a hardcoded start row of 6 — report_parser.py:130-132
    df = pd.DataFrame([["a", "b", "c"]] * 10)
    assert rp.find_data_start_row(df) == 6


# =============================================================================
# extract_row_data
# =============================================================================


def test_extract_row_data_normal_detail() -> None:
    assert rp.extract_row_data(
        _row(
            ministry="020",
            chapter_full="0110",
            program="0110000000",
            expense_type="244",
            value_executed="5.5",
        )
    ) == {
        "ministry_code": "020",
        "chapter_code": "01",
        "subchapter_code": "0110",
        "program_code": "011",
        "expense_type_code": "244",
        "value": 5.5,
        "name": "Some name",
    }


def test_extract_row_data_aggregate_expense_type_skipped() -> None:
    # x00 aggregate rows are dropped entirely (is_valid_row False).
    assert (
        rp.extract_row_data(
            _row(
                ministry="020",
                chapter_full="0110",
                program="0110000000",
                expense_type="200",
                value_executed="5.5",
            )
        )
        is None
    )


@pytest.mark.parametrize("ministry", ["x", "х", None])
def test_extract_row_data_missing_or_placeholder_ministry_skipped(ministry: object) -> None:
    # characterization: rows whose ministry is empty or the Latin/Cyrillic "x" placeholder
    # are skipped — report_parser.py:287-288
    assert (
        rp.extract_row_data(
            _row(
                ministry=ministry,
                chapter_full="0110",
                program="0110000000",
                expense_type="244",
                value_executed="5.5",
            )
        )
        is None
    )


def test_extract_row_data_placeholder_chapter_becomes_none() -> None:
    # Cyrillic "х" in the chapter column ⇒ chapter/subchapter left as None.
    result = rp.extract_row_data(_row(ministry="020", chapter_full="х"))
    assert result is not None
    assert result["chapter_code"] is None
    assert result["subchapter_code"] is None


def test_extract_row_data_non_numeric_value_becomes_none_current_behavior() -> None:
    # characterization: an unparsable executed-value cell is silently swallowed to None
    # (the row is still kept) — report_parser.py:301-305
    result = rp.extract_row_data(
        _row(
            ministry="020",
            chapter_full="0110",
            program="0110000000",
            expense_type="244",
            value_executed="nope",
        )
    )
    assert result is not None
    assert result["value"] is None


# =============================================================================
# _find_parent_program (report variant — prefixes length-2 and up)
# =============================================================================


def _program_lookup(*identifiers: str) -> dict[tuple[str, str], Dimension]:
    return {
        ("PROGRAM", ident): Dimension(
            original_identifier=ident, type="PROGRAM", name="", name_translated=None
        )
        for ident in identifiers
    }


def test_report_find_parent_program_longest_prefix() -> None:
    lookup = _program_lookup("01", "011", "0110", "01104")
    assert rp._find_parent_program("011049", lookup) == "01104"


def test_report_find_parent_program_falls_back_to_short_prefix() -> None:
    lookup = _program_lookup("01", "011", "0110", "01104")
    # "01302": "0130"/"013" absent, "01" present ⇒ returns "01".
    assert rp._find_parent_program("01302", lookup) == "01"


def test_report_find_parent_program_two_char_code_returns_none_current_behavior() -> None:
    # characterization: report variant only considers prefixes of length >= 2, so a code of
    # length <= 2 never has a parent — report_parser.py:340
    assert rp._find_parent_program("01", _program_lookup("0")) is None


# =============================================================================
# create_dimensions_from_report_rows / create_expenses_from_report_rows
# =============================================================================


def _classification_matrix() -> list[dict]:
    """Hand-built rows covering every dimension type the report parser emits."""

    def row(**kwargs: object) -> dict:
        base = {
            "ministry_code": None,
            "chapter_code": None,
            "subchapter_code": None,
            "program_code": None,
            "expense_type_code": None,
            "value": None,
            "name": "",
        }
        base.update(kwargs)
        return base

    return [
        row(ministry_code="020", name="Ministry 020"),
        row(ministry_code="020", chapter_code="01", name="Chapter 01"),
        row(ministry_code="020", chapter_code="01", subchapter_code="0110", name="Sub 0110"),
        row(
            ministry_code="020",
            chapter_code="01",
            subchapter_code="0110",
            program_code="011",
            name="Program 011",
        ),
        row(
            ministry_code="020",
            chapter_code="01",
            subchapter_code="0110",
            program_code="01104",
            name="Program 01104",
        ),
        row(
            ministry_code="020",
            chapter_code="01",
            subchapter_code="0110",
            program_code="01104",
            expense_type_code="244",
            value=100.0,
            name="Leaf (закупка)",
        ),
        row(
            ministry_code="020",
            chapter_code="01",
            subchapter_code="0110",
            program_code="01104",
            expense_type_code="121",
            value=None,
            name="Leaf no value",
        ),
        row(
            ministry_code="020",
            chapter_code="01",
            subchapter_code="0110",
            expense_type_code="244",
            value=50.0,
            name="ET only (услуги)",
        ),
    ]


def test_create_dimensions_from_report_rows() -> None:
    dims, lookup = rp.create_dimensions_from_report_rows(_classification_matrix())
    got = [(d.type, d.original_identifier, d.name, d.parent_id) for d in dims]
    assert got == [
        ("MINISTRY", "020", "Ministry 020", None),
        ("CHAPTER", "01", "Chapter 01", None),
        ("SUBCHAPTER", "0110", "Sub 0110", "01"),
        ("PROGRAM", "011", "Program 011", None),
        ("PROGRAM", "01104", "Program 01104", "011"),
        ("EXPENSE_TYPE", "244", "закупка", None),  # name from first parenthesis pair
        ("PROGRAM", "01104-244", "Leaf (закупка)", "011"),  # id is "{code}-{vr}"
        ("EXPENSE_TYPE", "121", "Leaf no value", None),  # no parens ⇒ full name
        ("PROGRAM", "01104-121", "Leaf no value", "011"),
    ]
    # lookup dedups by (type, identifier); the later "услуги" ET-244 row does not overwrite.
    assert lookup[("EXPENSE_TYPE", "244")].name == "закупка"


def test_create_expenses_from_report_rows() -> None:
    parsed = _classification_matrix()
    _, lookup = rp.create_dimensions_from_report_rows(parsed)
    expenses = rp.create_expenses_from_report_rows(parsed, lookup)

    # Only the two rows with an expense_type AND a value become expenses; the value=None
    # leaf (121) is dropped.
    assert [e.value for e in expenses] == [100.0, 50.0]

    leaf = expenses[0]
    assert {(d.type, d.original_identifier) for d in leaf.dimensions} == {
        ("MINISTRY", "020"),
        ("CHAPTER", "01"),
        ("SUBCHAPTER", "0110"),
        ("PROGRAM", "01104-244"),
        ("EXPENSE_TYPE", "244"),
    }

    # The ET-only row has no program_code, so no PROGRAM dimension is linked.
    et_only = expenses[1]
    assert {(d.type, d.original_identifier) for d in et_only.dimensions} == {
        ("MINISTRY", "020"),
        ("CHAPTER", "01"),
        ("SUBCHAPTER", "0110"),
        ("EXPENSE_TYPE", "244"),
    }
