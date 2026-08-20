"""Page photo upload, generation, replacement, and removal workflows."""

from contextlib import contextmanager
import re

import pytest
from playwright.sync_api import expect

from testing.definitions import Pages, Uploads, Users
from testing.elements import Attributes, UploadDropdown
from testing.resources import Page
from testing.utility import (
    expect_successful_response,
    multipart_form_fields,
    scoped_browser_route,
)

pytestmark = pytest.mark.e2e


def _photo_form(user):
    form = user.locate(Page.PHOTO_FORM)
    expect(form).to_be_visible()
    return form


def _photo_prompt(page):
    prompt = page.info_form.locator(page.PHOTO_PROMPT)
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

    expect(prompt).not_to_be_attached()
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
    requests = []

    def fulfill_generated_image(route):
        assert route.request.method == "POST"
        requests.append(multipart_form_fields(route.request))
        route.fulfill(status=200, content_type="text/html", body=html)

    with scoped_browser_route(
        page.context,
        f"**{path}",
        fulfill_generated_image,
    ):
        yield path, requests


def _expect_cache_busted_image(form):
    image = form.locator("[data-role='existing-image'] img")
    expect(image).to_be_visible()
    expect(image).to_have_attribute("src", re.compile(r"[?&]v=\d+"))


def _desktop_photo_toggle(user):
    return user.locate("#tabs nav[data-nav='tabs'] button[lp-show='photo:active']")


# @features pages
# @dimensions image-add photo-prompt
def test_add_image_to_page(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_image_page)

    _upload_image_from_prompt(user, page)

    expect(user.locate(page.PHOTO_EXISTING_IMAGE)).to_be_visible()
    expect(user.locate(page.PHOTO_EXISTING_IMAGE).locator("img")).to_be_visible()
    expect(user.locate("[lp-view]")).to_have_class(re.compile(".*max-w-7xl.*"))


# @features pages
# @dimensions photo-prompt desktop-tabs
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


# @pairs pages:photo-prompt pages:mobile-photo-tab
# @pair entity-layout:dynamic-secondary
# @template pages/page.html::main
def test_mobile_photo_prompt_rejoins_section_switching(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_generated_image_page)
    attributes = Attributes(page.info_form)

    attributes.set_selected("photo", False)
    user.mobile = True
    attributes.set_selected("photo", True)
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


# @features pages
# @dimensions image-replace
def test_replace_image_on_page(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_image_page)
    form = _ensure_photo_form(user, page)

    with user.page.expect_response("**/add-page-image"):
        with user.page.expect_file_chooser() as chooser:
            UploadDropdown.REPLACE.select(form)
        chooser.value.set_files(Uploads.editor_test_image.definition.file.path)

    _expect_cache_busted_image(form)


# @features pages
# @dimensions image-generate photo-prompt
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
    ) as (path, requests):
        with expect_successful_response(
            user.page,
            method="POST",
            path=path,
        ):
            generate_form.locator("button[data-role='generate']").click()

        expect(form.locator("img[alt='Generated test image']")).to_be_visible()
        expect(prompt).not_to_be_attached()
        expect(user.locate("[lp-view]")).to_have_class(re.compile(".*max-w-7xl.*"))

    assert len(requests) == 1
    assert ("prompt", image_prompt) in requests[0]


# @features pages
# @dimensions photo-prompt photo-disable
def test_empty_page_photo_prompt_can_disable_photo_without_reload(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_generated_image_page)
    info_form = page.info_form
    prompt = info_form.locator(page.PHOTO_PROMPT)
    expect(prompt).to_be_visible()
    expect(user.locate(page.PHOTO_FORM)).not_to_be_visible()
    expect(user.locate("[lp-view]")).to_have_class(re.compile(".*max-w-5xl.*"))

    user.page.evaluate("window.__photoPromptNoReload = true")
    with user.page.expect_response("**/attributes/photo"):
        prompt.locator(page.PHOTO_PROMPT_DISABLE).click()

    expect(prompt).not_to_be_visible()
    expect(user.locate(page.PHOTO_FORM)).not_to_be_visible()
    Attributes(info_form).expect_selected("photo", False)
    assert user.page.evaluate("window.__photoPromptNoReload") is True

    with user.page.expect_response("**/attributes/photo"):
        Attributes(info_form).set_selected("photo", True)

    expect(prompt).to_be_visible()
    expect(user.locate(page.PHOTO_FORM)).not_to_be_visible()
    assert user.page.evaluate("window.__photoPromptNoReload") is True


# @features pages
# @dimensions image-paste
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


# @features pages
# @dimensions image-remove
def test_remove_image_from_page(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_image_page)
    form = _ensure_photo_form(user, page)

    with user.page.expect_response("**/remove-page-image"):
        UploadDropdown.REMOVE.select(form)

    expect(user.locate(page.PHOTO_EXISTING_IMAGE).locator("img")).not_to_be_attached()
    expect(user.locate(page.PHOTO_FEEDBACK)).to_be_visible()
