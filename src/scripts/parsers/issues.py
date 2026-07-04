"""
Structured parse-issue collection.

Parsers accept an optional IssueCollector and record every place where input
data is skipped, coerced, or looks suspicious — with enough context (file,
sheet row, column, raw value) to trace the finding back to the source file.
The collector never changes parsing behavior; scripts/quality_report.py turns
the recorded issues into a readable report.

Severities:
    ERROR   — data is wrong or lost; the import run should fail.
    WARNING — data is suspicious or silently coerced; import continues.
    INFO    — expected quirk worth documenting (e.g. known file properties).
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Literal

Severity = Literal["ERROR", "WARNING", "INFO"]


class ParseError(ValueError):
    """Raised when a source file violates an assumption the parser depends on."""


@dataclass(frozen=True)
class ParseIssue:
    code: str  # machine-readable name, e.g. "value_unparseable"
    severity: Severity
    source_file: str
    message: str  # human-readable sentence
    row_idx: int | None = None  # 0-based sheet/frame row; None = file-level issue
    column: str | None = None
    raw_value: str | None = None


class IssueCollector:
    """Accumulates ParseIssues for one source file."""

    def __init__(self, source_file: str) -> None:
        self.source_file = source_file
        self._issues: list[ParseIssue] = []

    def add(
        self,
        code: str,
        message: str,
        *,
        severity: Severity = "WARNING",
        row_idx: int | None = None,
        column: str | None = None,
        raw_value: object = None,
    ) -> None:
        self._issues.append(
            ParseIssue(
                code=code,
                severity=severity,
                source_file=self.source_file,
                message=message,
                row_idx=row_idx,
                column=column,
                raw_value=None if raw_value is None else str(raw_value),
            )
        )

    def __iter__(self) -> Iterator[ParseIssue]:
        return iter(self._issues)

    def __len__(self) -> int:
        return len(self._issues)

    def counts_by_code(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self._issues:
            counts[issue.code] = counts.get(issue.code, 0) + 1
        return dict(sorted(counts.items()))

    def errors(self) -> list[ParseIssue]:
        return [i for i in self._issues if i.severity == "ERROR"]

    def write_json(self, path: Path) -> None:
        """Write all issues deterministically (sorted, no timestamps)."""
        payload = {
            "source_file": self.source_file,
            "counts_by_code": self.counts_by_code(),
            "issues": [
                asdict(issue)
                for issue in sorted(
                    self._issues, key=lambda i: (i.code, i.row_idx if i.row_idx is not None else -1)
                )
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
