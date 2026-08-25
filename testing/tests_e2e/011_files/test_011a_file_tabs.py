"""
Tests for the file view page tabs and mobile layout.

Verified against:
- lagniappe/web/templates/files/file.html
- lagniappe/web/templates/files/preview.html
- lagniappe/web/templates/files/text.html
- src/script/views/file.mjs
- src/script/widgets/fileInfo.mjs
"""

import re
from pathlib import Path
import time
from uuid import uuid4

from playwright.sync_api import expect
import pytest

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Pages, Uploads, Users
from testing.definitions.page_definitions import PageDefinition
from testing.elements import MobileNav, Select, SpinnerButtons, Tabs
from testing.resources import File, Page
from testing.utility import scoped_browser_route

pytestmark = pytest.mark.e2e


def _upload_file(user, upload):
    suffix = uuid4().hex
    category = Entities.CATEGORY.create(
        {
            "name": f"File Upload Category {suffix}",
            "attributes": ["files"],
        }
    )
    category.save()
    page_entity = Entities.PAGE.create(
        {
            "name": f"File Upload Page {suffix}",
            "model": category,
            "attributes": ["files"],
        }
    )
    page_entity.save()
    page = Page(
        user=user,
        definition=PageDefinition(
            name=page_entity.name,
            category=Pages.test_file_upload_page.value.definition.category,
            attributes=["files"],
        ),
    )
    page.entity = page_entity
    return page, File.upload_from_page(user, page, upload)


def _fill_file_info_field(info_form, field_selector, input_selector, value):
    field = info_form.locator(field_selector)
    field_input = field.locator(input_selector)
    if not field_input.is_visible():
        field.locator("[data-role='label']").click()
    expect(field_input).to_be_visible()
    field_input.fill(value)


def _canvas_has_ink(canvas):
    return canvas.evaluate(
        """(element) => {
            const context = element.getContext("2d", { willReadFrequently: true });
            const width = element.width;
            const height = element.height;
            if (!context || !width || !height) return false;
            const pixels = context.getImageData(0, 0, width, height).data;
            for (let offset = 0; offset < pixels.length; offset += 4) {
                const red = pixels[offset];
                const green = pixels[offset + 1];
                const blue = pixels[offset + 2];
                const alpha = pixels[offset + 3];
                if (alpha > 0 && (red < 245 || green < 245 || blue < 245)) {
                    return true;
                }
            }
            return false;
        }"""
    )


def _select_file_page_link(info_form, file, page):
    select = Select(info_form.locator(file.INFO_PAGES))
    panel = select.open()
    expect(select.input).to_be_focused()
    select.input.fill(page.definition.name)

    option = panel.locator(f"[role='option'][data-id='{page.entity.urlsafe_key}']")
    expect(option).to_be_visible()
    option.click()
    select.input.press("Escape")


# @matrix file : load tabs text-asset text-tab
# @template files/file.html::main
# @template files/text.html::text_tab
def test_file_text_tab_renders_uploaded_text_content(get_user):
    user = get_user(Users.OWNER)
    _, file = _upload_file(user, Uploads.csv_file_input)

    user.go(file)

    expect(user.locate(file.FILE_TITLE)).to_contain_text("sample_data")
    expect(user.page).to_have_title(re.compile("^sample_data$"))
    expect(user.locate(file.DOWNLOAD_LINK)).to_be_visible()
    expect(Tabs(user).info.locator(file.INFO_FORM)).to_have_attribute("rendered", "")

    text_content = file.text_content
    expect(text_content).to_contain_text("alice.johnson@example.com")
    expect(text_content).to_contain_text("Engineering")


# @matrix file : file-upload page-upload
# @template pages/files.html::files_form
# @template pages/files.html::file_list_item
# @template files/file.html::main
# @template files/text.html::text_tab
def test_page_uploaded_text_file_renders_original_content_in_text_tab(get_user):
    user = get_user(Users.OWNER)
    _, file = _upload_file(user, Uploads.plain_text_file)

    user.go(file)

    expect(user.locate(file.FILE_TITLE)).to_contain_text("sample_notes")
    expect(user.locate(file.PREVIEW_CARD)).not_to_be_attached()
    expect(user.locate(Tabs.PREVIEW_TOGGLE_DESKTOP)).not_to_be_attached()
    expect(user.locate(Tabs.TEXT_TOGGLE_DESKTOP)).to_be_visible()

    info_form = file.info_form
    expect(info_form).to_contain_text("sample_notes.txt")
    expect(info_form).to_contain_text("text/plain")

    text_content = file.text_content
    expect(text_content).to_contain_text("Page upload text fixture")
    expect(text_content).to_contain_text("not through the ingress import flow")


# @matrix file : badges linked-entities reverse-links
# @template files/file.html::main
# @template files/file.html::linked_badges
# @template badge.html::entity_badge
def test_file_page_shows_linked_page_and_task_badges(get_user):
    user = get_user(Users.OWNER)
    page, file = _upload_file(user, Uploads.plain_text_file)
    file_entity = Entities.fetch_one(file.key, request=Fetch.direct())
    task_entity = Entities.TASK.create(
        {
            "name": "File Link Badge Task",
            "page": page.entity,
        }
    )
    task_entity.properties.files.add(file_entity)
    task_entity.save()

    user.go(file)

    linked = user.locate(file.LINKED_ENTITIES)
    expect(linked).to_be_visible()
    expect(linked.locator("a[href*='/pages/']")).to_contain_text(
        page.definition.name
    )
    expect(linked.locator("a[href*='/tasks/']")).to_contain_text(task_entity.name)


# @matrix file : add linked-pages reload remove
# @template files/info.html::info_form
# @template files/file.html::linked_badges
def test_file_info_page_links_can_be_added_and_removed(get_user):
    user = get_user(Users.OWNER)
    source_page, file = _upload_file(user, Uploads.plain_text_file)
    target_page = Pages.test_category_edit_page.get(user)

    user.go(file)
    info_form = file.info_form
    _select_file_page_link(info_form, file, target_page)

    with user.page.expect_response("**/update"):
        SpinnerButtons.UPDATE.click(info_form)

    linked_pages = user.locate(file.LINKED_ENTITIES).locator("a[href*='/pages/']")
    expect(linked_pages.filter(has_text=source_page.definition.name)).to_be_visible()
    expect(linked_pages.filter(has_text=target_page.definition.name)).to_be_visible()

    info_form = file.info_form
    _select_file_page_link(info_form, file, target_page)

    with user.page.expect_response("**/update"):
        SpinnerButtons.UPDATE.click(info_form)

    linked_pages = user.locate(file.LINKED_ENTITIES).locator("a[href*='/pages/']")
    expect(linked_pages.filter(has_text=source_page.definition.name)).to_be_visible()
    expect(linked_pages.filter(has_text=target_page.definition.name)).to_have_count(0)

    file_entity = Entities.fetch_one(file.key, request=Fetch.direct())
    assert {page.key for page in file_entity.pages} == {source_page.entity.key}


# @matrix file : file-upload page-upload preview text-tab
# @template pages/files.html::files_form
# @template pages/files.html::file_list_item
# @template files/file.html::main
# @template files/preview.html::preview_tab
def test_page_uploaded_image_shows_desktop_preview(get_user):
    user = get_user(Users.OWNER)
    _, file = _upload_file(user, Uploads.editor_test_image)

    user.go(file)

    expect(user.locate(file.FILE_TITLE)).to_contain_text("editor_test_image")
    preview = user.locate(file.PREVIEW_IMAGE)
    expect(user.locate(Tabs.PREVIEW_TOGGLE_DESKTOP)).to_be_visible()
    expect(user.locate(file.PREVIEW_CARD)).to_be_visible()
    expect(preview).to_be_visible()
    expect(preview).to_have_attribute("alt", "editor_test_image.jpeg")
    expect(preview).to_have_attribute("src", re.compile(r".+"))
    expect(user.locate(Tabs.TEXT_TOGGLE_DESKTOP)).not_to_be_attached()
    expect(user.locate(Tabs.TEXT_TAB)).not_to_be_attached()
    expect(user.locate(file.TEXT_CONTENT)).not_to_be_attached()

    info_form = file.info_form
    expect(info_form).to_contain_text("editor_test_image.jpeg")
    expect(info_form).to_contain_text("image/jpeg")


# @matrix file : file-upload page-upload pdf-preview preview text-tab
# @template pages/files.html::files_form
# @template pages/files.html::file_list_item
# @template files/file.html::main
# @template files/preview.html::preview_tab
def test_page_uploaded_pdf_renders_pdf_preview_widget(get_user):
    user = get_user(Users.OWNER)
    _, file = _upload_file(user, Uploads.pdf_file)

    user.go(file)

    expect(user.locate(file.FILE_TITLE)).to_contain_text("sample_document")
    preview = user.locate(file.PREVIEW_PDF)
    first_page = user.locate(file.PREVIEW_PDF_CANVAS).first
    expect(user.locate(Tabs.PREVIEW_TOGGLE_DESKTOP)).to_be_visible()
    expect(user.locate(file.PREVIEW_CARD)).to_be_visible()
    expect(preview).to_be_visible()
    expect(preview).to_have_attribute("data-filename", "sample_document.pdf")
    expect(preview).to_have_attribute("data-url", re.compile(r".+"))
    expect(first_page).to_be_visible()
    expect(first_page).not_to_have_attribute("width", "0")
    expect(first_page).not_to_have_attribute("height", "0")
    expect(user.locate(Tabs.TEXT_TOGGLE_DESKTOP)).not_to_be_attached()
    expect(user.locate(Tabs.TEXT_TAB)).not_to_be_attached()
    expect(user.locate(file.TEXT_CONTENT)).not_to_be_attached()

    info_form = file.info_form
    expect(info_form).to_contain_text("sample_document.pdf")
    expect(info_form).to_contain_text("application/pdf")


# @matrix file : loading-state pdf-preview view-transition
# @template pages/files.html::files_form
# @template pages/files.html::file_list_item
# @template files/file.html::main
# @template files/preview.html::preview_tab
def test_pdf_preview_loading_state_paints_before_document_render(get_user):
    user = get_user(Users.OWNER)
    _, uploaded_file = _upload_file(user, Uploads.pdf_file)

    def delay_range_request(route):
        range_header = route.request.header_value("range")
        if range_header:
            assert route.request.method == "GET"
            time.sleep(1.5)
        route.continue_()

    with scoped_browser_route(
        user.page.context,
        f"**/assets/{uploaded_file.key}/file*",
        delay_range_request,
    ):
        user.go(uploaded_file)

        preview = user.locate(uploaded_file.PREVIEW_PDF)
        status = user.locate(uploaded_file.PREVIEW_PDF_STATUS)
        first_page = user.locate(uploaded_file.PREVIEW_PDF_CANVAS).first
        expect(preview).to_have_attribute("aria-busy", "true")
        expect(status).to_be_visible()
        expect(user.locate(uploaded_file.PREVIEW_PDF_LOADING_BARS)).to_have_count(3)

        expect(status).to_be_hidden()
        expect(preview).not_to_have_attribute("aria-busy", "true")
        expect(first_page).not_to_have_attribute("width", "0")
        expect(first_page).not_to_have_attribute("height", "0")

# @matrix file : file-upload page-upload pdf-preview pdf-toolbar preview
# @template pages/files.html::files_form
# @template pages/files.html::file_list_item
# @template files/file.html::main
# @template files/preview.html::preview_tab
def test_page_uploaded_pdf_toolbar_navigates_pages(get_user):
    user = get_user(Users.OWNER)
    _, file = _upload_file(user, Uploads.pdf_two_page_file)

    user.go(file)

    preview = user.locate(file.PREVIEW_PDF)
    toolbar = user.locate(file.PREVIEW_PDF_TOOLBAR)
    first_page = user.locate(file.PREVIEW_PDF_CANVAS).first
    page_input = user.locate(file.PREVIEW_PDF_PAGE_INPUT)
    page_count = user.locate(file.PREVIEW_PDF_PAGE_COUNT)
    next_page = user.locate(file.PREVIEW_PDF_NEXT_PAGE)
    previous_page = user.locate(file.PREVIEW_PDF_PREVIOUS_PAGE)
    focus = user.locate(file.PREVIEW_PDF_FOCUS)

    expect(preview).to_be_visible()
    expect(first_page).to_be_visible()
    expect(first_page).not_to_have_attribute("width", "0")
    expect(first_page).not_to_have_attribute("height", "0")
    expect(first_page.locator("xpath=..")).to_have_attribute(
        "data-rendered", "true"
    )
    assert _canvas_has_ink(first_page)
    expect(toolbar).to_be_visible()
    expect(page_count).to_have_text("/ 2")

    # The active-page observer may already report page 2 when rendering or
    # viewport restoration centers it. Establish the toolbar story's starting
    # page through the same visible page control a user would use.
    page_input.fill("1")
    page_input.press("Enter")
    expect(page_input).to_have_value("1")
    expect(previous_page).to_be_disabled()
    expect(next_page).to_be_enabled()

    next_page.click()
    expect(page_input).to_have_value("2")
    expect(previous_page).to_be_enabled()
    expect(next_page).to_be_disabled()

    previous_page.click()
    expect(page_input).to_have_value("1")
    expect(previous_page).to_be_disabled()
    expect(next_page).to_be_enabled()

    focus.click()
    expect(preview).to_have_attribute("data-fullscreen", "true")
    expect(focus).to_have_attribute("aria-pressed", "true")
    fullscreen_box = preview.evaluate(
        """(node) => {
            const rect = node.getBoundingClientRect();
            return {
                height: rect.height,
                maxHeight: getComputedStyle(node).maxHeight,
                viewportHeight: window.innerHeight,
            };
        }"""
    )
    assert fullscreen_box["maxHeight"] == "none"
    assert fullscreen_box["height"] >= fullscreen_box["viewportHeight"] - 2

    focus.click()
    expect(preview).to_have_attribute("data-fullscreen", "false")
    expect(focus).to_have_attribute("aria-pressed", "false")


# @matrix file : file-mobile preview tabs
# @template files/file.html::mobile_nav
# @template files/preview.html::preview_tab
def test_file_mobile_preview_uses_preview_tab(get_user):
    user = get_user(Users.OWNER)
    _, file = _upload_file(user, Uploads.editor_test_image)

    user.go(file)
    expect(user.locate(file.PREVIEW_CARD)).to_be_visible()
    expect(user.locate(file.PREVIEW_IMAGE)).to_be_visible()

    user.mobile = True
    mobile_nav = MobileNav(user)
    expect(mobile_nav.nav).to_be_visible()
    expect(user.locate(file.DESKTOP_TAB_NAV)).to_be_hidden()
    expect(user.locate(Tabs.PREVIEW_TOGGLE_MOBILE)).to_be_visible()

    mobile_nav.open_tab_slider()
    expect(user.locate(Tabs.PREVIEW_TOGGLE_MOBILE)).to_be_visible()

    mobile_nav.select_section("info")
    expect(user.locate(file.INFO_FORM)).to_be_visible()

    mobile_nav.select_section("preview")
    expect(user.locate(file.PREVIEW_CARD)).to_be_visible()
    expect(user.locate(file.PREVIEW_IMAGE)).to_be_visible()
    assert mobile_nav.get_section_title() == "Preview"


# @matrix file : file-mobile pdf-preview preview tabs
# @template files/file.html::mobile_nav
# @template files/preview.html::preview_tab
def test_file_mobile_pdf_preview_renders_canvas(get_user):
    user = get_user(Users.OWNER)
    _, file = _upload_file(user, Uploads.pdf_file)

    user.go(file)
    user.mobile = True
    mobile_nav = MobileNav(user)
    first_page = user.locate(file.PREVIEW_PDF_CANVAS).first

    expect(mobile_nav.nav).to_be_visible()
    expect(user.locate(file.DESKTOP_TAB_NAV)).to_be_hidden()
    expect(user.locate(file.PREVIEW_PDF)).to_be_visible()
    expect(first_page).to_be_visible()

    mobile_nav.select_section("info")
    expect(user.locate(file.INFO_FORM)).to_be_visible()

    mobile_nav.select_section("preview")
    expect(user.locate(file.PREVIEW_PDF)).to_be_visible()
    expect(first_page).to_be_visible()
    assert mobile_nav.get_section_title() == "Preview"


# @matrix file : display-name info-update summary
# @template files/file.html::view_header
def test_file_info_update_persists_name_and_summary(get_user):
    user = get_user(Users.OWNER)
    _, file = _upload_file(user, Uploads.plain_text_file)
    updated_name = "Updated page upload notes"
    updated_summary = "A saved summary for a page-uploaded text file."

    user.go(file)
    info_form = file.info_form
    _fill_file_info_field(
        info_form,
        file.INFO_NAME_FIELD,
        file.INFO_NAME,
        updated_name,
    )
    _fill_file_info_field(
        info_form,
        file.INFO_DESCRIPTION_FIELD,
        file.INFO_DESCRIPTION,
        updated_summary,
    )

    with user.page.expect_response("**/update"):
        SpinnerButtons.UPDATE.click(info_form)

    assert SpinnerButtons.UPDATE_SUCCESS.successful(info_form)
    expect(user.locate(file.FILE_TITLE)).to_contain_text(updated_name)
    expect(user.locate("[data-role='description']")).to_contain_text(
        updated_summary
    )

    file.reload()
    expect(user.locate(file.FILE_TITLE)).to_contain_text(updated_name)
    reloaded_info = file.info_form
    expect(reloaded_info.locator(file.INFO_NAME)).to_have_value(updated_name)
    expect(reloaded_info.locator(file.INFO_DESCRIPTION)).to_have_value(
        updated_summary
    )


# @matrix file : download filename mimetype
def test_file_download_uses_original_filename_and_mimetype(get_user):
    user = get_user(Users.OWNER)
    upload = Uploads.plain_text_file
    _, file = _upload_file(user, upload)

    user.go(file)
    expect(user.locate(file.DOWNLOAD_LINK)).to_be_visible()

    with user.page.expect_download() as download_info:
        with user.page.expect_response("**/download") as response_info:
            user.locate(file.DOWNLOAD_LINK).click()

    download = download_info.value
    response = response_info.value

    assert response.status == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="sample_notes.txt"'
    )
    assert response.headers["content-type"].startswith("text/plain")
    assert download.suggested_filename == "sample_notes.txt"
    assert Path(download.path()).read_bytes() == upload.definition.file.content
