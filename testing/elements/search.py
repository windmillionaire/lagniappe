from playwright.sync_api import expect

from .combobox import Select


class HeaderSearch:
    SEARCH_ELEMENT = "[lp-search]"

    def __init__(self, user):
        self.page = user.page

    def search(self, query):
        combobox = Select(self.page.locator(self.SEARCH_ELEMENT))
        combobox.input.fill(query)
        self.panel = combobox.panel

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
