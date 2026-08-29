from contextlib import contextmanager
from html import escape
import json
import re

import pytest
from playwright.sync_api import expect

from testing.definitions import Pages, Tasks, Uploads, Users
from testing.elements import EditorGenerateText, EditorGenerateTextMode, Modal
from testing.resources import File
from testing.utility.network import (
    expect_successful_response,
    multipart_form_fields,
    scoped_browser_route,
)
from testing.utility.live_ai import LIVE_AI_RESPONSE_TIMEOUT_MS

pytestmark = pytest.mark.e2e


@contextmanager
def _mock_generate_text(browser_page, key, markers=None, error=None):
    path = f"/assets/{key}/document/generate"
    remaining_markers = list(markers or ["Generated text marker"])

    def field_value(fields, name):
        return next((value for field, value in fields if field == name), "")

    def fulfill_generate_text(route):
        assert route.request.method == "POST"
        fields = multipart_form_fields(route.request)

        if error:
            route.fulfill(status=422, content_type="text/plain", body=error)
            return

        if field_value(fields, "role") == "explain":
            prompt = escape(field_value(fields, "prompt"))
            selected_text = escape(field_value(fields, "selected_text"))
            modal = f"""
                <div id="modal">
                  <div id="modal-content">
                    <button type="button" lp-control="close">Close</button>
                    <section>
                      <h2>Prompt</h2>
                      <p>Prompt: {prompt}</p>
                      <p>Selected text: {selected_text}</p>
                    </section>
                  </div>
                </div>"""
            body = {"modal": modal}
        else:
            marker = (
                remaining_markers.pop(0)
                if remaining_markers
                else "Generated text marker"
            )
            body = {"markup": f"<p>{escape(marker)}</p>"}

        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(body),
        )

    with scoped_browser_route(
        browser_page.context,
        f"**{path}",
        fulfill_generate_text,
    ):
        yield path


def _submit_generated_text(editor, mode, prompt, path):
    page = editor.editor.page
    form = EditorGenerateText(editor)
    form.set_mode(mode)
    form.fill_prompt(prompt)
    with expect_successful_response(
        page,
        method="POST",
        path=path,
    ):
        form.submit()
    editor.wait_for_render()


def _assert_ordered(text, first, second):
    assert first in text
    assert second in text
    assert text.index(first) < text.index(second)


# @matrix ai editor : generate-text insert-mode
def test_generate_text_inserts_ai_markup_with_insert_modes(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_document_generation_page)
    editor = page.editor

    markers = [
        "Generated replace marker",
        "Generated append marker",
        "Generated prepend marker",
        "Generated quote marker",
        "Generated cursor marker",
    ]
    with _mock_generate_text(
        user.page,
        page.key,
        markers,
    ) as path:
        editor.clear_text()
        editor.type_text("Original replace text")
        _submit_generated_text(
            editor,
            EditorGenerateTextMode.REPLACE_DOCUMENT,
            "Replace the document",
            path,
        )
        expect(editor.text_entry).to_contain_text("Generated replace marker")
        expect(editor.text_entry).not_to_contain_text("Original replace text")

        editor.clear_text()
        editor.type_text("Append base")
        _submit_generated_text(
            editor,
            EditorGenerateTextMode.APPEND_TO_DOCUMENT,
            "Append to the document",
            path,
        )
        _assert_ordered(editor.get_text(), "Append base", "Generated append marker")

        editor.clear_text()
        editor.type_text("Prepend base")
        _submit_generated_text(
            editor,
            EditorGenerateTextMode.PREPEND_TO_DOCUMENT,
            "Prepend to the document",
            path,
        )
        _assert_ordered(
            editor.get_text(),
            "Generated prepend marker",
            "Prepend base",
        )

        editor.clear_text()
        editor.type_text("Quote base")
        _submit_generated_text(
            editor,
            EditorGenerateTextMode.ADD_AS_QUOTE,
            "Quote this at the top",
            path,
        )
        expect(editor.get_element("blockquote")).to_contain_text(
            "Generated quote marker"
        )

        editor.clear_text()
        editor.type_text("Cursor base ")
        _submit_generated_text(
            editor,
            EditorGenerateTextMode.ADD_AT_CURSOR,
            "Insert at the cursor",
            path,
        )
        _assert_ordered(editor.get_text(), "Cursor base", "Generated cursor marker")

    editor.blur()
    user.go(page)
    expect(page.editor.text_entry).to_contain_text("Generated cursor marker")


# @matrix ai editor : generate-text replace-selection selected-text
def test_generate_text_replaces_selection_and_posts_selected_text(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_document_generation_selection_page)
    editor = page.editor

    selected_text = "Selected page document text"

    editor.clear_text()
    editor.type_text(selected_text)
    editor.select_text()

    form = EditorGenerateText(editor)
    expect(form.form.locator("input[name='selected_text']")).to_have_value(
        selected_text
    )
    expect(form.form.locator('input[value="replace-selection"]')).to_be_checked()
    selection_highlight = editor.text_entry.locator(
        "[data-role='selection-highlight']"
    )
    expect(selection_highlight).to_have_text(selected_text)
    form.fill_prompt("Rewrite the selected text")
    expect(selection_highlight).to_have_text(selected_text)

    with _mock_generate_text(
        user.page,
        page.key,
        ["Generated selection marker"],
    ) as path:
        with expect_successful_response(
            user.page,
            method="POST",
            path=path,
        ):
            form.submit()
        editor.wait_for_render()

        expect(editor.text_entry).to_contain_text("Generated selection marker")
        expect(editor.text_entry).not_to_contain_text(selected_text)
        expect(selection_highlight).to_have_count(0)


# @matrix ai editor : explain generate-text selected-text
def test_generate_text_explain_includes_selected_text_context(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_document_generation_selection_page)
    editor = page.editor

    selected_text = "Explain selected document text"

    editor.clear_text()
    editor.type_text(selected_text)
    editor.select_text()

    form = EditorGenerateText(editor)
    form.fill_prompt("Explain the prompt that will be sent")
    expect(form.form.locator(form.EXPLAIN)).to_have_accessible_name(
        "Initial Prompt"
    )

    with _mock_generate_text(user.page, page.key) as path:
        with expect_successful_response(
            user.page,
            method="POST",
            path=path,
        ):
            form.explain()

        modal = Modal(user.page)
        expect(modal.element).to_be_visible()
        expect(modal.element).to_contain_text(re.compile("selected text", re.I))
        expect(modal.element).to_contain_text(selected_text)
        modal.close()


# @matrix ai editor : error generate-text
def test_generate_text_provider_error_surfaces_in_form(
    get_user,
    browser_failures,
):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_document_generation_page)
    editor = page.editor
    error = "Synthetic provider failure"

    editor.clear_text()
    form = EditorGenerateText(editor)
    prompt = "Trigger an error"
    form.fill_prompt(prompt)

    with _mock_generate_text(
        user.page,
        page.key,
        error=error,
    ) as path:
        with browser_failures.expect(
            user,
            kind="console",
            console_type="error",
            text_contains=(
                "Failed to load resource: the server responded with a status of 422"
            ),
            source_path=path,
        ):
            with user.page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and response.url.endswith(path)
                )
            ) as response_info:
                form.submit()

            response = response_info.value
            assert response.status == 422
            assert response.text() == error
            expect(form.form.locator("[data-role='error']")).to_contain_text(
                re.compile(error)
            )

# @matrix ai : document-context generate-text live-provider page-context
@pytest.mark.ai
def test_generate_text_live_page_context_with_tasks_and_files(get_user, request):
    """
    Make one real provider call against a page with document, task, and file context.

    The ``ai`` mark automatically attaches ``request.node.ai_results`` so prompt,
    response, and generated document output are saved under reports/test_reports/.
    """
    user = get_user(Users.OWNER)
    page = Pages.test_page_review.get(user)
    seeded_tasks = [
        Tasks.test_page_review_active.get(user),
        Tasks.test_page_review_due.get(user),
        Tasks.test_page_review_form.get(user),
    ]
    uploaded_file = File.upload_from_page(user, page, Uploads.plain_text_file)

    page = user.go(page)
    editor = page.editor
    source_text = (
        "Live AI page context note. Include the existing document, related "
        "tasks, and attached file in the response."
    )
    editor.clear_text()
    editor.type_text(source_text)
    editor.blur()

    prompt = (
        "Append two short QA notes for this page. Use the existing page "
        "document, page details, open page tasks, and attached file context if "
        "available. Keep the result under 80 words."
    )

    report = request.node.ai_results
    report.record(
        "setup",
        {
            "page": page.definition.name,
            "tasks": [task.definition.name for task in seeded_tasks],
            "file": uploaded_file.key,
        },
    )
    report.record("prompt", prompt)
    report.record("document_before", source_text)

    form = EditorGenerateText(editor)
    form.set_mode(EditorGenerateTextMode.APPEND_TO_DOCUMENT)
    form.fill_prompt(prompt)
    with user.page.expect_response(
        "**/document/generate",
        timeout=LIVE_AI_RESPONSE_TIMEOUT_MS,
    ) as response:
        form.submit()

    generated_response = response.value
    response_body = generated_response.text()
    report.record("response_status", generated_response.status)
    report.record("response_body", response_body)

    assert generated_response.ok, response_body

    editor.wait_for_render()
    final_text = editor.get_text()
    report.record("document_after", final_text)

    assert source_text in final_text
    assert len(final_text) > len(source_text)
