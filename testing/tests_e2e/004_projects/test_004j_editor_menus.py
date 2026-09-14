"""Document toolbar menus retain selection and expose contextual table actions."""

from uuid import uuid4

from playwright.sync_api import expect
import pytest

from testing.definitions import Users
from testing.definitions.project_definitions import ProjectDefinition
from testing.elements.combobox import Dropdown
from testing.resources import Project
from testing.utility.network import expect_successful_response


def open_editor(get_user, mobile):
    user = get_user(Users.OWNER, has_touch=mobile)
    project = Project(
        user=user,
        definition=ProjectDefinition(name=f"Editor menus {uuid4().hex[:8]}"),
    ).create()
    user.go(project, query_params={"tab": "document"})
    user.mobile = mobile
    return user, project, project.editor


# @matrix editor : compact-menus
# @style editor.toolbar.menu
# @style editor.toolbar.menuIcon
# @style editor.toolbar.caret
# @style editor.toolbar.section
# @style editor.toolbar.portalIconContext
@pytest.mark.parametrize("mobile", [False, True], ids=["desktop", "mobile"])
def test_compact_editor_menus(get_user, mobile):
    user, project, editor = open_editor(get_user, mobile)
    if not mobile:
        user.page.set_viewport_size({"width": 1600, "height": 900})
    expect(
        editor.toolbar.locator('[data-role="toolbar-menus"] > button')
    ).to_have_count(7)
    assert editor.toolbar.locator('[data-role="toolbar-menus"] > button').evaluate_all(
        "buttons => buttons.map(button => button.title)"
    ) == ["Style", "Headings", "Lists", "Table", "Align", "Insert", "History"]
    first_row = editor.toolbar.get_by_title("Bold", exact=True).bounding_box()
    for title in ["Style", "Headings"]:
        box = editor.toolbar.get_by_label(title, exact=True).bounding_box()
        assert first_row and box and abs(box["y"] - first_row["y"]) <= 1
    for title, option in [
        ("History", "Pin Version"),
        ("Style", "Underline"),
        ("Headings", "Heading 1"),
        ("Lists", "Bullet List"),
        ("Table", "Insert Table"),
        ("Insert", "Link"),
        ("Align", "Align Left"),
    ]:
        trigger = editor.toolbar.get_by_label(title, exact=True)
        expect(trigger).to_be_visible()
        expect(trigger).to_have_attribute("title", title)
        expect(trigger.locator('[data-icon="menu"]')).to_be_visible()
        expect(trigger).to_have_accessible_name(title)
        expect(trigger.locator(":scope > :not([aria-hidden='true'])")).to_have_count(0)
        box = trigger.bounding_box()
        assert box and box["width"] <= 64
        assert (
            0 <= box["x"] < box["x"] + box["width"] <= user.page.viewport_size["width"]
        )
        dropdown = Dropdown(trigger)
        trigger.tap() if mobile else trigger.click()
        dropdown.expect_open(dropdown.panel)
        expect(
            dropdown.panel.get_by_role("option", name=option, exact=True)
        ).to_be_visible()
        icon = (
            dropdown.panel.get_by_role("option", name=option, exact=True)
            .locator(".icon-glyph")
            .first
        )
        expect(icon).to_have_css("font-size", "20px")
        if title == "History" and not mobile:
            panel_box = dropdown.panel.bounding_box()
            assert panel_box and abs(panel_box["x"] - box["x"]) <= 1
        trigger.tap() if mobile else trigger.click()
        expect(dropdown.panel).to_be_hidden()

    expect(editor.toolbar.locator('[data-icon="lists"]')).to_be_visible()
    for icon in ["lists", "table"]:
        expect(editor.toolbar.locator(f'[data-icon="{icon}"]')).to_have_attribute(
            "data-fill", "0"
        )
    expect(editor.toolbar.locator('button[title="Bullet List"]')).to_have_count(0)
    expect(editor.toolbar.locator('button[title="Ordered List"]')).to_have_count(0)
    expect(editor.toolbar.locator('button[title="Task List"]')).to_have_count(0)


# @matrix editor : list-menu selection toggle
@pytest.mark.parametrize("mobile", [False, True], ids=["desktop", "mobile"])
def test_list_menu_formats_selection(get_user, mobile):
    user, project, editor = open_editor(get_user, mobile)
    dropdown = Dropdown(editor.toolbar.get_by_label("Lists", exact=True))

    for title, selector in [
        ("Bullet List", "ul:not([data-type])"),
        ("Ordered List", "ol"),
        ("Task List", 'ul[data-type="taskList"]'),
    ]:
        editor.clear_text()
        editor.type_text("First item").press("Enter")
        editor.type_text("Second item")
        editor.select_text()
        dropdown.select_by_name(title)
        items = editor.get_element(f"{selector} > li")
        expect(items).to_have_count(2)
        expect(items.nth(0).locator("p")).to_have_text("First item")
        expect(items.nth(1).locator("p")).to_have_text("Second item")
        items.nth(1).locator("p").click()
        editor.wait_for_render()

        panel = dropdown.open()
        option = panel.get_by_role("option", name=title, exact=True)
        expect(option).to_have_attribute("data-active", "true")
        option.click()
        expect(items).to_have_count(1)
        expect(items.locator("p")).to_have_text("First item")
        items.locator("p").click()
        dropdown.select_by_name(title)
        expect(editor.get_element(selector)).to_have_count(0)
        expect(editor.get_element("p").filter(has_text="item")).to_have_text(
            ["First item", "Second item"]
        )


# @matrix editor : table-menu
@pytest.mark.parametrize("mobile", [False, True], ids=["desktop", "mobile"])
def test_table_menu_creates_edits_and_saves(get_user, mobile):
    user, project, editor = open_editor(get_user, mobile)
    dropdown = Dropdown(editor.toolbar.get_by_label("Table", exact=True))
    panel = dropdown.open()
    expect(panel.get_by_role("option")).to_have_count(1)
    expect(panel.get_by_role("option", name="Insert Table", exact=True)).to_be_visible()
    dropdown.select_by_name("Insert Table")
    table = editor.get_element("table")
    expect(table.locator("tr")).to_have_count(3)
    expect(table.locator("th")).to_have_count(3)
    expect(table.locator("td")).to_have_count(6)
    # The header toggle affects the first row even with the caret in a body cell.
    table.locator("td").first.click()
    dropdown.select_by_name("Toggle Header Row")
    expect(table.locator("th")).to_have_count(0)
    dropdown.select_by_name("Toggle Header Row")
    expect(table.locator("tr").first.locator("th")).to_have_count(3)
    table.locator("tr").nth(1).locator("td").nth(1).click()
    editor.type_text("Keep this cell")
    cell = table.get_by_role("cell", name="Keep this cell", exact=True)

    panel = dropdown.open()
    expect(panel.get_by_role("option", name="Insert Table", exact=True)).to_have_count(
        0
    )
    for title, icon in [
        ("Add Row Above", "tableRowAbove"),
        ("Add Row Below", "tableRowBelow"),
        ("Add Column Left", "tableColumnLeft"),
        ("Add Column Right", "tableColumnRight"),
    ]:
        expect(
            panel.get_by_role("option", name=title).locator(f'[data-icon="{icon}"]')
        ).to_be_visible()
    dropdown.select_by_name("Add Row Above")
    expect(table.locator("tr")).to_have_count(4)
    expect(table.locator("tr").nth(2)).to_contain_text("Keep this cell")
    cell.click()
    dropdown.select_by_name("Add Row Below")
    expect(table.locator("tr")).to_have_count(5)
    expect(table.locator("tr").nth(2)).to_contain_text("Keep this cell")
    cell.click()
    dropdown.select_by_name("Add Column Left")
    expect(cell.locator("..").locator("td")).to_have_count(4)
    expect(cell.locator("..").locator("td").nth(2)).to_have_text("Keep this cell")
    cell.click()
    dropdown.select_by_name("Add Column Right")
    expect(cell.locator("..").locator("td")).to_have_count(5)
    expect(cell.locator("..").locator("td").nth(2)).to_have_text("Keep this cell")

    # Delete only the newly inserted row and column beside the retained content.
    table.locator("tr").nth(1).locator("td").nth(1).click()
    dropdown.select_by_name("Delete Row")
    expect(table.locator("tr")).to_have_count(4)
    cell.locator("..").locator("td").nth(1).click()
    dropdown.select_by_name("Delete Column")
    expect(cell.locator("..").locator("td")).to_have_count(4)
    expect(cell).to_be_visible()

    cell.click()
    editor.wait_for_render()
    with expect_successful_response(
        user.page,
        method="POST",
        path="/l/sync",
        request_payload_contains=(
            project.entity.sync_ids["document"]["id"],
            '"save":true',
            "Keep this cell",
        ),
    ):
        editor.text_entry.blur()

    user.go(project, query_params={"tab": "document"})
    user.mobile = mobile
    editor = project.editor
    table = editor.get_element("table")
    expect(table.locator("tr")).to_have_count(4)
    expect(table.locator("th, td")).to_have_count(16)
    expect(table.locator("tr").first.locator("th")).to_have_count(4)
    table.get_by_role("cell", name="Keep this cell", exact=True).click()
    Dropdown(editor.toolbar.get_by_label("Table", exact=True)).select_by_name(
        "Delete Table"
    )
    expect(editor.get_element("table")).to_have_count(0)
    editor.toolbar.locator('button[title="Undo"]').click()
    expect(editor.get_element("table")).to_contain_text("Keep this cell")


# @matrix editor : table-menu
def test_table_menu_edits_pasted_table(get_user):
    user, project, editor = open_editor(get_user, False)
    user.page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    user.page.evaluate("""async () => {
        await navigator.clipboard.write([new ClipboardItem({
            'text/html': new Blob(['<table><tr><td>Label</td><td>Value</td></tr><tr><td>Pasted cell</td><td>42</td></tr></table>'], { type: 'text/html' }),
            'text/plain': new Blob(['Label\\tValue\\nPasted cell\\t42'], { type: 'text/plain' }),
        })]);
    }""")
    editor.text_entry.press("Control+V")
    table = editor.get_element("table")
    expect(table.locator("tr")).to_have_count(2)
    expect(table.locator("th")).to_have_count(0)
    cell = table.get_by_role("cell", name="Pasted cell", exact=True)
    cell.click()
    dropdown = Dropdown(editor.toolbar.get_by_label("Table", exact=True))
    dropdown.select_by_name("Toggle Header Row")
    expect(table.locator("tr").first.locator("th")).to_have_text(["Label", "Value"])
    expect(table.locator("tr").nth(1).locator("td")).to_have_text(["Pasted cell", "42"])
    dropdown.select_by_name("Add Row Below")
    expect(table.locator("tr")).to_have_count(3)
    cell.click()
    dropdown.select_by_name("Add Column Right")
    expect(table.locator("th, td")).to_have_count(9)
    expect(cell).to_be_visible()
    expect(table.get_by_role("cell", name="42", exact=True)).to_be_visible()
