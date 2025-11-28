"""
Budget import script.

Clean, human-readable import logic. Each file is read ONCE.

Usage:
    python import.py                              # Import all laws 2018-2025
    python import.py --years 2020 2021            # Import specific years (laws)
    python import.py --file law_2024.xlsx         # Import single file
    python import.py --type report --years 2018   # Import reports for 2018
    python import.py --type report                # Import all reports 2018-2025
    python import.py --type all                   # Import all laws and reports
"""

import sys
import argparse
from pathlib import Path
from typing import List, Dict, Literal
import logging

# Add parent to path if needed
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import Session
from models import Budget, Dimension, Expense
from database.sessions import get_sync_session
from parsers import parse_law_file, parse_report_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================


def save_budget(session: Session, budget: Budget) -> int:
    """
    Save or update budget in database.

    Returns: database ID
    """
    select_stmt = select(Budget).where(Budget.original_identifier == budget.original_identifier)
    existing = session.scalars(select_stmt).first()

    if existing:
        budget.id = existing.id
        logger.info(f"Updating existing budget (ID: {existing.id})")

    merged = session.merge(budget)
    session.flush()
    return merged.id


def upsert_dimension(
    session: Session,
    original_identifier: str,
    dim_type: str,
    name: str,
    parent_db_id: int | None,
    name_translated: str | None = None,
) -> Dimension:
    """
    Upsert dimension with special parent_id handling:

    1. If exists with same parent_id → skip (return existing)
    2. If exists with parent_id=None → update to new parent_id
    3. If exists with different non-null parent_id → add new row
    """
    # First: check for exact match (same parent_id) → skip
    exact_match = (
        session.query(Dimension)
        .filter_by(
            original_identifier=original_identifier,
            type=dim_type,
            name=name,
            parent_id=parent_db_id,
        )
        .first()
    )

    if exact_match:
        logger.debug(f"Exact match found: {original_identifier} ({dim_type})")
        return exact_match

    # Second: check for match with parent_id=None → update
    if parent_db_id is not None:
        null_parent = (
            session.query(Dimension)
            .filter_by(
                original_identifier=original_identifier,
                type=dim_type,
                name=name,
                parent_id=None,
            )
            .first()
        )

        if null_parent:
            logger.debug(
                f"Updating null parent: {original_identifier} ({dim_type}) -> parent_id={parent_db_id}"
            )
            null_parent.parent_id = parent_db_id
            session.flush()
            return null_parent

    # Third: no match or different parent → insert new row
    logger.debug(f"Inserting new: {original_identifier} ({dim_type}), parent_id={parent_db_id}")
    new_dim = Dimension(
        original_identifier=original_identifier,
        type=dim_type,
        name=name,
        name_translated=name_translated,
        parent_id=parent_db_id,
    )
    session.add(new_dim)
    session.flush()
    return new_dim


def _find_parent_db_id(
    parent_identifier: str, expected_type: str | None, dim_map: Dict[tuple, Dimension]
) -> int | None:
    """
    Find parent's DB id by its original_identifier.

    Args:
        parent_identifier: The string identifier (e.g., "01")
        expected_type: Expected dimension type (e.g., "PROGRAM", "CHAPTER")
        dim_map: Mapping of (identifier, type) -> DB Dimension

    Returns:
        The parent's database id, or None if not found
    """
    for (orig_id, dim_type), db_dim in dim_map.items():
        if orig_id == parent_identifier and (expected_type is None or dim_type == expected_type):
            return db_dim.id
    return None


def save_dimensions(
    session: Session, dimensions: List[Dimension], budget_db_id: int
) -> Dict[tuple, Dimension]:
    """
    Save dimensions using upsert logic:
    - Skip if exact match exists
    - Update if exists with parent_id=None
    - Add new row if exists with different parent_id

    Returns: mapping of (identifier, type) -> DB dimension
    """
    dim_map: Dict[tuple, Dimension] = {}

    # First pass: dimensions without parents
    for dim in dimensions:
        if dim.parent_id is not None:
            continue

        db_dim = upsert_dimension(
            session,
            original_identifier=dim.original_identifier,
            dim_type=dim.type,
            name=dim.name,
            parent_db_id=None,
            name_translated=dim.name_translated,
        )
        dim_map[(dim.original_identifier, dim.type)] = db_dim

    # Second pass: dimensions with parents
    for dim in dimensions:
        if dim.parent_id is None:
            continue

        # dim.parent_id is a string identifier (e.g., "01")
        # We need to find the DB id of that parent
        expected_parent_type = (
            "PROGRAM" if dim.type == "PROGRAM" else "CHAPTER" if dim.type == "SUBCHAPTER" else None
        )
        parent_db_id = _find_parent_db_id(str(dim.parent_id), expected_parent_type, dim_map)

        if parent_db_id is None:
            logger.warning(
                f"Parent '{dim.parent_id}' not found for {dim.original_identifier} ({dim.type})"
            )

        db_dim = upsert_dimension(
            session,
            original_identifier=dim.original_identifier,
            dim_type=dim.type,
            name=dim.name,
            parent_db_id=parent_db_id,
            name_translated=dim.name_translated,
        )
        dim_map[(dim.original_identifier, dim.type)] = db_dim

    session.flush()
    logger.info(f"Saved {len(dim_map)} dimensions")
    return dim_map


def save_expenses(
    session: Session, expenses: List[Expense], budget_db_id: int, dim_map: Dict[tuple, Dimension]
) -> None:
    """Save expenses with dimension links."""
    for expense in expenses:
        # Map in-memory dimensions to DB dimensions
        db_dims = []
        for dim in expense.dimensions:
            db_dim = dim_map.get((dim.original_identifier, dim.type))
            if db_dim:
                db_dims.append(db_dim)

        new_expense = Expense(
            budget_id=budget_db_id,
            value=expense.value,
            dimensions=db_dims,
        )
        session.add(new_expense)

    logger.info(f"Saved {len(expenses)} expenses")


# =============================================================================
# MAIN IMPORT FUNCTIONS
# =============================================================================


def import_budget_file(file_path: Path, file_type: Literal["law", "report"]) -> int:
    """
    Import a single budget file (LAW or REPORT).

    Steps:
        1. Parse file (read ONCE) → budget, dimensions, expenses
        2. Save budget → get budget_db_id
        3. Save dimensions → get dim_map
        4. Save expenses with dimension links

    Returns: budget database ID
    """
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Importing {file_type.upper()}: {file_path.name}")
    logger.info(f"{'=' * 60}")

    # Step 1: Parse (file read ONCE here)
    if file_type == "law":
        budget, dimensions, expenses = parse_law_file(file_path)
    else:
        budget, dimensions, expenses = parse_report_file(file_path)

    # Steps 2-4: Save to database
    with get_sync_session() as session:
        budget_db_id = save_budget(session, budget)
        dim_map = save_dimensions(session, dimensions, budget_db_id)
        save_expenses(session, expenses, budget_db_id, dim_map)
        session.commit()

    logger.info(f"✓ Imported {file_path.name} (ID: {budget_db_id})")
    return budget_db_id


def import_law_file(file_path: Path) -> int:
    """Import a single LAW file."""
    return import_budget_file(file_path, "law")


def import_report_file(file_path: Path) -> int:
    """Import a single REPORT file."""
    return import_budget_file(file_path, "report")


# =============================================================================
# FILE DISCOVERY
# =============================================================================


def get_law_files(data_dir: Path, years: List[int] | None = None) -> List[Path]:
    """Get law files for specified years (or all years 2018-2025)."""
    if years is None:
        years = list(range(2018, 2026))
    
    laws_dir = data_dir / "laws"
    return [laws_dir / f"law_{year}.xlsx" for year in years]


def get_report_files(data_dir: Path, years: List[int] | None = None) -> List[Path]:
    """
    Get report files for specified years (or all years 2018-2025).
    
    Reports are named: report_YYYY_MM.xlsx
    Returns all report files found for the specified years.
    """
    if years is None:
        years = list(range(2018, 2026))
    
    reports_dir = data_dir / "reports"
    
    if not reports_dir.exists():
        logger.warning(f"Reports directory not found: {reports_dir}")
        return []
    
    files = []
    for year in years:
        # Find all report files for this year
        pattern = f"report_{year}_*.xls*"
        year_files = sorted(reports_dir.glob(pattern))
        files.extend(year_files)
    
    return files


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Import budget data")
    parser.add_argument(
        "--type",
        type=str,
        choices=["law", "report", "all"],
        default="law",
        help="Type of files to import: law, report, or all (default: law)",
    )
    parser.add_argument("--years", nargs="+", type=int, help="Years to import")
    parser.add_argument("--file", type=Path, help="Single file to import")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).parent.parent / "data" / "import_files" / "clean",
        help="Directory with import files",
    )
    args = parser.parse_args()

    success, failed = [], []

    # Single file import
    if args.file:
        file_path = args.file
        # Detect type from filename
        if file_path.name.startswith("law"):
            file_type = "law"
        elif file_path.name.startswith("report"):
            file_type = "report"
        else:
            logger.error(f"Cannot determine file type from filename: {file_path.name}")
            sys.exit(1)
        
        try:
            import_budget_file(file_path, file_type)
            success.append(file_path.name)
        except Exception as e:
            logger.error(f"Failed: {e}", exc_info=True)
            failed.append((file_path.name, str(e)))
    
    else:
        # Batch import
        files_to_import: List[tuple[Path, Literal["law", "report"]]] = []
        
        if args.type in ("law", "all"):
            for f in get_law_files(args.data_dir, args.years):
                files_to_import.append((f, "law"))
        
        if args.type in ("report", "all"):
            for f in get_report_files(args.data_dir, args.years):
                files_to_import.append((f, "report"))
        
        # Import files
        for file_path, file_type in files_to_import:
            if not file_path.exists():
                logger.warning(f"File not found: {file_path}")
                failed.append((file_path.name, "not found"))
                continue

            try:
                import_budget_file(file_path, file_type)
                success.append(file_path.name)
            except Exception as e:
                logger.error(f"Failed: {e}", exc_info=True)
                failed.append((file_path.name, str(e)))

    # Summary
    logger.info(f"\n{'=' * 60}")
    logger.info(f"DONE: {len(success)} success, {len(failed)} failed")
    if failed:
        for name, err in failed:
            logger.error(f"  ✗ {name}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()