"""
Budget parsers package.

Usage:
    from parsers import parse_law_file, parse_report_file, parse_totals_file
    
    # For LAW files:
    budget, dimensions, expenses = parse_law_file(Path("law_2024.xlsx"))
    
    # For REPORT files:
    budget, dimensions, expenses = parse_report_file(Path("report_2024_03.xlsx"))
    
    # For TOTALS files (monthly budget execution):
    # Returns: budgets, chapter_codes, list of (budget_id, expense) tuples
    # Expense budgets link to existing CHAPTER dimensions (01-14)
    budgets, chapter_codes, expenses = parse_totals_file(Path("totals_2026.xlsx"))
"""

from .law_parser import parse_law_file
from .report_parser import parse_report_file
from .totals_parser import parse_totals_file

__all__ = [
    "parse_law_file",
    "parse_report_file",
    "parse_totals_file",
]