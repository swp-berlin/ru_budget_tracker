"""
Shared helper functions for budget parsing.

These are low-level utilities used by multiple parsers.
"""

import re
import pandas as pd
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel
import logging

from models import Budget, Dimension, DimensionTypeLiteral

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class MergedRow(BaseModel):
    """A row from the Excel file after multi-line merging."""
    row_idx: int
    name: str
    ministry_code: Optional[str] = None
    chapter_code: Optional[str] = None
    subchapter_code: Optional[str] = None
    program_code: Optional[str] = None
    expense_type_code: Optional[str] = None
    value: Optional[float] = None


# =============================================================================
# BUDGET METADATA (from filename)
# =============================================================================

def extract_budget_metadata_from_filename(excel_file_path: Path) -> dict:
    """
    Extract metadata from filename.
    
    Patterns:
        law_2024.xlsx → type=LAW, year=2024
        report_2024_03.xlsx → type=REPORT, year=2024, month=3
        draft_2024.xlsx → type=DRAFT, year=2024
    """
    filename = excel_file_path.stem.lower()

    # Determine type
    if filename.startswith("law"):
        budget_type, title, scope = "LAW", "Federal Budget Law", "YEARLY"
    elif filename.startswith("report"):
        budget_type, title, scope = "REPORT", "Federal Budget Report", "QUARTERLY"
    elif filename.startswith("draft"):
        budget_type, title, scope = "DRAFT", "Federal Budget Draft", "YEARLY"
    else:
        raise ValueError(f"Unknown file type: {filename}")

    # Extract year
    year_match = re.search(r"(\d{4})", filename)
    if not year_match:
        raise ValueError(f"No year found in filename: {filename}")
    year = int(year_match.group(1))

    # Extract month (reports only)
    month = None
    if budget_type == "REPORT":
        month_match = re.search(r"_(\d{2})(?:\.|$)", filename)
        if month_match:
            month = int(month_match.group(1))

    # Build identifier
    if budget_type == "REPORT" and month:
        original_identifier = f"{budget_type}-{year}-{month:02d}"
    else:
        original_identifier = f"{budget_type}-{year}"

    return {
        "original_identifier": original_identifier,
        "title": title,
        "year": year,
        "month": month,
        "type": budget_type,
        "scope": scope,
    }


def create_budget_from_metadata(metadata: dict) -> Budget:
    """Create a Budget object from metadata dict."""
    if metadata["month"]:
        published_at = date(metadata["year"], metadata["month"], 1)
    else:
        published_at = date(metadata["year"], 1, 1)

    return Budget(
        original_identifier=metadata["original_identifier"],
        name=metadata["title"],
        name_translated=None,
        description=f"{metadata['title']} {metadata['year']}"
        + (f"-{metadata['month']:02d}" if metadata["month"] else ""),
        description_translated=None,
        type=metadata["type"],
        scope=metadata["scope"],
        published_at=published_at,
        planned_at=None,
    )


# =============================================================================
# EXCEL PARSING
# =============================================================================

def find_header_row(df: pd.DataFrame) -> int:
    """Find the row containing column headers (Наименование, Мін, etc.)."""
    for idx, *row in df.itertuples():
        row_str = " ".join(str(val) for val in row if pd.notna(val))
        if "Наименование" in row_str and ("Мін" in row_str or "Мин" in row_str):
            return idx
    raise ValueError("Could not find header row")


def get_column_mapping(header_row: pd.Series) -> Dict[str, int]:
    """Map column names to indices."""
    col_mapping = {}

    for col_idx, col_name in enumerate(header_row):
        if pd.isna(col_name):
            continue
        col_str = str(col_name).strip()

        if "наименование" in col_str.lower():
            col_mapping["name"] = col_idx
        elif col_str in ("Мин", "Мін"):
            col_mapping["ministry"] = col_idx
        elif col_str == "Рз":
            col_mapping["chapter"] = col_idx
        elif col_str == "ПР":
            col_mapping["subchapter"] = col_idx
        elif col_str == "ЦСР":
            col_mapping["program"] = col_idx
        elif col_str == "ВР":
            col_mapping["expense_type"] = col_idx

    if "expense_type" in col_mapping:
        col_mapping["value"] = col_mapping["expense_type"] + 1

    logger.info(f"Column mapping: {col_mapping}")
    return col_mapping


def clean_code_value(value) -> Optional[str]:
    """Clean a code value, returning None if empty."""
    if pd.isna(value):
        return None
    cleaned = str(value).strip().replace(" ", "")
    if cleaned.lower() == "nan" or cleaned == "":
        return None
    return cleaned


def merge_rows(df: pd.DataFrame, header_row_idx: int, col_mapping: Dict[str, int]) -> List[MergedRow]:
    """
    Merge multi-row entries where text spans multiple rows.
    
    Returns list of MergedRow objects with consolidated text and codes.
    """
    logger.info("Merging multi-row entries...")

    merged_rows: List[MergedRow] = []
    accumulated_name = ""
    first_data_row = True
    name_idx = col_mapping.get("name", 0)

    for idx in range(header_row_idx + 1, len(df)):
        row = df.iloc[idx]

        # Get and clean name
        name = row.iloc[name_idx]
        if pd.isna(name) or str(name).strip() == "":
            continue

        name = str(name).replace("\n", " ").replace("\r", " ")
        name = " ".join(name.split())

        # Skip total row
        if first_data_row:
            first_data_row = False
            if "всего" in name.replace(" ", "").lower():
                continue

        # Get codes
        ministry_code = clean_code_value(row.iloc[col_mapping["ministry"]] if "ministry" in col_mapping else None)
        chapter_code = clean_code_value(row.iloc[col_mapping["chapter"]] if "chapter" in col_mapping else None)
        subchapter_code = clean_code_value(row.iloc[col_mapping["subchapter"]] if "subchapter" in col_mapping else None)
        program_code = clean_code_value(row.iloc[col_mapping["program"]] if "program" in col_mapping else None)
        expense_type_code = clean_code_value(row.iloc[col_mapping["expense_type"]] if "expense_type" in col_mapping else None)

        has_codes = any([ministry_code, chapter_code, subchapter_code, program_code, expense_type_code])

        if not has_codes:
            # Decide: append to previous or accumulate forward
            if merged_rows:
                prev = merged_rows[-1]
                if prev.expense_type_code and not prev.name.endswith(")"):
                    prev.name += " " + name
                    continue
                if not prev.expense_type_code and name.endswith('"'):
                    prev.name += " " + name
                    continue
            accumulated_name = name if not accumulated_name else accumulated_name + " " + name
            continue

        # Has codes: create entry
        full_name = (accumulated_name + " " + name) if accumulated_name else name
        accumulated_name = ""

        # Get value
        value = None
        if "value" in col_mapping:
            value_raw = row.iloc[col_mapping["value"]]
            if pd.notna(value_raw):
                try:
                    value = float(value_raw)
                except (ValueError, TypeError):
                    pass

        merged_rows.append(MergedRow(
            row_idx=idx,
            name=full_name,
            ministry_code=ministry_code,
            chapter_code=chapter_code,
            subchapter_code=subchapter_code,
            program_code=program_code,
            expense_type_code=expense_type_code,
            value=value,
        ))

    logger.info(f"Merged into {len(merged_rows)} rows")
    return merged_rows


# =============================================================================
# DEDUPLICATION
# =============================================================================

def deduplicate_dimensions(dimensions_list: List[Dimension]) -> List[Dimension]:
    """
    Remove duplicates and warn about data quality issues.
    
    Deduplication key: (name, type, original_identifier, parent_id)
    """
    # Check for same identifier with different names (data quality warning)
    identifier_names: Dict[tuple, List[str]] = {}
    for dim in dimensions_list:
        key = (dim.original_identifier, dim.type, dim.parent_id)
        if key not in identifier_names:
            identifier_names[key] = []
        identifier_names[key].append(dim.name)

    for (identifier, dim_type, parent_id), names in identifier_names.items():
        unique_names = set(names)
        if len(unique_names) > 1:
            logger.warning(f"Same {dim_type} '{identifier}' (parent={parent_id}) has {len(unique_names)} names:")
            for name in sorted(unique_names):
                logger.warning(f"  - {name[:150]}")

    # Deduplicate
    seen: set = set()
    unique: List[Dimension] = []

    for dim in dimensions_list:
        key = (dim.name, dim.type, dim.original_identifier, dim.parent_id)
        if key not in seen:
            seen.add(key)
            unique.append(dim)

    logger.info(f"Deduplication: {len(dimensions_list)} → {len(unique)} dimensions")
    return unique


# =============================================================================
# TEXT EXTRACTION
# =============================================================================

def extract_expense_type_name(full_text: str) -> str:
    """Extract expense type name from last parenthesis pair, or return full text."""
    last_close = full_text.rfind(")")
    if last_close == -1:
        return full_text

    depth = 0
    for i in range(last_close - 1, -1, -1):
        if full_text[i] in (")", "）", "\uff09"):
            depth += 1
        elif full_text[i] in ("(", "（", "\uff08"):
            if depth == 0:
                return full_text[i + 1:last_close].strip()
            depth -= 1

    return full_text
