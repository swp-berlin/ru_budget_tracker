"""
Budget import CLI.

Reads each input file once and writes parsed data to the database.

Commands:
  budget   Import LAW/REPORT budget files
  totals   Import totals spreadsheet (monthly aggregates)
  gdp      Import GDP conversion data (Rosstat + Minekonom)

Examples:
  python import.py budget
  python import.py budget --type report --years 2018 2019
  python import.py budget --file path/to/law_2024.xlsx
  python import.py totals path/to/totals.xlsx
  python import.py gdp
  python import.py gdp --rosstat path/to/rosstat.xlsx --minekonom path/to/minekonom.xlsx
  python import.py ppp

Notes:
  - Totals import expects CHAPTER dimensions to exist (import LAW files first).
  - GDP auto-discovery searches under: <data-dir-parent>/raw/conversion_tables/gdp/{rosstat,minekonom}/
  - PPP fetches from World Bank API, falls back to CSV cache on failure.
"""

import sys
import argparse
from pathlib import Path
from typing import List, Dict, Literal, Optional, Tuple
import logging

# Add parent to path if needed
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import Session
from models import Budget, Dimension, Expense, ConversionRate
from database.sessions import get_sync_session
from parsers import (
    parse_law_file,
    parse_report_file,
    parse_totals_file,
    fetch_ppp_rates,
    save_ppp_csv,
    fetch_ppp_api_data,
)
        

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


def get_chapter_dimensions(session: Session, chapter_codes: List[str]) -> List[Dimension]:
    """
    Get existing CHAPTER dimensions from the database.
    
    If a chapter code exists multiple times (e.g., with different names),
    only one is returned per code (the first one found).
    
    Args:
        session: Database session
        chapter_codes: List of chapter codes to find (e.g., ["01", "02", ..., "14"])
        
    Returns:
        List of Dimension objects for matching chapters (one per code)
    """
    all_chapters = (
        session.query(Dimension)
        .filter(
            Dimension.type == "CHAPTER",
            Dimension.original_identifier.in_(chapter_codes),
        )
        .all()
    )
    
    # Deduplicate: keep only one per original_identifier
    seen_codes: set = set()
    chapters: List[Dimension] = []
    for chapter in all_chapters:
        if chapter.original_identifier not in seen_codes:
            seen_codes.add(chapter.original_identifier)
            chapters.append(chapter)
        else:
            logger.debug(
                f"Skipping duplicate chapter {chapter.original_identifier}: {chapter.name[:50]}"
            )
    
    found_codes = {c.original_identifier for c in chapters}
    missing = set(chapter_codes) - found_codes
    
    if missing:
        logger.warning(f"Missing chapter dimensions: {sorted(missing)}")
    
    if len(all_chapters) != len(chapters):
        logger.info(
            f"Found {len(all_chapters)} chapter rows, deduplicated to {len(chapters)} unique codes"
        )
    else:
        logger.info(f"Found {len(chapters)} of {len(chapter_codes)} chapter dimensions")
    
    return chapters


## GDP FUNCTIONS 


def save_conversion_rates(session, rates: List) -> Tuple[int, int]:
    """
    Save ConversionRate entries to database (upsert by name).
    
    Returns: (inserted_count, updated_count)
    """
    inserted, updated = 0, 0
    
    for rate in rates:
        existing = session.query(ConversionRate).filter_by(name=rate.name).first()
        if existing:
            existing.value = rate.value
            existing.started_at = rate.started_at
            existing.ended_at = rate.ended_at
            updated += 1
        else:
            session.add(rate)
            inserted += 1
    
    session.flush()
    return inserted, updated




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


def import_totals_file(file_path: Path) -> int:
    """
    Import a totals file.
    
    Creates per month (from 2018 onwards):
    - 1 Budget for total revenue (TOTAL-REVENUE-YYYY-MM) with 1 expense, no dimensions
    - 1 Budget for total expenses (TOTAL-EXPENSE-YYYY-MM) with 15 expenses:
      - 1 total expense (no dimensions)
      - 14 chapter expenses (each linked to one chapter)
    
    IMPORTANT: Law files must be imported first to create the CHAPTER dimensions.
    
    Returns: number of budgets imported
    """
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Importing TOTALS: {file_path.name}")
    logger.info(f"{'=' * 60}")

    budgets, chapter_codes, expenses_with_chapter = parse_totals_file(file_path)
    
    if not budgets:
        logger.warning(f"No data found in {file_path.name}")
        return 0

    with get_sync_session() as session:
        # Get existing chapter dimensions from the database
        chapter_dimensions = get_chapter_dimensions(session, chapter_codes)
        
        if not chapter_dimensions:
            logger.warning(
                "No CHAPTER dimensions found in database. "
                "Import LAW files first to create chapters."
            )
        
        # Build lookup: chapter_code -> Dimension
        chapter_lookup: Dict[str, Dimension] = {
            dim.original_identifier: dim for dim in chapter_dimensions
        }
        
        # Group expenses by budget identifier
        expenses_by_budget: Dict[str, List[Tuple[Expense, Optional[str]]]] = {}
        for budget_id, expense, chapter_code in expenses_with_chapter:
            if budget_id not in expenses_by_budget:
                expenses_by_budget[budget_id] = []
            expenses_by_budget[budget_id].append((expense, chapter_code))
        
        # Save each budget and its expenses
        count = 0
        for budget in budgets:
            budget_db_id = save_budget(session, budget)
            
            budget_expenses = expenses_by_budget.get(budget.original_identifier, [])
            for expense, chapter_code in budget_expenses:
                # Link to chapter dimension if specified
                db_dims: List[Dimension] = []
                if chapter_code:
                    chapter_dim = chapter_lookup.get(chapter_code)
                    if chapter_dim:
                        db_dims.append(chapter_dim)
                    else:
                        logger.warning(f"Chapter {chapter_code} not found in database")
                
                new_expense = Expense(
                    budget_id=budget_db_id,
                    value=expense.value,
                    dimensions=db_dims,
                )
                session.add(new_expense)
            
            count += 1
        
        session.commit()

    # Summary
    years = sorted(set(b.published_at.year for b in budgets))
    revenue_count = len([b for b in budgets if "REVENUE" in b.original_identifier])
    expense_count = len([b for b in budgets if "EXPENSE" in b.original_identifier])
    
    logger.info(f"✓ Imported {count} budgets")
    logger.info(f"  Revenue budgets: {revenue_count} (1 expense each, no dimensions)")
    logger.info(f"  Expense budgets: {expense_count} (15 expenses each: 1 total + 14 per chapter)")
    logger.info(f"  Years: {min(years)} - {max(years)}")
    
    return count

def import_gdp_data(rosstat_path: Path, minekonom_path: Path) -> None:
    """
    Import GDP data from Rosstat and Minekonom files.
    
    Creates ConversionRate entries:
    - Quarterly: gdp_YYYY_qN (e.g., gdp_2024_q1)
    - Yearly: gdp_YYYY (e.g., gdp_2024)
    - Estimates: gdp_YYYY_qN_estimate or gdp_YYYY_estimate
    """
    from parsers import parse_gdp_files
    from database.sessions import get_sync_session
    
    logger.info(f"Parsing GDP files...")
    logger.info(f"  Rosstat: {rosstat_path}")
    logger.info(f"  Minekonom: {minekonom_path}")
    
    quarterly_rates, yearly_rates = parse_gdp_files(rosstat_path, minekonom_path)
    
    with get_sync_session() as session:
        q_ins, q_upd = save_conversion_rates(session, quarterly_rates)
        y_ins, y_upd = save_conversion_rates(session, yearly_rates)
        session.commit()
    
    logger.info(f"✓ Quarterly GDP: {q_ins} inserted, {q_upd} updated")
    logger.info(f"✓ Yearly GDP: {y_ins} inserted, {y_upd} updated")


def import_ppp_data(save_csv: bool = True) -> None:
    """
    Import PPP data from World Bank API (with CSV fallback).
    
    Creates ConversionRate entries:
    - Yearly: ppp_YYYY (e.g., ppp_2024)
    - Imputed: ppp_YYYY_imputed_SSSS (e.g., ppp_2025_imputed_2024)
    
    Args:
        save_csv: If True, updates CSV cache when API fetch succeeds
    """
    logger.info("Fetching PPP data...")
    
    # Try to update CSV cache if API works
    if save_csv:
        try:
            ppp_data = fetch_ppp_api_data()
            save_ppp_csv(ppp_data)
        except Exception as e:
            logger.warning(f"Could not update CSV cache: {e}")
    
    rates = fetch_ppp_rates()
    
    with get_sync_session() as session:
        ins, upd = save_conversion_rates(session, rates)
        session.commit()
    
    logger.info(f"✓ PPP: {ins} inserted, {upd} updated")





# =============================================================================
# FILE DISCOVERY
# =============================================================================


def get_law_files(data_dir: Path, years: List[int] | None = None) -> List[Path]:
    """Get law files for specified years (or all years 2018-2025)."""
    if years is None:
        years = list(range(2018, 2027))
    
    laws_dir = data_dir / "laws"
    return [laws_dir / f"law_{year}.xlsx" for year in years]


def get_report_files(data_dir: Path, years: List[int] | None = None) -> List[Path]:
    """
    Get report files for specified years (or all years 2018-2025).
    
    Reports are named: report_YYYY_MM.xlsx
    Returns all report files found for the specified years.
    """
    if years is None:
        years = list(range(2018, 2027))
    
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


def find_gdp_files(raw_dir: Path) -> Tuple[Path, Path]:
    """
    Auto-discover GDP files in the raw data directory.
    
    Expects:
        raw_dir/conversion_tables/gdp/rosstat/*.xlsx
        raw_dir/conversion_tables/gdp/minekonom/*.xlsx
    
    Returns: (rosstat_path, minekonom_path)
    """
    rosstat_dir = raw_dir / "conversion_tables" / "gdp" / "rosstat"
    minekonom_dir = raw_dir / "conversion_tables" / "gdp" / "minekonom"
    
    rosstat_files = list(rosstat_dir.glob("*.xlsx")) if rosstat_dir.exists() else []
    minekonom_files = list(minekonom_dir.glob("*.xlsx")) if minekonom_dir.exists() else []
    
    if not rosstat_files:
        raise FileNotFoundError(f"No Rosstat files found in {rosstat_dir}")
    if not minekonom_files:
        raise FileNotFoundError(f"No Minekonom files found in {minekonom_dir}")
    
    return rosstat_files[0], minekonom_files[0]


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Import budget data")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # -------------------------
    # budget subcommand
    # -------------------------
    p_budget = subparsers.add_parser("budget", help="Import budget laws/reports")
    p_budget.add_argument(
        "--type",
        choices=["law", "report", "all"],
        default="law",
        help="Type of files to import (default: law)",
    )
    p_budget.add_argument("--years", nargs="+", type=int, help="Years to import")
    p_budget.add_argument("--file", type=Path, help="Single file to import")
    p_budget.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).parent.parent / "data" / "import_files" / "clean",
        help="Directory with import files",
    )

    # -------------------------
    # totals subcommand
    # -------------------------
    p_totals = subparsers.add_parser("totals", help="Import totals file")
    p_totals.add_argument("totals_path", type=Path, help="Path to totals xlsx")
    p_totals.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).parent.parent / "data" / "import_files" / "clean",
        help="Directory with import files (used to locate related dirs if needed)",
    )

    # -------------------------
    # gdp subcommand
    # -------------------------
    p_gdp = subparsers.add_parser("gdp", help="Import GDP conversion data")
    p_gdp.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).parent.parent / "data" / "import_files" / "clean",
        help="Directory with import files (used to locate raw/ for auto-discovery)",
    )
    p_gdp.add_argument("--rosstat", type=Path, help="Path to Rosstat quarterly GDP file")
    p_gdp.add_argument("--minekonom", type=Path, help="Path to Minekonom yearly GDP file")

    # -------------------------
    # ppp subcommand
    # -------------------------
    p_ppp = subparsers.add_parser("ppp", help="Import PPP conversion data from World Bank")
    p_ppp.add_argument(
        "--no-save-csv",
        action="store_true",
        help="Don't update CSV cache when API fetch succeeds",
    )

    args = parser.parse_args()

    success, failed = [], []

    # =========================
    # budget command
    # =========================
    if args.command == "budget":
        if args.file:
            file_path = args.file
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
            files_to_import: List[tuple[Path, Literal["law", "report"]]] = []

            if args.type in ("law", "all"):
                for f in get_law_files(args.data_dir, args.years):
                    files_to_import.append((f, "law"))

            if args.type in ("report", "all"):
                for f in get_report_files(args.data_dir, args.years):
                    files_to_import.append((f, "report"))

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

    # =========================
    # totals command
    # =========================
    elif args.command == "totals":
        totals_path = args.totals_path
        if not totals_path.exists():
            logger.error(f"Totals file not found: {totals_path}")
            sys.exit(1)
        try:
            import_totals_file(totals_path)
            success.append(totals_path.name)
        except Exception as e:
            logger.error(f"Failed to import totals: {e}", exc_info=True)
            failed.append((totals_path.name, str(e)))

    # =========================
    # gdp command
    # =========================
    elif args.command == "gdp":
        try:
            if args.rosstat and args.minekonom:
                rosstat_path, minekonom_path = args.rosstat, args.minekonom
            elif args.rosstat or args.minekonom:
                raise SystemExit("Provide both --rosstat and --minekonom, or neither (for auto-discovery).")
            else:
                raw_dir = args.data_dir.parent / "raw"
                rosstat_path, minekonom_path = find_gdp_files(raw_dir)

            import_gdp_data(rosstat_path, minekonom_path)
            success.append("GDP data")
        except Exception as e:
            logger.error(f"GDP import failed: {e}", exc_info=True)
            failed.append(("GDP data", str(e)))

    # =========================
    # ppp command
    # =========================
    elif args.command == "ppp":
        try:
            import_ppp_data(save_csv=not args.no_save_csv)
            success.append("PPP data")
        except Exception as e:
            logger.error(f"PPP import failed: {e}", exc_info=True)
            failed.append(("PPP data", str(e)))

    # Summary
    logger.info(f"\n{'=' * 60}")
    logger.info(f"DONE: {len(success)} success, {len(failed)} failed")
    if failed:
        for name, err in failed:
            logger.error(f"  ✗ {name}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()