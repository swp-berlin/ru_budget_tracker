"""Unit tests for get_law_files / get_report_files in scripts.import.

Uses tmp_path with touch()ed fake files. Since the Phase B "glob everything"
change, default discovery (years=None) picks up EVERY matching file on disk —
there is no year window, so files cannot be silently skipped. An explicit
years= filter still narrows discovery to those years.
"""

import importlib
from pathlib import Path

import pytest

# scripts.import is a reserved-word module name, so import it dynamically.
import_module = importlib.import_module("scripts.import")


# =============================================================================
# get_law_files
# =============================================================================


@pytest.fixture
def laws_dir(tmp_path: Path) -> Path:
    """A data dir whose laws/ holds files bracketing the former year window."""
    laws = tmp_path / "laws"
    laws.mkdir()
    for name in [
        "law_2017.xlsx",
        "law_2018.xlsx",
        "law_2026.xlsx",
        "law_2027.xlsx",
        "law_2018.txt",  # wrong extension ⇒ ignored
        "draft_2018.xlsx",  # wrong prefix ⇒ ignored
    ]:
        (laws / name).touch()
    return tmp_path


def test_get_law_files_default_discovers_every_file_on_disk(laws_dir: Path) -> None:
    # No year window: 2017 and 2027 are discovered too.
    files = import_module.get_law_files(laws_dir)
    assert [p.name for p in files] == [
        "law_2017.xlsx",
        "law_2018.xlsx",
        "law_2026.xlsx",
        "law_2027.xlsx",
    ]


def test_get_law_files_explicit_years_builds_paths_without_existence_check() -> None:
    # With an explicit filter, one path per requested year is built (no glob/stat);
    # main() reports missing files as "not found" instead of skipping silently.
    files = import_module.get_law_files(Path("/data"), [2017, 2018, 2027])
    assert [p.name for p in files] == ["law_2017.xlsx", "law_2018.xlsx", "law_2027.xlsx"]
    assert all(p.parent.name == "laws" for p in files)


# =============================================================================
# get_report_files
# =============================================================================


@pytest.fixture
def reports_dir(tmp_path: Path) -> Path:
    """A data dir whose reports/ holds files bracketing the former year window."""
    reports = tmp_path / "reports"
    reports.mkdir()
    for name in [
        "report_2017_03.xlsx",
        "report_2018_03.xlsx",
        "report_2018_06.xls",  # .xls also matches the glob
        "report_2026_12.xlsx",
        "report_2027_03.xlsx",
        "report_2018_notmatch.txt",  # not report_YYYY_MM.xls* ⇒ ignored
    ]:
        (reports / name).touch()
    return tmp_path


def test_get_report_files_default_discovers_every_file_on_disk(reports_dir: Path) -> None:
    # No year window: 2017 and 2027 are discovered too.
    files = import_module.get_report_files(reports_dir)
    assert [p.name for p in files] == [
        "report_2017_03.xlsx",
        "report_2018_03.xlsx",
        "report_2018_06.xls",
        "report_2026_12.xlsx",
        "report_2027_03.xlsx",
    ]


def test_get_report_files_year_filter(reports_dir: Path) -> None:
    files = import_module.get_report_files(reports_dir, [2018])
    assert [p.name for p in files] == ["report_2018_03.xlsx", "report_2018_06.xls"]


def test_get_report_files_missing_directory_returns_empty(tmp_path: Path) -> None:
    assert import_module.get_report_files(tmp_path / "nonexistent") == []
