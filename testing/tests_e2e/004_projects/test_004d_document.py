"""
Tests for project document tab functionality.

Tests document editor persistence - verifying that content and formatting
survive save/reload cycles.

Related Files:
    Application:
        - lagniappe/web/templates/projects/document.html: Document tab template
        - src/script/widgets/document.mjs: Document widget
        - src/script/elements/editor/collaborative.mjs: Collaborative editor

    Test Framework:
        - testing/elements/editor.py: Editor class and option enums
        - testing/resources/project.py: Project resource with editor property

Test Strategy:
    Each test types content, applies formatting, triggers save (blur),
    reloads the page, and verifies the content/formatting persisted.
"""

import re
from uuid import uuid4

from bs4 import BeautifulSoup
from playwright.sync_api import expect
import pytest

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Projects, Uploads, Users
from testing.definitions.project_definitions import ProjectDefinition
from testing.elements import (
    EditorAddImage,
    EditorMenuOptions,
    EditorToggleOptions,
    SpinnerButtons,
    Tabs,
)
from testing.resources import Project
from testing.utility.network import expect_successful_response
from testing.utility.polling import expect_poll_result


MARKDOWN_TABLE_PASTE_FIXTURE = "\n".join(
    [
        "| Work | Usefulness | Feasibility | Verdict |",
        "|---|---|---|---|",
        "| Keep `response_mime_type` for no-tool JSON prompts | High | Done | Keep. |",
        "| Add schemas/Pydantic models per generator | High | Medium | Worth doing generator-by-generator. |",
    ]
)


# @matrix sync : empty-content initialization parent-modified save-guard
def test_untouched_document_does_not_save_or_touch_project(get_user):
    user = get_user(Users.OWNER)
    # The shared toolbar project is intentionally edited by the earlier offline
    # lifecycle coverage. Use a dedicated fresh document so this regression
    # test measures eager-save behavior instead of depending on suite order.
    project = Projects.test_untouched_document.get(user)
    before = Entities.fetch_one(project.key, request=Fetch.direct()).modified
    sync_updates = []
    document_sync_id = project.entity.sync_ids["document"]["id"]

    def record_sync_updates(request):
        if request.method != "POST" or not request.url.endswith("/l/sync"):
            return
        sync_updates.extend((request.post_data_json or {}).get("updates", []))

    user.page.on("request", record_sync_updates)
    user.page.bring_to_front()
    with expect_poll_result(
        user.page,
        subscription_id=f"document:{document_sync_id}",
        status=None,
    ):
        user.go(project, query_params={"tab": "document"})
    editor = project.editor
    assert editor.get_text() == ""

    with expect_successful_response(
        user.page,
        method="POST",
        path="/l/poll",
        request_payload_contains=(
            f'"closed_documents":["{document_sync_id}"]'
        ),
    ):
        Tabs(user).info

    after = Entities.fetch_one(project.key, request=Fetch.direct()).modified
    assert after == before
    assert not any(
        update.get("save") or update.get("touch_parent")
        for update in sync_updates
    )


# @matrix editor : reload text-save
def test_editor_loads_and_saves_text(get_user):
    user = get_user(Users.OWNER)
    project = Projects.test_toolbar_loads.get(user)
    user.go(project)

    editor = project.editor

    editor.clear_text()
    test_text = "Hello, world!"
    editor.type_text(test_text)
    assert editor.get_text() == test_text

    editor.blur()

    user.go(project)
    editor = project.editor
    assert editor.get_text() == test_text


# @matrix editor : formatting reload
@pytest.mark.filterwarnings("ignore:.*[tiptap warn].*")
def test_formatting_persists(get_user):
    user = get_user(Users.OWNER)
    project = Projects.test_formatting_persists.get(user)
    user.go(project)

    editor = project.editor
    editor.clear_text()

    EditorToggleOptions.BOLD.toggle(editor)
    bold_text = "Bold text here"
    editor.type_text(bold_text).press("Enter")
    EditorToggleOptions.BOLD.toggle(editor)

    EditorToggleOptions.ITALIC.toggle(editor)
    italic_text = "Italic text here"
    editor.type_text(italic_text).press("Enter")
    EditorToggleOptions.ITALIC.toggle(editor)

    header_text = "This is a heading"
    editor.type_text(header_text)
    EditorMenuOptions.HEADING_1.click(editor)

    editor.enter()
    EditorMenuOptions.BULLET_LIST.click(editor)
    editor.type_text("First item").press("Enter")
    editor.type_text("Second item")

    editor.blur()
    user.go(project)
    editor = project.editor

    expect(editor.get_element("strong")).to_contain_text(bold_text)
    expect(editor.get_element("em")).to_contain_text(italic_text)
    expect(editor.get_element("h1")).to_contain_text(header_text)
    expect(editor.get_element("ul")).to_contain_text("First item")
    expect(editor.get_element("ul")).to_contain_text("Second item")


# @source src/script/elements/editor/extensions/image.mjs::getImageStyles
# @pair editor:image-layout
def test_image_layout_survives_document_autosave_and_reload(get_user):
    user = get_user(Users.OWNER)
    project = Project(
        user=user,
        definition=ProjectDefinition(name=f"Document image layout {uuid4().hex[:8]}"),
    ).create()
    user.go(project)
    editor = project.editor
    editor.type_text("Keep this document instruction.").press("Enter")

    form = EditorAddImage(editor).form
    Uploads.editor_test_image.set(form)
    SpinnerButtons.UPLOAD.click(form)
    image = editor.get_element("img")
    expect(image).to_be_visible()
    image_src = image.get_attribute("src")
    image.click()
    editor.toolbar.locator("button[title='Decrease size']").click()
    editor.toolbar.locator("button[title='Decrease size']").click()
    editor.toolbar.locator("button[title='Align right']").click()
    expect(image).to_have_attribute("style", re.compile(r"width:\s*80%"))
    expect(image).to_have_css("float", "none")
    assert image.evaluate("image => image.style.marginLeft") == "auto"
    assert image.evaluate("image => image.style.marginRight") == "0px"

    # Match this document's durable HTML checkpoint, not a background Yjs delta.
    document_sync_id = project.entity.sync_ids["document"]["id"]
    image.click()
    editor.wait_for_render()
    with expect_successful_response(
        user.page,
        method="POST",
        path="/l/sync",
        request_payload_contains=(document_sync_id, '"save":true', image_src, "80%"),
    ):
        editor.text_entry.blur()

    # Reloaded collaborative state can retain image attributes even when its
    # serialized HTML is broken. Inspect the separately persisted HTML as well.
    persisted = Entities.fetch_one(project.key, request=Fetch.direct())
    saved_html = persisted.properties.document.html
    saved_image = BeautifulSoup(saved_html, "html.parser").find("img", src=image_src)
    assert saved_image is not None
    styles = dict(
        declaration.strip().split(":", 1)
        for declaration in saved_image.get("style", "").split(";")
        if declaration.strip()
    )
    styles = {name.strip(): value.strip() for name, value in styles.items()}
    assert styles["width"] == "80%"
    assert styles["float"] == "none"
    assert styles["margin-left"] == "auto"
    assert styles["margin-right"] in {"0", "0px"}

    user.go(project)
    editor = project.editor
    image = editor.get_element("img")
    expect(image).to_be_visible()
    expect(image).to_have_attribute("style", re.compile(r"width:\s*80%"))
    expect(image).to_have_css("float", "none")
    assert image.evaluate("image => image.style.marginLeft") == "auto"
    assert image.evaluate("image => image.style.marginRight") == "0px"
    expect(editor.text_entry).to_contain_text("Keep this document instruction.")


# @matrix editor : formatting inline-code reload selection toggle
def test_inline_code_style_formats_selected_text_and_persists(get_user):
    user = get_user(Users.OWNER)
    project = Projects.test_inline_code_style.get(user)
    user.go(project)

    editor = project.editor
    editor.clear_text()

    prefix = "Plain text before"
    code_text = "inline_code"
    full_text = f"{prefix} {code_text}"
    editor.type_text(full_text)
    editor.text_entry.press("Control+Shift+ArrowLeft")

    EditorMenuOptions.INLINE_CODE.click(editor)
    inline_code = editor.get_element("p > code")
    expect(inline_code).to_have_count(1)
    expect(inline_code).to_have_text(code_text)
    expect(editor.get_element("p")).to_have_text(full_text)

    EditorMenuOptions.INLINE_CODE.click(editor)
    expect(editor.get_element("p > code")).to_have_count(0)

    EditorMenuOptions.INLINE_CODE.click(editor)
    expect(editor.get_element("p > code")).to_have_text(code_text)

    editor.blur()
    user.go(project)
    editor = project.editor

    expect(editor.get_element("p > code")).to_have_text(code_text)
    expect(editor.get_element("p")).to_have_text(full_text)


# @matrix editor markdown : conversion paste
def test_pasting_markdown_table_preserves_table_after_reload(get_user):
    user = get_user(Users.OWNER)
    project = Projects.test_editor_markdown_table_paste.get(user)
    user.go(project)

    editor = project.editor
    editor.clear_text()
    editor.paste(MARKDOWN_TABLE_PASTE_FIXTURE)

    source = editor.get_element('pre[data-type="markdownSource"]')
    prompt = editor.toolbar.locator('[data-role="markdown-paste-prompt"]')
    expect(source).to_contain_text("response_mime_type")
    expect(prompt).to_be_visible()
    with expect_successful_response(
        user.page,
        method="POST",
        path="/l/markdown",
    ):
        prompt.get_by_role("button", name="Convert").click()

    expect(editor.get_element("table")).to_be_visible()
    expect(editor.get_element("th").filter(has_text="Work")).to_be_visible()
    expect(editor.get_element("td").filter(has_text="response_mime_type")).to_be_visible()

    editor.blur()

    user.go(project)
    editor = project.editor
    expect(editor.get_element("table")).to_be_visible()
    expect(editor.get_element("th").filter(has_text="Work")).to_be_visible()
    expect(editor.get_element("td").filter(has_text="response_mime_type")).to_be_visible()


# @matrix editor markdown : conversion paste
# @matrix files security : html-sanitization
def test_pasting_plain_html_inserts_safe_formatted_content(get_user):
    user = get_user(Users.OWNER)
    project = Projects.test_editor_plain_html_paste.get(user)
    user.go(project)

    editor = project.editor
    editor.clear_text()
    editor.paste(
        """
        <p><strong>Note</strong> before the table.</p>
        <script>alert("bad")</script>
        <table onclick="alert('bad')">
          <thead>
            <tr><th>Label</th><th>Value</th></tr>
          </thead>
          <tbody>
            <tr>
              <td><a href="javascript:alert('bad')">Bad link</a></td>
              <td><em>Safe value</em></td>
            </tr>
          </tbody>
        </table>
        """
    )

    source = editor.get_element('pre[data-type="markdownSource"]')
    prompt = editor.toolbar.locator('[data-role="markdown-paste-prompt"]')
    expect(source).to_contain_text("<strong>Note</strong>")
    with expect_successful_response(
        user.page,
        method="POST",
        path="/l/markdown",
    ):
        prompt.get_by_role("button", name="Convert").click()

    expect(editor.get_element("strong")).to_contain_text("Note")
    expect(editor.get_element("table")).to_be_visible()
    expect(editor.get_element("th").filter(has_text="Label")).to_be_visible()
    expect(editor.get_element("td").filter(has_text="Bad link")).to_be_visible()
    expect(editor.get_element("td").filter(has_text="Safe value")).to_be_visible()
    expect(editor.get_element("script")).not_to_be_attached()

    markup = editor.text_entry.evaluate("(element) => element.innerHTML")
    assert "onclick" not in markup
    assert "javascript:" not in markup
    assert "alert" not in markup


# @matrix editor markdown : conversion paste
# @style editor.markdownSource
# @style editor.toolbar.markdownPrompt
# @style editor.toolbar.markdownPromptMessage
# @style editor.toolbar.markdownPromptActions
# @style editor.toolbar.markdownPromptKeep
# @style editor.toolbar.markdownPromptStatus
# @style editor.container
def test_pasting_common_markdown_preserves_formatting(get_user):
    user = get_user(Users.OWNER)
    project = Projects.test_editor_common_markdown_paste.get(user)
    user.go(project)

    editor = project.editor
    editor.clear_text()
    editor.paste(
        """## Paste Heading

Intro with **bold text**, *italic text*, `inline_code`, and [safe link](https://example.com), plus a sentence that wraps
onto another source line without becoming a hard break.

- First item that wraps
onto another source line in the same bullet.
- Second item with ~~removed words~~

1. Step one
2. Step two

- [ ] Open task that wraps
onto another source line.
    - [x] Nested complete
- [X] Finished task

> Quoted line
> With another line

```text
raw <script> stays text
```

---
"""
    )

    source = editor.get_element('pre[data-type="markdownSource"]')
    prompt = editor.toolbar.locator('[data-role="markdown-paste-prompt"]')
    expect(source).to_contain_text("## Paste Heading")
    expect(prompt).to_be_visible()
    with expect_successful_response(
        user.page,
        method="POST",
        path="/l/markdown",
    ):
        prompt.get_by_role("button", name="Convert").click()
    expect(prompt).not_to_be_visible()

    expect(editor.get_element("h2")).to_contain_text("Paste Heading")
    expect(editor.get_element("strong")).to_contain_text("bold text")
    expect(editor.get_element("em")).to_contain_text("italic text")
    expect(editor.get_element("code").filter(has_text="inline_code")).to_be_visible()
    expect(editor.get_element("a[href='https://example.com']")).to_contain_text(
        "safe link"
    )
    first_item = editor.get_element("ul:not([data-type]) > li").first
    expect(first_item).to_contain_text(
        "First item that wraps onto another source line in the same bullet."
    )
    expect(first_item.locator("br")).to_have_count(0)
    assert not first_item.evaluate("element => element.textContent.includes('\\n')")
    expect(editor.get_element("s")).to_contain_text("removed words")
    expect(editor.get_element("ol")).to_contain_text("Step two")
    expect(editor.get_element("blockquote")).to_contain_text("Quoted line")
    expect(editor.get_element("pre code")).to_contain_text("raw <script> stays text")
    expect(editor.get_element("hr")).to_be_attached()
    intro = editor.get_element("p").filter(has_text="Intro with").first
    expect(intro).to_contain_text(
        "plus a sentence that wraps onto another source line without becoming a hard break."
    )
    expect(intro.locator("br")).to_have_count(0)
    assert not intro.evaluate("element => element.textContent.includes('\\n')")

    task_items = editor.get_element('ul[data-type="taskList"] li[data-checked]')
    expect(task_items).to_have_count(3)
    expect(task_items.nth(0)).to_contain_text(
        "Open task that wraps onto another source line."
    )
    expect(task_items.nth(0).locator("br")).to_have_count(0)
    checkbox = ':scope > label > input[type="checkbox"]'
    expect(task_items.nth(0).locator(checkbox)).not_to_be_checked()
    expect(task_items.nth(0).locator(checkbox)).to_have_css("opacity", "1")
    expect(task_items.nth(0).locator(checkbox)).to_have_css("appearance", "none")
    expect(task_items.nth(0).locator(checkbox)).to_have_css("border-radius", "4px")
    task_items.nth(0).locator(checkbox).hover()
    assert task_items.nth(0).locator(checkbox).evaluate(
        "element => getComputedStyle(element).boxShadow !== 'none'"
    )
    expect(task_items.nth(1).locator(checkbox)).to_be_checked()
    expect(task_items.nth(2).locator(checkbox)).to_be_checked()

    editor.blur()

    user.go(project)
    editor = project.editor
    expect(editor.get_element("h2")).to_contain_text("Paste Heading")
    expect(editor.get_element("ul:not([data-type])")).to_contain_text("Second item")
    expect(editor.get_element("ol")).to_contain_text("Step one")
    expect(editor.get_element("blockquote")).to_contain_text("With another line")
    expect(editor.get_element("pre code")).to_contain_text("raw <script> stays text")
    expect(
        editor.get_element('ul[data-type="taskList"] li[data-checked]')
    ).to_have_count(3)


# @matrix editor markdown : paste source-block
# @style editor.markdownSource
def test_keeping_pasted_markdown_preserves_source_block(get_user):
    user = get_user(Users.OWNER)
    project = Projects.test_editor_markdown_source_paste.get(user)
    user.go(project)

    editor = project.editor
    editor.clear_text()
    source_text = "## Editable source\n\n- [ ] Keep this raw"
    editor.paste(source_text)

    source = editor.get_element('pre[data-type="markdownSource"]')
    prompt = editor.toolbar.locator('[data-role="markdown-paste-prompt"]')
    expect(source).to_have_text(source_text)
    expect(prompt).to_be_visible()
    prompt.get_by_role("button", name="Keep as text").click()
    expect(prompt).not_to_be_visible()
    expect(source).to_have_text(source_text)

    editor.blur()
    user.go(project)
    editor = project.editor
    source = editor.get_element('pre[data-type="markdownSource"]')
    expect(source).to_have_text(source_text)
    expect(source).to_have_class("markdown-source")


# @matrix editor : reload task-list
def test_task_list_persists(get_user):
    user = get_user(Users.OWNER)
    project = Projects.test_editor_task_list.get(user)
    user.go(project)

    editor = project.editor
    editor.clear_text()

    EditorMenuOptions.TASK_LIST.click(editor)
    editor.type_text("First task").press("Enter")
    editor.type_text("Second task")
    editor.wait_for_render()

    task_items = editor.get_element('ul[data-type="taskList"] > li')
    expect(task_items).to_have_count(2)

    first_checkbox = task_items.first.locator('input[type="checkbox"]')
    expect(first_checkbox).to_be_visible()
    first_checkbox.check()
    expect(first_checkbox).to_be_checked()

    editor.blur()

    user.go(project)
    editor = project.editor

    task_list = editor.get_element('ul[data-type="taskList"]')
    expect(task_list).to_be_visible()
    expect(task_list).to_contain_text("First task")
    expect(task_list).to_contain_text("Second task")
    expect(
        editor.get_element('ul[data-type="taskList"] > li')
        .first.locator('input[type="checkbox"]')
    ).to_be_checked()
