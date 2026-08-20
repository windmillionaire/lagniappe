"""
Test results recording and HTML report generation.

This module provides infrastructure for recording test results and generating
readable HTML reports with collapsible sections.

Usage:
    def test_ai_response(results):
        response = ai.generate(prompt)
        results.record("prompt", prompt)
        results.record("response", response)
        results.record("metadata", {"model": "gpt-4", "tokens": 150})

Related Files:
    - testing/conftest.py: results fixture definition
    - testing/utility/error_tracking.py: capture_on_failure for screenshots

Output:
    HTML reports are saved to reports/test_reports/{test_name}_{timestamp}.html
"""

from datetime import datetime
import html
import json
import logging
from typing import Any

from .artifacts import TEST_REPORTS_DIR

logger = logging.getLogger(__name__)

REPORTS_DIR = TEST_REPORTS_DIR
__test__ = False


def _format_value(value: Any) -> tuple[str, str]:
    """
    Format a value for display in HTML report.

    Returns:
        tuple: (formatted_html, css_class)
    """
    if value is None:
        return '<span class="null">null</span>', "null"

    if isinstance(value, bool):
        return f'<span class="boolean">{str(value).lower()}</span>', "boolean"

    if isinstance(value, (int, float)):
        return f'<span class="number">{value}</span>', "number"

    if isinstance(value, str):
        # Check if it's JSON string
        try:
            parsed = json.loads(value)
            formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
            return f'<pre class="json">{html.escape(formatted)}</pre>', "json"
        except (json.JSONDecodeError, TypeError):
            pass

        # Multi-line string
        if "\n" in value:
            return f'<pre class="text">{html.escape(value)}</pre>', "text"

        # Single line string
        return f'<span class="string">"{html.escape(value)}"</span>', "string"

    if isinstance(value, dict):
        try:
            formatted = json.dumps(value, indent=2, ensure_ascii=False, default=str)
            return f'<pre class="json">{html.escape(formatted)}</pre>', "json"
        except (TypeError, ValueError):
            return f'<pre class="text">{html.escape(str(value))}</pre>', "text"

    if isinstance(value, (list, tuple)):
        try:
            formatted = json.dumps(value, indent=2, ensure_ascii=False, default=str)
            return f'<pre class="json">{html.escape(formatted)}</pre>', "json"
        except (TypeError, ValueError):
            return f'<pre class="text">{html.escape(str(value))}</pre>', "text"

    # Fallback for any other type
    return f'<pre class="text">{html.escape(str(value))}</pre>', "text"


def _generate_html(
    test_name: str, records: list[tuple[str, Any]], metadata: dict
) -> str:
    """Generate HTML report content."""

    timestamp = metadata.get("timestamp", datetime.now().isoformat())
    duration = metadata.get("duration_ms")
    duration_str = f"{duration:.0f}ms" if duration else "N/A"

    records_html = []
    for idx, (name, value) in enumerate(records):
        formatted_value, css_class = _format_value(value)
        records_html.append(f"""
        <details class="record" open>
            <summary class="record-header">
                <span class="record-index">#{idx + 1}</span>
                <span class="record-name">{html.escape(name)}</span>
                <span class="record-type">{css_class}</span>
            </summary>
            <div class="record-content {css_class}">
                {formatted_value}
            </div>
        </details>
        """)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test Report: {html.escape(test_name)}</title>
    <style>
        :root {{
            --bg-primary: #1a1b26;
            --bg-secondary: #24283b;
            --bg-tertiary: #2a2e42;
            --text-primary: #c0caf5;
            --text-secondary: #7aa2f7;
            --text-muted: #565f89;
            --accent: #bb9af7;
            --success: #9ece6a;
            --warning: #e0af68;
            --error: #f7768e;
            --border: #3b4261;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', monospace;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            padding: 2rem;
            min-height: 100vh;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        header {{
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.5rem 2rem;
            margin-bottom: 2rem;
        }}

        h1 {{
            color: var(--accent);
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 1rem;
            word-break: break-word;
        }}

        .metadata {{
            display: flex;
            flex-wrap: wrap;
            gap: 1.5rem;
            font-size: 0.875rem;
        }}

        .meta-item {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .meta-label {{
            color: var(--text-muted);
        }}

        .meta-value {{
            color: var(--text-secondary);
        }}

        .records {{
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }}

        .record {{
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
        }}

        .record-header {{
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 1rem 1.5rem;
            cursor: pointer;
            user-select: none;
            background: var(--bg-tertiary);
            border-bottom: 1px solid var(--border);
            transition: background 0.15s ease;
        }}

        .record-header:hover {{
            background: var(--bg-secondary);
        }}

        .record-index {{
            color: var(--text-muted);
            font-size: 0.75rem;
            min-width: 2rem;
        }}

        .record-name {{
            color: var(--success);
            font-weight: 500;
            flex: 1;
        }}

        .record-type {{
            color: var(--text-muted);
            font-size: 0.75rem;
            padding: 0.125rem 0.5rem;
            background: var(--bg-primary);
            border-radius: 4px;
        }}

        .record-content {{
            padding: 1.5rem;
            overflow-x: auto;
        }}

        pre {{
            margin: 0;
            white-space: pre-wrap;
            word-wrap: break-word;
            font-size: 0.875rem;
            line-height: 1.5;
        }}

        .json {{
            color: var(--text-primary);
        }}

        .text {{
            color: var(--text-secondary);
        }}

        .string {{
            color: var(--success);
        }}

        .number {{
            color: var(--warning);
        }}

        .boolean {{
            color: var(--accent);
        }}

        .null {{
            color: var(--text-muted);
            font-style: italic;
        }}

        details[open] .record-header::before {{
            content: '▼';
            color: var(--text-muted);
            font-size: 0.625rem;
            margin-right: -0.5rem;
        }}

        details:not([open]) .record-header::before {{
            content: '▶';
            color: var(--text-muted);
            font-size: 0.625rem;
            margin-right: -0.5rem;
        }}

        .no-records {{
            text-align: center;
            padding: 3rem;
            color: var(--text-muted);
            font-style: italic;
        }}

        .controls {{
            margin-bottom: 1rem;
            display: flex;
            gap: 0.5rem;
        }}

        button {{
            font-family: inherit;
            font-size: 0.75rem;
            padding: 0.5rem 1rem;
            background: var(--bg-tertiary);
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text-secondary);
            cursor: pointer;
            transition: all 0.15s ease;
        }}

        button:hover {{
            background: var(--bg-secondary);
            border-color: var(--text-secondary);
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{html.escape(test_name)}</h1>
            <div class="metadata">
                <div class="meta-item">
                    <span class="meta-label">Timestamp:</span>
                    <span class="meta-value">{timestamp}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Duration:</span>
                    <span class="meta-value">{duration_str}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Records:</span>
                    <span class="meta-value">{len(records)}</span>
                </div>
            </div>
        </header>

        <div class="controls">
            <button onclick="document.querySelectorAll('details').forEach(d => d.open = true)">
                Expand All
            </button>
            <button onclick="document.querySelectorAll('details').forEach(d => d.open = false)">
                Collapse All
            </button>
        </div>

        <div class="records">
            {"".join(records_html) if records_html else '<div class="no-records">No records captured</div>'}
        </div>
    </div>
</body>
</html>"""


class TestResults:
    """
    Collects and formats test results for HTML report generation.

    This class is instantiated per-test by the results fixture. Records are
    written to an HTML file on finalize() which is called during fixture teardown.

    Attributes:
        test_name: Name of the test function
        records: List of (name, value) tuples
        metadata: Auto-collected information (timestamp, duration, etc.)

    Example:
        results.record("input", {"query": "test"})
        results.record("output", response_text)
        results.record("tokens_used", 150)
    """

    def __init__(self, test_name: str):
        self.test_name = test_name
        self.records: list[tuple[str, Any]] = []
        self.metadata: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "start_time": datetime.now(),
        }
        self._finalized = False

    def record(self, name: str, value: Any) -> "TestResults":
        """
        Record a named value for the test report.

        Args:
            name: Label for this record (e.g., "prompt", "response", "error")
            value: Any value - dicts/lists become formatted JSON, strings are
                   auto-detected as JSON or plain text, other types are stringified

        Returns:
            self for chaining: results.record("a", 1).record("b", 2)
        """
        self.records.append((name, value))
        logger.debug(f"Recorded '{name}' for test '{self.test_name}'")
        return self

    def finalize(self) -> str | None:
        """
        Generate and save the HTML report.

        Called automatically during fixture teardown. Only generates a report
        if records were captured.

        Returns:
            Path to generated report file, or None if no records
        """
        if self._finalized:
            return None

        self._finalized = True

        if not self.records:
            logger.debug(f"No records for '{self.test_name}', skipping report")
            return None

        # Calculate duration
        start_time = self.metadata.get("start_time")
        if start_time:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            self.metadata["duration_ms"] = duration_ms

        # Ensure reports directory exists
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in self.test_name
        )
        filename = REPORTS_DIR / f"{safe_name}_{timestamp}.html"

        # Generate and write HTML
        html_content = _generate_html(self.test_name, self.records, self.metadata)
        filename.write_text(html_content, encoding="utf-8")

        logger.info(f"Test report saved: {filename}")
        return str(filename)
