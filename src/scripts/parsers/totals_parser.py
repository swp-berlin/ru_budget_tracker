"""
TOTALS parser for federal budget summary data.

Handles two file types:
1. total_report_YYYY.xlsx - Monthly budget execution (REPORT) data
2. total_law_YYYY.csv - Annual budget law (LAW) data

REPORT totals (from xlsx):
    Creates per month:
    - 1 Budget for total REVENUE (TOTAL-REPORT-REVENUE-YYYY-MM) with 1 Expense (no dimensions)
    - 1 Budget for total EXPENSES (TOTAL-REPORT-EXPENSE-YYYY-MM) with 15 Expenses:
      - 1 total expense (no dimensions) - from row "2"
      - 14 chapter expenses (each linked to one CHAPTER dimension 01-14) - from rows 2.1-2.14

LAW totals (from csv):
    Creates per year:
    - 1 Budget for total EXPENSES (TOTAL-LAW-EXPENSE-YYYY) with 15 Expenses:
      - 1 total expense (no dimensions) - from RZ=0
      - 14 chapter expenses (each linked to one CHAPTER dimension 01-14) - from RZ=1-14

The functional sections in the report file (2.1 - 2.14) map directly to
budget chapters (01 - 14):
    2.1.  -> Chapter 01 (Общегосударственные вопросы)
    2.2.  -> Chapter 02 (Национальная оборона)
    ...
    2.14. -> Chapter 14 (Межбюджетные трансферты)

Values in report xlsx are in BILLIONS of rubles.
Values in law csv are already in RUBLES.
Values stored in database are always in RUBLES.
"""

import re
import pandas as pd
from pathlib import Path
from datetime import date, datetime
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass, field
import logging

from models import Budget, Expense

logger = logging.getLogger(__name__)

TOTALS_SHEET_NAME = "месяц"
BILLION = 1_000_000_000

# Mapping from functional section indicator to chapter code
FUNCTIONAL_TO_CHAPTER = {
    "2.1.": "01",  # Общегосударственные вопросы
    "2.2.": "02",  # Национальная оборона
    "2.3.": "03",  # Национальная безопасность и правоохранительная деятельность
    "2.4.": "04",  # Национальная экономика
    "2.5.": "05",  # Жилищно-коммунальное хозяйство
    "2.6.": "06",  # Охрана окружающей среды
    "2.7.": "07",  # Образование
    "2.8.": "08",  # Культура, кинематография
    "2.9.": "09",  # Здравоохранение
    "2.10.": "10",  # Социальная политика
    "2.11.": "11",  # Физическая культура и спорт
    "2.12.": "12",  # Средства массовой информации
    "2.13.": "13",  # Обслуживание государственного и муниципального долга
    "2.14.": "14",  # Межбюджетные трансферты общего характера
}

# Mapping from RZ code (int) in CSV to chapter code (str)
RZ_TO_CHAPTER = {i: f"{i:02d}" for i in range(1, 15)}


@dataclass
class ChapterExpense:
    """Expense value for a specific chapter."""

    chapter_code: str
    value: float


@dataclass
class ParsedReportMonth:
    """Parsed data for a single month from report xlsx."""

    date: date
    year: int
    month: int
    total_revenue: Optional[float] = None
    total_expenses: Optional[float] = None
    chapter_expenses: List[ChapterExpense] = field(default_factory=list)


@dataclass
class ParsedLawYear:
    """Parsed data for a single year from law csv."""

    year: int
    total_expenses: Optional[float] = None
    chapter_expenses: List[ChapterExpense] = field(default_factory=list)


# =============================================================================
# REPORT XLSX PARSING
# =============================================================================


def read_report_excel(file_path: Path) -> pd.DataFrame:
    """Read the totals report Excel file."""
    df = pd.read_excel(
        file_path,
        sheet_name=TOTALS_SHEET_NAME,
        header=None,
        engine="openpyxl",
    )
    logger.info(f"Read sheet '{TOTALS_SHEET_NAME}' with shape {df.shape}")
    return df


def parse_column_dates(df: pd.DataFrame) -> Dict[int, date]:
    """Parse column headers to extract dates."""
    header_row = df.iloc[2]
    col_dates: Dict[int, date] = {}

    month_map = {
        "янв": 1,
        "фев": 2,
        "мар": 3,
        "апр": 4,
        "май": 5,
        "июн": 6,
        "июл": 7,
        "авг": 8,
        "сен": 9,
        "окт": 10,
        "ноя": 11,
        "дек": 12,
    }

    for col_idx in range(2, len(header_row)):
        val = header_row.iloc[col_idx]
        if pd.isna(val):
            continue

        if isinstance(val, (datetime, pd.Timestamp)):
            col_dates[col_idx] = (
                val.date() if hasattr(val, "date") else date(val.year, val.month, val.day)
            )
            continue

        val_str = str(val).strip().lower()
        for month_abbr, month_num in month_map.items():
            if month_abbr in val_str:
                year_match = re.search(r"\.(\d{2})", val_str)
                if year_match:
                    year = 2000 + int(year_match.group(1))
                    col_dates[col_idx] = date(year, month_num, 1)
                    break

    return col_dates


def get_row_index_by_indicator(df: pd.DataFrame, indicator: str) -> Optional[int]:
    """Find row index by its indicator code in column 0."""
    for idx in range(len(df)):
        row_indicator = df.iloc[idx, 0]
        if pd.notna(row_indicator) and str(row_indicator).strip() == indicator:
            return idx
    return None


def get_functional_section_rows(df: pd.DataFrame) -> Dict[str, int]:
    """Find row indices for all functional sections (2.1. - 2.14.)."""
    rows: Dict[str, int] = {}
    for indicator in FUNCTIONAL_TO_CHAPTER.keys():
        idx = get_row_index_by_indicator(df, indicator)
        if idx is not None:
            rows[indicator] = idx
        else:
            logger.warning(f"Could not find row for functional section {indicator}")
    return rows


def parse_cell_value_billions(df: pd.DataFrame, row_idx: int, col_idx: int) -> Optional[float]:
    """Safely parse a cell value as float, converting from billions to rubles."""
    val = df.iloc[row_idx, col_idx]
    if pd.notna(val):
        try:
            return float(str(val)) * BILLION
        except (ValueError, TypeError):
            pass
    return None


def parse_report_file(
    file_path: Path,
    start_year: int = 2018,
) -> Tuple[List[Budget], List[str], List[Tuple[str, Expense, Optional[str]]]]:
    """
    Parse a totals report xlsx file (budget execution data).

    Creates per month:
    - 1 Budget "TOTAL-REPORT-REVENUE-YYYY-MM" with 1 Expense (no dimensions)
    - 1 Budget "TOTAL-REPORT-EXPENSE-YYYY-MM" with 15 Expenses:
      - 1 total expense (no dimensions)
      - 14 chapter expenses (each linked to one chapter 01-14)
    """
    logger.info(f"Parsing report totals file: {file_path.name}")

    df = read_report_excel(file_path)
    col_dates = parse_column_dates(df)

    revenue_row_idx = get_row_index_by_indicator(df, "1")
    expense_row_idx = get_row_index_by_indicator(df, "2")
    functional_section_rows = get_functional_section_rows(df)

    if revenue_row_idx is None:
        logger.error("Could not find revenue row (indicator '1')")
    if expense_row_idx is None:
        logger.error("Could not find total expense row (indicator '2')")

    logger.info(f"Found {len(functional_section_rows)} functional section rows")

    months: List[ParsedReportMonth] = []
    for col_idx, col_date in sorted(col_dates.items()):
        if col_date.year < start_year:
            continue

        month = ParsedReportMonth(date=col_date, year=col_date.year, month=col_date.month)

        if revenue_row_idx is not None:
            month.total_revenue = parse_cell_value_billions(df, revenue_row_idx, col_idx)

        if expense_row_idx is not None:
            month.total_expenses = parse_cell_value_billions(df, expense_row_idx, col_idx)

        for indicator, row_idx in functional_section_rows.items():
            chapter_code = FUNCTIONAL_TO_CHAPTER[indicator]
            value = parse_cell_value_billions(df, row_idx, col_idx)
            if value is not None:
                month.chapter_expenses.append(
                    ChapterExpense(
                        chapter_code=chapter_code,
                        value=value,
                    )
                )

        months.append(month)

    logger.info(f"Parsed {len(months)} months from {start_year}")

    budgets: List[Budget] = []
    expenses: List[Tuple[str, Expense, Optional[str]]] = []

    for month in months:
        if month.total_revenue is not None:
            rev_budget_id = f"TOTAL-REPORT-REVENUE-{month.year}-{month.month:02d}"
            rev_budget = Budget(
                original_identifier=rev_budget_id,
                name=f"Total Federal Revenue (Report) {month.year}-{month.month:02d}",
                name_translated=None,
                description=f"Federal budget revenue execution for {month.year}-{month.month:02d}",
                description_translated=None,
                type="TOTAL",
                scope="MONTHLY",
                published_at=month.date,
                planned_at=None,
            )
            budgets.append(rev_budget)

            rev_expense = Expense(budget_id=None, value=month.total_revenue)
            expenses.append((rev_budget_id, rev_expense, None))

        if month.total_expenses is not None or month.chapter_expenses:
            exp_budget_id = f"TOTAL-REPORT-EXPENSE-{month.year}-{month.month:02d}"
            exp_budget = Budget(
                original_identifier=exp_budget_id,
                name=f"Total Federal Expenses (Report) {month.year}-{month.month:02d}",
                name_translated=None,
                description=f"Federal budget expense execution for {month.year}-{month.month:02d}",
                description_translated=None,
                type="TOTAL",
                scope="MONTHLY",
                published_at=month.date,
                planned_at=None,
            )
            budgets.append(exp_budget)

            if month.total_expenses is not None:
                total_exp = Expense(budget_id=None, value=month.total_expenses)
                expenses.append((exp_budget_id, total_exp, None))

            for chapter_exp in month.chapter_expenses:
                exp = Expense(budget_id=None, value=chapter_exp.value)
                expenses.append((exp_budget_id, exp, chapter_exp.chapter_code))

    chapter_codes = list(FUNCTIONAL_TO_CHAPTER.values())
    revenue_budgets = len([b for b in budgets if "REVENUE" in b.original_identifier])
    expense_budgets = len([b for b in budgets if "EXPENSE" in b.original_identifier])

    logger.info(
        f"Created {len(budgets)} budgets ({revenue_budgets} revenue, {expense_budgets} expense)"
    )
    logger.info(f"Created {len(expenses)} expense entries")

    return budgets, chapter_codes, expenses


# =============================================================================
# LAW CSV PARSING
# =============================================================================


def read_law_csv(file_path: Path) -> pd.DataFrame:
    """Read the totals law CSV file."""
    df = pd.read_csv(file_path, sep=";")
    # Drop empty rows
    df = df.dropna(subset=["year", "RZ", "Budget"])
    logger.info(f"Read CSV with shape {df.shape}, columns: {list(df.columns)}")
    return df


def parse_budget_value(value) -> float:
    """Parse budget value, handling comma decimal separators."""
    if pd.isna(value):
        return 0.0
    val_str = str(value).strip()
    # Handle comma as decimal separator (e.g., "2757480200,00")
    val_str = val_str.replace(",", ".")
    return float(val_str)


def parse_law_file(
    file_path: Path,
    start_year: int = 2018,
) -> Tuple[List[Budget], List[str], List[Tuple[str, Expense, Optional[str]]]]:
    """
    Parse a totals law csv file (annual budget law data).

    Creates per year:
    - 1 Budget "TOTAL-LAW-EXPENSE-YYYY" with 15 Expenses:
      - 1 total expense (no dimensions) - from RZ=0
      - 14 chapter expenses (each linked to one chapter 01-14) - from RZ=1-14
    """
    logger.info(f"Parsing law totals file: {file_path.name}")

    df = read_law_csv(file_path)

    years_data: Dict[int, ParsedLawYear] = {}

    for _, row in df.iterrows():
        try:
            year = int(row["year"])
        except (ValueError, TypeError):
            continue  # Skip invalid rows

        if year < start_year:
            continue

        rz = int(row["RZ"])
        budget_value = parse_budget_value(row["Budget"])

        if year not in years_data:
            years_data[year] = ParsedLawYear(year=year)

        if rz == 0:
            years_data[year].total_expenses = budget_value
        elif rz in RZ_TO_CHAPTER:
            chapter_code = RZ_TO_CHAPTER[rz]
            years_data[year].chapter_expenses.append(
                ChapterExpense(
                    chapter_code=chapter_code,
                    value=budget_value,
                )
            )

    logger.info(f"Parsed {len(years_data)} years from {start_year}")

    # Compute total from chapters if RZ=0 was missing
    for year, year_data in years_data.items():
        if year_data.total_expenses is None and year_data.chapter_expenses:
            computed_total = sum(ce.value for ce in year_data.chapter_expenses)
            year_data.total_expenses = computed_total
            logger.info(
                f"Year {year}: computed total {computed_total:,.0f} from chapter sum (RZ=0 missing)"
            )

    budgets: List[Budget] = []
    expenses: List[Tuple[str, Expense, Optional[str]]] = []

    for year in sorted(years_data.keys()):
        year_data = years_data[year]

        exp_budget_id = f"TOTAL-LAW-EXPENSE-{year}"
        exp_budget = Budget(
            original_identifier=exp_budget_id,
            name=f"Total Federal Expenses (Law) {year}",
            name_translated=None,
            description=f"Federal budget law planned expenses for {year}",
            description_translated=None,
            type="TOTAL",
            scope="YEARLY",
            published_at=date(year, 1, 1),
            planned_at=None,
        )
        budgets.append(exp_budget)

        if year_data.total_expenses is not None:
            total_exp = Expense(budget_id=None, value=year_data.total_expenses)
            expenses.append((exp_budget_id, total_exp, None))

        for chapter_exp in year_data.chapter_expenses:
            exp = Expense(budget_id=None, value=chapter_exp.value)
            expenses.append((exp_budget_id, exp, chapter_exp.chapter_code))

    chapter_codes = list(RZ_TO_CHAPTER.values())

    logger.info(f"Created {len(budgets)} budgets")
    logger.info(f"Created {len(expenses)} expense entries")

    return budgets, chapter_codes, expenses


# =============================================================================
# UNIFIED INTERFACE
# =============================================================================


def parse_totals_file(
    file_path: Path,
    start_year: int = 2018,
) -> Tuple[List[Budget], List[str], List[Tuple[str, Expense, Optional[str]]]]:
    """
    Parse a totals file (auto-detects format from extension).

    Supports:
    - .xlsx files: Report budget execution data (monthly)
    - .csv files: Law budget data (annual)
    """
    suffix = file_path.suffix.lower()

    if suffix == ".xlsx":
        return parse_report_file(file_path, start_year)
    elif suffix == ".csv":
        return parse_law_file(file_path, start_year)
    else:
        raise ValueError(f"Unsupported file format: {suffix}. Expected .xlsx or .csv")
