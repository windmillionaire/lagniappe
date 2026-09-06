import re
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect

from .combobox import Select


class HeaderSearch:
    SEARCH_ELEMENT = "[lp-search]"

    def __init__(self, user):
        self.page = user.page

    def search(self, query):
        search = self.page.locator(self.SEARCH_ELEMENT)
        with self.page.expect_response(
            lambda response: (
                urlsplit(response.url).path == "/l/search-bar"
                and parse_qs(urlsplit(response.url).query).get("q") == [query]
                and response.request.method == "GET"
            )
        ) as result:
            search.locator("input[name='q']").fill(query)
        assert result.value.status == 200
        expect(search).to_have_attribute("data-combobox-id", re.compile(r".+"))
        combobox = Select(search)
        self.panel = combobox.panel
        # Empty results legitimately keep the panel hidden. Wait for query
        # publication, not panel visibility or absence of old text.
        expect(search.locator("input[name='q']")).to_have_attribute("aria-busy", "false")

    def verify_entity_in_results(self, entity):
        self.search(entity.name)
        expect(self.panel).to_contain_text(entity.name)

    def verify_entity_not_in_results(self, entity):
        self.search(entity.name)
        expect(self.panel).not_to_contain_text(entity.name)

    def verify_keyword_finds_entity(self, keyword, entity):
        self.search(keyword)
        expect(self.panel).to_contain_text(entity.name)

    def verify_keyword_does_not_find_entity(self, keyword, entity):
        self.search(keyword)
        expect(self.panel).not_to_contain_text(entity.name)
