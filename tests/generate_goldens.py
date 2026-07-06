"""Regenerate the golden characterization files in tests/goldens/.

Run from the repo root:

    uv run --group dev python tests/generate_goldens.py [--only STEM] [--dump-rows STEM]

Only regenerate deliberately: goldens pin current parser behavior, and the commit
that changes them must explain why the numbers changed (see docs/tests.md).

--dump-rows STEM writes the full canonical row list for one file to
tests/goldens/.rowdumps/<stem>.txt (gitignored) WITHOUT touching the golden —
use it to find which rows changed when only rows_sha256 differs (dump, then
`git stash` / check out the old code, dump again, diff the two files).
"""

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from scripts.parsers import parse_law_file, parse_report_file, parse_totals_file  # noqa: E402

from tests.conftest import GOLDENS_DIR  # noqa: E402
from tests.golden_utils import (  # noqa: E402
    TOTALS_FILES,
    canonical_rows,
    golden_name,
    law_files,
    report_files,
    summarize_parse,
    summarize_totals_parse,
)


def log(message: str) -> None:
    print(message, file=sys.stderr)  # noqa: T201


def write_golden(golden: dict, path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(golden, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")


def parse_budget_file(source: Path) -> tuple:
    parse = parse_law_file if source.stem.startswith("law") else parse_report_file
    return parse(source)


def dump_rows(stem: str) -> None:
    """Write the canonical row list for one law/report file; does NOT update its golden."""
    sources = [f for f in law_files() + report_files() if f.stem == stem]
    if not sources:
        raise SystemExit(f"no law/report data file with stem {stem!r}")
    _, _, expenses = parse_budget_file(sources[0])
    dump_dir = GOLDENS_DIR / ".rowdumps"
    dump_dir.mkdir(parents=True, exist_ok=True)
    dump_path = dump_dir / f"{stem}.txt"
    dump_path.write_text("\n".join(canonical_rows(expenses)) + "\n", encoding="utf-8")
    log(f"{stem}: wrote {dump_path}")


def generate(only: str | None) -> None:
    GOLDENS_DIR.mkdir(exist_ok=True)
    matched = False

    for source in law_files() + report_files():
        if only and source.stem != only:
            continue
        matched = True
        started = time.monotonic()
        budget, dimensions, expenses = parse_budget_file(source)
        write_golden(
            summarize_parse(budget, dimensions, expenses, source),
            GOLDENS_DIR / golden_name(source),
        )
        log(f"{source.stem}: {len(expenses)} expenses ({time.monotonic() - started:.1f}s)")

    for source in TOTALS_FILES:
        if only and source.stem != only:
            continue
        matched = True
        budgets, chapter_codes, expenses = parse_totals_file(source)
        write_golden(
            summarize_totals_parse(budgets, chapter_codes, expenses, source),
            GOLDENS_DIR / golden_name(source),
        )
        log(f"{source.stem}: {len(expenses)} expense entries")

    if only and not matched:
        raise SystemExit(f"no data file with stem {only!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="regenerate a single golden by file stem")
    parser.add_argument(
        "--dump-rows",
        metavar="STEM",
        help="dump canonical rows for this file stem instead of regenerating goldens",
    )
    args = parser.parse_args()
    if args.dump_rows:
        dump_rows(args.dump_rows)
    else:
        generate(args.only)


if __name__ == "__main__":
    main()
