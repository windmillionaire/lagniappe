from enum import Enum

from playwright.sync_api import expect

UPLOAD_MENU = "[data-role='upload-menu']"


class UploadDropdown(Enum):
    REMOVE = "Remove"
    REPLACE = "Replace"
    GENERATE = "Generate"
    PASTE = "Paste"

    def select(self, container):
        menu = container.locator(UPLOAD_MENU)
        expect(menu).to_be_visible()
        button = menu.get_by_role("button", name=self.value)
        expect(button).to_be_visible()
        button.click()
