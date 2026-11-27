"""Validation for self-contained interactive HTML files."""

from lagniappe.core.exceptions import ValidationError

from .constants import MAX_ARTIFACT_BYTES, MAX_ARTIFACT_NAME_LENGTH


def artifact_content(name: object, html: object) -> tuple[str, bytes]:
    """Validate the artifact's title and encode its original HTML as UTF-8."""
    title = name.strip() if isinstance(name, str) else ""
    if not title or len(title) > MAX_ARTIFACT_NAME_LENGTH:
        raise ValidationError(f"Artifact name must contain 1 to {MAX_ARTIFACT_NAME_LENGTH} characters.")
    if not isinstance(html, str) or not html.strip() or "\x00" in html:
        raise ValidationError("Artifact HTML must be a non-empty document without NUL characters.")
    try:
        content = html.encode("utf-8")
    except UnicodeEncodeError:
        raise ValidationError("Artifact HTML must be valid UTF-8.") from None
    if len(content) > MAX_ARTIFACT_BYTES:
        raise ValidationError(f"Artifact HTML must be at most {MAX_ARTIFACT_BYTES // 1024} KiB in UTF-8.")
    return title, content
