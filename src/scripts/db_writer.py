"""
Database write layer for the budget importer.

All functions that persist parsed data (budgets, dimensions, expenses,
conversion rates) live here; parsing stays in scripts/parsers and
orchestration/CLI in scripts/import.py.
"""

import logging
from typing import Dict, List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session, noload

from models import Budget, ConversionRate, Dimension, Expense
from scripts.parsers.issues import IssueCollector

logger = logging.getLogger(__name__)


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
    exact_cache: Dict[tuple, "Dimension"] | None = None,
    null_parent_cache: Dict[tuple, "Dimension"] | None = None,
) -> Dimension:
    """
    Upsert dimension with special parent_id handling.

    When called from save_dimensions, exact_cache and null_parent_cache are
    pre-populated from a single bulk query so no per-row DB round-trips occur.

    1. If exists with same parent_id → skip (return existing)
    2. If exists with parent_id=None → update to new parent_id
    3. If exists with different non-null parent_id → add new row
    """
    # First: check for exact match (same parent_id) → skip
    exact_key = (original_identifier, dim_type, name, parent_db_id)
    if exact_cache is not None:
        exact_match = exact_cache.get(exact_key)
    else:
        exact_match = (
            session.query(Dimension)
            .options(noload(Dimension.expenses))
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
        null_key = (original_identifier, dim_type, name)
        if null_parent_cache is not None:
            null_parent = null_parent_cache.get(null_key)
        else:
            null_parent = (
                session.query(Dimension)
                .options(noload(Dimension.expenses))
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
            if null_parent_cache is not None:
                del null_parent_cache[null_key]
            if exact_cache is not None:
                exact_cache[exact_key] = null_parent
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
    if exact_cache is not None:
        exact_cache[exact_key] = new_dim
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


def _find_parent_db_id_in_existing(
    parent_identifier: str,
    expected_type: str | None,
    existing_parent_map: Dict[tuple, Dimension],
) -> int | None:
    """Find parent DB id from existing database rows loaded in bulk."""
    if expected_type is not None:
        parent = existing_parent_map.get((parent_identifier, expected_type))
        return parent.id if parent else None

    for (orig_id, _dim_type), db_dim in existing_parent_map.items():
        if orig_id == parent_identifier:
            return db_dim.id
    return None


def save_dimensions(
    session: Session,
    dimensions: List[Dimension],
    budget_db_id: int,
    issues: IssueCollector | None = None,
) -> Dict[tuple, Dimension]:
    """
    Save dimensions using upsert logic:
    - Skip if exact match exists
    - Update if exists with parent_id=None
    - Add new row if exists with different parent_id

    Bulk-fetches all potentially matching existing rows up front so the loop
    does pure in-memory lookups instead of one SELECT per dimension.

    Returns: mapping of (identifier, type) -> DB dimension
    """
    # Bulk pre-fetch: include identifiers from current dimensions and possible parent identifiers.
    orig_ids = {d.original_identifier for d in dimensions}
    orig_ids.update({str(d.parent_id) for d in dimensions if d.parent_id is not None})
    existing_rows = (
        session.query(Dimension)
        .options(noload(Dimension.expenses))
        .filter(Dimension.original_identifier.in_(orig_ids))
        .all()
    )

    # exact_cache: (orig_id, type, name, parent_id) -> Dimension
    exact_cache: Dict[tuple, Dimension] = {
        (d.original_identifier, d.type, d.name, d.parent_id): d for d in existing_rows
    }
    # null_parent_cache: (orig_id, type, name) -> Dimension  (only rows where parent_id is None)
    null_parent_cache: Dict[tuple, Dimension] = {
        (d.original_identifier, d.type, d.name): d for d in existing_rows if d.parent_id is None
    }
    existing_parent_map: Dict[tuple, Dimension] = {
        (d.original_identifier, d.type): d for d in existing_rows
    }

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
            exact_cache=exact_cache,
            null_parent_cache=null_parent_cache,
        )
        dim_map[(dim.original_identifier, dim.type)] = db_dim

    # Flush once to assign DB ids to newly inserted parent rows before children reference them.
    session.flush()

    # Second pass: dimensions with parents. Iterate until no progress so order does not matter.
    pending = [d for d in dimensions if d.parent_id is not None]
    unresolved_warned: set[tuple] = set()

    while pending:
        progressed = False
        next_pending: List[Dimension] = []

        for dim in pending:
            expected_parent_type = (
                "PROGRAM"
                if dim.type == "PROGRAM"
                else "CHAPTER"
                if dim.type == "SUBCHAPTER"
                else None
            )
            parent_db_id = _find_parent_db_id(str(dim.parent_id), expected_parent_type, dim_map)

            if parent_db_id is None:
                parent_db_id = _find_parent_db_id_in_existing(
                    str(dim.parent_id), expected_parent_type, existing_parent_map
                )

            if parent_db_id is None:
                next_pending.append(dim)
                continue

            db_dim = upsert_dimension(
                session,
                original_identifier=dim.original_identifier,
                dim_type=dim.type,
                name=dim.name,
                parent_db_id=parent_db_id,
                name_translated=dim.name_translated,
                exact_cache=exact_cache,
                null_parent_cache=null_parent_cache,
            )
            dim_map[(dim.original_identifier, dim.type)] = db_dim
            progressed = True

        if not progressed:
            for dim in next_pending:
                warn_key = (dim.original_identifier, dim.type, dim.parent_id)
                if warn_key in unresolved_warned:
                    continue
                unresolved_warned.add(warn_key)
                logger.warning(
                    f"Parent '{dim.parent_id}' not found for {dim.original_identifier} ({dim.type})"
                )
                if issues is not None:
                    # Preserved behavior: the dimension is dropped for this budget.
                    issues.add(
                        "unresolved_dimension_parent",
                        f"Parent '{dim.parent_id}' not found for "
                        f"{dim.original_identifier} ({dim.type}); dimension not saved",
                    )
            break

        session.flush()
        pending = next_pending

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


def get_chapter_dimensions(
    session: Session, chapter_codes: List[str], issues: IssueCollector | None = None
) -> List[Dimension]:
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
        .options(noload(Dimension.expenses))
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
        if issues is not None:
            issues.add(
                "chapter_dimension_missing",
                f"CHAPTER dimensions not in database: {sorted(missing)} (import LAW files first)",
            )

    if len(all_chapters) != len(chapters):
        logger.info(
            f"Found {len(all_chapters)} chapter rows, deduplicated to {len(chapters)} unique codes"
        )
    else:
        logger.info(f"Found {len(chapters)} of {len(chapter_codes)} chapter dimensions")

    return chapters


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
