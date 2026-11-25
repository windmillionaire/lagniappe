"""AI ingress for static task-form content authored as Markdown."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..files.html import SafeHTML

from copy import deepcopy

from lagniappe.core import exceptions

from .references import render_ai_markdown


def static_form_markdown(field: dict[str, object], *, form_type: str | None) -> str | None:
    """Validate generated static content without rendering or fetching references."""
    if "html" in field:
        raise exceptions.ValidationError(
            "Generated form fields must use content_markdown instead of html."
        )

    markdown = field.get("content_markdown")
    if field.get("type") != "html":
        if markdown is not None:
            raise exceptions.ValidationError(
                "content_markdown is supported only on static HTML fields."
            )
        return None

    if form_type != "task":
        raise exceptions.ValidationError(
            "Static HTML fields are supported only on generated task forms."
        )
    field_id = field.get("id")
    if not isinstance(field_id, str) or not field_id.strip():
        raise exceptions.ValidationError("Static HTML fields require a valid id.")
    if not isinstance(markdown, str) or not markdown.strip():
        raise exceptions.ValidationError(
            "Static HTML fields require non-empty content_markdown."
        )
    return markdown


def prepare_static_form_element(element: dict[str, object], *, form_type: str | None) -> tuple[dict[str, object], SafeHTML | None]:
    """Return a durable field plus optional rendered static HTML sidecar."""
    markdown = static_form_markdown(element, form_type=form_type)
    field = deepcopy(element)
    field.pop("content_markdown", None)
    return field, render_ai_markdown(markdown) if markdown is not None else None
