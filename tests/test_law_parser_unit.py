"""Characterization unit tests for scripts.parsers.law_parser.

Synthetic MergedRow inputs, no data files. Notable pin: the law variant of
_find_parent_program walks the hierarchy differently from the report variant.
"""

from models import Dimension
from scripts.parsers import law_parser as lp
from scripts.parsers.helpers import MergedRow, deduplicate_dimensions


# =============================================================================
# normalize_chapter_name
# =============================================================================


def test_normalize_chapter_name_2020_special_case() -> None:
    # law_2020 spells this chapter with parentheses; it is rewritten to the "и" form.
    assert (
        lp.normalize_chapter_name("Обслуживание государственного (муниципального) долга")
        == "Обслуживание государственного и муниципального долга"
    )


def test_normalize_chapter_name_passthrough() -> None:
    assert lp.normalize_chapter_name("Национальная оборона") == "Национальная оборона"


# =============================================================================
# _find_parent_program (law variant — character-based, includes 1-char prefixes)
# =============================================================================


def _finder(*identifiers: str):
    dims = [
        Dimension(original_identifier=i, type="PROGRAM", name="", name_translated=None)
        for i in identifiers
    ]

    def find_dim(identifier: str, dim_type: str) -> Dimension | None:
        for d in dims:
            if d.original_identifier == identifier and d.type == dim_type:
                return d
        return None

    return find_dim


def test_law_find_parent_program_longest_prefix() -> None:
    assert lp._find_parent_program("0110", _finder("0", "01", "011")) == "011"


def test_law_find_parent_program_allows_single_char_prefix_current_behavior() -> None:
    # characterization: unlike the report variant (which needs len > 2), the law variant
    # accepts a 1-char parent, so "01" resolves to parent "0" — law_parser.py:158-172
    assert lp._find_parent_program("01", _finder("0", "01", "011")) == "0"


def test_law_find_parent_program_single_char_code_returns_none() -> None:
    # a code of length <= 1 has no parent.
    assert lp._find_parent_program("0", _finder("0")) is None


# =============================================================================
# parse_law_dimensions / parse_law_expenses
# =============================================================================


def _merged_matrix() -> list[MergedRow]:
    """Merged rows covering every dimension type the law parser emits."""
    return [
        MergedRow(row_idx=1, name="Ministry 020", ministry_code="020"),
        MergedRow(row_idx=2, name="Chapter 01", chapter_code="01"),
        MergedRow(row_idx=3, name="Sub 0110", chapter_code="01", subchapter_code="10"),
        MergedRow(
            row_idx=4,
            name="Program 011",
            ministry_code="020",
            chapter_code="01",
            subchapter_code="10",
            program_code="011",
        ),
        MergedRow(
            row_idx=5,
            name="Program 01104",
            ministry_code="020",
            chapter_code="01",
            subchapter_code="10",
            program_code="01104",
        ),
        MergedRow(
            row_idx=6,
            name="Leaf (закупка)",
            ministry_code="020",
            chapter_code="01",
            subchapter_code="10",
            program_code="01104",
            expense_type_code="244",
            value=1000.0,
        ),
        MergedRow(
            row_idx=7,
            name="Leaf no value",
            ministry_code="020",
            chapter_code="01",
            subchapter_code="10",
            program_code="01104",
            expense_type_code="121",
            value=None,
        ),
    ]


def test_parse_law_dimensions() -> None:
    dims = lp.parse_law_dimensions(_merged_matrix())
    got = [(d.type, d.original_identifier, d.name, d.parent_id) for d in dims]
    assert got == [
        ("MINISTRY", "020", "Ministry 020", None),
        ("CHAPTER", "01", "Chapter 01", None),
        # subchapter id is chapter_code + subchapter_code = "01" + "10"
        ("SUBCHAPTER", "0110", "Sub 0110", "01"),
        ("PROGRAM", "011", "Program 011", None),
        ("PROGRAM", "01104", "Program 01104", "011"),
        ("EXPENSE_TYPE", "244", "закупка", None),
        ("PROGRAM", "01104-244", "Leaf (закупка)", "011"),  # id is "{code}-{vr}"
        ("EXPENSE_TYPE", "121", "Leaf no value", None),
        ("PROGRAM", "01104-121", "Leaf no value", "011"),
    ]


def test_parse_law_expenses_only_valued_expense_type_rows() -> None:
    merged = _merged_matrix()
    dims = deduplicate_dimensions(lp.parse_law_dimensions(merged))
    expenses = lp.parse_law_expenses(merged, dims)

    # Only the single expense_type row that also has a value becomes an Expense;
    # the value=None row (121) is dropped.
    assert [e.value for e in expenses] == [1000.0]
    assert {(d.type, d.original_identifier) for d in expenses[0].dimensions} == {
        ("MINISTRY", "020"),
        ("CHAPTER", "01"),
        ("SUBCHAPTER", "0110"),
        ("PROGRAM", "01104-244"),
        ("EXPENSE_TYPE", "244"),
    }
