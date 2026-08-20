from playwright.sync_api import expect


class Tabs:
    INFO_TOGGLE_DESKTOP = "[data-nav='tabs'] button[lp-show='info:active']"
    INFO_TOGGLE_MOBILE = "[data-nav='mobile'] button[lp-show='info:active']"
    INFO_TAB = "#info"

    FILTERS_TOGGLE_DESKTOP = "[data-nav='tabs'] button[lp-show='filters:active']"
    FILTERS_TOGGLE_MOBILE = "[data-nav='mobile'] button[lp-show='filters:active']"
    FILTERS_TAB = "#filters"

    DOCUMENT_TOGGLE_DESKTOP = "[data-nav='tabs'] button[lp-show='document:active']"
    DOCUMENT_TOGGLE_MOBILE = "[data-nav='mobile'] button[lp-show='document:active']"
    DOCUMENT_TAB = "#document"

    TEXT_TOGGLE_DESKTOP = "[data-nav='tabs'] button[lp-show='text:active']"
    TEXT_TOGGLE_MOBILE = "[data-nav='mobile'] button[lp-show='text:active']"
    TEXT_TAB = "#text"

    NOTES_TOGGLE_DESKTOP = "[data-nav='tabs'] button[lp-show='notes:active']"
    NOTES_TOGGLE_MOBILE = "[data-nav='mobile'] button[lp-show='notes:active']"
    NOTES_TAB = "#notes"

    FILES_TOGGLE_DESKTOP = "[data-nav='tabs'] button[lp-show='files:active']"
    FILES_TOGGLE_MOBILE = "[data-nav='mobile'] button[lp-show='files:active']"
    FILES_TAB = "#files"

    TASKS_TOGGLE_DESKTOP = "[data-nav='tabs'] button[lp-show='tasks:active']"
    TASKS_TOGGLE_MOBILE = "[data-nav='mobile'] button[lp-show='tasks:active']"
    TASKS_TAB = "#tasks"

    MODEL_TASKS_TOGGLE_MOBILE = "[data-nav='mobile'] button[lp-show='models:active']"
    MODEL_TASKS_CARD = "#models"

    PREVIEW_TOGGLE_DESKTOP = "[data-nav='tabs'] button[lp-show='preview:active']"
    PREVIEW_TOGGLE_MOBILE = "[data-nav='mobile'] button[lp-show='preview:active']"
    PREVIEW_TAB = "#preview"

    def __init__(self, user):
        self.user = user

    def _open(self, tab_name):
        toggle = getattr(self, f"{tab_name}_TOGGLE_DESKTOP")
        if self.user.mobile:
            toggle = getattr(self, f"{tab_name}_TOGGLE_MOBILE")
        tab = getattr(self, f"{tab_name}_TAB")

        tab_panel = self.user.locate(tab)
        if not tab_panel.is_visible():
            self.user.locate(toggle).click()
        expect(tab_panel).to_be_visible()

        return tab_panel

    @property
    def info(self):
        return self._open("INFO")

    @property
    def filters(self):
        return self._open("FILTERS")

    @property
    def document(self):
        return self._open("DOCUMENT")

    @property
    def text(self):
        return self._open("TEXT")

    @property
    def notes(self):
        return self._open("NOTES")

    @property
    def files(self):
        return self._open("FILES")

    @property
    def tasks(self):
        return self._open("TASKS")

    @property
    def preview(self):
        return self._open("PREVIEW")


class MobileNav:
    """
    Helper for interacting with mobile navigation on entity pages.

    The mobile nav (data-role='mobile-nav') provides section switching on small
    screens. It includes:
    - Section title display
    - Two sliders:
      - Tab slider (slide-left): Reveals section toggle icons
      - Title slider (slide-right): Reveals parent/breadcrumb info
    - Section toggle buttons (info, document, filters, models, etc.)
    - Help and close buttons when expanded

    Related Files:
        - lagniappe/web/templates/projects/project.html: mobile_nav macro
        - lagniappe/web/templates/pages/page.html: mobile_nav macro
        - src/script/views/base/entity.mjs: _initMobileNav method
        - src/style/special.css: slide-left, slide-right, data-flipped styles

    Attributes:
        MOBILE_NAV: Main mobile nav container
        SECTION_TITLE: Current section title text
        TAB_SLIDER_BUTTON: Button that toggles tab icons (slide-left)
        TAB_SLIDER_CONTENT: Container for section toggle buttons
        TITLE_SLIDER_BUTTON: Button that toggles title/breadcrumb info (slide-right)
        TITLE_SLIDER_CONTENT: Container for parent title info
        SECTION_CONTROLS: Help and close buttons container
    """

    MOBILE_NAV = "[lp-nav][data-nav='mobile']"
    SECTION_TITLE = "[lp-nav][data-nav='mobile'] [data-role='title']"
    SECTION_CONTROLS = "[lp-nav][data-nav='mobile'] [data-role='controls']"

    # Tab slider (slide-left) - reveals section toggle icons
    TAB_SLIDER_WRAPPER = "[lp-nav][data-nav='mobile'] [data-flipped]"
    TAB_SLIDER_BUTTON = "[lp-nav][data-nav='mobile'] [data-role='flipper']"
    TAB_SLIDER_CONTENT = "[lp-nav][data-nav='mobile'] .slide-left"

    # Title slider (slide-right) - reveals parent/breadcrumb info
    # Note: This is in the breadcrumbs area, not mobile-nav
    TITLE_SLIDER_BUTTON = "[data-role='breadcrumbs'] button[data-flipped]"
    TITLE_SLIDER_CONTENT = "[data-role='breadcrumbs'] .slide-right"

    def __init__(self, user):
        """
        Initialize MobileNav helper.

        Args:
            user: User resource with page and locate() method
        """
        self.user = user
        self.nav = user.locate(self.MOBILE_NAV)

    def locate(self, selector):
        return self.nav.locator(selector)

    def is_visible(self):
        """Check if mobile nav is visible (only on mobile viewport)."""
        return self.nav.is_visible()

    def get_section_title(self):
        """Get the current section title text."""
        return self.user.locate(self.SECTION_TITLE).text_content()

    def get_selected_section(self):
        """Get the lp-show target for the currently selected mobile nav button."""
        selected = self.nav.locator(
            "nav[data-nav='mobile'] button[data-selected='true']"
        )
        if not selected.count():
            return None
        return selected.first.get_attribute("lp-show")

    def is_expanded(self):
        """Check if the nav is in expanded state (showing help/close)."""
        return self.nav.get_attribute("data-expanded") == "true"

    def get_open_section(self):
        """Get the currently open section ID."""
        return self.nav.get_attribute("data-open")

    # --- Tab Slider (slide-left) ---

    def open_tab_slider(self):
        """
        Open the tab slider to reveal section toggle icons.

        Clicks the slider button (data-flipped) to show the section icons.
        """
        slider = self.user.locate(self.TAB_SLIDER_BUTTON)
        expect(slider).to_be_visible()
        slider.click()

        icons = self.user.locate(self.TAB_SLIDER_CONTENT)
        expect(icons).to_be_visible()
        expect(self.user.locate(self.TAB_SLIDER_WRAPPER)).to_have_attribute(
            "data-flipped", "true"
        )
        return icons

    def close_tab_slider(self):
        """
        Close the tab slider to hide section toggle icons.

        Clicks the slider button again to hide the section icons.
        """
        slider = self.user.locate(self.TAB_SLIDER_BUTTON)
        slider.click()
        expect(self.user.locate(self.TAB_SLIDER_WRAPPER)).to_have_attribute(
            "data-flipped", "false"
        )

    def is_tab_slider_open(self):
        """Check if the tab slider is currently open."""
        wrapper = self.user.locate(self.TAB_SLIDER_WRAPPER)
        return wrapper.get_attribute("data-flipped") == "true"

    # --- Title Slider (slide-right) ---

    def open_title_slider(self):
        """
        Open the title slider to reveal parent/breadcrumb info.

        Clicks the slider button to show the parent title.
        """
        slider = self.user.locate(self.TITLE_SLIDER_BUTTON)
        if not slider.is_visible():
            return None  # No title slider on this page

        slider.click()

        content = self.user.locate(self.TITLE_SLIDER_CONTENT)
        expect(content).to_be_visible()
        return content

    def close_title_slider(self):
        """
        Close the title slider to hide parent/breadcrumb info.
        """
        slider = self.user.locate(self.TITLE_SLIDER_BUTTON)
        if not slider.is_visible():
            return

        slider.click()

        content = self.user.locate(self.TITLE_SLIDER_CONTENT)
        expect(content).to_be_hidden()

    def is_title_slider_open(self):
        """Check if the title slider is currently open."""
        content = self.user.locate(self.TITLE_SLIDER_CONTENT)
        if not content.count():
            return False
        return content.get_attribute("data-open") == "true"

    # --- Section Selection ---

    def select_section(self, section_name, widget_name=None):
        """
        Select a section by clicking its toggle button.

        Args:
            section_name: Component identifier (info, document, filters, model-tasks)

        Returns:
            The section element
        """
        if not self.is_tab_slider_open():
            self.open_tab_slider()

        section_id = section_name.split(":", 1)[0]
        if widget_name is not None:
            button = self.nav.locator(
                f"button[lp-show^='{section_name}:{widget_name}']"
            )
        else:
            button = self.nav.locator(
                f"nav[data-nav='mobile'] button[lp-show^='{section_name}']"
            )
        expect(button).to_be_visible()
        button.click()

        section = self.user.locate(f"#{section_id}")
        # The selected attribute is implementation state.  Waiting for the
        # requested section to paint proves that lazy activation and mobile
        # layout reconciliation both finished, including slower hosted loads.
        expect(section).to_be_visible(timeout=15000)
        return section
