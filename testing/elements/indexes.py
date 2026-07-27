from playwright.sync_api import expect


class Tools:
    TOOLS = "#tools"
    TOGGLE = "button[lp-show='tools:default']"
    CLOSE = "[lp-close]"

    def __init__(self, user):
        self.tools = user.page.locator(self.TOOLS)
        self.toggle = user.page.locator(self.TOGGLE)
        self.close_button = user.page.locator(self.CLOSE)
        expect(self.toggle).to_be_visible()
        expect(self.tools).to_be_hidden()

    def open(self):
        self.toggle.click()
        expect(self.tools).to_be_visible()

    def close(self):
        expect(self.close_button).to_be_visible()
        self.close_button.click()
        expect(self.tools).to_be_hidden()

    def locate(self, selector):
        return self.tools.locator(selector)


class Table:
    TABLE = "#table"
    ENTITY_URL = "td[data-column='name'] a[data-role='title']"
    ENTITY_KEY = "data-key"

    def __init__(self, user):
        self.table = user.page.locator(self.TABLE)
        expect(self.table).to_be_visible()

    def new_row(self, name):
        row = self.table.locator(f"tr.flash:has-text('{name}')")
        expect(row).to_be_visible()
        expect(row).to_contain_class("flash")
        return row

    def get_row(self, name):
        row = self.table.locator(f"tr:has-text('{name}')")
        return row

class MobileTableControls:
    TOGGLE = "button[lp-show='table:MobileTableControls']"
    PANEL = "#mobile-controls"
    COLUMN_ROW = "[data-column='{column}']"
    VISIBILITY_BUTTON = "button[data-toggle='visibility']"
    FILTER_BUTTON = "button[data-toggle='filter']"

    def __init__(self, user):
        self.user = user
        self.toggle = user.locate(self.TOGGLE)
        self.panel = user.locate(self.PANEL)

    def open(self):
        expect(self.toggle).to_be_visible()
        self.toggle.click()
        expect(self.panel).to_be_visible()
        return self.panel

    def row(self, column):
        row = self.panel.locator(self.COLUMN_ROW.format(column=column))
        expect(row).to_be_visible()
        return row

    def visibility_button(self, column):
        button = self.row(column).locator(self.VISIBILITY_BUTTON)
        expect(button).to_be_visible()
        return button

    def filter_button(self, column):
        button = self.row(column).locator(self.FILTER_BUTTON)
        expect(button).to_be_visible()
        return button

    def toggle_column(self, column):
        button = self.visibility_button(column)
        button.click()
        return button
