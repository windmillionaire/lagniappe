import re
from urllib.parse import parse_qsl, urlsplit

from playwright.sync_api import expect

from testing.utility.network import expect_successful_response


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

    def find_item(self, entity):
        """Find a named row in a loaded Home list, following its pagination controls."""
        row = self.get_item(entity)
        first_page = self.list.locator("button[lp-control='previous']")
        next_page = self.list.locator("button[lp-control='next']")
        control = first_page if first_page.count() else next_page
        visited = set()
        while not row.count():
            expect(control, f"Missing a page containing {entity.name!r}").to_have_attribute(
                "data-route", re.compile(r"\S+")
            )
            route = control.get_attribute("data-route")
            target = urlsplit(route)
            with expect_successful_response(
                self.list.page,
                method="GET",
                path=target.path,
                query=dict(parse_qsl(target.query)),
            ) as response:
                control.click()
            url = response.value.url
            assert url not in visited, f"Home pagination returned {url} twice"
            visited.add(url)
            # The response arrives before the widget replaces the outgoing controls.
            outgoing = self.list.locator(f'button[lp-control][data-route="{route}"]')
            expect(outgoing).not_to_be_attached()
            control = next_page
        return row

    def count(self):
        return self.list.count()
