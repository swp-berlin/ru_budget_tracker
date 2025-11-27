"""
Budget parsers package.

Usage:
    from parsers import parse_law_file, parse_report_file
    
    # For LAW files:
    budget, dimensions, expenses = parse_law_file(Path("law_2024.xlsx"))
    
    # For REPORT files (needs DB session):
    budget, dimensions, expenses = parse_report_file(Path("report_2024_03.xlsx"), session)
"""

from .law_parser import parse_law_file
from .report_parser import parse_report_file

__all__ = [
    "parse_law_file",
    "parse_report_file",
]
