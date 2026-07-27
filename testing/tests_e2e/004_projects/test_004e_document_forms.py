"""
Tests for editor form-based options.

Tests that editor forms (link, image, youtube, generate, color, font)
open correctly and have the expected UI elements. Some tests also verify
that editor option changes persist after reload.

Related Files:
    Application:
        - src/script/elements/editor/options/: Editor option implementations
        - src/script/elements/editor/toolbar.mjs: Toolbar and menus

    Test Framework:
        - testing/elements/editor.py: Editor class, option enums, and form helpers
"""

import re

from playwright.sync_api import expect

from testing.definitions import Projects, Uploads, Users
from testing.elements import (
    EditorAddImage,
    UploadDropdown,
    EditorAddLink,
    EditorAddYouTube,
    EditorColorOptions,
    EditorFontFamilyOptions,
    SpinnerButtons,
    Tabs,
)


# @features editor
# @dimensions color reload
def test_color_picker(get_user):
    """
    Test that color picker opens and colors can be selected.

    Flow:
        1. Navigate to project document tab
        2. Open color picker via menu
        3. Select a color
    """
    user = get_user(Users.OWNER)
    project = user.go(Projects.test_editor_forms)

    editor = project.editor
    editor.clear_text()

    text = "Colored text"
    editor.type_text(text)
    editor.select_text()

    EditorColorOptions.RED.click(editor)
    expect(editor.get_element("span[style*='color']")).to_contain_text(text)

    editor.blur()
    user.go(project)
    editor = project.editor
    expect(editor.get_element("span[style*='color']")).to_contain_text(text)


# @features editor
# @dimensions font-family reload
def test_font_family(get_user):
    """
    Test that font family picker opens and fonts can be selected.

    Flow:
        1. Navigate to project document tab
        2. Open font family picker via menu
        3. Select a font
    """
    user = get_user(Users.OWNER)
    project = user.go(Projects.test_editor_forms)

    editor = project.editor
    editor.clear_text()

    text = "Font family text"
    editor.type_text(text)
    editor.select_text()

    EditorFontFamilyOptions.MONO.click(editor)
    # Verify action applied immediately
    expect(editor.get_element("span[style*='font-family']")).to_contain_text(text)

    # Verify formatting persists after save/reload
    editor.blur()
    user.go(project)
    editor = project.editor
    expect(editor.get_element("span[style*='font-family']")).to_contain_text(text)


# @features editor
# @dimensions link reload external-link shortcut search unlink
def test_external_link_persists_searches_and_unlinks(get_user):
    user = get_user(Users.OWNER)
    project = user.go(Projects.test_editor_forms)
    editor = project.editor
    editor.clear_text()

    test_text = "Test link"
    test_url = "https://example.com"

    editor.type_text(test_text)
    editor.select_text()

    link_form = EditorAddLink.from_shortcut(editor)
    link_form.fill(test_url)
    link_form.submit()

    # Verify action applied immediately
    expect(editor.get_element("a")).to_contain_text(test_text)
    expect(editor.get_element("a")).to_have_attribute("href", test_url)
    expect(editor.get_element("a")).to_have_attribute("target", "_blank")

    editor.blur()
    user.go(project)
    editor = project.editor
    expect(editor.get_element("a")).to_contain_text(test_text)
    expect(editor.get_element("a")).to_have_attribute("href", test_url)
    expect(editor.get_element("a")).to_have_attribute("target", "_blank")

    editor.clear_text()
    search_text = "Search result link"
    editor.type_text(search_text)
    editor.select_text()
    link_form = EditorAddLink.from_shortcut(editor)
    link_form.select_search_result(project.definition.name, project.definition.name)

    search_link = editor.get_element("a")
    expect(search_link).to_contain_text(search_text)
    expect(search_link).to_have_attribute("href", re.compile(r"/projects/"))

    editor.select_text()
    link_form = EditorAddLink.from_shortcut(editor)
    expect(link_form.input).to_have_value(re.compile(r"/projects/"))
    link_form.input.fill("")
    link_form.submit()
    expect(editor.get_element("a")).to_have_count(0)
    expect(editor.text_entry).to_contain_text(search_text)


# @features editor
# @dimensions link delimiter
def test_space_exits_link_at_document_end(get_user):
    user = get_user(Users.OWNER)
    project = user.go(Projects.test_editor_forms)
    editor = project.editor
    editor.clear_text()

    link_text = "Link boundary"
    editor.type_text(link_text)
    editor.select_text()

    link_form = EditorAddLink.from_shortcut(editor)
    link_form.fill("https://example.com")
    link_form.submit()

    editor.focus()
    editor.text_entry.press("Space")
    editor.type_text("outside")

    expect(editor.get_element("a")).to_have_text(link_text)
    expect(editor.text_entry).to_have_text(f"{link_text} outside")


# @features editor
# @dimensions link form-dismissal selection
def test_link_form_dismissal_preserves_selection_interactions(get_user):
    user = get_user(Users.OWNER)
    project = user.go(Projects.test_editor_forms)
    editor = project.editor
    editor.clear_text()

    close_text = "Close link form"
    editor.type_text(close_text)
    editor.select_text()
    link_form = EditorAddLink.from_shortcut(editor)
    editor.text_entry.click()
    expect(link_form.form).not_to_be_visible()

    editor.select_text()
    link_form = EditorAddLink.from_shortcut(editor)
    box = editor.text_entry.bounding_box()
    assert box is not None
    user.page.mouse.move(box["x"] + 8, box["y"] + 8)
    user.page.mouse.down()
    user.page.mouse.move(box["x"] + 120, box["y"] + 8, steps=5)
    user.page.mouse.up()
    expect(link_form.form).to_be_visible()
    editor.text_entry.click()
    expect(link_form.form).not_to_be_visible()


# @features editor
# @dimensions link reload internal-link click-navigation shortcut popover readonly paste unlink
def test_internal_links_normalize_paste_and_popover_navigation(get_user):
    user = get_user(Users.OWNER)
    project = user.go(Projects.test_editor_forms)
    editor = project.editor
    editor.clear_text()

    internal_text = "Internal page link"
    origin = user.page.evaluate("window.location.origin")
    internal_url = f"{origin}/pages/editor-link-target?from=editor#notes"
    internal_href = "/pages/editor-link-target?from=editor#notes"

    editor.type_text(internal_text)
    editor.select_text()

    link_form = EditorAddLink.from_shortcut(editor)
    link_form.fill(internal_url)
    link_form.submit()

    internal_link = editor.get_element("a")
    expect(internal_link).to_contain_text(internal_text)
    expect(internal_link).to_have_attribute("href", internal_href)
    expect(internal_link).not_to_have_attribute("target", re.compile(r".+"))
    expect(internal_link).not_to_have_attribute("rel", re.compile(r".+"))

    editor.blur()
    user.go(project)
    editor = project.editor
    internal_link = editor.get_element("a")
    expect(internal_link).to_contain_text(internal_text)
    expect(internal_link).to_have_attribute("href", internal_href)
    expect(internal_link).not_to_have_attribute("target", re.compile(r".+"))
    expect(internal_link).not_to_have_attribute("rel", re.compile(r".+"))

    editor.clear_text()

    pasted_internal_text = "Pasted internal page link"
    editor.type_text(pasted_internal_text)
    editor.select_text()
    editor.paste(internal_url, focus=False)

    pasted_internal_link = editor.get_element("a")
    expect(pasted_internal_link).to_contain_text(pasted_internal_text)
    expect(pasted_internal_link).to_have_attribute("href", internal_href)
    expect(pasted_internal_link).not_to_have_attribute("target", re.compile(r".+"))
    expect(pasted_internal_link).not_to_have_attribute("rel", re.compile(r".+"))

    editor.select_text()
    link_form = EditorAddLink.from_shortcut(editor)
    expect(link_form.input).to_have_value(internal_href)
    link_form.submit()

    current_path = user.page.evaluate("window.location.pathname")
    click_text = "Current page link"
    click_url = f"{origin}{current_path}#editor-link-click"
    click_href = f"{current_path}#editor-link-click"

    editor.text_entry.evaluate(
        """(element, link) => {
            const widget = element.closest('[data-widget]')._lp_widget;
            widget.editor.commands.setContent(
                `<p><a href="${link.url}">${link.text}</a></p>`,
            );
        }""",
        {"text": click_text, "url": click_url},
    )
    editor.wait_for_render()

    click_link = editor.get_element("a")
    expect(click_link).to_contain_text(click_text)
    expect(click_link).to_have_attribute("href", click_href)
    expect(click_link).not_to_have_attribute("target", re.compile(r".+"))

    editor.blur()
    user.go(project)
    editor = project.editor
    click_link = editor.get_element("a")
    expect(click_link).to_contain_text(click_text)
    expect(click_link).to_have_attribute("href", click_href)

    editable_url = user.page.evaluate("window.location.href")
    click_link.click()
    popover = editor.link_popover
    expect(popover.locator("[data-role='link-preview-url']")).to_contain_text(
        click_href
    )
    expect(user.page).to_have_url(editable_url)

    editor.link_popover_action("edit")
    link_form = EditorAddLink(editor, open_form=False)
    expect(link_form.input).to_have_value(click_href)

    click_link.click()
    popups = []
    user.page.on("popup", lambda page: popups.append(page))
    editor.link_popover_action("open")

    expect(user.page).to_have_url(re.compile(f"{re.escape(origin + click_href)}$"))
    assert popups == []
    expect(editor.get_element("a")).to_contain_text(click_text)

    viewer = get_user(Users.general_models_view_only)
    viewer.go(project)
    document_tab = Tabs(viewer).document
    readonly_editor = document_tab.locator("[data-role='editor']")
    expect(readonly_editor).to_have_attribute("loaded", "")
    expect(readonly_editor).to_have_attribute("initialized", "")
    readonly_link = readonly_editor.locator("a").filter(has_text=click_text)
    expect(readonly_link).to_be_visible()
    readonly_origin = viewer.page.evaluate("window.location.origin")
    readonly_link.click()
    expect(viewer.page).to_have_url(
        re.compile(f"{re.escape(readonly_origin + click_href)}$")
    )

    user.go(project)
    editor = project.editor
    click_link = editor.get_element("a")
    click_link.click()
    editor.link_popover_action("remove")
    expect(editor.get_element("a")).to_have_count(0)
    expect(editor.text_entry).to_contain_text(click_text)


# @features editor
# @dimensions link kind-color
def test_links_colorize_properly(get_user):
    user = get_user(Users.OWNER)
    project = user.go(Projects.test_editor_forms)
    editor = project.editor

    editor.text_entry.evaluate(
        """(element) => {
            const widget = element.closest('[data-widget]')._lp_widget;
            widget.editor.commands.setContent(`
                <p>
                    <a href="/projects/color-test">Project</a>
                    <a href="/pages/color-test">Page</a>
                    <a href="/categories/color-test">Category</a>
                    <a href="/tasks/color-test">Task</a>
                    <a href="/files/color-test">File</a>
                    <a href="/unprefixed-color-test">Plain</a>
                    <a href="https://example.com">External</a>
                </p>
            `);
        }"""
    )
    editor.wait_for_render()

    colors = editor.text_entry.evaluate(
        """(element) => {
            const rootStyle = getComputedStyle(document.documentElement);
            const resolveColor = (name) => {
                const probe = document.createElement("span");
                probe.style.color = rootStyle.getPropertyValue(name).trim();
                document.body.append(probe);
                const color = getComputedStyle(probe).color;
                probe.remove();
                return color;
            };
            const colorOf = (href) =>
                getComputedStyle(element.querySelector(`a[href="${href}"]`)).color;

            return {
                project: colorOf("/projects/color-test"),
                projectExpected: resolveColor("--color-project-default"),
                page: colorOf("/pages/color-test"),
                pageExpected: resolveColor("--color-page-default"),
                category: colorOf("/categories/color-test"),
                categoryExpected: resolveColor("--color-category-default"),
                task: colorOf("/tasks/color-test"),
                taskExpected: resolveColor("--color-task-default"),
                file: colorOf("/files/color-test"),
                fileExpected: resolveColor("--color-file-default"),
                plain: colorOf("/unprefixed-color-test"),
                external: colorOf("https://example.com"),
                defaultExpected: resolveColor("--color-page-default"),
            };
        }"""
    )

    assert colors["project"] == colors["projectExpected"]
    assert colors["page"] == colors["pageExpected"]
    assert colors["category"] == colors["categoryExpected"]
    assert colors["task"] == colors["taskExpected"]
    assert colors["file"] == colors["fileExpected"]
    assert colors["plain"] == colors["defaultExpected"]
    assert colors["external"] == colors["defaultExpected"]


# @features editor
# @dimensions youtube-embed
def test_add_youtube(get_user):
    """
    Test that YouTube form opens with URL input and can be filled.

    Flow:
        1. Navigate to project document tab
        2. Open YouTube form via menu
        3. Fill a URL (without submitting)
    """
    user = get_user(Users.OWNER)
    project = user.go(Projects.test_editor_forms)

    editor = project.editor
    youtube_form = EditorAddYouTube(editor)

    test_url = "https://www.youtube.com/watch?v=nignmGXUr24"

    youtube_form.fill(test_url)
    youtube_form.submit()

    player = editor.get_element("iframe")
    expect(player).to_be_attached()


# @features editor
# @dimensions image-generate-toggle
def test_add_image_generate_toggle(get_user):
    """
    Test that Image form opens and generate mode can be toggled.

    Flow:
        1. Navigate to project document tab
        2. Open image form via menu
        3. Open generate form via menu
        4. Verify generate textarea is visible
        5. Cancel generate and verify textarea is hidden
    """
    user = get_user(Users.OWNER)
    project = user.go(Projects.test_editor_forms)

    editor = project.editor
    form = EditorAddImage(editor).form

    # Generate textarea should start hidden
    expect(form.locator(EditorAddImage.PROMPT)).to_be_hidden()
    expect(form.locator(EditorAddImage.DROPZONE)).to_be_visible()

    # Open generate form
    UploadDropdown.GENERATE.select(form)
    expect(form.locator(EditorAddImage.PROMPT)).to_be_visible()

    # Cancel should hide the generate textarea
    form.locator(EditorAddImage.GENERATE_CANCEL).click()
    expect(form.locator(EditorAddImage.PROMPT)).to_be_hidden()


# @features editor
# @dimensions image-upload image-selection
def test_add_image(get_user):
    """
    Test image upload and setImage options appearing when image is selected.

    Flow:
        1. Navigate to project document tab
        2. Clear editor content
        3. Open image form and upload an image
        4. Verify image appears in editor
        5. Click the image to select it
        6. Verify setImage options appear
        7. Click elsewhere to deselect
        8. Verify setImage options disappear
    """
    user = get_user(Users.OWNER)
    project = user.go(Projects.test_editor_forms)

    editor = project.editor
    editor.clear_text()

    # Upload an image
    form = EditorAddImage(editor).form
    Uploads.editor_test_image.set(form)
    SpinnerButtons.UPLOAD.click(form)

    image = editor.get_element("img")
    expect(image).to_be_visible()
