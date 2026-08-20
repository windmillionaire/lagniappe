from enum import Enum

from playwright.sync_api import expect

from .combobox import Dropdown

UPLOAD_MENU = "[data-role='upload-menu']"


class UploadDropdown(Enum):
    REMOVE = "Remove"
    REPLACE = "Replace"
    GENERATE = "Generate"
    PASTE = "Paste"

    def select(self, container):
        element = container.locator(UPLOAD_MENU)
        expect(element).to_be_visible()
        dropdown = Dropdown(element)
        dropdown.select_by_name(self.value)
