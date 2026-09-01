"""AI ingress for static task-form content authored as Markdown."""

from copy import deepcopy

from lagniappe.core import exceptions

from .references import render_ai_markdown


# @testable true
# @tests tests_unit/test_004b_schema_core.py::test_schema_validate_ai_html_calls_set_html_field
# @tests tests_unit/test_004b_schema_core.py::test_schema_validate_ai_rejects_raw_or_invalid_static_content
# @matrix form-schema html-field : ai-value markdown validation
def prepare_static_form_element(element, *, form_type):
    """Return a durable field plus optional rendered static HTML sidecar."""
    field = deepcopy(element)
    if "html" in field:
        raise exceptions.ValidationError(
            "Generated form fields must use content_markdown instead of html."
        )

    markdown = field.pop("content_markdown", None)
    if field.get("type") != "html":
        if markdown is not None:
            raise exceptions.ValidationError(
                "content_markdown is supported only on static HTML fields."
            )
        return field, None

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
    return field, render_ai_markdown(markdown)
