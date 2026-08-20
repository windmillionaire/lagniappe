"""
Common site-wide UI element selectors and helpers.

Provides reusable selectors for buttons, form fields, and common UI patterns
used across the application. These are CSS selectors as class attributes,
not instances.

Related Files:
    Templates (organized by feature, mirroring routes/entities):
        - lagniappe/web/templates/users/: User-related templates (login.html, etc.)
        - lagniappe/web/templates/home/: Home page templates
        - lagniappe/web/templates/layouts/: Base layout templates

    Styles (YAML-based build system):
        - src/style/styles.yaml: Typed semantic style definitions
        - src/style/icons.yaml: Shared icon definitions
        - build/rollup.config.mjs: Build process that processes YAML styles
        - lagniappe/web/start/styles/: Generated Python maps (styles.py, icons.py)

        The build process reads the YAML registries, exposes them through the
        virtual JavaScript "styles" module, and generates matching Python maps
        for server-side templates.

Usage:
    # Selectors are used with locator methods
    form.locator(FormElements.NAME).fill("Test Name")
    form.locator(Buttons.SIGNIN).click()

    # Check for error messages
    error = form.locator(Roles.ERROR)
    expect(error).to_be_visible()

    # Helper classes wrap elements with built-in assertions
    link = Link(list_item)
    link.click()
"""

from playwright.sync_api import expect


DELETE_COMPLETION_TIMEOUT = 30000


class Buttons:
    """
    CSS selectors for common button elements.

    These selectors use data attributes for reliable targeting.
    Buttons typically use custom lp-* attributes or data-role/data-action-type.

    Selectors:
        Lagniappe custom buttons (lp-* attributes):
            LP_STAR: Star/favorite toggle
            LP_DELETE: Delete with confirmation modal
            LP_CLOSE: Close panel/modal
            LP_HELP: Open help/documentation

        Form buttons:
            SIGNIN: Login form submit (data-role='signin')
            DELETE: Confirm delete action (data-role='delete')
            CANCEL: Cancel/close action (data-role='cancel')

        Mode toggles:
            AI_MODE: Switch to AI-assisted mode
            MANUAL_MODE: Switch to manual entry mode
            EXPLAIN: Request AI explanation

        Source selection:
            SOURCE_TEXT: Text input source
            SOURCE_PHOTO: Photo/image source

    See Also:
        testing/elements/forms_common.py FormSelect, ProjectSelect, DateSelect, UserSelect, FileSelect for action-type buttons
        (date picker, form selector, project selector, etc.)
    """

    LP_DELETE = "button[lp-delete]"
    LP_CLOSE = "button[lp-close]"
    LP_HELP = "button[lp-help]"
    SIGNIN = "button[data-role='signin']"
    EXPLAIN = "button[data-role='explain']"
    DELETE = "button[data-role='delete']"
    CANCEL = "button[data-role='cancel']"
    AI_MODE = "button[data-role='ai']"
    MANUAL_MODE = "button[data-role='manual']"
    SOURCE_TEXT = "[data-source='text']"
    SOURCE_PHOTO = "[data-source='photo']"


class Roles:
    """
    CSS selectors for elements identified by data-role attribute.

    Used for semantic element targeting where role describes purpose.

    Selectors:
        ERROR: Error message display area
        OPTIONS: Options/actions container
        SOURCE: Source selection area
    """

    ERROR = "[data-role='error']"
    OPTIONS = "[data-role='options']"
    SOURCE = "[data-role='source']"
    PAGE_HEADER = "nav[data-nav='view']"
    USER_PAGE = "a[href*='/pages/'] button[data-kind='user']"


class FormElements:
    """
    CSS selectors for common form input fields.

    These target form fields by name attribute or input type.
    Used across entity creation forms, settings, etc.

    Selectors:
        NAME: Standard name input field
        DESCRIPTION: Multi-line description textarea
        AI_DESCRIPTION: AI prompt/description for generation
        EMAIL: Email input (uses type='email')
        FORM_TYPE: Radio buttons for form type selection
        NOTE: Note/comment textarea
        FILE_INPUT: File upload input
    """

    NAME = "input[name='name']"
    DESCRIPTION = "textarea[name='description']"
    AI_DESCRIPTION = "textarea[name='user_description']"
    EMAIL = "input[type='email']"
    FORM_TYPE = "input[name='form-type']"
    NOTE = "textarea[name='note']"
    FILE_INPUT = "input[type='file']"


class Link:
    """
    Helper for entity title links in lists and tables.

    Wraps an element containing a title link (a[data-role='title'])
    and provides click functionality with visibility assertion.

    Attributes:
        element: The parent element containing the link
        title: The title anchor element

    Usage:
        list_item = category_list.get_item(category)
        link = Link(list_item)
        link.click()  # Navigates to entity page
    """

    TITLE = "a[data-role='title']"

    def __init__(self, element):
        """
        Initialize Link helper.

        Args:
            element: Parent element (e.g., list item, table row) containing the title link
        """
        self.element = element
        self.title = element.locator(self.TITLE)
        expect(self.title).to_be_visible()

    def click(self):
        """Click the title link to navigate to the entity."""
        self.title.click()


class Modal:
    """
    Helper for interacting with the site's modal dialog.

    The application uses a single modal (#modal) for confirmations,
    forms, and dialogs. This helper provides common modal interactions.

    Attributes:
        modal: The modal element locator

    Usage:
        # After triggering delete action
        modal = Modal(user.page)
        modal.delete()  # Confirms delete with spinner wait

        # Or close without action
        modal = Modal(user.page)
        modal.close()

        # Click any button by name
        modal.click("Confirm")
    """

    MODAL = "#modal"

    def __init__(self, page):
        """
        Initialize Modal helper.

        Args:
            page: Playwright Page object
        """
        self.element = page.locator(self.MODAL)
        self.page = page

    def close(self):
        """Click Close button and wait for modal to hide."""
        close_button = self.element.get_by_role("button", name="Close")
        expect(close_button).to_be_visible()
        close_button.click()
        expect(self.element).to_be_hidden()

    def delete(self, timeout=DELETE_COMPLETION_TIMEOUT):
        """
        Click Delete button, wait for spinner, then modal hide.

        Used for delete confirmations. Verifies the loading spinner
        appears during the delete operation. Deletions may synchronously
        traverse substantial related data, so their completion has a longer
        timeout than ordinary modal interactions.
        """
        delete_button = self.element.locator(Buttons.DELETE)
        expect(delete_button).to_be_visible()
        delete_button.click()
        expect(delete_button.locator("[data-icon='spinner']")).to_be_visible()
        expect(self.element).to_be_hidden(timeout=timeout)

    def click(self, name):
        """
        Click any button in the modal by its accessible name.

        Args:
            name: Button text/label (e.g., "Confirm", "Save", "Cancel")
        """
        button = self.element.get_by_role("button", name=name)
        expect(button).to_be_visible()
        button.click()
        expect(self.element).to_be_hidden()

    def open(self, trigger):
        """Open the modal by clicking the trigger."""
        trigger_locator = (
            trigger if hasattr(trigger, "click") else self.page.locator(trigger)
        )
        trigger_locator.click()
        expect(self.element).to_be_visible()
        return self


class StarButton:
    """
    Helper for interacting with the star button.
    """

    STAR_BUTTON = "button[lp-control='star']"

    def __init__(self, element):
        """
        Initialize StarButton helper.
        """
        self.button = element.locator(self.STAR_BUTTON)
        expect(self.button).to_be_visible()

    def click(self):
        """Click the star button."""
        self.button.click()

    @property
    def is_starred(self):
        """Check if the star button is starred."""
        return self.button.get_attribute("data-active") == "true"

    @property
    def is_unstarred(self):
        """Check if the star button is unstarred."""
        return self.button.get_attribute("data-active") == "false"

    def toggle(self):
        """Toggle the star button."""
        starred = self.button.get_attribute("data-active") == "true"
        with self.button.page.expect_response("**/l/toggle-star/*"):
            self.button.click()

        expected = "false" if starred else "true"
        expect(self.button).to_have_attribute("data-active", expected)
        expect(self.button).to_have_attribute(
            "aria-label", "Star" if starred else "Unstar"
        )
