"""
Dimension name translation script.

Translates Russian dimension names to English using DeepL API.
Caches translations in CSV to avoid redundant API calls.

Usage:
    python translations.py                    # Translate all missing names
    python translations.py --dry-run          # Show what would be translated
    python translations.py --force            # Re-translate all names
    python translations.py --batch-size 50    # Custom batch size per API call
    python translations.py --workers 5        # Parallel API calls (default: 5)
    python translations.py --limit 20         # Test with first 20 names only

Environment:
   IMPORTER__DEEPL_API_KEY: Required. Your DeepL API key.
"""

import sys
import os
import csv
import argparse
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Set

sys.path.insert(0, str(Path(__file__).parent.parent))

import deepl
from sqlalchemy import select, update
from models import Dimension
from database.sessions import get_sync_session
from settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# TRANSLATIONS_DIR = Path(__file__).parent.parent / "data" / "import_files" / "clean" / "translations"
# TRANSLATIONS_FILE = TRANSLATIONS_DIR / "dimension_translations.csv"
TRANSLATIONS_DIR = settings.importer.translation_dir
TRANSLATIONS_FILE = TRANSLATIONS_DIR / "dimension_translations.csv"

BATCH_SIZE = 50  # DeepL supports up to 50 texts per request
MAX_WORKERS = 2  # Parallel API calls (free tier is rate-limited)
RETRY_ATTEMPTS = 4
RETRY_BASE_DELAY = 2.0  # seconds, doubles on each retry


# =============================================================================
# CSV OPERATIONS
# =============================================================================


def load_existing_translations() -> Dict[str, str]:
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
    with get_sync_session() as session:
        stmt = select(Dimension.name).distinct()
        result = session.execute(stmt).scalars().all()
        names = {name for name in result if name}

    logger.info(f"Found {len(names)} unique dimension names in database")
    return names


def upsert_translations_to_db(translations: Dict[str, str]) -> int:
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
            updated_count += result.rowcount  # type: ignore

        session.commit()

    logger.info(f"Updated {updated_count} dimension records with translations")
    return updated_count


# =============================================================================
# DEEPL TRANSLATION
# =============================================================================


def translate_names_batch(names: List[str], translator: deepl.Translator) -> Dict[str, str]:
    """Translate a batch of Russian names to English using DeepL, with exponential backoff."""
    if not names:
        return {}

    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = translator.translate_text(names, source_lang="RU", target_lang="EN-US")
            results = [response] if isinstance(response, deepl.TextResult) else response
            translations = {name: result.text for name, result in zip(names, results)}
            logger.debug(f"Translated batch of {len(translations)} names")
            return translations
        except deepl.TooManyRequestsException:
            delay = RETRY_BASE_DELAY * (2**attempt)
            logger.warning(
                f"Rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{RETRY_ATTEMPTS})"
            )
            time.sleep(delay)
        except Exception as e:
            logger.error(f"DeepL API error: {e}")
            raise

    raise RuntimeError(f"Batch failed after {RETRY_ATTEMPTS} attempts due to rate limiting")


def translate_missing_names(
    db_names: Set[str],
    existing_translations: Dict[str, str],
    translator: deepl.Translator,
    batch_size: int = BATCH_SIZE,
    max_workers: int = MAX_WORKERS,
) -> Dict[str, str]:
    missing_names = [name for name in db_names if name not in existing_translations]

    if not missing_names:
        logger.info("All dimension names already have translations")
        return existing_translations

    logger.info(f"Found {len(missing_names)} names needing translation")

    batches = [missing_names[i : i + batch_size] for i in range(0, len(missing_names), batch_size)]
    total_batches = len(batches)
    logger.info(f"Processing {total_batches} batches with {max_workers} workers")

    new_translations: Dict[str, str] = {}
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(translate_names_batch, batch, translator): i
            for i, batch in enumerate(batches)
        }

        for future in as_completed(futures):
            batch_num = futures[future] + 1
            try:
                batch_translations = future.result()
                new_translations.update(batch_translations)
                completed += 1
                logger.info(
                    f"Completed batch {batch_num}/{total_batches} ({completed}/{total_batches} done)"
                )
            except Exception as e:
                logger.error(f"Batch {batch_num} failed: {e}")

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
        "--skip-db-update", action="store_true", help="Only update CSV, don't update database"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit to first N dimension names (for testing)"
    )
    args = parser.parse_args()

    api_key = os.environ.get("IMPORTER__DEEPL_API_KEY") or settings.importer.deepl_api_key
    if not api_key and not args.dry_run:
        logger.error("IMPORTER__DEEPL_API_KEY not found")
        sys.exit(1)

    db_names = get_unique_dimension_names()

    if not db_names:
        logger.warning("No dimension names found in database. Import data first.")
        sys.exit(0)

    if args.limit:
        db_names = set(list(db_names)[: args.limit])
        logger.info(f"Limited to first {args.limit} dimension names (for testing)")

    existing_translations = {} if args.force else load_existing_translations()
    missing_names = [name for name in db_names if name not in existing_translations]

    if args.dry_run:
        logger.info(f"\n{'=' * 60}")
        logger.info("DRY RUN - No changes will be made")
        logger.info(f"{'=' * 60}")
        logger.info(f"Total unique names in database: {len(db_names)}")
        logger.info(f"Existing translations in CSV: {len(existing_translations)}")
        logger.info(f"Names needing translation: {len(missing_names)}")
        logger.info(f"Batch size: {args.batch_size}, Workers: {args.workers}")
        logger.info(
            f"Estimated batches: {(len(missing_names) + args.batch_size - 1) // args.batch_size}"
        )
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

    # The deepl client routes keys to the free/pro endpoint by the ':fx' key
    # suffix; scoped Pro keys are misrouted. DEEPL_SERVER_URL overrides
    # (e.g. https://api.deepl.com); unset keeps the client's own detection.
    translator = deepl.Translator(api_key, server_url=os.environ.get("DEEPL_SERVER_URL"))

    all_translations = translate_missing_names(
        db_names, existing_translations, translator, args.batch_size, args.workers
    )

    save_translations_to_csv(all_translations)

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
