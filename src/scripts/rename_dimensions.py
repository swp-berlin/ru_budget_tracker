"""
Dimension name normalization script.

Cleans up dimension names in the database for better display. Runs after
import + translation. All transformations are idempotent.

Transformations (applied in order):
    0. Quote normalization (all types, name_translated only):
         curly “ ” -> ", curly ‘ ’ -> ', and a trailing `,"` -> `"`.
       DeepL emits both quote styles, often unpaired, which breaks the
       back-referenced quote matching the strip rules rely on.
    1. Program-title prefix strip (type == PROGRAM, name + name_translated):
         Государственная программа Российской Федерации "xyz" ...  ->  xyz ...
         State Program of the Russian Federation "xyz" ...         ->  xyz ...
       The quoted title and any trailing text are kept; the prefix and the
       surrounding quotes are removed.
    2. Program type-label strip (type == PROGRAM, name_translated only):
         Main Event: "xyz"          ->  xyz
         "xyz" Federal Project      ->  xyz
         Subprogram: xyz            ->  xyz
       DeepL renders the Russian type prefixes (Основное мероприятие,
       Федеральный проект, Подпрограмма, ...) with wildly varying English
       wording, position and punctuation; PROGRAM_TYPE_LABELS lists what it
       actually produced. Applied repeatedly because the source data nests
       type labels (Основное мероприятие "Приоритетный проект "xyz"").
    3. Federation short-form (all types, name + name_translated):
         Российск.. Федерац..  ->  РФ
         Russian Federation    ->  RF
    4. Trailing federation suffix (all types, name + name_translated):
         xyz РФ                   ->  xyz
         xyz of the RF           ->  xyz

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

# Strip "<prefix> "title" trailing" -> "title trailing". Quotes are " or '. The
# closing quote must be the same character as the opening one (\1), otherwise an
# apostrophe inside the title closes the match early: "Russia's Space Activities"
# used to become 'Russias Space Activities"' - apostrophe eaten, quote dangling.
PROGRAM_PREFIX_RU = re.compile(
    r'^Государственная программа Российской Федерации\s*(["\'])(.+?)\1(.*)$'
)
PROGRAM_PREFIX_EN = re.compile(
    r'^State Program of the Russian Federation\s*(["\'])(.+?)\1(.*)$',
    re.IGNORECASE,
)

# English renderings DeepL produced for each Russian program type prefix. Keyed
# by the Russian prefix so the inventory stays traceable; the values are the
# label alone - articles, punctuation and the quoted title are handled below.
PROGRAM_TYPE_LABELS = {
    "Государственная программа Российской Федерации": (
        r"State Program of the (?:Russian Federation|RF)"
    ),
    "Комплекс процессных мероприятий": (
        r"(?:Set|Series|Complex|Program|Package) of [\w\s-]{0,40}?"
        r"(?:Measures|Activities|Initiatives|Events|Actions)"
    ),
    "Подпрограмма": r"Subprogram(?:me)?",
    "Основное мероприятие": (
        r"(?:Main|Key|Flagship) (?:Event|Activity|Initiative|Project|Program|Measure)"
    ),
    "Федеральный проект": r"Federal Project",
    "Национальный проект": r"National Project",
    "Приоритетный проект": r"Priority Project",
    "Ведомственный проект": (
        r"(?:Departmental|Agency|Agency-Level|Agency-led|Ministry|Ministry-led)"
        r" (?:Project|Draft|Bill)"
    ),
    "Ведомственная целевая программа": r"(?:Departmental|Ministry-Level) Targeted Program",
    "Федеральная целевая программа": r"Federal Target Program",
}

_LABEL = r"(?:A|An|The)?\s*(?:" + "|".join(PROGRAM_TYPE_LABELS.values()) + r")"
# What DeepL put between the label and the title: "titled", "for", ":" or ",".
_LINK = r"(?:\s+titled|\s+named|\s+for|\s+aimed at)?\s*[:,]?\s*"

# The three shapes DeepL used, most specific first. All of them require either a
# quoted title (with the same back-reference as above, so an apostrophe inside
# the title cannot close it) or an explicit colon, so a title that merely starts
# with a label word - "Federal Target Program for the Development of the
# Kaliningrad Region ..." - is left alone.
LABEL_RULES = [
    # Main Event: "xyz" (trailing)  ->  xyz (trailing)
    (re.compile(rf'^{_LABEL}{_LINK}(["\'])(.+)\1(.*)$', re.IGNORECASE), (2, 3)),
    # The "xyz" Federal Project     ->  xyz   (labels stack: "xyz" A B)
    (re.compile(rf'^(?:The\s+)?(["\'])(.+)\1(?:\s+{_LABEL})+$', re.IGNORECASE), (2,)),
    # Subprogram: xyz               ->  xyz
    (re.compile(rf'^{_LABEL}\s*:\s*(?![\'"])(.+)$', re.IGNORECASE), (1,)),
]

# Quote normalization, applied to every translated name before the strip rules.
CURLY_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
TRAILING_COMMA_QUOTE = re.compile(r',(["\'])$')

# Federation short-form. \w* covers all declension endings (and truncated source
# values); IGNORECASE covers the all-caps ministry names. The leading \b prevents
# matching inside larger words such as "Всероссийской федерации" (a sports org).
FEDERATION_RU = re.compile(r"\bРоссийск\w* Федерац\w*", re.IGNORECASE)
FEDERATION_EN = re.compile(r"\bRussian Federation\b", re.IGNORECASE)
TRAILING_FEDERATION_RU = re.compile(r"\s+РФ$", re.IGNORECASE)
TRAILING_FEDERATION_EN = re.compile(r"\s+of the RF$", re.IGNORECASE)


def strip_program_prefix(value: str | None) -> str | None:
    """Strip the 'State Program of the Russian Federation' title prefix."""
    if not value:
        return value
    for pattern in (PROGRAM_PREFIX_RU, PROGRAM_PREFIX_EN):
        match = pattern.match(value)
        if match:
            return (match.group(2) + match.group(3)).strip()
    return value


def normalize_quotes(value: str | None) -> str | None:
    """Fold DeepL's curly quotes to straight ones and drop the `,"` artifact."""
    if not value:
        return value
    return TRAILING_COMMA_QUOTE.sub(r"\1", value.translate(CURLY_QUOTES))


def _strip_type_label_once(value: str) -> str:
    """Strip one leading/trailing program type label, if any rule matches."""
    for pattern, groups in LABEL_RULES:
        match = pattern.match(value)
        if match:
            stripped = "".join(match.group(group) for group in groups).strip()
            if stripped:
                return stripped
    return value


def strip_type_label(value: str | None) -> str | None:
    """Strip program type labels until none is left (labels can be nested)."""
    if not value:
        return value
    while True:
        stripped = _strip_type_label_once(value)
        if stripped == value:
            return value
        value = stripped


def shorten_federation(value: str | None) -> str | None:
    """Replace the long 'Russian Federation' forms with the short form."""
    if not value:
        return value
    value = FEDERATION_RU.sub("РФ", value)
    value = FEDERATION_EN.sub("RF", value)
    return value


def strip_trailing_federation(value: str | None) -> str | None:
    """Strip a Russian or English federation suffix at the end of a name."""
    if not value:
        return value
    value = TRAILING_FEDERATION_RU.sub("", value)
    return TRAILING_FEDERATION_EN.sub("", value)


def normalize_name(value: str | None, is_program: bool) -> str | None:
    """Apply all transformations in order to a single Russian name."""
    if is_program:
        value = strip_program_prefix(value)
    return strip_trailing_federation(shorten_federation(value))


def normalize_translated_name(value: str | None, is_program: bool) -> str | None:
    """Apply all transformations in order to a single English name."""
    value = normalize_quotes(value)
    if is_program:
        value = strip_type_label(strip_program_prefix(value))
    return strip_trailing_federation(shorten_federation(value))


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
        new_translated = normalize_translated_name(name_translated, is_program)
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
