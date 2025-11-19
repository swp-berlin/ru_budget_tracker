"""
Example script to import budgets into the database.
Import files should be placed in the 'data/import_files' directory.
"""
import csv
from typing import Sequence
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from models import (
    Budget,
    Expense,
    Dimension,
)

from parse_budget import create_budget_from_excel
from parse_dimensions import load_dimensions_and_expenses_from_excel


from sqlalchemy.dialects.sqlite import insert
import logging

from database.sessions import get_sync_session

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def load_data_from_file(file_path: Path, budget_db_id: int = None) -> dict:
    """
    Load budget data from a given file path.
    
    Args:
        file_path: Path to the Excel file
        budget_db_id: Optional budget database ID. If provided, expenses will also be loaded.
        
    Returns:
        Dict with keys: 'budget', 'dimensions', and optionally 'expenses'
    """
    data = {}

    data["budget"] = create_budget_from_excel(file_path)

    # Load dimensions and expenses together
    parsed_data = load_dimensions_and_expenses_from_excel(file_path, budget_db_id)
    data["dimensions"] = parsed_data["dimensions"]
    data["expenses"] = parsed_data["expenses"]

    return data


def import_budget(file_path: Path) -> int:
    """
    Import budget from file into the database.
    
    Returns:
        int: The database ID of the imported/updated budget
    """
    data = load_data_from_file(file_path)
    budget = data.get("budget")
    
    if not budget:
        logger.error(f"No budget data found in {file_path}")
        raise ValueError(f"No budget data found in {file_path}")
    
    try:
        with get_sync_session() as session:
            # Check if budget with this original_identifier already exists
            existing_budget = session.query(Budget).filter_by(
                original_identifier=budget.original_identifier
            ).first()
            
            if existing_budget:
                # Update the existing budget's id so merge works correctly
                budget.id = existing_budget.id
            
            # merge() will insert if new, update if exists (based on primary key)
            merged_budget = session.merge(budget)
            session.commit()
            budget_db_id = merged_budget.id
            
            logger.info(f"Successfully imported budget: {budget.original_identifier} (ID: {budget_db_id})")
            return budget_db_id
            
    except Exception as e:
        logger.error(f"Failed to import budget from {file_path}: {e}")
        raise


def import_dimensions_and_expenses(file_path: Path, budget_db_id: int) -> None:
    """
    Import both dimensions and expenses from file into the database in one pass.
    
    This is the recommended way to import data as it's more efficient than
    parsing the file twice.
    
    Args:
        file_path: Path to Excel file
        budget_db_id: Database ID of the budget these belong to
    """
    logger.info(f"Importing dimensions and expenses from {file_path}")
    
    # Load data using the unified loader
    data = load_data_from_file(file_path, budget_db_id)
    dimensions = data.get("dimensions", [])
    expenses = data.get("expenses", [])
    
    if not dimensions:
        logger.warning(f"No dimensions found in {file_path}")
        return
    
    try:
        with get_sync_session() as session:
            # Map: (original_identifier, type) -> database Dimension object
            dimension_db_map = {}
            
            # PHASE 1: Insert all dimensions without parent_id
            logger.info(f"Phase 1: Inserting {len(dimensions)} dimensions...")
            for dimension in dimensions:
                # Create new dimension (without parent_id first)
                new_dim = Dimension(
                    original_identifier=dimension.original_identifier,
                    type=dimension.type,
                    name=dimension.name,
                    name_translated=dimension.name_translated,
                    budget_id=budget_db_id,
                    parent_id=None  # Set in phase 2
                )
                session.add(new_dim)
                session.flush()  # Get the id - will raise IntegrityError if duplicate
                
                # Store mapping
                key = (new_dim.original_identifier, new_dim.type)
                dimension_db_map[key] = new_dim
                logger.debug(f"Created dimension: {dimension.original_identifier} ({dimension.type})")
            
            # PHASE 2: Set parent_id relationships
            logger.info("Phase 2: Setting parent relationships...")
            for dimension in dimensions:
                if dimension.parent_id:
                    # Get the database object for this dimension
                    dim_key = (dimension.original_identifier, dimension.type)
                    db_dimension = dimension_db_map.get(dim_key)
                    
                    if not db_dimension:
                        logger.warning(f"Could not find DB object for {dimension.original_identifier} ({dimension.type})")
                        continue
                    
                    # Find parent by matching identifier AND checking if it's the right type
                    expected_parent_type = None
                    if dimension.type == 'PROGRAM':
                        expected_parent_type = 'PROGRAM'
                    elif dimension.type == 'SUBCHAPTER':
                        expected_parent_type = 'CHAPTER'
                    
                    # Search for parent with correct type
                    parent_db_obj = None
                    for (parent_orig_id, parent_type), parent_obj in dimension_db_map.items():
                        if (parent_orig_id == dimension.parent_id and
                            (expected_parent_type is None or parent_type == expected_parent_type)):
                            parent_db_obj = parent_obj
                            break
                    
                    if parent_db_obj:
                        db_dimension.parent_id = parent_db_obj.id
                        logger.debug(f"Set parent for {dimension.original_identifier} ({dimension.type}) -> {dimension.parent_id} (type: {expected_parent_type})")
                    else:
                        logger.warning(f"Parent {dimension.parent_id} (expected type: {expected_parent_type}) not found for {dimension.original_identifier} ({dimension.type})")
            
            session.flush()  # Flush parent relationships
            
            # PHASE 3: Insert expenses with dimension links
            logger.info(f"Phase 3: Inserting {len(expenses)} expenses...")
            for expense in expenses:
                # Replace in-memory dimension objects with database dimension objects
                db_dimensions = []
                for dim in expense.dimensions:
                    key = (dim.original_identifier, dim.type)
                    db_dim = dimension_db_map.get(key)
                    if db_dim:
                        db_dimensions.append(db_dim)
                    else:
                        logger.warning(f"Could not find DB dimension for {dim.original_identifier} ({dim.type})")
                
                # Create expense with database dimensions
                new_expense = Expense(
                    budget_id=budget_db_id,
                    value=expense.value,
                    dimensions=db_dimensions  # SQLAlchemy will handle the association table
                )
                session.add(new_expense)
            
            # Commit everything
            session.commit()
            logger.info(f"Successfully imported {len(dimensions)} dimensions and {len(expenses)} expenses for budget ID {budget_db_id}")
            
    except Exception as e:
        logger.error(f"Failed to import data from {file_path}: {e}")
        raise

