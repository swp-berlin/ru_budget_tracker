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

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

# Add parent to path if needed
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.sessions import get_sync_session
from models import Dimension, Expense

# DB write layer lives in scripts/db_writer.py; names imported here so
# scripts.import keeps its public attributes (tests and callers import them).
from scripts.db_writer import (
    get_chapter_dimensions,
    save_budget,
    save_conversion_rates,
    save_dimensions,
    save_expenses,
)
from scripts.parsers import (
    fetch_ppp_api_data,
    fetch_ppp_rates,
    parse_gdp_files,
    parse_law_file,
    parse_report_file,
    parse_totals_file,
    save_ppp_csv,
)
from scripts.parsers.issues import IssueCollector
from settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _issue_file_path(source_file: Path) -> Path:
    """Where the per-file parse-issue JSON is written (next to the database)."""
    return settings.database.directory / "quality" / "issues" / f"{source_file.stem}.json"


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

    issues = IssueCollector(file_path.name)

    # Step 1: Parse (file read ONCE here)
    if file_type == "law":
        budget, dimensions, expenses = parse_law_file(file_path, issues=issues)
    else:
        budget, dimensions, expenses = parse_report_file(file_path, issues=issues)

    # Steps 2-4: Save to database
    with get_sync_session() as session:
        budget_db_id = save_budget(session, budget)
        dim_map = save_dimensions(session, dimensions, budget_db_id, issues=issues)
        save_expenses(session, expenses, budget_db_id, dim_map)
        session.commit()

    issues.write_json(_issue_file_path(file_path))
    if len(issues):
        logger.info(f"Recorded {len(issues)} data-quality issue(s): {issues.counts_by_code()}")

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

    issues = IssueCollector(file_path.name)
    budgets, chapter_codes, expenses_with_chapter = parse_totals_file(file_path, issues=issues)

    if not budgets:
        logger.warning(f"No data found in {file_path.name}")
        issues.add("no_data_parsed", "No budgets parsed from totals file", severity="ERROR")
        issues.write_json(_issue_file_path(file_path))
        return 0

    with get_sync_session() as session:
        # Get existing chapter dimensions from the database
        chapter_dimensions = get_chapter_dimensions(session, chapter_codes, issues=issues)

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
                        issues.add(
                            "chapter_dimension_missing",
                            f"Chapter {chapter_code} not in database; expense for "
                            f"{budget.original_identifier} saved without dimension",
                        )

                new_expense = Expense(
                    budget_id=budget_db_id,
                    value=expense.value,
                    dimensions=db_dims,
                )
                session.add(new_expense)

            count += 1

        session.commit()

    issues.write_json(_issue_file_path(file_path))
    if len(issues):
        logger.info(f"Recorded {len(issues)} data-quality issue(s): {issues.counts_by_code()}")

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
    """Get law files: all law_*.xlsx on disk, or explicit paths for the given years.

    With no year filter, every file on disk is discovered — nothing is
    silently skipped by a year window. (The golden test suite forces a
    deliberately generated golden for any new file.)
    """
    laws_dir = data_dir / "laws"
    if years is None:
        return sorted(laws_dir.glob("law_*.xlsx"))

    return [laws_dir / f"law_{year}.xlsx" for year in years]


def get_report_files(data_dir: Path, years: List[int] | None = None) -> List[Path]:
    """
    Get report files: all report_YYYY_MM.xls* on disk, optionally filtered by year.

    With no year filter, every file on disk is discovered — nothing is
    silently skipped by a year window.
    """
    reports_dir = data_dir / "reports"

    if not reports_dir.exists():
        logger.warning(f"Reports directory not found: {reports_dir}")
        return []

    if years is None:
        return sorted(reports_dir.glob("report_*_*.xls*"))

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
    # Imported here, not at module level: ImporterSettings requires env vars
    # (DEEPL_API_KEY, NEXTCLOUD_DOWNLOAD_LINK) that only the CLI needs.
    from settings_importer import importer_settings

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
        default=importer_settings.data_dir,  # Path(__file__).parent.parent / "data" / "import_files" / "clean",
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
        default=importer_settings.data_dir,
        help="Directory with import files (used to locate related dirs if needed)",
    )

    # -------------------------
    # gdp subcommand
    # -------------------------
    p_gdp = subparsers.add_parser("gdp", help="Import GDP conversion data")
    p_gdp.add_argument(
        "--data-dir",
        type=Path,
        default=importer_settings.data_dir,  # Path(__file__).parent.parent / "data" / "import_files" / "clean",
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
                raise SystemExit(
                    "Provide both --rosstat and --minekonom, or neither (for auto-discovery)."
                )
            else:
                raw_dir = importer_settings.raw_dir  # args.data_dir.parent / "raw"
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
