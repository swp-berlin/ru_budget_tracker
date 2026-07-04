"""Characterization unit tests for get_law_files / get_report_files in scripts.import.

Uses tmp_path with touch()ed fake files. The key pinned behavior is the hardcoded
year window range(2018, 2027), which silently drops 2017 and 2027.
"""

import importlib
from pathlib import Path

import pytest

# scripts.import is a reserved-word module name, so import it dynamically.
import_module = importlib.import_module("scripts.import")


# =============================================================================
# get_law_files
# =============================================================================


def test_get_law_files_default_year_window() -> None:
    # characterization: with years=None the window is range(2018, 2027) ⇒ 2018..2026 only;
    # 2017 and 2027 are excluded — import.py:612-613
    files = import_module.get_law_files(Path("/data"))
    assert [p.name for p in files] == [f"law_{year}.xlsx" for year in range(2018, 2027)]


def test_get_law_files_builds_paths_without_existence_check_current_behavior() -> None:
    # characterization: get_law_files does not glob or stat — it builds one path per
    # requested year, including out-of-window years when passed explicitly — import.py:615-616
    files = import_module.get_law_files(Path("/data"), [2017, 2018, 2027])
    assert [p.name for p in files] == ["law_2017.xlsx", "law_2018.xlsx", "law_2027.xlsx"]
    assert all(p.parent.name == "laws" for p in files)


# =============================================================================
# get_report_files
# =============================================================================


@pytest.fixture
def reports_dir(tmp_path: Path) -> Path:
    """A data dir whose reports/ holds files spanning and bracketing the year window."""
    reports = tmp_path / "reports"
    reports.mkdir()
    for name in [
        "report_2017_03.xlsx",  # below window
        "report_2018_03.xlsx",
        "report_2018_06.xls",  # .xls also matches the glob
        "report_2026_12.xlsx",
        "report_2027_03.xlsx",  # above window
        "report_2018_notmatch.txt",  # not report_YYYY_MM.xls* ⇒ ignored
    ]:
        (reports / name).touch()
    return tmp_path


def test_get_report_files_default_window_ignores_out_of_range_years(reports_dir: Path) -> None:
    # characterization: 2017 and 2027 files exist on disk but the default range(2018, 2027)
    # window silently skips them — import.py:626-627
    files = import_module.get_report_files(reports_dir)
    assert [p.name for p in files] == [
        "report_2018_03.xlsx",
        "report_2018_06.xls",
        "report_2026_12.xlsx",
    ]


def test_get_report_files_year_filter(reports_dir: Path) -> None:
    files = import_module.get_report_files(reports_dir, [2018])
    assert [p.name for p in files] == ["report_2018_03.xlsx", "report_2018_06.xls"]


def test_get_report_files_missing_directory_returns_empty(tmp_path: Path) -> None:
    assert import_module.get_report_files(tmp_path / "nonexistent") == []
