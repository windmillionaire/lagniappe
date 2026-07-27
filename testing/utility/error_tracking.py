from datetime import datetime
import logging
import re

from .artifacts import TEST_FAILURES_DIR

logger = logging.getLogger(__name__)

# Patterns that indicate a 500 error page
_500_PATTERNS = [
    r"<title>\s*Error 500",
    r"500\s*[-–—]\s*Internal Server Error",
    r"Internal Server Error",
    r"Exception",
]

FAILURES_DIR = TEST_FAILURES_DIR


def _is_500_error(html_content: str) -> bool:
    """Check if HTML content appears to be a 500 error page."""
    for pattern in _500_PATTERNS:
        if re.search(pattern, html_content, re.IGNORECASE):
            return True
    return False


def capture_on_failure(page, name) -> str:
    """Capture screenshot on test failure, with HTML only for 500 errors.

    Args:
        page: Playwright Page object
        name: Name for the captured files

    Returns:
        str: Base path to saved files (without extension)
    """
    # Create screenshots directory if it doesn't exist
    FAILURES_DIR.mkdir(parents=True, exist_ok=True)

    # Generate filename with timestamp and test name
    timestamp = datetime.now().strftime("%H%M%S")
    filename = FAILURES_DIR / f"{name} - {timestamp}"

    # Failure artifacts are best-effort and must never mask the test failure.
    try:
        page.screenshot(path=f"{filename}.png", timeout=2000)
    except Exception as error:
        logger.warning("Could not capture failure screenshot: %s", error)

    # Only capture HTML content for 500 errors
    try:
        html_content = page.content()
    except Exception as error:
        logger.warning("Could not capture failure page HTML: %s", error)
        return filename
    if _is_500_error(html_content):
        html_path = f"{filename}.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

    return filename
