"""Shared fixtures and paths for the test suite.

Tiers (see docs/tests.md):
- unit (no marker): pure parser functions, synthetic inputs, no data files or DB.
- db: assertions against the checked-in src/data/budget.db.
- golden: parses the real Excel/CSV files under src/data/import_files.
- e2e: real import into a temporary database.
- external: needs untracked third-party CSVs in .claude/validation/.
"""

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

# scripts.import pulls in settings.importer, whose pydantic settings require
# these env vars at import time. Tests never download or translate anything, so stubs
# are enough. Must run before any test module imports scripts.*.
os.environ.setdefault("DEEPL_API_KEY", "test-dummy")
os.environ.setdefault("NEXTCLOUD_DOWNLOAD_LINK", "https://example.invalid")

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "src" / "data" / "budget.db"
IMPORT_FILES_DIR = REPO_ROOT / "src" / "data" / "import_files"
LAWS_DIR = IMPORT_FILES_DIR / "clean" / "laws"
REPORTS_DIR = IMPORT_FILES_DIR / "clean" / "reports"
TOTALS_DIR = IMPORT_FILES_DIR / "raw" / "totals"
GOLDENS_DIR = REPO_ROOT / "tests" / "goldens"
EXTERNAL_VALIDATION_DIR = REPO_ROOT / ".claude" / "validation"


@pytest.fixture(scope="session")
def db_connection() -> Iterator[sqlite3.Connection]:
    """Read-only connection to the checked-in budget.db."""
    if not DB_PATH.exists():
        pytest.fail(f"Database file not found: {DB_PATH}")

    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        yield connection
    finally:
        connection.close()
