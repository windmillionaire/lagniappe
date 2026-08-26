"""Repository report artifact path checks."""

from pathlib import Path
import sys
import types

import pytest

from testing.utility import (
    browser_review,
    error_tracking,
    test_reporting,
)
from testing.utility.artifacts import (
    BROWSER_REVIEWS_DIR,
    TEST_FAILURES_DIR,
    TEST_REPORTS_DIR,
)

pytestmark = pytest.mark.tooling


def test_test_artifacts_write_under_reports():
    assert TEST_FAILURES_DIR == Path("reports/test_failures")
    assert TEST_REPORTS_DIR == Path("reports/test_reports")
    assert BROWSER_REVIEWS_DIR == Path("reports/browser_reviews")
    assert error_tracking.FAILURES_DIR == TEST_FAILURES_DIR
    assert test_reporting.REPORTS_DIR == TEST_REPORTS_DIR


def test_failure_capture_does_not_mask_screenshot_errors(monkeypatch, tmp_path):
    class Page:
        def screenshot(self, **kwargs):
            raise TimeoutError("screenshot timed out")

        def content(self):
            return "<html><body>ordinary failure</body></html>"

    monkeypatch.setattr(error_tracking, "FAILURES_DIR", tmp_path)

    filename = error_tracking.capture_on_failure(Page(), "failed test")

    assert filename.parent == tmp_path
    assert not list(tmp_path.iterdir())


def test_browser_review_dir_is_timestamped_folder(tmp_path):
    review_dir = browser_review.create_review_dir(
        "Home First Load",
        timestamp="20260603_170000",
        root=tmp_path,
    )

    assert review_dir == tmp_path / "home-first-load_20260603_170000"
    assert (review_dir / "screenshots").is_dir()


def test_browser_review_html_is_curated_to_findings(tmp_path):
    report_dir = tmp_path / "home-review"
    screenshots_dir = report_dir / "screenshots"
    screenshots_dir.mkdir(parents=True)
    (screenshots_dir / "finding.png").write_bytes(b"not a real png")

    html = browser_review.render_report(
        {
            "title": "Homepage UX Review",
            "subtitle": "Primary action hierarchy",
            "summary": "The page is usable, but creation actions need clearer labels.",
            "findings": [
                {
                    "severity": "medium",
                    "title": "Icon-only create actions are hard to scan.",
                    "body": "The plus buttons read as detached controls.",
                    "suggestions": ["Add explicit tooltips or adjacent labels."],
                    "screenshots": [
                        {
                            "path": "screenshots/finding.png",
                            "caption": "The create button sits apart from its row label.",
                        }
                    ],
                }
            ],
        },
        report_dir,
    )

    assert "Homepage UX Review" in html
    assert "Medium" in html
    assert "screenshots/finding.png" in html
    assert "Add explicit tooltips" in html
    assert "Diagnostics" not in html


def test_browser_review_html_includes_diagnostics_only_when_present(tmp_path):
    html = browser_review.render_report(
        {
            "title": "Homepage UX Review",
            "findings": [],
            "diagnostics": [
                {
                    "title": "Console error",
                    "content": "error: failed to load module",
                }
            ],
        },
        tmp_path,
    )

    assert "Diagnostics" in html
    assert "Console error" in html
    assert "failed to load module" in html


# @matrix browser-review : attachment failure-cleanup
@pytest.mark.parametrize(
    ("keep_failed", "exists_after_failure"),
    [(False, False), (True, True)],
)
def test_browser_review_capture_cleans_failed_folder(
    monkeypatch, tmp_path, keep_failed, exists_after_failure
):
    review_dir = tmp_path / "failed-review"

    def fake_create_review_dir(name):
        (review_dir / "screenshots").mkdir(parents=True)
        return review_dir

    class FailingChromium:
        def launch(self, **kwargs):
            raise RuntimeError("chromium failed")

    class FakePlaywright:
        chromium = FailingChromium()

    class FakePlaywrightContext:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, traceback):
            return False

    fake_sync_api = types.ModuleType("playwright.sync_api")
    fake_sync_api.sync_playwright = lambda: FakePlaywrightContext()
    attachments = []
    fake_testing = types.ModuleType("runner.testing")
    fake_testing.attach_browser_review = (
        lambda command: attachments.append(("attach", command)) or "attachment-1"
    )
    fake_testing.detach_browser_review = (
        lambda attachment_id: attachments.append(("detach", attachment_id))
    )

    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)
    monkeypatch.setitem(sys.modules, "runner.testing", fake_testing)
    monkeypatch.setattr(browser_review, "create_review_dir", fake_create_review_dir)

    args = types.SimpleNamespace(
        name="failed-review",
        path="/",
        viewport=["desktop"],
        login_admin=False,
        wait_for=None,
        settle_ms=0,
        timeout=1,
        title=None,
        focus=None,
        keep_failed=keep_failed,
    )

    with pytest.raises(RuntimeError, match="chromium failed"):
        browser_review.capture_review(args)

    assert review_dir.exists() is exists_after_failure
    assert [event[0] for event in attachments] == ["attach", "detach"]
