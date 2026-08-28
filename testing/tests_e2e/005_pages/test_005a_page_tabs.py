import re
from urllib.parse import urlsplit

from playwright.sync_api import expect
import pytest

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Categories, Forms, Pages, Submissions, Uploads, Users
from testing.elements import (
    Attributes,
    Buttons,
    EditorAddImage,
    FormSelect,
    Modal,
    Select,
    SpinnerButtons,
    Table,
    Tabs,
)
from testing.utility.network import expect_successful_response
from testing.utility.test_file import TestFile as UploadTestFile

pytestmark = pytest.mark.e2e


# @matrix entity-layout : persistence query-tab
def test_page_url_tab_overrides_saved_tab(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_page_loads.get(user)
    user.go(page)

    Tabs(user).document

    user.go(page, query_params={"tab": "tasks"})

    expect(user.locate(Tabs.TASKS_TAB)).to_be_visible()
    expect(user.locate(Tabs.DOCUMENT_TAB)).to_be_hidden()
    expect(user.locate(Tabs.TASKS_TOGGLE_DESKTOP)).to_have_attribute(
        "data-selected", "true"
    )

    user.go(page)

    expect(user.locate(Tabs.TASKS_TAB)).to_be_visible()
    expect(user.locate(Tabs.DOCUMENT_TAB)).to_be_hidden()
    expect(user.locate(Tabs.TASKS_TOGGLE_DESKTOP)).to_have_attribute(
        "data-selected", "true"
    )


# @matrix pages : attributes-live-toggle no-reload tabs
# @template pages/page.html::main
# @template pages/info.html::info_form
def test_page_attribute_toggle_updates_tabs_without_reload(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_page_loads.get(user)
    user.go(page)
    info_form = page.info_form
    attributes = Attributes(info_form)
    tasks_toggle = user.locate(Tabs.TASKS_TOGGLE_DESKTOP)

    expect(tasks_toggle).to_be_visible()
    user.page.evaluate("window.__attributeToggleNoReload = true")

    with user.page.expect_response("**/attributes/tasks"):
        attributes.set_selected("tasks", False)

    expect(tasks_toggle).not_to_be_visible()
    expect(user.locate(page.TASK_LIST)).not_to_be_visible()
    assert user.page.evaluate("window.__attributeToggleNoReload") is True

    with user.page.expect_response("**/attributes/tasks"):
        attributes.set_selected("tasks", True)

    expect(tasks_toggle).to_be_visible()
    assert user.page.evaluate("window.__attributeToggleNoReload") is True


# @matrix pages : default-form submission
def test_page_with_default_category_form(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_page_with_default_category_form.get(user)
    user.go(page)

    submission = Submissions.default_category_form.get()

    page.set_submission(submission)
    page.submit_and_verify_submission(submission)


# @matrix pages : form-switch info-form
def test_switch_page_form(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_switch_page_form.get(user)
    user.go(page)

    info_form = page.info_form
    for field in page.form_definition.schema:
        expect(field.locate(info_form)).to_be_visible()

    new_form = Forms.test_basic_inputs_form.get(user)

    with user.page.expect_response("**/update?form=*"):
        FormSelect(info_form).select(new_form)

    for field in new_form.definition.schema:
        expect(field.locate(info_form)).to_be_visible()


# @matrix pages : form-clear info-form
def test_clear_page_info_form_selector_keeps_widget_stable(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_switch_page_form.get(user)
    user.go(page)

    info_form = page.info_form
    FormSelect(info_form).clear()
    user.page.evaluate("() => new Promise((resolve) => setTimeout(resolve, 0))")
    expect(info_form).to_be_visible()


def _open_document_settings(user, page):
    Tabs(user).document
    settings = user.locate(page.DOCUMENT_SETTINGS_FORM)
    if not settings.is_visible():
        user.locate(page.DOCUMENT_SETTINGS_TOGGLE).click()
    expect(settings).to_be_visible()
    return settings


def _document_save_response(text):
    def predicate(response):
        if not response.url.endswith("/l/sync"):
            return False
        post_data = response.request.post_data or ""
        return '"save":true' in post_data and text in post_data

    return predicate


# @matrix pages : document-visibility private public public-document
# @pair public-directory:category
def test_document_visibility_can_toggle_public_private(get_user, browser_failures):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_document_visibility_page)
    category = page.definition.category.get(user)

    editor = page.editor
    editor.clear_text()
    public_text = "Public document visibility marker"
    editor.type_text(public_text)
    editor.wait_for_render()
    with user.page.expect_response(_document_save_response(public_text)):
        user.page.evaluate("window.dispatchEvent(new CustomEvent('sync-save'))")

    settings = _open_document_settings(user, page)
    settings.locator("input[value='public']").check()
    directory_category = settings.locator("select[name='directory-category']")
    directory_category_select = Select(
        settings.locator("[data-role='directory-category']")
    )
    expect(directory_category).to_be_hidden()
    expect(directory_category.locator("option")).to_contain_text(
        ["Public Pages", category.definition.name]
    )
    expect(directory_category_select.input).to_have_attribute(
        "placeholder", "Public Pages"
    )
    directory_category_select.select_by_key(category.key)
    with user.page.expect_response("**/visibility"):
        SpinnerButtons.UPDATE.click(settings)

    expect(settings).to_contain_text("This page is public")
    expect(settings.locator("input[value='public']")).to_be_checked()
    expect(settings.locator("select[name='directory-category']")).to_have_value(
        category.key
    )
    public_link = settings.locator("a")
    expect(public_link).to_be_visible()
    public_url = public_link.evaluate("(element) => element.href")

    public_response = user.page.goto(public_url)
    assert public_response.status == 200
    expect(user.locate("#content")).to_contain_text(public_text)

    user.go(page)
    settings = _open_document_settings(user, page)
    expect(settings).to_contain_text("This page is public")
    expect(settings.locator("input[value='public']")).to_be_checked()
    assert settings.locator("a").evaluate("(element) => element.href") == public_url

    directory_category_select = Select(
        settings.locator("[data-role='directory-category']")
    )
    expect(directory_category_select.input).to_have_attribute(
        "placeholder", category.definition.name
    )
    directory_category_select.select_by_name("Public Pages")
    with user.page.expect_response("**/visibility"):
        SpinnerButtons.UPDATE.click(settings)
    expect(
        Select(settings.locator("[data-role='directory-category']")).input
    ).to_have_attribute("placeholder", "Public Pages")

    settings.locator("input[value='private']").check()
    with user.page.expect_response("**/visibility"):
        SpinnerButtons.UPDATE.click(settings)

    expect(settings).to_contain_text("This page is private")
    expect(settings.locator("input[value='private']")).to_be_checked()
    expect(settings.locator("a")).to_have_count(0)


# @matrix public-pages : document-image metadata preview public-rendering public-route revocation
# @template public/nav.html::public_nav
def test_public_document_images_are_anonymous_and_revocable(
    get_user,
    browser,
    browser_failures,
    setup_test_server,
):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_document_visibility_page)
    editor = page.editor
    editor.clear_text()
    marker = "Public image route marker"
    editor.type_text(marker)

    image_form = EditorAddImage(editor).form
    Uploads.editor_test_image.set(image_form)
    with user.page.expect_response("**/document/image"):
        SpinnerButtons.UPLOAD.click(image_form)
    image = editor.get_element("img")
    expect(image).to_be_visible()
    editor.wait_for_render()
    with user.page.expect_response(_document_save_response(marker)):
        user.page.evaluate("window.dispatchEvent(new CustomEvent('sync-save'))")

    user.go(page)
    settings = _open_document_settings(user, page)
    settings.locator("input[value='public']").check()
    preview = settings.locator(
        "input[name='preview-image-asset']:not([value=''])"
    )
    expect(preview).to_have_count(1)
    preview.check()
    settings.locator("input[name='public-title']").fill("Public image preview")
    with user.page.expect_response("**/visibility"):
        SpinnerButtons.UPDATE.click(settings)
    public_url = settings.locator("a").evaluate("element => element.href")

    anonymous_context = browser.new_context()
    if setup_test_server.browser_cookies:
        anonymous_context.add_cookies(list(setup_test_server.browser_cookies))
    try:
        anonymous = anonymous_context.new_page()
        anonymous.add_init_script(
            """
            Object.defineProperty(navigator, "share", {
              configurable: true,
              value: undefined,
            });
            Object.defineProperty(navigator, "clipboard", {
              configurable: true,
              value: { writeText: async () => {} },
            });
            """
        )
        response = anonymous.goto(public_url)
        assert response.status == 200
        expect(anonymous.locator("meta[property='og:title']")).to_have_attribute(
            "content", "Public image preview"
        )
        share_button = anonymous.locator("[data-role='share-button']")
        expect(share_button).to_contain_class("action-button")
        expect(share_button.locator("[data-icon='share']")).to_be_visible()
        share_button.click()
        expect(share_button.locator("[data-role='share-label']")).to_have_text(
            "Copied"
        )
        expect(anonymous.locator("[data-role='share-status']")).to_have_text(
            "Link copied"
        )
        public_image = anonymous.locator("#content img")
        expect(public_image).to_be_visible()
        public_image_url = public_image.get_attribute("src")
        assert "/pages/public/" in public_image_url
        assert "/images/image_" in public_image_url
        public_image_path = urlsplit(public_image_url).path
        origin = anonymous.evaluate("location.origin")
        image_response = anonymous_context.request.get(
            f"{origin}{public_image_path}"
        )
        assert image_response.status == 200
    finally:
        anonymous_context.close()

    user.go(page)
    settings = _open_document_settings(user, page)
    settings.locator("input[value='private']").check()
    with user.page.expect_response("**/visibility"):
        SpinnerButtons.UPDATE.click(settings)

    revoked = user.page.context.request.get(f"{origin}{public_image_path}")
    assert revoked.status == 404
    with browser_failures.expect_http_error(
        user,
        status=404,
        path=public_url,
    ):
        private_response = user.page.goto(public_url)
    assert private_response.status == 404


# @matrix pages : delete file-upload
# @template pages/files.html::file_list_item
def test_add_file_to_page(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_file_upload_page)

    files_tab = page.files_tab
    upload_form = files_tab.locator(page.UPLOAD_FILE_FORM)
    if not upload_form.is_visible():
        user.locate(page.UPLOAD_FILE_TOGGLE).click()
    expect(upload_form).to_be_visible()

    image_file = UploadTestFile("editor_test_image.jpeg")
    image_file.input(upload_form.locator("input[type='file']"))

    with user.page.expect_response("**/upload"):
        SpinnerButtons.UPLOAD.click(upload_form)

    file_list = files_tab.locator("[data-widget='BaseList']")
    file_item = file_list.locator("li").filter(has_text="editor_test_image")
    expect(file_item).to_be_visible()
    thumbnail = file_item.locator("[data-role='thumbnail']")
    expect(thumbnail).to_be_visible()
    expect(thumbnail).to_have_attribute(
        "src", re.compile(r"/assets/.+/file\.jpeg$")
    )
    expect(file_item).to_have_attribute("data-key", re.compile(r"\S+"))

    file_item.locator(Buttons.LP_DELETE).click()
    Modal(user.page).delete()
    expect(file_item).not_to_be_visible()

    user.page.reload()
    files_tab = page.files_tab
    file_list = files_tab.locator("[data-widget='BaseList']")
    expect(file_list.locator("li").filter(has_text="editor_test_image")).to_have_count(0)


# @matrix file pages : file-upload multi-file page-upload
# @template pages/files.html::files_form
# @template pages/files.html::file_list_item
def test_add_multiple_files_to_page_hides_existing_file_select(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_file_upload_page)

    files_tab = page.files_tab
    upload_form = files_tab.locator(page.UPLOAD_FILE_FORM)
    if not upload_form.is_visible():
        user.locate(page.UPLOAD_FILE_TOGGLE).click()
    expect(upload_form).to_be_visible()

    upload_form.locator("input[type='file']").set_input_files(
        [
            UploadTestFile("sample_notes.txt").path,
            UploadTestFile("sample_document.pdf").path,
        ]
    )

    expect(upload_form.locator("[data-role='select-file']")).not_to_be_visible()
    expect(upload_form.locator("[data-role='display-name']")).not_to_be_visible()
    expect(upload_form.locator("[data-role='dropzone']")).to_contain_text(
        "2 files selected"
    )

    with user.page.expect_response("**/upload"):
        SpinnerButtons.UPLOAD.click(upload_form)

    file_list = files_tab.locator("[data-widget='BaseList']")
    notes_item = file_list.locator("li").filter(has_text="sample_notes").first
    document_item = file_list.locator("li").filter(has_text="sample_document").first
    expect(notes_item).to_be_visible()
    expect(document_item).to_be_visible()

    for item, expected_name in [
        (notes_item, "sample_notes"),
        (document_item, "sample_document"),
    ]:
        expect(item).to_have_attribute("data-key", re.compile(r"\S+"))
        file_key = item.get_attribute("data-key")
        file_entity = Entities.fetch_one(file_key, request=Fetch.direct())
        assert file_entity.name == expected_name


# @pair pages:category-add
def test_add_category_to_page(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_category_edit_page)
    category = Categories.test_empty_category.get(user)

    info_form = page.info_form
    Select(info_form.locator("[data-role='categories']")).select_by_name(
        category.definition.name
    )

    with user.page.expect_response("**/update"):
        SpinnerButtons.UPDATE.click(info_form)

    user.go(category)
    row = Table(user).get_row(page.definition.name)
    expect(row).to_be_visible()

    user.go(page)
    expect(user.locate(page.PAGE_TITLE)).to_contain_text(page.definition.name)


# @matrix pages : delete parentless title-menu
# @template pages/page.html::view_header
# @template menus.html::title
# @template menus.html::delete
def test_delete_page_from_title_menu(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_delete_page)
    page.wait_for_interaction_readiness()

    trigger = user.page.get_by_role("button", name="Page actions")
    trigger.hover()
    trigger.click()
    expect(trigger).to_have_attribute("aria-busy", "true")
    expect(trigger).to_have_attribute("data-combobox-id", re.compile(r".+"))
    menu = user.page.get_by_role("menu", name="Page actions")
    expect(menu).to_be_visible()
    expect(menu).to_have_attribute("data-positioned", "true")
    expect(trigger).not_to_have_attribute("aria-busy", "true")
    delete_item = menu.get_by_role("menuitem", name="Delete")
    delete_item.click()

    Modal(user.page).delete()
    expect(user.page).to_have_url(re.compile(r"/$"))
    assert Entities.fetch_one(page.key, request=Fetch.root()) is None


# @pair pages:category-remove
def test_remove_category_from_page(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_category_edit_page)
    original = Categories.test_create_page.get(user)
    added = [
        Categories.test_empty_category.get(user),
        Categories.test_category_info_update.get(user),
    ]

    info_form = page.info_form
    category_select = Select(info_form.locator("[data-role='categories']"))
    for category in added:
        if category.definition.name not in category_select.placeholder:
            category_select.select_by_name(category.definition.name)
    if original.definition.name in category_select.placeholder:
        category_select.select_by_name(original.definition.name)

    with expect_successful_response(
        user.page,
        method="PUT",
        path=f"/pages/{page.key}/update",
        entity_key=page.key,
    ):
        SpinnerButtons.UPDATE.click(info_form)

    user.go(original)
    expect(Table(user).get_row(page.definition.name)).not_to_be_attached()
    user.go(page)
    expect(user.locate("[data-nav='view']")).to_contain_text(
        re.compile("|".join(re.escape(category.definition.name) for category in added))
    )
