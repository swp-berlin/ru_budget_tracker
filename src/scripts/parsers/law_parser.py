"""
LAW-specific parsing functions.

Handles: law_YYYY.xlsx files
"""

import pandas as pd
from pathlib import Path
from typing import List, Tuple, Optional
import logging

from models import Budget, Dimension, Expense
from .helpers import (
    extract_budget_metadata_from_filename,
    create_budget_from_metadata,
    find_header_row,
    get_column_mapping,
    merge_rows,
    deduplicate_dimensions,
    extract_expense_type_name,
    MergedRow,
)

logger = logging.getLogger(__name__)


def parse_law_budget(file_path: Path) -> Budget:
    """Parse budget metadata from a LAW file."""
    metadata = extract_budget_metadata_from_filename(file_path)
    return create_budget_from_metadata(metadata)


def parse_law_dimensions(merged_rows: List[MergedRow]) -> List[Dimension]:
    """
    Parse dimensions from merged rows (LAW-specific logic).
    
    Creates: MINISTRY, CHAPTER, SUBCHAPTER, PROGRAM, EXPENSE_TYPE
    """
    dimensions: List[Dimension] = []

    def find_dim(identifier: str, dim_type: str) -> Optional[Dimension]:
        for d in dimensions:
            if d.original_identifier == identifier and d.type == dim_type:
                return d
        return None

    for row in merged_rows:
        name = row.name

        # PROGRAM (without expense_type)
        if row.program_code and not row.expense_type_code:
            parent_id = _find_parent_program(row.program_code, find_dim)
            dimensions.append(Dimension(
                original_identifier=row.program_code,
                type="PROGRAM",
                name=name,
                name_translated=None,
                parent_id=parent_id,
            ))

        # SUBCHAPTER
        if row.subchapter_code and not row.program_code:
            subchapter_id = f"{row.chapter_code}{row.subchapter_code}"
            dimensions.append(Dimension(
                original_identifier=subchapter_id,
                type="SUBCHAPTER",
                name=name,
                name_translated=None,
                parent_id=row.chapter_code,
            ))

        # CHAPTER
        if row.chapter_code and not row.subchapter_code and not row.program_code:
            dimensions.append(Dimension(
                original_identifier=row.chapter_code,
                type="CHAPTER",
                name=name,
                name_translated=None,
                parent_id=None,
            ))

        # MINISTRY
        if row.ministry_code and not row.chapter_code and not row.program_code:
            dimensions.append(Dimension(
                original_identifier=row.ministry_code,
                type="MINISTRY",
                name=name,
                name_translated=None,
                parent_id=None,
            ))

        # EXPENSE_TYPE
        if row.expense_type_code:
            expense_name = extract_expense_type_name(name)
            dimensions.append(Dimension(
                original_identifier=row.expense_type_code,
                type="EXPENSE_TYPE",
                name=expense_name,
                name_translated=None,
                parent_id=None,
            ))

            # PROGRAM with expense_type (most specific)
            if row.program_code:
                program_id = f"{row.program_code}-{row.expense_type_code}"
                parent_id = _find_parent_program(row.program_code, find_dim)
                dimensions.append(Dimension(
                    original_identifier=program_id,
                    type="PROGRAM",
                    name=name,
                    name_translated=None,
                    parent_id=parent_id,
                ))

    logger.info(f"Parsed {len(dimensions)} dimensions")
    return dimensions


def _find_parent_program(program_code: str, find_dim) -> Optional[str]:
    """Find parent program by walking up the hierarchy (character-based)."""
    code = program_code.strip()
    
    if len(code) <= 1:
        return None
    
    # Try progressively longer prefixes, return the longest match
    longest_match = None
    for length in range(1, len(code)):
        candidate = code[:length]
        if find_dim(candidate, "PROGRAM"):
            longest_match = candidate
    
    return longest_match


def parse_law_expenses(merged_rows: List[MergedRow], dimensions: List[Dimension]) -> List[Expense]:
    """
    Create expenses from merged rows and link to dimensions.
    
    Only rows with expense_type_code AND value become expenses.
    """
    # Build lookup: (type, identifier) -> Dimension
    dim_lookup = {(d.type, d.original_identifier): d for d in dimensions}

    expenses: List[Expense] = []

    for row in merged_rows:
        if not row.expense_type_code or row.value is None:
            continue

        expense = Expense(budget_id=None, value=row.value)

        # Link dimensions
        if row.ministry_code:
            dim = dim_lookup.get(("MINISTRY", row.ministry_code))
            if dim:
                expense.dimensions.append(dim)

        if row.chapter_code:
            dim = dim_lookup.get(("CHAPTER", row.chapter_code))
            if dim:
                expense.dimensions.append(dim)

        if row.subchapter_code and row.chapter_code:
            subchapter_id = f"{row.chapter_code}{row.subchapter_code}"
            dim = dim_lookup.get(("SUBCHAPTER", subchapter_id))
            if dim:
                expense.dimensions.append(dim)

        if row.program_code and row.expense_type_code:
            program_id = f"{row.program_code}-{row.expense_type_code}"
            dim = dim_lookup.get(("PROGRAM", program_id))
            if dim:
                expense.dimensions.append(dim)

        if row.expense_type_code:
            dim = dim_lookup.get(("EXPENSE_TYPE", row.expense_type_code))
            if dim:
                expense.dimensions.append(dim)

        if expense.dimensions:
            expenses.append(expense)

    logger.info(f"Created {len(expenses)} expenses")
    return expenses


def parse_law_file(file_path: Path) -> Tuple[Budget, List[Dimension], List[Expense]]:
    """
    Parse a LAW file completely.
    
    This is the main entry point - reads the file ONCE and returns everything.
    
    Returns:
        (budget, dimensions, expenses)
    """
    logger.info(f"Parsing LAW file: {file_path.name}")

    # 1. Parse budget metadata (from filename)
    budget = parse_law_budget(file_path)

    # 2. Read Excel file (ONCE)
    df = pd.read_excel(file_path, header=None, engine="openpyxl")

    # 3. Find structure
    header_idx = find_header_row(df)
    col_mapping = get_column_mapping(df.iloc[header_idx])

    # 4. Merge multi-line rows (LAW values are in thousands → multiply by 1000)
    merged_rows = merge_rows(df, header_idx, col_mapping, multiplier=1000.0)

    # 5. Parse dimensions
    dimensions = parse_law_dimensions(merged_rows)
    dimensions = deduplicate_dimensions(dimensions)

    # 6. Parse expenses
    expenses = parse_law_expenses(merged_rows, dimensions)

    logger.info(f"Parsed: {budget.original_identifier}, {len(dimensions)} dimensions, {len(expenses)} expenses")

    return budget, dimensions, expenses
