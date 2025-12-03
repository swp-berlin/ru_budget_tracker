"""
TOTALS parser for federal budget execution summary data.

Handles: totals_YYYY.xlsx files

Creates per month:
- 1 Budget for total REVENUE (TOTAL-REVENUE-YYYY-MM) with 1 Expense (no dimensions)
- 1 Budget for total EXPENSES (TOTAL-EXPENSE-YYYY-MM) with 15 Expenses:
  - 1 total expense (no dimensions) - from row "2"
  - 14 chapter expenses (each linked to one CHAPTER dimension 01-14) - from rows 2.1-2.14

The functional sections in the totals file (2.1 - 2.14) map directly to 
budget chapters (01 - 14):
    2.1.  -> Chapter 01 (Общегосударственные вопросы)
    2.2.  -> Chapter 02 (Национальная оборона)
    ...
    2.14. -> Chapter 14 (Межбюджетные трансферты)

Values in source file are in BILLIONS of rubles.
Values stored in database are in RUBLES.
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
# 2.1. -> 01, 2.2. -> 02, ..., 2.14. -> 14
FUNCTIONAL_TO_CHAPTER = {
    "2.1.": "01",   # Общегосударственные вопросы
    "2.2.": "02",   # Национальная оборона
    "2.3.": "03",   # Национальная безопасность и правоохранительная деятельность
    "2.4.": "04",   # Национальная экономика
    "2.5.": "05",   # Жилищно-коммунальное хозяйство
    "2.6.": "06",   # Охрана окружающей среды
    "2.7.": "07",   # Образование
    "2.8.": "08",   # Культура, кинематография
    "2.9.": "09",   # Здравоохранение
    "2.10.": "10",  # Социальная политика
    "2.11.": "11",  # Физическая культура и спорт
    "2.12.": "12",  # Средства массовой информации
    "2.13.": "13",  # Обслуживание государственного и муниципального долга
    "2.14.": "14",  # Межбюджетные трансферты общего характера
}


@dataclass
class ChapterExpense:
    """Expense value for a specific chapter."""
    chapter_code: str
    value: float  # in rubles


@dataclass
class ParsedMonth:
    """Parsed data for a single month."""
    date: date
    year: int
    month: int
    total_revenue: Optional[float] = None  # in rubles (row "1")
    total_expenses: Optional[float] = None  # in rubles (row "2")
    chapter_expenses: List[ChapterExpense] = field(default_factory=list)  # 14 chapter expenses (rows 2.1-2.14)


def read_totals_excel(file_path: Path) -> pd.DataFrame:
    """Read the totals Excel file."""
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
        'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4,
        'май': 5, 'июн': 6, 'июл': 7, 'авг': 8,
        'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12
    }
    
    for col_idx in range(2, len(header_row)):
        val = header_row.iloc[col_idx]
        if pd.isna(val):
            continue
        
        if isinstance(val, (datetime, pd.Timestamp)):
            col_dates[col_idx] = val.date() if hasattr(val, 'date') else date(val.year, val.month, val.day)
            continue
        
        val_str = str(val).strip().lower()
        for month_abbr, month_num in month_map.items():
            if month_abbr in val_str:
                year_match = re.search(r'\.(\d{2})', val_str)
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
    """
    Find row indices for all functional sections (2.1. - 2.14.).
    
    Returns: dict mapping indicator (e.g., "2.1.") to row index
    """
    rows: Dict[str, int] = {}
    for indicator in FUNCTIONAL_TO_CHAPTER.keys():
        idx = get_row_index_by_indicator(df, indicator)
        if idx is not None:
            rows[indicator] = idx
        else:
            logger.warning(f"Could not find row for functional section {indicator}")
    return rows


def parse_cell_value(df: pd.DataFrame, row_idx: int, col_idx: int) -> Optional[float]:
    """Safely parse a cell value as float, converting from billions to rubles."""
    val = df.iloc[row_idx, col_idx]
    if pd.notna(val):
        try:
            return float(str(val)) * BILLION
        except (ValueError, TypeError):
            pass
    return None


def parse_totals_file(
    file_path: Path,
    start_year: int = 2018,
) -> Tuple[List[Budget], List[str], List[Tuple[str, Expense, Optional[str]]]]:
    """
    Parse a totals file.
    
    Creates per month:
    - 1 Budget "TOTAL-REVENUE-YYYY-MM" with 1 Expense (no dimensions)
    - 1 Budget "TOTAL-EXPENSE-YYYY-MM" with 15 Expenses:
      - 1 total expense (no dimensions)
      - 14 chapter expenses (each linked to one chapter 01-14)
    
    Args:
        file_path: Path to totals Excel file
        start_year: Only include data from this year onwards
        
    Returns:
        Tuple of:
        - List of Budget objects
        - List of chapter codes (["01", "02", ..., "14"])
        - List of (budget_identifier, Expense, chapter_code or None) tuples
    """
    logger.info(f"Parsing totals file: {file_path.name}")
    
    df = read_totals_excel(file_path)
    col_dates = parse_column_dates(df)
    
    # Find row indices
    revenue_row_idx = get_row_index_by_indicator(df, "1")  # Доходы, всего
    expense_row_idx = get_row_index_by_indicator(df, "2")  # Расходы, всего
    functional_section_rows = get_functional_section_rows(df)  # 2.1. - 2.14.
    
    if revenue_row_idx is None:
        logger.error("Could not find revenue row (indicator '1')")
    if expense_row_idx is None:
        logger.error("Could not find total expense row (indicator '2')")
    
    logger.info(f"Found {len(functional_section_rows)} functional section rows")
    
    # Parse monthly data
    months: List[ParsedMonth] = []
    for col_idx, col_date in sorted(col_dates.items()):
        if col_date.year < start_year:
            continue
        
        month = ParsedMonth(date=col_date, year=col_date.year, month=col_date.month)
        
        # Parse revenue (indicator "1")
        if revenue_row_idx is not None:
            month.total_revenue = parse_cell_value(df, revenue_row_idx, col_idx)
        
        # Parse total expenses (indicator "2")
        if expense_row_idx is not None:
            month.total_expenses = parse_cell_value(df, expense_row_idx, col_idx)
        
        # Parse chapter expenses (2.1. - 2.14.)
        for indicator, row_idx in functional_section_rows.items():
            chapter_code = FUNCTIONAL_TO_CHAPTER[indicator]
            value = parse_cell_value(df, row_idx, col_idx)
            if value is not None:
                month.chapter_expenses.append(ChapterExpense(
                    chapter_code=chapter_code,
                    value=value,
                ))
        
        months.append(month)
    
    logger.info(f"Parsed {len(months)} months from {start_year}")
    
    # Create budgets and expenses
    budgets: List[Budget] = []
    # (budget_identifier, Expense, chapter_code or None)
    expenses: List[Tuple[str, Expense, Optional[str]]] = []
    
    for month in months:
        # Revenue budget (1 expense, no dimensions)
        if month.total_revenue is not None:
            rev_budget_id = f"TOTAL-REVENUE-{month.year}-{month.month:02d}"
            rev_budget = Budget(
                original_identifier=rev_budget_id,
                name=f"Total Federal Revenue {month.year}-{month.month:02d}",
                name_translated=None,
                description=f"Federal budget revenue for {month.year}-{month.month:02d}",
                description_translated=None,
                type="TOTAL",
                scope="MONTHLY",
                published_at=month.date,
                planned_at=None,
            )
            budgets.append(rev_budget)
            
            # Single expense entry for revenue (no chapter)
            rev_expense = Expense(budget_id=None, value=month.total_revenue)
            expenses.append((rev_budget_id, rev_expense, None))
        
        # Expense budget (15 expenses: 1 total + 14 per chapter)
        if month.total_expenses is not None or month.chapter_expenses:
            exp_budget_id = f"TOTAL-EXPENSE-{month.year}-{month.month:02d}"
            exp_budget = Budget(
                original_identifier=exp_budget_id,
                name=f"Total Federal Expenses {month.year}-{month.month:02d}",
                name_translated=None,
                description=f"Federal budget expenses for {month.year}-{month.month:02d}",
                description_translated=None,
                type="TOTAL",
                scope="MONTHLY",
                published_at=month.date,
                planned_at=None,
            )
            budgets.append(exp_budget)
            
            # Total expense (no dimensions)
            if month.total_expenses is not None:
                total_exp = Expense(budget_id=None, value=month.total_expenses)
                expenses.append((exp_budget_id, total_exp, None))
            
            # One expense per chapter (linked to chapter dimension)
            for chapter_exp in month.chapter_expenses:
                exp = Expense(budget_id=None, value=chapter_exp.value)
                expenses.append((exp_budget_id, exp, chapter_exp.chapter_code))
    
    # Summary
    chapter_codes = list(FUNCTIONAL_TO_CHAPTER.values())
    revenue_budgets = len([b for b in budgets if "REVENUE" in b.original_identifier])
    expense_budgets = len([b for b in budgets if "EXPENSE" in b.original_identifier])
    
    logger.info(f"Created {len(budgets)} budgets ({revenue_budgets} revenue, {expense_budgets} expense)")
    logger.info(f"Created {len(expenses)} expense entries")
    
    return budgets, chapter_codes, expenses

