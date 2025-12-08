"""
Budget parsers package.

Usage:
    from parsers import parse_law_file, parse_report_file, parse_totals_file
    
    # For LAW files:
    budget, dimensions, expenses = parse_law_file(Path("law_2024.xlsx"))
    
    # For REPORT files:
    budget, dimensions, expenses = parse_report_file(Path("report_2024_03.xlsx"))
    
    # For TOTALS files (monthly budget execution):
    budgets, chapter_codes, expenses = parse_totals_file(Path("totals_2026.xlsx"))
    
    # For GDP files:
    quarterly_rates, yearly_rates = parse_gdp_files(rosstat_path, minekonom_path)
"""

from .law_parser import parse_law_file
from .report_parser import parse_report_file
from .totals_parser import parse_totals_file
from .gdp_parser import parse_gdp_files

__all__ = [
    "parse_law_file",
    "parse_report_file",
    "parse_totals_file",
    "parse_gdp_files",
]