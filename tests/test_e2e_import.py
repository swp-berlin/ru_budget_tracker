"""End-to-end import test: migrations + real import of one report into a temp DB.

The only test of the DB-write path (save_budget / save_dimensions / save_expenses
+ the alembic schema); the parser side is covered per-file by the golden tier.
Runs via subprocess because database/sessions.py binds the engine to
settings.database at import time — the env must be set before interpreter start.
Writes only to pytest's tmp_path; the checked-in src/data/budget.db is untouched.
"""

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from tests.conftest import GOLDENS_DIR, REPO_ROOT

pytestmark = pytest.mark.e2e

SRC_DIR = REPO_ROOT / "src"


def run_in_src(command: list[str], database_directory: Path) -> None:
    env = os.environ | {
        "DATABASE__DIRECTORY": str(database_directory),
        "DEEPL_API_KEY": os.environ.get("DEEPL_API_KEY", "test-dummy"),
        "NEXTCLOUD_DOWNLOAD_LINK": os.environ.get(
            "NEXTCLOUD_DOWNLOAD_LINK", "https://example.invalid"
        ),
    }
    result = subprocess.run(
        command, cwd=SRC_DIR, env=env, capture_output=True, text=True, timeout=600
    )
    assert result.returncode == 0, (
        f"{' '.join(command)} failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
    )


def test_import_report_2026_into_fresh_db(tmp_path: Path) -> None:
    run_in_src(["uv", "run", "alembic", "upgrade", "head"], tmp_path)
    run_in_src(
        [
            "uv",
            "run",
            "python",
            "-m",
            "scripts.import",
            "budget",
            "--type",
            "report",
            "--years",
            "2026",
        ],
        tmp_path,
    )

    with (GOLDENS_DIR / "report_2026_03.json").open(encoding="utf-8") as f:
        golden = json.load(f)

    connection = sqlite3.connect(f"file:{tmp_path / 'budget.db'}?mode=ro", uri=True)
    try:
        count, total = connection.execute(
            """
            SELECT COUNT(e.id), COALESCE(SUM(e.value), 0)
            FROM budgets b LEFT JOIN expenses e ON e.budget_id = b.id
            WHERE b.original_identifier = 'REPORT-2026-03'
            """
        ).fetchone()
        # The DB-write path must persist exactly what the parser produced
        # (which the golden tier pins against the source file).
        assert count == golden["expense_count"]
        assert f"{total:.2f}" == golden["expense_total"]

        expenses_missing_dimensions = connection.execute(
            """
            SELECT COUNT(*) FROM expenses e
            WHERE NOT EXISTS (SELECT 1 FROM association_table a WHERE a.expense_id = e.id)
            """
        ).fetchone()[0]
        assert expenses_missing_dimensions == 0

        dangling_parents = connection.execute(
            """
            SELECT COUNT(*) FROM dimensions c LEFT JOIN dimensions p ON p.id = c.parent_id
            WHERE c.parent_id IS NOT NULL AND p.id IS NULL
            """
        ).fetchone()[0]
        assert dangling_parents == 0
    finally:
        connection.close()
