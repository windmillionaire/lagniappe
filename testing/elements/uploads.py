from enum import Enum

from playwright.sync_api import expect

UPLOAD_MENU = "[data-role='upload-menu']"
PHOTO_MENU_TRIGGER = "[data-photo-menu='true']"


class UploadDropdown(Enum):
    REMOVE = "Remove"
    REPLACE = "Replace"
    GENERATE = "Generate"
    PASTE = "Paste"

    def select(self, container):
        menu = container.locator(UPLOAD_MENU)
        if menu.is_visible():
            button = menu.get_by_role("button", name=self.value)
            expect(button).to_be_visible()
            button.click()
            return
        page = container.page
        trigger = page.locator(PHOTO_MENU_TRIGGER)
        expect(trigger).to_be_visible()
        trigger.click()
        action = self.name.lower()
        item = page.locator(f"[data-photo-action='{action}']:visible").first
        expect(item).to_be_visible()
        item.click()
