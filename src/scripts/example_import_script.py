"""
Example script to import budgets into the database.
Import files should be placed in the 'data/import_files' directory.
"""

import csv
from typing import Sequence

from pydantic import BaseModel
from sqlalchemy import select
from models.budget import (
    Budget,
    Expense,
    Dimension,
)

from pathlib import Path
from sqlalchemy.dialects.sqlite import insert
import logging

from database.sessions import get_sync_session

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def load_data_from_file(file_path: Path) -> dict:
    """Load budget data from a given file path."""
    # Placeholder for actual file loading logic
    with open(file_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            # Implement actual data parsing logic here
            pass

    return {}
    

def import_budgets(file_path: Path) -> None:
    """Import budgets from files into the database."""
    data = load_data_from_file(file_path)
    # Verify data structure is as expected, for example using Pydantic models
    # update/insert logic, e.g. using SQLAlchemy's upsert capabilities
    upsert_stmt = (
        insert(Budget)
        .values(
            data
            # Map data fields to Budget model fields
        )
        .on_conflict_do_update(
            index_elements=[Budget.original_identifier],
            set_={
                "name": data.get("name"),
                "name_translated": data.get("name_translated"),
                "description": data.get("description"),
                "description_translated": data.get("description_translated"),
                "type": data.get("type"),
                "scope": data.get("scope"),
                "published_at": data.get("published_at"),
                "planned_at": data.get("planned_at"),
                "updated_at": data.get("updated_at"),
            },
        )
    )

    try:
        with get_sync_session() as session:
            session.execute(upsert_stmt)
            session.commit()
        logger.info(f"Successfully imported budgets from {file_path}")
    except Exception as e:
        logger.error(f"Failed to import budgets from {file_path}: {e}")


def import_dimensions(file_path: Path) -> None:
    """Import dimensions from files into the database."""
    data = load_data_from_file(file_path)
    # Verify data structure is as expected
    # update/insert logic, e.g. using SQLAlchemy's upsert capabilities
    upsert_stmt = (
        insert(Dimension)
        .values(
            data
            # Map data fields to Dimension model fields
        )
        .on_conflict_do_update(
            index_elements=[Dimension.original_identifier],
            set_={
                "name": data.get("name"),
                "name_translated": data.get("name_translated"),
                "type": data.get("type"),
                "original_identifier": data.get("original_identifier"),
                "updated_at": data.get("updated_at"),
            },
        )
    )

    try:
        with get_sync_session() as session:
            session.execute(upsert_stmt)
            session.commit()
        logger.info(f"Successfully imported dimensions from {file_path}")
    except Exception as e:
        logger.error(f"Failed to import dimensions from {file_path}: {e}")


def fetch_dimensions_by_identifiers(
        dimension_identifiers: list[str]
    ) -> Sequence[Dimension]:
    """Fetch dimensions from the database based on their original identifiers."""
    with get_sync_session() as session:
        dimensions = session.scalars(
            select(Dimension).where(
                Dimension.original_identifier.in_(dimension_identifiers)
            )
        ).all()
    return dimensions


def import_expenses(file_path: Path) -> None:
    """Import expenses from files into the database."""
    data = load_data_from_file(file_path)
    # Verify data structure is as expected
    # update/insert logic, e.g. using SQLAlchemy's upsert capabilities

    expense_list = []
    for expense in data.get("expenses", []):
        dimension_ids = expense.get("dimension_identifiers", [])
        dimensions_list = fetch_dimensions_by_identifiers(dimension_ids)
        # Map dimensions to expense and automatically handles the association table
        expense = Expense(
            budget_id=expense.get("budget_id"),
            value=expense.get("value"),
            dimensions=dimensions_list, 
            created_at=expense.get("created_at"),
            updated_at=expense.get("updated_at"),
        )
        expense_list.append(expense)
        

    upsert_stmt = (
        insert(Expense)
        .values(
            data
            # Map data fields to Expense model fields
        )
        .on_conflict_do_update(
            index_elements=[Expense.id],
            set_={
                "budget_id": data.get("budget_id"),
                "value": data.get("value"),
                "updated_at": data.get("updated_at"),
            },
        )
    )

    try:
        with get_sync_session() as session:
            session.execute(upsert_stmt)
            session.commit()
        logger.info(f"Successfully imported expenses from {file_path}")
    except Exception as e:
        logger.error(f"Failed to import expenses from {file_path}: {e}")
    