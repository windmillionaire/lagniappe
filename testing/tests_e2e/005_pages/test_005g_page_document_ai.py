import re

import pytest
from playwright.sync_api import expect

from testing.definitions import Pages, Tasks, Uploads, Users
from testing.elements import EditorGenerateText, EditorGenerateTextMode, Modal
from testing.resources import File

pytestmark = pytest.mark.e2e


def _mock_generate_text(page, markers=None, error=None):
    page.evaluate(
        """({markers, error}) => {
            const escapeHtml = (value) => String(value ?? "").replace(
                /[&<>"']/g,
                (character) => ({
                    "&": "&amp;",
                    "<": "&lt;",
                    ">": "&gt;",
                    '"': "&quot;",
                    "'": "&#039;",
                })[character],
            );

            if (!window.__lagniappeOriginalFetch) {
                window.__lagniappeOriginalFetch = window.fetch.bind(window);
            }

            window.__generateTextRequests = [];
            window.__generateTextMarkers = [...markers];
            window.__generateTextError = error;
            window.fetch = async (input, init = {}) => {
                const url = typeof input === "string" ? input : input.url;
                if (!url.includes("/document/generate")) {
                    return window.__lagniappeOriginalFetch(input, init);
                }

                const fields = [];
                if (init.body instanceof FormData) {
                    for (const [name, value] of init.body.entries()) {
                        fields.push([
                            name,
                            value instanceof File ? value.name : String(value),
                        ]);
                    }
                }
                window.__generateTextRequests.push(fields);

                if (window.__generateTextError) {
                    return new Response(window.__generateTextError, {
                        status: 422,
                        headers: { "content-type": "text/plain" },
                    });
                }

                const fieldValue = (name) => {
                    const field = fields.find(([key]) => key === name);
                    return field ? field[1] : "";
                };
                if (fieldValue("role") === "explain") {
                    const selectedText = escapeHtml(fieldValue("selected_text"));
                    const prompt = escapeHtml(fieldValue("prompt"));
                    const modal = `
                        <div id="modal">
                          <div id="modal-content">
                            <button type="button" lp-control="close">Close</button>
                            <section>
                              <h2>Prompt</h2>
                              <p>Prompt: ${prompt}</p>
                              <p>Selected text: ${selectedText}</p>
                            </section>
                          </div>
                        </div>`;
                    return new Response(JSON.stringify({ modal }), {
                        status: 200,
                        headers: { "content-type": "application/json" },
                    });
                }

                const marker =
                    window.__generateTextMarkers.shift() || "Generated text marker";
                return new Response(
                    JSON.stringify({ markup: `<p>${escapeHtml(marker)}</p>` }),
                    {
                        status: 200,
                        headers: { "content-type": "application/json" },
                    },
                );
            };
        }""",
        {
            "markers": markers or ["Generated text marker"],
            "error": error,
        },
    )


def _generate_text_request_count(page):
    return page.evaluate("window.__generateTextRequests?.length || 0")


def _generate_text_requests(page):
    return page.evaluate("window.__generateTextRequests || []")


def _wait_for_generate_text_request(page, count):
    page.wait_for_function(
        "(count) => (window.__generateTextRequests || []).length > count",
        arg=count,
    )


def _field_values(request, field):
    return [value for name, value in request if name == field]


def _submit_generated_text(editor, mode, prompt):
    page = editor.editor.page
    request_count = _generate_text_request_count(page)
    form = EditorGenerateText(editor)
    form.set_mode(mode)
    form.fill_prompt(prompt)
    form.submit()
    _wait_for_generate_text_request(page, request_count)
    editor.wait_for_render()


def _assert_ordered(text, first, second):
    assert first in text
    assert second in text
    assert text.index(first) < text.index(second)


# @features editor ai
# @dimensions generate-text insert-mode
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
    _mock_generate_text(user.page, markers)

    editor.clear_text()
    editor.type_text("Original replace text")
    _submit_generated_text(
        editor,
        EditorGenerateTextMode.REPLACE_DOCUMENT,
        "Replace the document",
    )
    expect(editor.text_entry).to_contain_text("Generated replace marker")
    expect(editor.text_entry).not_to_contain_text("Original replace text")

    editor.clear_text()
    editor.type_text("Append base")
    _submit_generated_text(
        editor,
        EditorGenerateTextMode.APPEND_TO_DOCUMENT,
        "Append to the document",
    )
    _assert_ordered(editor.get_text(), "Append base", "Generated append marker")

    editor.clear_text()
    editor.type_text("Prepend base")
    _submit_generated_text(
        editor,
        EditorGenerateTextMode.PREPEND_TO_DOCUMENT,
        "Prepend to the document",
    )
    _assert_ordered(editor.get_text(), "Generated prepend marker", "Prepend base")

    editor.clear_text()
    editor.type_text("Quote base")
    _submit_generated_text(
        editor,
        EditorGenerateTextMode.ADD_AS_QUOTE,
        "Quote this at the top",
    )
    expect(editor.get_element("blockquote")).to_contain_text("Generated quote marker")

    editor.clear_text()
    editor.type_text("Cursor base ")
    _submit_generated_text(
        editor,
        EditorGenerateTextMode.ADD_AT_CURSOR,
        "Insert at the cursor",
    )
    _assert_ordered(editor.get_text(), "Cursor base", "Generated cursor marker")

    requests = _generate_text_requests(user.page)
    assert len(requests) == len(markers)
    for mode, post_data in zip(
        [
            "replace",
            "append",
            "prepend",
            "quote-top",
            "cursor",
        ],
        requests,
    ):
        assert mode in _field_values(post_data, "insert_mode")

    editor.blur()
    user.go(page)
    expect(page.editor.text_entry).to_contain_text("Generated cursor marker")


# @features editor ai
# @dimensions generate-text selected-text replace-selection
def test_generate_text_replaces_selection_and_posts_selected_text(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_document_generation_selection_page)
    editor = page.editor

    selected_text = "Selected page document text"
    _mock_generate_text(user.page, ["Generated selection marker"])

    editor.clear_text()
    editor.type_text(selected_text)
    editor.select_text()

    form = EditorGenerateText(editor)
    expect(form.form.locator("input[name='selected_text']")).to_have_value(
        selected_text
    )
    expect(form.form.locator('input[value="replace-selection"]')).to_be_checked()
    form.fill_prompt("Rewrite the selected text")

    request_count = _generate_text_request_count(user.page)
    form.submit()
    _wait_for_generate_text_request(user.page, request_count)
    editor.wait_for_render()

    requests = _generate_text_requests(user.page)
    assert selected_text in _field_values(requests[0], "selected_text")
    assert "replace-selection" in _field_values(requests[0], "insert_mode")
    expect(editor.text_entry).to_contain_text("Generated selection marker")
    expect(editor.text_entry).not_to_contain_text(selected_text)


# @features editor ai
# @dimensions generate-text selected-text explain
def test_generate_text_explain_includes_selected_text_context(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_document_generation_selection_page)
    editor = page.editor

    selected_text = "Explain selected document text"
    _mock_generate_text(user.page)

    editor.clear_text()
    editor.type_text(selected_text)
    editor.select_text()

    form = EditorGenerateText(editor)
    form.fill_prompt("Explain the prompt that will be sent")
    expect(form.form.locator(form.EXPLAIN)).to_have_accessible_name(
        "Initial Prompt"
    )

    request_count = _generate_text_request_count(user.page)
    form.explain()
    _wait_for_generate_text_request(user.page, request_count)

    modal = Modal(user.page)
    expect(modal.element).to_be_visible()
    expect(modal.element).to_contain_text(re.compile("selected text", re.I))
    expect(modal.element).to_contain_text(selected_text)
    modal.close()


# @features editor ai
# @dimensions generate-text error
def test_generate_text_provider_error_surfaces_in_form(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_document_generation_page)
    editor = page.editor
    error = "Synthetic provider failure"
    _mock_generate_text(user.page, error=error)

    editor.clear_text()
    form = EditorGenerateText(editor)
    form.fill_prompt("Trigger an error")

    request_count = _generate_text_request_count(user.page)
    form.submit()
    _wait_for_generate_text_request(user.page, request_count)

    expect(form.form.locator("[data-role='error']")).to_contain_text(
        re.compile(error)
    )


# @features ai
# @dimensions generate-text live-provider page-context document-context
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
    with user.page.expect_response("**/document/generate", timeout=90000) as response:
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
