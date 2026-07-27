from bs4 import BeautifulSoup
from playwright.sync_api import expect

from ..elements import List, SpinnerButtons, Tabs
from .core import SiteResource


class File(SiteResource):
    _initialize = True
    _sync = True

    # Main layout
    FILE_TITLE = "[data-nav='view'] [data-role='title']"
    DOWNLOAD_LINK = "[data-nav='view'] a[href$='/download']"
    MOBILE_NAV = "[lp-nav][data-nav='mobile']"
    DESKTOP_TAB_NAV = "#tabs [lp-nav][data-nav='tabs']"
    TABS_CARD = "#tabs"
    LINKED_ENTITIES = "[data-role='linked-entities']"

    # Preview section
    PREVIEW_CARD = "#preview"
    PREVIEW_IMAGE = "#preview img[data-widget='FilePreview']"
    PREVIEW_PDF = "#preview [data-widget='PDFPreview']"
    PREVIEW_PDF_CANVAS = "#preview [data-widget='PDFPreview'] canvas"
    PREVIEW_PDF_STATUS = (
        "#preview [data-widget='PDFPreview'] [data-role='pdf-status']"
    )
    PREVIEW_PDF_LOADING_BARS = f"{PREVIEW_PDF_STATUS} > div > div"
    PREVIEW_PDF_TOOLBAR = "#preview [data-widget='PDFPreview'] [data-role='toolbar']"
    PREVIEW_PDF_PAGE_INPUT = (
        "#preview [data-widget='PDFPreview'] [data-role='pdf-page-input']"
    )
    PREVIEW_PDF_PAGE_COUNT = (
        "#preview [data-widget='PDFPreview'] [data-role='pdf-page-count']"
    )
    PREVIEW_PDF_NEXT_PAGE = (
        "#preview [data-widget='PDFPreview'] [data-action='next-page']"
    )
    PREVIEW_PDF_PREVIOUS_PAGE = (
        "#preview [data-widget='PDFPreview'] [data-action='previous-page']"
    )
    PREVIEW_PDF_FOCUS = (
        "#preview [data-widget='PDFPreview'] [data-action='toggle-fullscreen']"
    )
    PREVIEW_MEDIA = "#preview [data-widget='FilePreview']"
    EXTRACT_RELOAD_NOTICE = "[data-role='extract-reload']"
    EXTRACT_RELOAD_BUTTON = "[data-role='extract-reload-button']"

    # Info tab
    INFO_FORM = "[data-widget='FileInfo']"
    INFO_NAME_FIELD = "#name"
    INFO_NAME = "input[name='name']"
    INFO_DESCRIPTION_FIELD = "#description"
    INFO_DESCRIPTION = "textarea[name='description']"
    INFO_PAGES = "[data-role='pages']"

    # Text tab
    TEXT_CONTENT = "[data-widget='TextContent']"

    # Ingress tab
    INGRESS_WIDGET = "[data-widget='ImportData']"

    # Page file list
    PAGE_FILE_ITEM = "li[lp-entity][data-kind='file']"

    @property
    def url_suffix(self):
        return f"files/{self.key}"

    @staticmethod
    def _upload_display_name(upload):
        definition = upload.definition
        return (
            definition.display_name
            or definition.filename
            or definition.file.name.rsplit(".", 1)[0]
        )

    @classmethod
    def upload_from_page(cls, user, page_resource, upload):
        page = user.go(page_resource)
        files_tab = page.files_tab
        upload_form = files_tab.locator(page.UPLOAD_FILE_FORM)

        if not upload_form.is_visible():
            user.locate(page.UPLOAD_FILE_TOGGLE).click()
        expect(upload_form).to_be_visible()

        upload.set(upload_form)
        with user.page.expect_response("**/upload") as response_info:
            SpinnerButtons.UPLOAD.click(upload_form)

        response = response_info.value
        created = BeautifulSoup(response.text(), "html.parser").find(
            "li", attrs={"data-key": True}
        )

        file_list = List(files_tab.locator("[data-widget='BaseList']"))
        if created:
            file_item = file_list.list.locator(f"li[data-key='{created['data-key']}']")
            expect(file_item).to_be_visible()
        else:
            file_item = file_list.new_item(cls._upload_display_name(upload))

        file = cls(user=user)
        file.key = file_item.get_attribute("data-key")
        return file

    @property
    def info_form(self):
        info_tab = Tabs(self.user).info
        form = info_tab.locator(self.INFO_FORM)
        expect(form).to_have_attribute("rendered", "")
        return form

    @property
    def text_content(self):
        text_tab = Tabs(self.user).text
        content = text_tab.locator(self.TEXT_CONTENT)
        expect(content).to_be_visible()
        return content

    @property
    def preview_content(self):
        preview_tab = Tabs(self.user).preview
        content = preview_tab.locator(self.PREVIEW_MEDIA)
        expect(content).to_be_visible()
        return content
