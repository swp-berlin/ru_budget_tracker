"""
Budget import script.

Clean, human-readable import logic. Each file is read ONCE.

Usage:
    python import.py                      # Import all laws 2018-2025
    python import.py --years 2020 2021    # Import specific years
    python import.py --file law_2024.xlsx # Import single file
"""

import sys
import argparse
from pathlib import Path
from typing import List, Dict, Optional
import logging

# Add parent to path if needed
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from models import Budget, Dimension, Expense
from database.sessions import get_sync_session
from parsers import parse_law_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

def save_budget(session: Session, budget: Budget) -> int:
    """
    Save or update budget in database.
    
    Returns: database ID
    """
    existing = session.query(Budget).filter_by(
        original_identifier=budget.original_identifier
    ).first()

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
    parent_db_id: int | None,  # Renamed for clarity: this is the DB id, not the string identifier
    name_translated: str | None = None,
) -> Dimension:
    """
    Upsert dimension with special parent_id handling:
    
    1. If exists with same parent_id → skip (return existing)
    2. If exists with parent_id=None → update to new parent_id
    3. If exists with different non-null parent_id → add new row
    """
    # First: check for exact match (same parent_id) → skip
    exact_match = session.query(Dimension).filter_by(
        original_identifier=original_identifier,
        type=dim_type,
        name=name,
        parent_id=parent_db_id,
    ).first()

    if exact_match:
        logger.debug(f"Exact match found: {original_identifier} ({dim_type})")
        return exact_match

    # Second: check for match with parent_id=None → update
    if parent_db_id is not None:
        null_parent = session.query(Dimension).filter_by(
            original_identifier=original_identifier,
            type=dim_type,
            name=name,
            parent_id=None,
        ).first()

        if null_parent:
            logger.debug(f"Updating null parent: {original_identifier} ({dim_type}) -> parent_id={parent_db_id}")
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
    parent_identifier: str,
    expected_type: str | None,
    dim_map: Dict[tuple, Dimension]
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
    session: Session,
    dimensions: List[Dimension],
    budget_db_id: int
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
        expected_parent_type = "PROGRAM" if dim.type == "PROGRAM" else "CHAPTER" if dim.type == "SUBCHAPTER" else None
        parent_db_id = _find_parent_db_id(dim.parent_id, expected_parent_type, dim_map)

        if parent_db_id is None:
            logger.warning(f"Parent '{dim.parent_id}' not found for {dim.original_identifier} ({dim.type})")

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
    session: Session,
    expenses: List[Expense],
    budget_db_id: int,
    dim_map: Dict[tuple, Dimension]
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
# MAIN IMPORT FUNCTION
# =============================================================================

def import_law_file(file_path: Path) -> int:
    """
    Import a single LAW file.
    
    Steps:
        1. Parse file (read ONCE) → budget, dimensions, expenses
        2. Save budget → get budget_db_id
        3. Save dimensions → get dim_map
        4. Save expenses with dimension links
    
    Returns: budget database ID
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"Importing: {file_path.name}")
    logger.info(f"{'='*60}")

    # Step 1: Parse (file read ONCE here)
    budget, dimensions, expenses = parse_law_file(file_path)

    # Steps 2-4: Save to database
    with get_sync_session() as session:
        budget_db_id = save_budget(session, budget)
        dim_map = save_dimensions(session, dimensions, budget_db_id)
        save_expenses(session, expenses, budget_db_id, dim_map)
        session.commit()

    logger.info(f"✓ Imported {file_path.name} (ID: {budget_db_id})")
    return budget_db_id


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Import budget data")
    parser.add_argument("--years", nargs="+", type=int, help="Years to import")
    parser.add_argument("--file", type=Path, help="Single file to import")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/import_files/clean/laws"),
        help="Directory with import files"
    )
    args = parser.parse_args()

    # Determine files
    if args.file:
        files = [args.file]
    elif args.years:
        files = [args.data_dir / f"law_{y}.xlsx" for y in args.years]
    else:
        files = [args.data_dir / f"law_{y}.xlsx" for y in range(2018, 2026)]

    # Import
    success, failed = [], []

    for f in files:
        if not f.exists():
            logger.warning(f"File not found: {f}")
            failed.append((f.name, "not found"))
            continue

        try:
            import_law_file(f)
            success.append(f.name)
        except Exception as e:
            logger.error(f"Failed: {e}", exc_info=True)
            failed.append((f.name, str(e)))

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"DONE: {len(success)} success, {len(failed)} failed")
    if failed:
        for name, err in failed:
            logger.error(f"  ✗ {name}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
