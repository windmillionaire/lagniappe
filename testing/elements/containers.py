from playwright.sync_api import expect


class List:
    def __init__(self, list):
        self.list = list

    @property
    def is_loaded(self):
        expect(self.list).to_be_attached()
        expect(self.list).to_have_attribute("loaded", "")
        return True

    @property
    def is_visible(self):
        """Whether Playwright considers the list element visible right now (no wait)."""
        return self.list.is_visible()

    def new_item(self, name, flash=True):
        locator = f"li.flash:has-text('{name}')" if flash else f"li:has-text('{name}')"
        item = self.list.locator(locator)
        expect(item).to_be_visible()
        key = item.get_attribute("data-key")
        if key:
            return self.list.locator(f"li[data-key='{key}']")
        return item

    def new_ai_generated_item(self, flash=True):
        item = self.list.locator("li[ai-generated]")
        if flash:
            expect(item).to_contain_class("flash")
        expect(item).to_be_visible()
        return item

    def get_item(self, entity):
        assert entity.key, "Entity must have a key"

        return self.list.locator(f"li[lp-entity][data-key='{entity.key}']")

    def count(self):
        return self.list.count()
