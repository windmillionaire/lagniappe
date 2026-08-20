"""Shared paths for generated local reports and test artifacts."""

from pathlib import Path
import re
from typing import Iterable, TypeVar


REPORTS_ROOT = Path("reports")
TEST_FAILURES_DIR = REPORTS_ROOT / "test_failures"
TEST_REPORTS_DIR = REPORTS_ROOT / "test_reports"
BROWSER_REVIEWS_DIR = REPORTS_ROOT / "browser_reviews"
TEST_RUNS_DIR = REPORTS_ROOT / "test_runs"
T = TypeVar("T")


def write_markdown_report(path: Path, content: str) -> None:
    """Replace Markdown reports by unlinking first so editor previews refresh."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def markdown_escape(value: object) -> str:
    return str(value).replace("|", "\\|")


def markdown_code(value: object) -> str:
    text = str(value).replace("`", "\\`")
    return f"`{text}`"


def markdown_section_count(title: str, count: int) -> str:
    return f"### {title} ({count})"


def markdown_more_line(remaining: int) -> str:
    return f"- _... {remaining} more_" if remaining else ""


def limited(items: list[T], limit: int) -> tuple[list[T], int]:
    shown = items[:limit]
    return shown, max(0, len(items) - len(shown))


def slugify(value: object, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(value)).strip("-").lower()
    return slug or fallback


def markdown_list(values: Iterable[object]) -> str:
    items = list(values)
    return ", ".join(markdown_code(value) for value in items) if items else "_none_"
