"""
Dimension name normalization script.

Cleans up dimension names in the database for better display. Runs after
import + translation. All transformations are idempotent.

Transformations (applied in order):
    1. Program-title prefix strip (type == PROGRAM, name + name_translated):
         Государственная программа Российской Федерации "xyz" ...  ->  xyz ...
         State Program of the Russian Federation "xyz" ...         ->  xyz ...
       The quoted title and any trailing text are kept; the prefix and the
       surrounding quotes are removed.
    2. Federation short-form (all types, name + name_translated):
         Российск.. Федерац..  ->  РФ
         Russian Federation    ->  RF

Usage:
    python rename_dimensions.py             # apply changes
    python rename_dimensions.py --dry-run   # show what would change
"""

import sys
import re
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from models import Dimension
from database.sessions import get_sync_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# TRANSFORMATIONS
# =============================================================================

# Strip "<prefix> "title" trailing" -> "title trailing". Quotes are " or '.
PROGRAM_PREFIX_RU = re.compile(
    r'^Государственная программа Российской Федерации\s*["\'](.+?)["\'](.*)$'
)
PROGRAM_PREFIX_EN = re.compile(
    r'^State Program of the Russian Federation\s*["\'](.+?)["\'](.*)$',
    re.IGNORECASE,
)

# Federation short-form. \w* covers all declension endings (and truncated source
# values); IGNORECASE covers the all-caps ministry names. The leading \b prevents
# matching inside larger words such as "Всероссийской федерации" (a sports org).
FEDERATION_RU = re.compile(r"\bРоссийск\w* Федерац\w*", re.IGNORECASE)
FEDERATION_EN = re.compile(r"\bRussian Federation\b", re.IGNORECASE)


def strip_program_prefix(value: str | None) -> str | None:
    """Strip the 'State Program of the Russian Federation' title prefix."""
    if not value:
        return value
    for pattern in (PROGRAM_PREFIX_RU, PROGRAM_PREFIX_EN):
        match = pattern.match(value)
        if match:
            return (match.group(1) + match.group(2)).strip()
    return value


def shorten_federation(value: str | None) -> str | None:
    """Replace the long 'Russian Federation' forms with the short form."""
    if not value:
        return value
    value = FEDERATION_RU.sub("РФ", value)
    value = FEDERATION_EN.sub("RF", value)
    return value


def normalize_name(value: str | None, is_program: bool) -> str | None:
    """Apply all transformations in order to a single name."""
    if is_program:
        value = strip_program_prefix(value)
    return shorten_federation(value)


# =============================================================================
# MAIN
# =============================================================================


def compute_changes() -> List[Tuple[int, str | None, str | None, str | None, str | None]]:
    """
    Compute the new name / name_translated for every dimension that changes.

    Returns:
        List of (id, new_name, new_name_translated, old_name, old_name_translated)
        for rows where at least one field changes.
    """
    changes = []
    with get_sync_session() as session:
        rows = session.execute(
            select(
                Dimension.id,
                Dimension.type,
                Dimension.name,
                Dimension.name_translated,
            )
        ).all()

    for dim_id, dim_type, name, name_translated in rows:
        is_program = dim_type == "PROGRAM"
        new_name = normalize_name(name, is_program)
        new_translated = normalize_name(name_translated, is_program)
        if new_name != name or new_translated != name_translated:
            changes.append((dim_id, new_name, new_translated, name, name_translated))

    return changes


def detect_name_collisions(changes) -> Tuple[set, List[str]]:
    """
    Detect renames that would violate the unique constraint on
    (name, type, original_identifier, parent_id). Only `name` (Russian) is in
    the constraint, so only its changes can collide.

    Such collisions come from near-duplicate source rows that normalize to the
    same value. We skip those changes (leaving the rows untouched) rather than
    fail the whole batch.

    Returns:
        (skip_ids, messages): dimension ids whose change must be skipped, and
        human-readable descriptions of each collision.
    """
    new_name_by_id = {c[0]: c[1] for c in changes}
    changed_ids = set(new_name_by_id)

    with get_sync_session() as session:
        rows = session.execute(
            select(
                Dimension.id,
                Dimension.name,
                Dimension.type,
                Dimension.original_identifier,
                Dimension.parent_id,
            )
        ).all()

    # Group every dimension by its final-state key (new name if changing).
    by_key: Dict[Tuple, List[int]] = {}
    for dim_id, name, dim_type, original_identifier, parent_id in rows:
        effective_name = new_name_by_id.get(dim_id, name)
        key = (effective_name, dim_type, original_identifier, parent_id)
        by_key.setdefault(key, []).append(dim_id)

    skip_ids: set = set()
    messages: List[str] = []
    for key, ids in by_key.items():
        if len(ids) > 1:
            # Skip only the rows that are actually changing; rows already at this
            # name keep their (unique) value.
            colliding_changed = [i for i in ids if i in changed_ids]
            skip_ids.update(colliding_changed)
            messages.append(
                f"Rename collision on key {key!r}: dimension ids {ids} (skipping {colliding_changed})"
            )

    return skip_ids, messages


def apply_changes(changes) -> int:
    """Apply computed changes in a single transaction."""
    with get_sync_session() as session:
        for dim_id, new_name, new_translated, _old_name, _old_translated in changes:
            dimension = session.get(Dimension, dim_id)
            if dimension is None:
                continue
            dimension.name = new_name
            dimension.name_translated = new_translated
        session.commit()
    return len(changes)


def main():
    parser = argparse.ArgumentParser(description="Normalize dimension names for display")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing to the database",
    )
    args = parser.parse_args()

    changes = compute_changes()
    logger.info(f"Found {len(changes)} dimensions to rename")

    if not changes:
        logger.info("Nothing to do.")
        return

    skip_ids, collisions = detect_name_collisions(changes)
    if collisions:
        logger.warning(
            f"Skipping {len(skip_ids)} rename(s) that would collide with a near-duplicate row:"
        )
        for line in collisions[:20]:
            logger.warning(f"  {line}")
        changes = [c for c in changes if c[0] not in skip_ids]
        logger.info(f"{len(changes)} dimensions remain to rename after skipping collisions")

    if not changes:
        logger.info("Nothing to do.")
        return

    if args.dry_run:
        logger.info(f"\n{'=' * 60}")
        logger.info("DRY RUN - No changes will be made")
        logger.info(f"{'=' * 60}")
        for _dim_id, new_name, new_translated, old_name, old_translated in changes[:10]:
            if new_name != old_name:
                logger.info(f"  name:       {old_name!r}\n           -> {new_name!r}")
            if new_translated != old_translated:
                logger.info(f"  translated: {old_translated!r}\n           -> {new_translated!r}")
        logger.info(f"\nTotal dimensions to rename: {len(changes)}")
        return

    updated = apply_changes(changes)
    logger.info(f"\n{'=' * 60}")
    logger.info("DONE")
    logger.info(f"  Renamed {updated} dimensions")
    logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    main()
