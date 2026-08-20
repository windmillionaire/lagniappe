from playwright.sync_api import expect


class Combobox:
    _multiple = False

    def __init__(self, element):
        if element.get_attribute("data-combobox-id") is not None:
            self.element = element
        else:
            self.element = element.locator("[data-combobox-id]")
        self._multiple = (
            self.element.get_attribute("data-multiple") == "true"
            or self.element.locator("[data-multiple='true']").count() > 0
        )

        self.id = self.element.get_attribute("data-combobox-id")

    @property
    def panel(self):
        if getattr(self, "_panel", None):
            return self._panel
        self._panel = self.element.page.locator(
            f"[role='listbox'][aria-labelledby='{self.id}']"
        )
        return self._panel

    def open(self):
        panel = self.panel
        if not panel.is_visible():
            # Playwright's click already waits for actionability. If a proven
            # pointer-transition race remains, hover here before clicking.
            self.click()
        self.expect_open(panel)
        return panel

    @staticmethod
    def expect_open(panel):
        expect(panel).to_be_visible()
        expect(panel).to_have_attribute("data-positioned", "true")

    def click(self):
        self.element.click()


class Select(Combobox):
    @property
    def input(self):
        if getattr(self, "_input", None):
            return self._input
        self._input = self.element.locator(f"input[id='{self.id}']")
        if self._input.count() == 0:
            self._input = self.element.page.locator(f"[id='{self.id}']")
        return self._input

    @input.setter
    def input(self, value):
        self._input = value

    def open(self):
        panel = self.panel
        if not panel.is_visible():
            self.click()

        # Search-backed facet boxes intentionally keep an empty panel hidden
        # until a query returns results. Static SelectBox controls can become
        # visible immediately and should still cross the positioning boundary
        # here.
        if self.input.get_attribute("inputmode") == "none":
            self.expect_open(panel)
        return panel

    @property
    def placeholder(self):
        return self.input.get_attribute("placeholder")

    def fill(self, value):
        self.input.fill(value)

    def blur(self):
        if getattr(self, "_input", None):
            self._input.blur()

    def _choose_option(self, panel, option):
        """Choose through the combobox keyboard contract after positioning."""
        option_id = option.get_attribute("id")
        option_count = panel.get_by_role("option").count()
        for _index in range(option_count):
            if self.input.get_attribute("aria-activedescendant") == option_id:
                break
            self.input.press("ArrowDown")
        expect(self.input).to_have_attribute("aria-activedescendant", option_id)
        self.input.press("Enter")

    def select_by_name(self, name):
        panel = self.open()

        mode = self.input.get_attribute("inputmode")
        if mode != "none":
            expect(self.input).to_be_focused()
            self.input.fill(name)
        self.expect_open(panel)

        option = panel.get_by_role("option", name=name, exact=True)
        expect(option).to_be_visible()
        self._choose_option(panel, option)

        if not self._multiple:
            expect(panel).to_be_hidden()
        else:
            self.input.press("Escape")

    def select_by_key(self, key, *, query=None):
        panel = self.open()

        if query is not None and self.input.get_attribute("inputmode") != "none":
            expect(self.input).to_be_focused()
            self.input.fill(query)
        self.expect_open(panel)

        option = panel.locator(f"[role='option'][data-id='{key}']")
        expect(option).to_be_visible()
        self._choose_option(panel, option)

        if not self._multiple:
            expect(panel).to_be_hidden()
        else:
            self.input.press("Escape")


class Dropdown(Combobox):
    def select_by_name(self, name):
        panel = self.open()
        expect(panel).to_be_visible()

        option = panel.get_by_role("option", name=name, exact=True)
        expect(option).to_be_visible()
        option.click()

        if not self._multiple:
            expect(panel).to_be_hidden()
