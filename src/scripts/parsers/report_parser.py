"""
REPORT-specific parsing functions.

Handles: report_YYYY_MM.xlsx and report_YYYY_MM.xls files

Report files use sheet "2.1" (Ведомственная структура расходов федерального бюджета).
Structure differs from LAW files:
- Column layout: Name | Код стро-ки | Глав-ный распо-рядитель | Р, Пр | ЦСР | ВР | Values...
- Filter to rows where ВР (expense type) is divisible by 100
- Chapter code (Р, Пр) contains both chapter (first 2 digits) and subchapter (full code)
- Value column is immediately after ВР (expense type)
"""

import pandas as pd
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import logging
import warnings

from models import Budget, Dimension, Expense
from .helpers import (
    extract_budget_metadata_from_filename,
    create_budget_from_metadata,
    clean_code_value,
    extract_expense_type_name,
)

logger = logging.getLogger(__name__)

# Silence noisy openpyxl warning about missing workbook style.
warnings.filterwarnings(
    "ignore",
    message="Workbook contains no default style, apply openpyxl's default",
    category=UserWarning,
    module="openpyxl.styles.stylesheet",
)


# =============================================================================
# CONSTANTS
# =============================================================================

REPORT_SHEET_NAME = "2.1"

# Column indices in report files (0-indexed)
REPORT_COLUMNS = {
    "name": 0,           # Наименование показателя
    "row_code": 1,       # Код стро-ки
    "ministry": 2,       # Глав-ный распо-рядитель
    "chapter_full": 3,   # Р, Пр (contains chapter + subchapter as XXYY)
    "program": 4,        # ЦСР
    "expense_type": 5,   # ВР
    "value_law": 6,      # Бюджетные ассигнования по закону
    "value_adjusted": 7, # Бюджетные ассигнования с учетом изменений
    "value_executed": 8, # Исполнено
}


# =============================================================================
# BUDGET PARSING
# =============================================================================

def parse_report_budget(file_path: Path) -> Budget:
    """Parse budget metadata from a REPORT file."""
    metadata = extract_budget_metadata_from_filename(file_path)
    return create_budget_from_metadata(metadata)


# =============================================================================
# EXCEL READING
# =============================================================================

def read_report_excel(file_path: Path) -> pd.DataFrame:
    """
    Read report Excel file from sheet 2.1.

    Handles both .xlsx and .xls formats.
    """
    suffix = file_path.suffix.lower()

    if suffix == ".xlsx":
        engine = "openpyxl"
    elif suffix == ".xls":
        engine = "xlrd"
    else:
        raise ValueError(f"Unsupported file format: {suffix}")

    try:
        df = pd.read_excel(
            file_path,
            sheet_name=REPORT_SHEET_NAME,
            header=None,
            engine=engine,
        )
        # Drop columns that are entirely empty (handles blank first column edge-case)
        original_columns = df.shape[1]
        df = df.replace(r"^\s*$", pd.NA, regex=True).dropna(axis=1, how="all")
        if df.shape[1] != original_columns:
            logger.info(
                "Dropped %d completely empty column(s)",
                original_columns - df.shape[1],
            )
        logger.info(f"Read sheet '{REPORT_SHEET_NAME}' with {len(df)} rows")
        return df
    except Exception as e:
        raise ValueError(f"Failed to read sheet '{REPORT_SHEET_NAME}' from {file_path}: {e}")


def find_data_start_row(df: pd.DataFrame) -> int:
    """
    Find the first data row (after headers).

    Looks for the row with column numbers (1, 2, 3, 4, 5, 6, 7, 8, 9, 10).
    """
    for idx in range(min(20, len(df))):
        row = df.iloc[idx]
        # Check if this looks like a column number row
        first_val = row.iloc[0]
        if first_val == 1 or str(first_val).strip() == "1":
            # Verify it's the column numbers row
            try:
                if int(row.iloc[1]) == 2 and int(row.iloc[2]) == 3:
                    return idx + 1  # Data starts after this row
            except (ValueError, TypeError):
                pass

    # Fallback: skip first 6 rows (typical header size)
    logger.warning("Could not find column number row, using default start row 6")
    return 6


# =============================================================================
# ROW PARSING
# =============================================================================

def is_valid_row(row: pd.Series) -> bool:
    """
    Check if row should be processed.

    Returns True if:
    - expense_type is empty (dimension name rows like ministry, chapter)
    - expense_type is divisible by 100 (aggregated expense rows)
    
    Returns False if expense_type exists but is not divisible by 100.
    """
    expense_type = row.iloc[REPORT_COLUMNS["expense_type"]]

    # Empty expense type is valid (dimension name rows)
    if pd.isna(expense_type):
        return True
    
    try:
        et_val = int(float(expense_type))
        # Only accept expense types divisible by 100
        return et_val > 0 and et_val % 100 == 0
    except (ValueError, TypeError, OverflowError):
        logger.info(
            "Treating non-numeric expense_type as empty: %s",
            expense_type,
        )
        return True  # Non-numeric values are treated as empty


def is_expense_row(row: pd.Series) -> bool:
    """
    Check if row is an expense row (has expense type divisible by 100 AND a value).

    Used to determine if a row should create an Expense object.
    """
    expense_type = row.iloc[REPORT_COLUMNS["expense_type"]]

    if pd.isna(expense_type):
        return False

    try:
        et_val = int(float(expense_type))
        return et_val > 0 and et_val % 100 == 0
    except (ValueError, TypeError, OverflowError):
        logger.info(
            "Skipping expense row with non-numeric expense_type: %s",
            expense_type,
        )
        return False


def parse_chapter_code(chapter_full: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse chapter code from the combined Р, Пр column.
    
    The 4-digit code structure:
    - If ends with "00" (e.g., "0100") → it's a chapter only, return chapter="01", subchapter=None
    - If doesn't end with "00" (e.g., "0110") → it's a subchapter, return chapter="01", subchapter="0110"

    Returns: (chapter_code, subchapter_code or None)
    """
    chapter_full = str(chapter_full).strip()

    if len(chapter_full) < 2:
        return chapter_full, None

    chapter_code = chapter_full[:2]
    
    # If the code ends with "00", it's a chapter-level code (no subchapter)
    if len(chapter_full) == 4 and chapter_full.endswith("00"):
        return chapter_code, None
    
    # Otherwise it's a subchapter
    subchapter_code = chapter_full if len(chapter_full) > 2 else None

    return chapter_code, subchapter_code


def parse_program_code(program_full: str) -> Optional[str]:
    """
    Parse program code by stripping trailing all-zero segments.
    
    10-character structure: XX X XX XXXXX (2+1+2+5)
    Segments: [0:2], [2:3], [3:5], [5:10]
    
    Strip trailing segments that are ALL zeros from right to left.
    
    Examples:
        "0100000000" → "01" (strip "00000", "00", "0")
        "0110000000" → "011" (strip "00000", "00", but "1" is not zeros)
        "0110400000" → "01104" (strip "00000", but "04" is not all zeros)
        "0110490000" → "0110490000" (no stripping, "90000" is not all zeros)
    
    Returns: Stripped program code, or None if invalid/empty
    """
    if not program_full:
        return None
    
    program_full = str(program_full).strip()
    
    if len(program_full) != 10:
        return program_full  # Return as-is if not 10 chars
    
    # Split into segments: XX X XX XXXXX
    segments = [
        program_full[0:2],   # 2 chars
        program_full[2:3],   # 1 char
        program_full[3:5],   # 2 chars
        program_full[5:10],  # 5 chars
    ]
    
    # Strip trailing all-zero segments from right to left
    while segments and all(c == '0' for c in segments[-1]):
        segments.pop()
    
    if not segments:
        return None
    
    return ''.join(segments)


def extract_row_data(row: pd.Series) -> Optional[Dict]:
    """
    Extract data from a row (either dimension row or expense row).

    Returns dict with:
        - ministry_code
        - chapter_code
        - subchapter_code
        - program_code (parsed/stripped)
        - expense_type_code (None for dimension-only rows)
        - value (executed amount, None for dimension-only rows)
        - name
    
    Returns None for rows that should be skipped (non-100-divisible expense types).
    """
    # Skip rows with expense types not divisible by 100
    if not is_valid_row(row):
        return None

    # Extract codes
    ministry_code = clean_code_value(row.iloc[REPORT_COLUMNS["ministry"]])
    chapter_full = clean_code_value(row.iloc[REPORT_COLUMNS["chapter_full"]])
    program_raw = clean_code_value(row.iloc[REPORT_COLUMNS["program"]])
    expense_type_code = clean_code_value(row.iloc[REPORT_COLUMNS["expense_type"]])

    # Skip rows without ministry (header rows, totals)
    if not ministry_code or ministry_code.lower() in ("х", "x", "nan"):
        return None

    # Parse chapter/subchapter
    chapter_code, subchapter_code = None, None
    if chapter_full and chapter_full.lower() not in ("х", "x", "nan"):
        chapter_code, subchapter_code = parse_chapter_code(chapter_full)

    # Parse program code (strip trailing zero segments)
    program_code = parse_program_code(program_raw) if program_raw else None

    # Get executed value (column 8)
    value = None
    value_raw = row.iloc[REPORT_COLUMNS["value_executed"]]
    if pd.notna(value_raw):
        try:
            value = float(value_raw)
        except (ValueError, TypeError):
            pass

    # Get name
    name = row.iloc[REPORT_COLUMNS["name"]]
    if pd.notna(name):
        name = str(name).replace("\n", " ").replace("\r", " ")
        name = " ".join(name.split())
    else:
        name = ""

    return {
        "ministry_code": ministry_code,
        "chapter_code": chapter_code,
        "subchapter_code": subchapter_code,
        "program_code": program_code,
        "expense_type_code": expense_type_code,
        "value": value,
        "name": name,
    }


# =============================================================================
# DIMENSION CREATION (from report data)
# =============================================================================

def _find_parent_program(program_code: str, dim_lookup: Dict[Tuple[str, str], Dimension]) -> Optional[str]:
    """
    Find parent program by checking progressively shorter prefixes.
    
    For program code "01302", check if "0130", "013", "01" exist as programs.
    Returns the longest matching parent identifier, or None.
    """
    if not program_code or len(program_code) <= 2:
        return None
    
    # Try progressively shorter prefixes
    for length in range(len(program_code) - 1, 1, -1):
        candidate = program_code[:length]
        if (("PROGRAM", candidate) in dim_lookup):
            return candidate
    
    return None


def create_dimensions_from_report_rows(
    parsed_rows: List[Dict],
) -> Tuple[List[Dimension], Dict[Tuple[str, str], Dimension]]:
    """
    Create dimensions from parsed report rows.

    Reports define their own dimensions since they may have different
    ministries, chapters, programs than the LAW files.

    Returns:
        - List of unique Dimension objects
        - Lookup dict: (type, identifier) -> Dimension
    """
    dimensions: List[Dimension] = []
    dim_lookup: Dict[Tuple[str, str], Dimension] = {}

    def add_dimension(dim_type: str, identifier: str, name: Optional[str], parent_id: Optional[str] = None):
        """Add dimension if not already present."""
        key = (dim_type, identifier)
        if key in dim_lookup:
            return dim_lookup[key]

        dim = Dimension(
            original_identifier=identifier,
            type=dim_type,
            name=name or "",
            name_translated=None,
            parent_id=parent_id,
        )
        dimensions.append(dim)
        dim_lookup[key] = dim
        return dim

    # Process rows following law_parser logic:
    # - MINISTRY: has ministry_code, no chapter_code, no program_code
    # - CHAPTER: has chapter_code, no subchapter_code, no program_code
    # - SUBCHAPTER: has subchapter_code, no program_code
    # - PROGRAM (without expense_type): has program_code, no expense_type_code
    # - EXPENSE_TYPE: has expense_type_code
    # - PROGRAM (with expense_type): has program_code AND expense_type_code
    
    for row_data in parsed_rows:
        ministry_code = row_data["ministry_code"]
        chapter_code = row_data["chapter_code"]
        subchapter_code = row_data["subchapter_code"]
        program_code = row_data["program_code"]
        expense_type_code = row_data["expense_type_code"]
        name = row_data["name"]

        # MINISTRY: has ministry, no chapter, no program
        if ministry_code and not chapter_code and not program_code:
            add_dimension("MINISTRY", ministry_code, name)

        # CHAPTER: has chapter, no subchapter, no program
        if chapter_code and not subchapter_code and not program_code:
            add_dimension("CHAPTER", chapter_code, name)

        # SUBCHAPTER: has subchapter, no program
        if subchapter_code and not program_code:
            subchapter_id = f"{subchapter_code}"
            add_dimension("SUBCHAPTER", subchapter_id, name, chapter_code)

        # PROGRAM (without expense_type)
        if program_code and not expense_type_code:
            parent_id = _find_parent_program(program_code, dim_lookup)
            add_dimension("PROGRAM", program_code, name, parent_id)

        # EXPENSE_TYPE
        if expense_type_code:
            expense_name = extract_expense_type_name(name) if name else None
            add_dimension("EXPENSE_TYPE", expense_type_code, expense_name)

            # PROGRAM with expense_type (most specific)
            if program_code:
                program_id = f"{program_code}-{expense_type_code}"
                parent_id = _find_parent_program(program_code, dim_lookup)
                add_dimension("PROGRAM", program_id, name, parent_id)

    logger.info(f"Created {len(dimensions)} dimensions from report data")
    return dimensions, dim_lookup


# =============================================================================
# EXPENSE CREATION
# =============================================================================

def create_expenses_from_report_rows(
    parsed_rows: List[Dict],
    dim_lookup: Dict[Tuple[str, str], Dimension],
) -> List[Expense]:
    """
    Create Expense objects from parsed rows, linking to dimensions.
    
    Only rows with expense_type_code AND value become expenses.
    """
    expenses: List[Expense] = []

    for row_data in parsed_rows:
        # Only create expenses for rows with expense_type and value
        expense_type_code = row_data["expense_type_code"]
        value = row_data["value"]
        if not expense_type_code or value is None:
            continue

        expense = Expense(budget_id=None, value=value)

        # Link MINISTRY
        ministry_code = row_data["ministry_code"]
        if ministry_code:
            dim = dim_lookup.get(("MINISTRY", ministry_code))
            if dim:
                expense.dimensions.append(dim)

        # Link CHAPTER
        chapter_code = row_data["chapter_code"]
        if chapter_code:
            dim = dim_lookup.get(("CHAPTER", chapter_code))
            if dim:
                expense.dimensions.append(dim)

        # Link SUBCHAPTER
        subchapter_code = row_data["subchapter_code"]
        if subchapter_code and chapter_code:
            subchapter_id = f"{subchapter_code}"
            dim = dim_lookup.get(("SUBCHAPTER", subchapter_id))
            if dim:
                expense.dimensions.append(dim)

        # Link PROGRAM
        program_code = row_data["program_code"]
        if program_code and expense_type_code:
            program_id = f"{program_code}-{expense_type_code}"
            dim = dim_lookup.get(("PROGRAM", program_id))
            if dim:
                expense.dimensions.append(dim)

        # Link EXPENSE_TYPE
        if expense_type_code:
            dim = dim_lookup.get(("EXPENSE_TYPE", expense_type_code))
            if dim:
                expense.dimensions.append(dim)

        if expense.dimensions:
            expenses.append(expense)

    logger.info(f"Created {len(expenses)} expenses")
    return expenses


# =============================================================================
# MAIN PARSING FUNCTION
# =============================================================================

def parse_report_file(
    file_path: Path,
) -> Tuple[Budget, List[Dimension], List[Expense]]:
    """
    Parse a REPORT file completely.

    This is the main entry point - reads the file ONCE and returns everything.

    Args:
        file_path: Path to report Excel file (.xlsx or .xls)

    Returns:
        (budget, dimensions, expenses)
    """
    logger.info(f"Parsing REPORT file: {file_path.name}")

    # 1. Parse budget metadata (from filename)
    budget = parse_report_budget(file_path)

    # 2. Read Excel file (ONCE)
    df = read_report_excel(file_path)

    # 3. Find where data starts
    start_row = find_data_start_row(df)
    logger.info(f"Data starts at row {start_row}")

    # 4. Parse expense rows
    parsed_rows: List[Dict] = []
    for idx in range(start_row, len(df)):
        row = df.iloc[idx]
        row_data = extract_row_data(row)
        if row_data:
            parsed_rows.append(row_data)

    logger.info(f"Parsed {len(parsed_rows)} expense rows")

    # 5. Create dimensions
    dimensions, dim_lookup = create_dimensions_from_report_rows(parsed_rows)

    # 6. Create expenses
    expenses = create_expenses_from_report_rows(parsed_rows, dim_lookup)

    logger.info(
        f"Parsed: {budget.original_identifier}, "
        f"{len(dimensions)} dimensions, {len(expenses)} expenses"
    )

    return budget, dimensions, expenses