"""
REPORT-specific parsing functions.

Handles: report_YYYY_MM.xlsx files

NOTE: This is a template. Implement based on actual report file structure.
"""

import pandas as pd
from pathlib import Path
from typing import List, Tuple, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select
import logging

from models import Budget, Dimension, Expense
from .helpers import (
    extract_budget_metadata_from_filename,
    create_budget_from_metadata,
)

logger = logging.getLogger(__name__)


def parse_report_budget(file_path: Path) -> Budget:
    """Parse budget metadata from a REPORT file."""
    metadata = extract_budget_metadata_from_filename(file_path)
    return create_budget_from_metadata(metadata)


def load_law_dimensions(session: Session, year: int) -> List[Dimension]:
    """
    Load dimensions from the corresponding LAW budget.
    
    Reports reference dimensions defined in the year's LAW.
    """
    law_identifier = f"LAW-{year}"

    stmt = select(Dimension).join(Budget).where(
        Budget.original_identifier == law_identifier
    )
    result = session.execute(stmt)
    dimensions = list(result.scalars().all())

    logger.info(f"Loaded {len(dimensions)} dimensions from {law_identifier}")
    return dimensions


def parse_report_file(
    file_path: Path, 
    session: Optional[Session] = None
) -> Tuple[Budget, List[Dimension], List[Expense]]:
    """
    Parse a REPORT file completely.
    
    Args:
        file_path: Path to report Excel file
        session: DB session for loading existing dimensions (required)
    
    Returns:
        (budget, dimensions, expenses)
    """
    logger.info(f"Parsing REPORT file: {file_path.name}")

    # 1. Parse budget metadata
    budget = parse_report_budget(file_path)
    metadata = extract_budget_metadata_from_filename(file_path)

    # 2. Load existing dimensions from LAW
    if session is None:
        raise ValueError("Session required for parsing reports (need to lookup LAW dimensions)")
    
    existing_dimensions = load_law_dimensions(session, metadata["year"])

    # 3. Read Excel file
    df = pd.read_excel(file_path, header=None, engine="openpyxl")

    # TODO: Implement report-specific parsing
    # - Find header row (may differ from LAW files)
    # - Parse rows and match to existing dimensions
    # - Create expenses linked to existing dimensions

    raise NotImplementedError(
        "Report parsing not yet implemented. "
        "Implement based on actual report file structure."
    )

    # Example structure (uncomment and modify when implementing):
    # 
    # dimensions = []  # Reports typically don't create new dimensions
    # expenses = parse_report_expenses(df, existing_dimensions)
    # 
    # return budget, dimensions, expenses
