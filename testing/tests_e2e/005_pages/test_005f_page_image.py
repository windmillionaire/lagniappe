from contextlib import contextmanager
import re

import pytest
from playwright.sync_api import expect

from testing.definitions import Pages, Uploads, Users
from testing.elements import UploadDropdown, Tabs
from testing.resources import Page
from testing.utility.network import (
    expect_successful_response,
    scoped_browser_route,
)

pytestmark = pytest.mark.e2e


def _photo_form(user):
    form = user.locate(Page.PHOTO_FORM)
    expect(form).to_be_visible()
    return form


def _photo_prompt(page):
    page.wait_for_interaction_readiness()
    prompt = page.user.locate(page.PHOTO_PROMPT)
    expect(prompt).to_be_visible()
    return prompt


def _upload_image_from_prompt(user, page):
    prompt = _photo_prompt(page)

    prompt.locator(page.PHOTO_PROMPT_UPLOAD).click()
    form = _photo_form(user)
    expect(user.locate(page.PHOTO_NEW_IMAGE)).to_be_visible()

    with user.page.expect_response("**/add-page-image"):
        with user.page.expect_file_chooser() as chooser:
            form.locator("[data-role='dropzone']").click()
        chooser.value.set_files(Uploads.editor_test_image.definition.file.path)

    expect(prompt).to_be_visible()
    expect(form.locator("img")).to_be_visible()
    return form


def _ensure_photo_form(user, page):
    form = user.locate(page.PHOTO_FORM)
    if form.locator("img").count() == 0:
        return _upload_image_from_prompt(user, page)
    expect(form).to_be_visible()
    return form


@contextmanager
def _mock_generated_image(page, key, html):
    path = f"/assets/{key}/generate-page-image"

    def fulfill_generated_image(route):
        assert route.request.method == "POST"
        route.fulfill(status=200, content_type="text/html", body=html)

    with scoped_browser_route(
        page.context,
        f"**{path}",
        fulfill_generated_image,
    ):
        yield path


def _expect_cache_busted_image(form):
    image = form.locator("[data-role='existing-image'] img")
    expect(image).to_be_visible()
    expect(image).to_have_attribute("src", re.compile(r"[?&]v=\d+"))


def _desktop_photo_toggle(user):
    return user.locate("#tabs nav[data-nav='tabs'] button[lp-show='photo:active']")


# @matrix pages : image-add photo-prompt
def test_add_image_to_page(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_image_page)

    _upload_image_from_prompt(user, page)

    expect(user.locate(page.PHOTO_EXISTING_IMAGE)).to_be_visible()
    expect(user.locate(page.PHOTO_EXISTING_IMAGE).locator("img")).to_be_visible()
    expect(user.locate("[lp-view]")).to_have_class(re.compile(".*max-w-7xl.*"))


# @matrix pages : desktop-tabs photo-prompt
def test_photo_prompt_upload_keeps_mobile_photo_tab_hidden_on_desktop(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_generated_image_page)
    prompt = _photo_prompt(page)
    desktop_photo_toggle = _desktop_photo_toggle(user)

    expect(desktop_photo_toggle).to_be_hidden()

    prompt.locator(page.PHOTO_PROMPT_UPLOAD).click()

    expect(user.locate(page.PHOTO_FORM)).to_be_visible()
    expect(user.locate(page.PHOTO_NEW_IMAGE)).to_be_visible()
    expect(desktop_photo_toggle).to_be_hidden()


# @matrix entity-layout : dynamic-secondary page-mobile
# @matrix pages : mobile-photo-tab photo-prompt
# @template pages/page.html::main
def test_mobile_photo_prompt_rejoins_section_switching(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_generated_image_page)
    user.mobile = True
    prompt = _photo_prompt(page)

    prompt.locator(page.PHOTO_PROMPT_UPLOAD).click()
    photo_form = _photo_form(user)
    photo_component = user.locate("#photo")
    expect(user.locate("#tabs > #photo")).to_have_count(1)
    expect(photo_component).to_have_attribute("data-persistent", "false")

    document = page.mobile_nav.select_section("document")

    expect(document).to_be_visible()
    expect(photo_component).to_have_attribute("data-visible", "false")
    expect(photo_form).to_be_hidden()


# @pair pages:image-replace
def test_replace_image_on_page(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_image_page)
    form = _ensure_photo_form(user, page)

    with user.page.expect_response("**/add-page-image"):
        with user.page.expect_file_chooser() as chooser:
            UploadDropdown.REPLACE.select(form)
        chooser.value.set_files(Uploads.editor_test_image.definition.file.path)

    _expect_cache_busted_image(form)


# @matrix pages : image-generate photo-prompt
def test_generate_image_on_page(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_generated_image_page)
    prompt = _photo_prompt(page)

    generated_dropzone = """
      <div data-role="dropzone" class="rounded-lg relative">
        <div data-role="existing-image" data-visible="true">
          <img src="/images/logo-192x192.png" alt="Generated test image">
        </div>
        <div data-role="new-image" data-visible="false">
          <p data-role="feedback">drop image here<br>or click to upload</p>
        </div>
      </div>
    """

    prompt.locator(page.PHOTO_PROMPT_GENERATE).click()
    form = _photo_form(user)
    generate_form = form.locator("[data-role='generate-image']")
    expect(generate_form).to_be_visible()
    image_prompt = "Create a bright page image"
    generate_form.locator("textarea[name='prompt']").fill(image_prompt)

    with _mock_generated_image(
        user.page,
        page.key,
        generated_dropzone,
    ) as path:
        with expect_successful_response(
            user.page,
            method="POST",
            path=path,
        ):
            generate_form.locator("button[data-role='generate']").click()

        expect(form.locator("img[alt='Generated test image']")).to_be_visible()
        expect(prompt).to_be_visible()
        expect(user.locate("[lp-view]")).to_have_class(re.compile(".*max-w-7xl.*"))


# @pair pages:image-paste
def test_paste_image_on_page(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_image_page)
    form = _ensure_photo_form(user, page)

    test_file = Uploads.editor_test_image.definition.file
    user.page.evaluate(
        """(data) => {
            const blob = new Blob([new Uint8Array(data.content)], {
                type: data.type,
            });
            navigator.clipboard.read = async () => [{
                types: [data.type],
                getType: async (requestedType) => {
                    if (requestedType !== data.type) {
                        throw new DOMException("Type not found", "NotFoundError");
                    }
                    return blob;
                },
            }];
        }""",
        {
            "content": list(test_file.content),
            "type": test_file.mime_type,
        },
    )
    with user.page.expect_response("**/add-page-image"):
        UploadDropdown.PASTE.select(form)

    _expect_cache_busted_image(form)


# @pair pages:image-remove
def test_remove_image_from_page(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_image_page)
    form = _ensure_photo_form(user, page)

    with user.page.expect_response("**/remove-page-image"):
        UploadDropdown.REMOVE.select(form)

    expect(user.locate(page.PHOTO_EXISTING_IMAGE).locator("img")).not_to_be_attached()
    expect(form).to_be_hidden()
    expect(_photo_prompt(page)).to_be_visible()
    expect(user.locate("[lp-view]")).to_have_class(re.compile(".*max-w-5xl.*"))


# @matrix pages : photo-visibility photo-prompt desktop-tabs mobile-photo-tab
# @template pages/photo.html::image_controls
# @template pages/page.html::main
def test_photo_controls_toggle_and_remember_desktop_visibility(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_generated_image_page.get(user)
    page.entity.properties.image.delete()
    page.entity.save()
    user.go(page)
    prompt = _photo_prompt(page)
    toggle = prompt.locator(page.PHOTO_PROMPT_UPLOAD)

    toggle.click()
    expect(user.locate(page.PHOTO_NEW_IMAGE)).to_be_visible()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    toggle.click()
    expect(user.locate(page.PHOTO_FORM)).to_be_hidden()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(prompt).to_be_visible()

    _upload_image_from_prompt(user, page)
    expect(toggle.locator("[data-icon]")).to_have_attribute("data-icon", "visibility.visible")
    toggle.click()
    expect(user.locate(page.PHOTO_FORM)).to_be_hidden()
    expect(toggle.locator("[data-icon]")).to_have_attribute("data-icon", "visibility.hidden")
    expect(user.locate("[lp-view]")).to_have_class(re.compile(".*max-w-5xl.*"))

    Tabs(user).tasks
    expect(prompt).to_be_visible()
    page.reload()
    expect(user.locate(page.PHOTO_FORM)).to_be_hidden()
    expect(prompt).to_be_visible()

    photo_tab = page.mobile_nav.select_section("photo")
    expect(photo_tab).to_be_visible()
    expect(prompt).to_be_hidden()
    page.mobile_nav.select_section("info")
    expect(user.locate(page.PHOTO_FORM)).to_be_hidden()
    user.mobile = False
    expect(prompt).to_be_visible()
    expect(user.locate(page.PHOTO_FORM)).to_be_hidden()
    toggle.click()
    expect(user.locate(page.PHOTO_EXISTING_IMAGE)).to_be_visible()
    expect(user.locate(page.PHOTO_MENU_BUTTON)).to_be_visible()


# @matrix pages : photo-visibility readonly
# @template pages/photo.html::image_controls
# @template pages/photo.html::card
def test_readonly_viewer_can_toggle_image_without_editing(get_user):
    owner = get_user(Users.OWNER)
    page = owner.go(Pages.acl_lab_visible)
    _ensure_photo_form(owner, page)
    viewer = get_user(Users.page_acl_one_visible)
    viewer.go(page)
    prompt = _photo_prompt(page)
    toggle = prompt.locator(page.PHOTO_PROMPT_UPLOAD)
    expect(viewer.locate(page.PHOTO_EXISTING_IMAGE)).to_be_visible()
    expect(viewer.locate(page.PHOTO_MENU_BUTTON)).not_to_be_attached()
    expect(prompt.locator(page.PHOTO_PROMPT_GENERATE)).not_to_be_attached()
    expect(viewer.locate(f"{page.PHOTO_FORM} input[type='file']")).not_to_be_attached()
    toggle.click()
    expect(viewer.locate(page.PHOTO_FORM)).to_be_hidden()
    toggle.click()
    expect(viewer.locate(page.PHOTO_EXISTING_IMAGE)).to_be_visible()
    expect(viewer.locate(page.PHOTO_MENU_BUTTON)).not_to_be_attached()


# @matrix pages : photo-prompt ai-disabled
# @template pages/photo.html::image_controls
# @template pages/photo.html::image
# @source src/script/widgets/pagePhoto.mjs::PagePhoto
def test_site_ai_disabled_upload_has_no_generation_controls(get_user, monkeypatch):
    from lagniappe import CONFIG
    from lagniappe.web import app

    owner = get_user(Users.OWNER)
    page = Pages.test_generated_image_page.get(owner)
    page.entity.properties.image.delete()
    page.entity.save()
    with monkeypatch.context() as patch:
        patch.setattr(CONFIG, "AI_ENABLED", False)
        with app.test_client() as client:
            for cookie in owner.page.context.cookies():
                client.set_cookie(cookie["name"], cookie["value"])
            response = client.get(f"/pages/{page.key}")
        assert response.status_code == 200
        html = response.get_data(as_text=True)

    def serve_ai_disabled_page(route):
        route.fulfill(status=200, content_type="text/html", body=html)

    with scoped_browser_route(owner.page.context, page.url, serve_ai_disabled_page):
        owner.go(page)
        prompt = _photo_prompt(page)
        expect(prompt.locator(page.PHOTO_PROMPT_GENERATE)).not_to_be_attached()
        prompt.locator(page.PHOTO_PROMPT_UPLOAD).click()
        form = _photo_form(owner)
        expect(form.locator("[data-role='generate-image']")).not_to_be_attached()
        expect(form.locator("[data-role='submit-group']")).not_to_be_attached()
        expect(form.get_by_role("button", name="Cancel")).not_to_be_attached()
        expect(owner.locate(page.PHOTO_NEW_IMAGE)).to_be_visible()
        prompt.locator(page.PHOTO_PROMPT_UPLOAD).click()
        expect(form).to_be_hidden()


# @matrix pages : image-generate photo-visibility
# @source src/script/widgets/pagePhoto.mjs::PagePhoto
def test_cancel_generation_restores_previous_image_visibility(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_image_page.get(user)
    page.entity.properties.image.delete()
    page.entity.save()
    user.go(page)
    prompt = _photo_prompt(page)
    toggle = prompt.locator(page.PHOTO_PROMPT_UPLOAD)
    generate = prompt.locator(page.PHOTO_PROMPT_GENERATE)
    generate.click()
    empty_form = _photo_form(user)
    empty_form.get_by_role("button", name="Cancel", exact=True).click()
    expect(empty_form).to_be_hidden()
    expect(prompt).to_be_visible()
    _upload_image_from_prompt(user, page)
    for initially_visible in (True, False):
        if not initially_visible:
            toggle.click()
            expect(user.locate(page.PHOTO_FORM)).to_be_hidden()
        generate.click()
        form = _photo_form(user)
        expect(form.locator("[data-role='generate-image']")).to_be_visible()
        description = form.locator("textarea[name='prompt']")
        description.fill("Keep this image description")
        generate.click()
        expect(description).to_have_value("Keep this image description")
        form.get_by_role("button", name="Cancel", exact=True).click()
        if initially_visible:
            expect(user.locate(page.PHOTO_EXISTING_IMAGE)).to_be_visible()
        else:
            expect(form).to_be_hidden()
        expect(prompt).to_be_visible()
        expect(generate).to_be_focused()


# @matrix pages : image-add image-replace image-remove unsaved-preservation
# @pair edited-entity-notice:unchanged-form
# @source src/script/shared/editReconciler.mjs::EditReconciler
# @source src/script/widgets/pagePhoto.mjs::PagePhoto.uploadImage
# @source src/script/widgets/pagePhoto.mjs::PagePhoto._removeImage
@pytest.mark.parametrize("dirty", [False, True])
def test_image_changes_preserve_page_info_dom_and_draft(get_user, dirty):
    from testing.utility.polling import expect_poll_result

    user = get_user(Users.OWNER)
    page = Pages.test_offline_sync_form_page.get(user)
    page.entity.properties.image.delete()
    page.entity.save()
    user.go(page)
    info = page.info_form
    original = info.element_handle()
    if dirty:
        for selector, value in (
            (Page.INFO_NAME, "Unsaved image page name"),
            (Page.INFO_DESCRIPTION, "Unsaved image page description"),
            ("[id^='sync-text-renderer-']", "Unsaved custom field"),
        ):
            field = info.locator(selector)
            field.locator("[data-role='label']").click()
            field.locator("input, textarea").fill(value)

    for action in ("add", "replace", "remove"):
        before = user.locate("[lp-view]").get_attribute("data-fingerprint")
        # Entity polls start at 15 seconds and back off while quiet; the natural
        # poll is the causal boundary proving image-only revision reconciliation.
        with expect_poll_result(user.page, subscription_id=f"view:entity:{page.key}", timeout=60000):
            if action == "add":
                _upload_image_from_prompt(user, page)
            elif action == "replace":
                with user.page.expect_response("**/add-page-image"):
                    with user.page.expect_file_chooser() as chooser:
                        UploadDropdown.REPLACE.select(_photo_form(user))
                    chooser.value.set_files(Uploads.editor_test_image.definition.file.path)
            else:
                with user.page.expect_response("**/remove-page-image"):
                    UploadDropdown.REMOVE.select(_photo_form(user))
        expect(user.locate("[lp-view]")).not_to_have_attribute("data-fingerprint", before)
        page.wait_for_interaction_readiness()
        assert original.evaluate("element => element.isConnected")
        expect(info.locator("[lp-edited-marker]")).to_be_hidden()
        if dirty:
            expect(info.locator("input[name='name']")).to_have_value("Unsaved image page name")
            expect(info.locator("textarea[name='description']")).to_have_value("Unsaved image page description")
            expect(info.locator("input[name='sync-text']")).to_have_value("Unsaved custom field")


# @matrix pages : image-replace upload-error
# @source src/script/widgets/pagePhoto.mjs::PagePhoto.uploadImage
def test_failed_image_replacement_preserves_existing_image(get_user, browser_failures):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_image_page)
    form = _ensure_photo_form(user, page)
    original_src = form.locator("[data-role='existing-image'] img").get_attribute("src")
    path = f"/assets/{page.key}/add-page-image"

    def reject_replacement(route):
        route.fulfill(
            status=422,
            content_type="application/json",
            body='{"error":"Image upload rejected"}',
        )

    with scoped_browser_route(user.page.context, f"**{path}", reject_replacement):
        with browser_failures.expect_http_error(user, status=422, path=path):
            with user.page.expect_response(f"**{path}"):
                with user.page.expect_file_chooser() as chooser:
                    UploadDropdown.REPLACE.select(form)
                chooser.value.set_files(Uploads.editor_test_image.definition.file.path)
            expect(form.locator("[data-role='image-error']")).to_have_text("Image upload rejected")
            image = form.locator("[data-role='existing-image'] img")
            expect(image).to_be_visible()
            expect(image).to_have_attribute("src", original_src)
            expect(user.locate(page.PHOTO_PROMPT_UPLOAD)).to_be_enabled()
