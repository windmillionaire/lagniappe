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

from playwright.sync_api import expect
import pytest

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Projects, Users
from testing.elements import EditorMenuOptions, EditorToggleOptions, Tabs
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
    EditorToggleOptions.BULLET_LIST.toggle(editor)
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


# @matrix editor : paste-markdown-table reload
def test_pasting_markdown_table_preserves_table_after_reload(get_user):
    user = get_user(Users.OWNER)
    project = Projects.test_editor_markdown_table_paste.get(user)
    user.go(project)

    editor = project.editor
    editor.clear_text()
    editor.paste(MARKDOWN_TABLE_PASTE_FIXTURE)

    expect(editor.get_element("table")).to_be_visible()
    expect(editor.get_element("th").filter(has_text="Work")).to_be_visible()
    expect(editor.get_element("td").filter(has_text="response_mime_type")).to_be_visible()

    editor.blur()

    user.go(project)
    editor = project.editor
    expect(editor.get_element("table")).to_be_visible()
    expect(editor.get_element("th").filter(has_text="Work")).to_be_visible()
    expect(editor.get_element("td").filter(has_text="response_mime_type")).to_be_visible()


# @matrix editor : paste-html sanitization
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


# @matrix editor : paste-markdown reload
def test_pasting_common_markdown_preserves_formatting(get_user):
    user = get_user(Users.OWNER)
    project = Projects.test_editor_common_markdown_paste.get(user)
    user.go(project)

    editor = project.editor
    editor.clear_text()
    editor.paste(
        """## Paste Heading

Intro with **bold text**, *italic text*, `inline_code`, and [safe link](https://example.com).

- First item
- Second item with ~~removed words~~

1. Step one
2. Step two

> Quoted line
> With another line

```text
raw <script> stays text
```

---
"""
    )

    expect(editor.get_element("h2")).to_contain_text("Paste Heading")
    expect(editor.get_element("strong")).to_contain_text("bold text")
    expect(editor.get_element("em")).to_contain_text("italic text")
    expect(editor.get_element("code").filter(has_text="inline_code")).to_be_visible()
    expect(editor.get_element("a[href='https://example.com']")).to_contain_text(
        "safe link"
    )
    expect(editor.get_element("ul")).to_contain_text("First item")
    expect(editor.get_element("s")).to_contain_text("removed words")
    expect(editor.get_element("ol")).to_contain_text("Step two")
    expect(editor.get_element("blockquote")).to_contain_text("Quoted line")
    expect(editor.get_element("pre code")).to_contain_text("raw <script> stays text")
    expect(editor.get_element("hr")).to_be_attached()

    editor.blur()

    user.go(project)
    editor = project.editor
    expect(editor.get_element("h2")).to_contain_text("Paste Heading")
    expect(editor.get_element("ul")).to_contain_text("Second item")
    expect(editor.get_element("ol")).to_contain_text("Step one")
    expect(editor.get_element("blockquote")).to_contain_text("With another line")
    expect(editor.get_element("pre code")).to_contain_text("raw <script> stays text")


# @matrix editor : reload task-list
def test_task_list_persists(get_user):
    user = get_user(Users.OWNER)
    project = Projects.test_editor_task_list.get(user)
    user.go(project)

    editor = project.editor
    editor.clear_text()

    EditorToggleOptions.TASK_LIST.toggle(editor)
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
