"""
Dimension name translation script.

Translates Russian dimension names to English using OpenAI API.
Caches translations in CSV to avoid redundant API calls.

Uses OpenAI Structured Outputs with strict JSON schema for reliable parsing.
Uses numeric IDs to avoid encoding issues when matching translations.

Usage:
    python translate_dimensions.py                    # Translate all missing names
    python translate_dimensions.py --dry-run          # Show what would be translated
    python translate_dimensions.py --force            # Re-translate all names
    python translate_dimensions.py --batch-size 50    # Custom batch size for API calls
    python translate_dimensions.py --workers 5        # Parallel API calls (default: 5)
    python translate_dimensions.py --limit 20         # Test with first 20 names only

Environment:
    OPENAI_API_KEY: Required. Your OpenAI API key.
"""

import sys
import os
import csv
import json
import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Set

# Add parent to path if needed
sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import BaseModel
from sqlalchemy import select, update
from openai import OpenAI
from models import Dimension
from database.sessions import get_sync_session
from settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

TRANSLATIONS_DIR = Path(__file__).parent.parent / "data" / "import_files" / "clean" / "translations"
TRANSLATIONS_FILE = TRANSLATIONS_DIR / "dimension_translations.csv"

# OpenAI settings
OPENAI_MODEL = "gpt-4o-mini"
BATCH_SIZE = 25  # Number of names to translate per API call
MAX_WORKERS = 8  # Parallel API calls


# =============================================================================
# PYDANTIC MODELS FOR STRUCTURED OUTPUT
# =============================================================================


class TranslationItem(BaseModel):
    """Single translation result with ID for reliable matching."""

    id: int
    original: str
    translation: str


class TranslationResponse(BaseModel):
    """Response schema for batch translation."""

    translations: list[TranslationItem]


# =============================================================================
# CSV OPERATIONS
# =============================================================================


def load_existing_translations() -> Dict[str, str]:
    """
    Load existing translations from CSV file.

    Returns:
        Dictionary mapping Russian names to English translations.
    """
    translations: Dict[str, str] = {}

    if not TRANSLATIONS_FILE.exists():
        logger.info(f"No existing translations file found at {TRANSLATIONS_FILE}")
        return translations

    with open(TRANSLATIONS_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            russian_name = row.get("name_russian", "").strip()
            english_name = row.get("name_english", "").strip()
            if russian_name and english_name:
                translations[russian_name] = english_name

    logger.info(f"Loaded {len(translations)} existing translations from CSV")
    return translations


def save_translations_to_csv(translations: Dict[str, str]) -> None:
    """
    Save all translations to CSV file.

    Args:
        translations: Dictionary mapping Russian names to English translations.
    """
    # Ensure directory exists
    TRANSLATIONS_DIR.mkdir(parents=True, exist_ok=True)

    with open(TRANSLATIONS_FILE, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name_russian", "name_english"])
        writer.writeheader()
        for russian, english in sorted(translations.items()):
            writer.writerow({"name_russian": russian, "name_english": english})

    logger.info(f"Saved {len(translations)} translations to {TRANSLATIONS_FILE}")


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================


def get_unique_dimension_names() -> Set[str]:
    """
    Get all unique dimension names from the database.

    Returns:
        Set of unique Russian dimension names.
    """
    with get_sync_session() as session:
        stmt = select(Dimension.name).distinct()
        result = session.execute(stmt).scalars().all()
        names = {name for name in result if name}

    logger.info(f"Found {len(names)} unique dimension names in database")
    return names


def upsert_translations_to_db(translations: Dict[str, str]) -> int:
    """
    Update dimension records with translated names.

    Args:
        translations: Dictionary mapping Russian names to English translations.

    Returns:
        Number of records updated.
    """
    updated_count = 0

    with get_sync_session() as session:
        for russian_name, english_name in translations.items():
            stmt = (
                update(Dimension)
                .where(Dimension.name == russian_name)
                .where(
                    (Dimension.name_translated.is_(None))
                    | (Dimension.name_translated != english_name)
                )
                .values(name_translated=english_name)
            )
            result = session.execute(stmt)
            updated_count += result.rowcount  # type: ignore[union-attr]

        session.commit()

    logger.info(f"Updated {updated_count} dimension records with translations")
    return updated_count


# =============================================================================
# OPENAI TRANSLATION
# =============================================================================


def translate_names_batch(names: List[str], client: OpenAI) -> Dict[str, str]:
    """
    Translate a batch of Russian names to English using OpenAI.

    Uses Structured Outputs with Pydantic for guaranteed schema compliance.
    Uses numeric IDs to avoid encoding issues when matching.

    Args:
        names: List of Russian names to translate.
        client: OpenAI client instance.

    Returns:
        Dictionary mapping Russian names to English translations.
    """
    if not names:
        return {}

    # Create indexed list with numeric IDs for safe matching
    indexed_names = [{"id": i, "name": name} for i, name in enumerate(names)]
    names_json = json.dumps(indexed_names, ensure_ascii=False, indent=2)

    prompt = f"""Translate the following Russian government budget dimension names to English.
These are official names of ministries, chapters, programs, and expense types from Russian federal budget documents.

Translation guidelines:
- Use accurate, official-sounding English government terminology
- Keep translations concise but complete
- Maintain consistency across similar terms
- Preserve the meaning and official nature of the terms

Input format: Each item has an "id" and a "name" (Russian text to translate).
Output format: Return translations with the same "id", the "original" Russian text, and the English "translation".

IMPORTANT: You must return the exact same "id" and "original" text for each item to ensure correct matching.

Names to translate:
{names_json}"""

    try:
        # Use the beta parse endpoint with Pydantic model for strict schema
        response = client.beta.chat.completions.parse(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional translator specializing in Russian government "
                        "and financial documents. Translate accurately using standard English "
                        "government terminology. Return structured JSON matching the exact schema."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format=TranslationResponse,
            temperature=0.1,  # Low temperature for consistent translations
        )

        # Check for refusal
        if response.choices[0].message.refusal:
            logger.error(f"Model refused request: {response.choices[0].message.refusal}")
            raise ValueError(f"Translation refused: {response.choices[0].message.refusal}")

        # Parse the structured response
        parsed_response = response.choices[0].message.parsed

        if parsed_response is None:
            logger.error("Failed to parse response: parsed_response is None")
            raise ValueError("OpenAI returned unparseable response")

        # Build result dictionary using IDs to match back to original names
        translations: Dict[str, str] = {}
        id_to_name = {i: name for i, name in enumerate(names)}

        for item in parsed_response.translations:
            original_name = id_to_name.get(item.id)
            if original_name is None:
                logger.warning(f"Unknown ID {item.id} in response, skipping")
                continue

            # Verify the original text matches (safety check)
            if item.original != original_name:
                logger.warning(
                    f"ID {item.id}: Original text mismatch. "
                    f"Expected: '{original_name[:50]}...', Got: '{item.original[:50]}...'"
                )
                # Still use the ID-based matching as primary
            translations[original_name] = item.translation

        # Check for missing translations
        missing = [name for name in names if name not in translations]
        if missing:
            logger.warning(f"Missing translations for {len(missing)} names")

        logger.debug(f"Translated batch of {len(translations)}/{len(names)} names")
        return translations

    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        raise


def translate_missing_names(
    db_names: Set[str],
    existing_translations: Dict[str, str],
    client: OpenAI,
    batch_size: int = BATCH_SIZE,
    max_workers: int = MAX_WORKERS,
) -> Dict[str, str]:
    """
    Translate names that don't have existing translations.

    Args:
        db_names: All unique names from database.
        existing_translations: Already translated names.
        client: OpenAI client.
        batch_size: Number of names per API call.
        max_workers: Number of parallel API calls.

    Returns:
        Dictionary with all translations (existing + new).
    """
    # Find names needing translation
    missing_names = [name for name in db_names if name not in existing_translations]

    if not missing_names:
        logger.info("All dimension names already have translations")
        return existing_translations

    logger.info(f"Found {len(missing_names)} names needing translation")

    # Split into batches
    batches = [missing_names[i : i + batch_size] for i in range(0, len(missing_names), batch_size)]
    total_batches = len(batches)
    logger.info(f"Processing {total_batches} batches with {max_workers} workers")

    # Translate in parallel
    new_translations: Dict[str, str] = {}
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(translate_names_batch, batch, client): i for i, batch in enumerate(batches)}

        for future in as_completed(futures):
            batch_num = futures[future] + 1
            try:
                batch_translations = future.result()
                new_translations.update(batch_translations)
                completed += 1
                logger.info(f"Completed batch {batch_num}/{total_batches} ({completed}/{total_batches} done)")
            except Exception as e:
                logger.error(f"Batch {batch_num} failed: {e}")

    # Combine existing and new translations
    all_translations = {**existing_translations, **new_translations}
    logger.info(f"Total translations: {len(all_translations)}")

    return all_translations


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Translate dimension names to English")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be translated without making changes",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-translate all names, ignoring existing translations",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Number of names per API call (default: {BATCH_SIZE})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=MAX_WORKERS,
        help=f"Number of parallel API calls (default: {MAX_WORKERS})",
    )
    parser.add_argument(
        "--skip-db-update",
        action="store_true",
        help="Only update CSV, don't update database",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit to first N dimension names (for testing)",
    )
    args = parser.parse_args()

    # Check for API key (environment variable takes precedence over settings)
    api_key = os.environ.get("OPENAI_API_KEY") or settings.openai_api_key
    if not api_key and not args.dry_run:
        logger.info("OPENAI_API_KEY not found")

    # Get dimension names from database
    db_names = get_unique_dimension_names()

    if not db_names:
        logger.warning("No dimension names found in database. Import data first.")
        sys.exit(0)

    # Apply limit for testing
    if args.limit:
        db_names = set(list(db_names)[: args.limit])
        logger.info(f"Limited to first {args.limit} dimension names (for testing)")

    # Load existing translations
    existing_translations = {} if args.force else load_existing_translations()

    # Find missing translations
    missing_names = [name for name in db_names if name not in existing_translations]

    if args.dry_run:
        logger.info(f"\n{'=' * 60}")
        logger.info("DRY RUN - No changes will be made")
        logger.info(f"{'=' * 60}")
        logger.info(f"Total unique names in database: {len(db_names)}")
        logger.info(f"Existing translations in CSV: {len(existing_translations)}")
        logger.info(f"Names needing translation: {len(missing_names)}")
        logger.info(f"Batch size: {args.batch_size}, Workers: {args.workers}")
        logger.info(f"Estimated batches: {(len(missing_names) + args.batch_size - 1) // args.batch_size}")

        if missing_names:
            logger.info("\nSample of names to translate (first 10):")
            for name in list(missing_names)[:10]:
                logger.info(f"  - {name}")

        return

    if not missing_names:
        logger.info("All names already translated. Updating database...")
        if not args.skip_db_update:
            upsert_translations_to_db(existing_translations)
        return

    # Initialize OpenAI client
    client = OpenAI(api_key=api_key)

    # Translate missing names
    all_translations = translate_missing_names(
        db_names, existing_translations, client, args.batch_size, args.workers
    )

    # Save to CSV
    save_translations_to_csv(all_translations)

    # Update database
    if not args.skip_db_update:
        upsert_translations_to_db(all_translations)

    logger.info(f"\n{'=' * 60}")
    logger.info("DONE")
    logger.info(f"  Translated: {len(missing_names)} new names")
    logger.info(f"  Total translations: {len(all_translations)}")
    logger.info(f"  CSV saved to: {TRANSLATIONS_FILE}")
    logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    main()