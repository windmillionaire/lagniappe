"""Collect and enforce browser failures for Playwright E2E tests."""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .artifacts import TEST_RUNS_DIR


logger = logging.getLogger(__name__)
DIAGNOSTIC_PATH = TEST_RUNS_DIR / "browser_failure_diagnostics.json"


@dataclass
class BrowserFailure:
    """A browser error observed from one monitored page context."""

    kind: str
    context_id: int
    context_label: str
    page_url: str
    details: dict[str, str | None]
    expected_by: str | None = None
    ignored_reason: str | None = None

    def matches(self, **criteria: str | None) -> bool:
        if criteria.get("kind") and self.kind != criteria["kind"]:
            return False
        for field, expected in criteria.items():
            if field == "kind" or expected is None:
                continue
            if field.endswith("_contains"):
                actual = self.details.get(field.removesuffix("_contains"))
                if actual is None or expected not in actual:
                    return False
                continue
            if self.details.get(field) != expected:
                return False
        return True

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "context": self.context_label,
            "page_url": self.page_url,
            "details": self.details,
            "expected": self.expected_by is not None,
            "expectation": self.expected_by,
            "actionable": self.ignored_reason is None,
            "ignored_reason": self.ignored_reason,
        }


# @testable true
# @tests tests_tooling/test_004_browser_failures.py
# @tests tests_e2e/001_site/test_001a_environment.py::test_browser_failure_guard_detects_unhandled_page_errors
# @features e2e browser-failures
# @dimensions console pageerror requestfailed expectations
class BrowserFailureCollector:
    """Monitor every page in a test's browser contexts and retain failures."""

    def __init__(self):
        self.events: list[BrowserFailure] = []
        self._contexts: dict[int, tuple[str, list[str] | None]] = {}
        self._pages: set[int] = set()

    def monitor_context(
        self,
        context: Any,
        *,
        label: str,
        console_messages: list[str] | None = None,
    ) -> None:
        """Attach listeners before a context creates or opens any pages."""
        context_id = id(context)
        if context_id in self._contexts:
            return

        self._contexts[context_id] = (label, console_messages)
        context.on("page", self._monitor_page)
        for page in context.pages:
            self._monitor_page(page)

    def expect(
        self,
        user: Any,
        *,
        kind: str,
        count: int = 1,
        max_count: int | None = None,
        method: str | None = None,
        path: str | None = None,
        exception_type: str | None = None,
        message: str | None = None,
        message_contains: str | None = None,
        console_type: str | None = None,
        text: str | None = None,
        text_contains: str | None = None,
        failure: str | None = None,
        source_path: str | None = None,
    ) -> "ExpectedBrowserFailure":
        """Return a scope that consumes an intentional failure pattern."""
        if count < 0:
            raise ValueError("Expected browser failure count cannot be negative.")
        if max_count is not None and max_count < count:
            raise ValueError(
                "Maximum browser failure count must be at least the minimum count."
            )
        return ExpectedBrowserFailure(
            self,
            context_id=id(user.page.context),
            kind=kind,
            count=count,
            max_count=max_count,
            criteria={
                "method": method,
                "path": path,
                "exception_type": exception_type,
                "message": message,
                "message_contains": message_contains,
                "console_type": console_type,
                "text": text,
                "text_contains": text_contains,
                "failure": failure,
                "source_path": source_path,
            },
        )

    def expect_http_error(
        self,
        user: Any,
        *,
        status: int,
        path: str,
        count: int = 1,
        max_count: int | None = None,
    ) -> "ExpectedBrowserFailure":
        """Account for an intentional HTTP error reported by Chromium."""
        source_path = urlsplit(path).path
        return self.expect(
            user,
            kind="console",
            count=count,
            max_count=max_count,
            console_type="error",
            text_contains=f"status of {status} ",
            source_path=source_path,
        )

    @contextmanager
    def expect_offline(
        self,
        user: Any,
        *,
        ping_count: int = 1,
        max_ping_count: int | None = None,
    ):
        """Account for the health check deliberately rejected by browser offline mode."""
        with self.expect(
            user,
            kind="requestfailed",
            count=ping_count,
            max_count=max_ping_count,
            method="HEAD",
            path="/l/ping",
            failure="net::ERR_INTERNET_DISCONNECTED",
        ):
            with self.expect(
                user,
                kind="console",
                count=ping_count,
                max_count=max_ping_count,
                console_type="error",
                text="Failed to load resource: net::ERR_INTERNET_DISCONNECTED",
                source_path="/l/ping",
            ):
                yield

    def assert_clean(self) -> None:
        """Raise one teardown-friendly failure for unaccounted browser events."""
        unexpected = [
            event
            for event in self.events
            if event.expected_by is None and event.ignored_reason is None
        ]
        if unexpected:
            raise AssertionError(self.format_events(unexpected))

    def diagnostic_record(self, nodeid: str) -> dict[str, object]:
        return {"nodeid": nodeid, "events": [event.as_dict() for event in self.events]}

    @staticmethod
    def format_events(events: list[BrowserFailure]) -> str:
        lines = ["Unexpected browser failures:"]
        for event in events:
            details = ", ".join(
                f"{name}={value!r}"
                for name, value in event.details.items()
                if value not in (None, "")
            )
            lines.append(
                f"- {event.kind} context={event.context_label!r} "
                f"page={event.page_url!r}; {details}"
            )
        return "\n".join(lines)

    def _monitor_page(self, page: Any) -> None:
        page_id = id(page)
        if page_id in self._pages:
            return
        self._pages.add(page_id)
        page.on("console", lambda message: self._capture_console(page, message))
        page.on("pageerror", lambda error: self._capture_pageerror(page, error))
        page.on("requestfailed", lambda request: self._capture_request(page, request))

    def _context(self, page: Any) -> tuple[int, str, list[str] | None]:
        context_id = id(page.context)
        label, console_messages = self._contexts[context_id]
        return context_id, label, console_messages

    def _record(self, page: Any, kind: str, **details: str | None) -> None:
        context_id, label, _ = self._context(page)
        self.events.append(
            BrowserFailure(
                kind=kind,
                context_id=context_id,
                context_label=label,
                page_url=page.url,
                details=details,
            )
        )

    def _capture_console(self, page: Any, message: Any) -> None:
        context_id, label, console_messages = self._context(page)
        rendered = f"{message.type}: {message.text}"
        if console_messages is not None:
            console_messages.append(rendered)
        logger.debug("Console [%s]: %s", label, rendered)
        if message.type != "error":
            return

        location = message.location or {}
        source_url = location.get("url")
        self.events.append(
            BrowserFailure(
                kind="console",
                context_id=context_id,
                context_label=label,
                page_url=page.url,
                details={
                    "console_type": message.type,
                    "text": message.text,
                    "source_url": source_url,
                    "source_path": urlsplit(source_url).path if source_url else None,
                    "line": str(location.get("lineNumber"))
                    if location.get("lineNumber") is not None
                    else None,
                },
            )
        )

    def _capture_pageerror(self, page: Any, error: BaseException) -> None:
        self._record(
            page,
            "pageerror",
            exception_type=type(error).__name__,
            message=str(error),
            stack=getattr(error, "stack", None),
        )

    def _capture_request(self, page: Any, request: Any) -> None:
        parsed = urlsplit(request.url)
        failure = str(request.failure) if request.failure else None
        self._record(
            page,
            "requestfailed",
            method=request.method,
            url=request.url,
            path=parsed.path,
            failure=failure,
        )
        if failure == "net::ERR_ABORTED":
            self.events[-1].ignored_reason = "browser-navigation-cancellation"


class ExpectedBrowserFailure(AbstractContextManager[None]):
    """Validate and account for one intentional event pattern in a small scope."""

    def __init__(
        self,
        collector: BrowserFailureCollector,
        *,
        context_id: int,
        kind: str,
        count: int,
        max_count: int | None,
        criteria: dict[str, str | None],
    ):
        self.collector = collector
        self.context_id = context_id
        self.kind = kind
        self.min_count = count
        self.max_count = count if max_count is None else max_count
        self.criteria = criteria
        self.start_index = 0

    def __enter__(self) -> None:
        self.start_index = len(self.collector.events)
        return None

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if exc_type is not None:
            return False
        matches = [
            event
            for event in self.collector.events[self.start_index :]
            if event.context_id == self.context_id
            and event.matches(kind=self.kind, **self.criteria)
        ]
        description = self._description()
        for event in matches:
            event.expected_by = description
        if not self.min_count <= len(matches) <= self.max_count:
            expected_count = (
                str(self.min_count)
                if self.min_count == self.max_count
                else f"between {self.min_count} and {self.max_count}"
            )
            raise AssertionError(
                f"Expected {expected_count} browser failure(s) matching {description}; "
                f"observed {len(matches)}.\n"
                + self.collector.format_events(matches)
            )
        return False

    def _description(self) -> str:
        fields = [f"kind={self.kind!r}"]
        fields.extend(
            f"{name}={value!r}"
            for name, value in self.criteria.items()
            if value is not None
        )
        return ", ".join(fields)


def write_diagnostic_report(
    records: list[dict[str, object]], *, path: Path = DIAGNOSTIC_PATH
) -> None:
    """Write one ignored, machine-readable report for a diagnostic E2E session."""
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tests": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
