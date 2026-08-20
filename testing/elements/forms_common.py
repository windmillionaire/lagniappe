"""
Form-specific UI element helpers.

Provides helpers for form interactions including action buttons with dropdowns,
attribute selection, and submit buttons with loading states.

Related Files:
    Templates (organized by feature):
        - lagniappe/web/templates/forms/: Form builder templates
        - lagniappe/web/templates/categories/: Category forms (use attributes)
        - lagniappe/web/templates/pages/: Page forms

    Scripts:
        - src/script/views/: View-specific JavaScript modules

Usage:
    # Select buttons open dropdowns for entity selection
    FormSelect.select(widget, form_entity)
    DateSelect.select(widget, due_date)

    # Attributes for toggling entity features
    attrs = Attributes(form)
    attrs.select(defaults=["tasks", "document"], selected=["tasks"])

    # Submit buttons with loading spinner verification
    SpinnerButtons.CREATE.click(form)  # Verifies spinner appears
"""

from enum import Enum

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, expect

from .combobox import Select


class SelectButton:
    """
    Action buttons that open selection dropdowns.

    These buttons use data-action-type attributes and open combobox/select
    dropdowns for choosing related entities.

    Members:
        FORM_SELECT: Select a form to attach
        PROJECT_SELECT: Select a project
        DATE_SELECT: Open date picker
        USER_SELECT: Select a user
        FILE_SELECT: Select a file

    Usage:
        # Select an entity by name
        FormSelect.select(widget, form_entity)

        # Get the dropdown form for custom interaction
        date_form = DateSelect.form(widget)
    """

    CLEAR_BUTTON = "[data-role='clear']"
    CLEAR_ICON = "[data-icon='x']"

    _element = None
    _form = None

    def __init__(self, form):
        self._form = form
        self._element = form.locator(self.value)
        expect(self._element).to_be_visible()

    @property
    def button(self):
        return self._element

    def contains(self, resource):
        """
        Check if the select button contains the item.

        Args:
            element: Parent element containing the select button
            resource: Resource with .definition.name to check
        """
        expect(self._element).to_contain_text(resource.definition.name)
        return True

    def panel(self, fill=False):
        """
        Open the dropdown and return the combobox panel.

        Args:
            element: Parent element containing the select button
            fill: Value to fill the combobox input with
        """
        self._element.click()
        combobox = Select(self._element)
        if fill:
            combobox.fill(fill)
        return combobox.panel

    def select(self, item):
        """
        Open dropdown and select an item by its definition name.

        Args:
            element: Parent element containing the select button
            item: Entity with .definition.name to select
        """
        combobox = Select(self._element)
        combobox.select_by_name(item.definition.name)

        expect(self._element).to_contain_text(item.definition.name)

    def select_by_key(self, item):
        """Open dropdown and select an item by its persisted entity key."""
        combobox = Select(self._element)
        combobox.select_by_key(item.key)

        expect(self._element).to_contain_text(item.definition.name)

    def form(self):
        """
        Click button and return the opened dropdown form.

        Args:
            element: Parent element containing the select button

        Returns:
            Locator: The dropdown form element for custom interaction
        """
        self.button.click()

        form = self._form.locator(self.form_value)
        expect(form).to_be_visible()
        return form

    def clear(self):
        """
        Clear the selected item by clicking the 'x' button.

        When a select button has a value (preloaded or selected), it shows
        a clear button (data-role='clear') that removes the selection.

        Args:
            element: Parent element containing the select button

        See Also:
            src/script/elements/sectionToggle.mjs: select button behavior
        """
        expect(self._element).to_be_visible()
        clear_button = self._element.locator(self.CLEAR_BUTTON)
        expect(clear_button).to_be_visible()
        clear_button.click()
        expect(self._element).to_contain_text(self.default_text)


class FormSelect(SelectButton):
    value = '[data-role="form-select"]'
    default_text = "Form"


class ProjectSelect(SelectButton):
    value = '[data-role="project-select"]'
    default_text = "Project"


class DateSelect(SelectButton):
    value = '[data-action="schedule"]'
    default_text = "Schedule"
    form_value = '[data-role="date-form"]'


class UserSelect(SelectButton):
    value = '[data-role="user-select"]'
    default_text = "Assign"


class FileSelect(SelectButton):
    value = '[data-role="file-select"]'
    form_value = '[data-role="file-form"]'
    default_text = "File"


class Attributes:
    """
    Helper for entity attribute toggles.

    Attributes are features that can be enabled/disabled for entities
    (e.g., tasks, document, notes, files). The UI shows them as toggleable
    icons that can be clicked to enable/disable.

    Selectors:
        SECTION: Container for all attributes
        ATTRIBUTE: Individual attribute element
        ADD/REMOVE: Toggle action buttons (shown on hover)
        ICON/TEXT: Attribute display elements

    Usage:
        attrs = Attributes(create_form)
        # Deselect attributes not in the selected list
        attrs.select(
            defaults=["tasks", "document", "notes", "files"],
            selected=["tasks", "document"]
        )
    """

    SECTION = "[data-role='attributes']"
    ATTRIBUTE = "[data-role='attribute']"
    ADD = "[data-role='add']"
    REMOVE = "[data-role='remove']"
    ICON = "[data-role='icon']"
    TEXT = "[data-role='text']"

    def __init__(self, element):
        """
        Initialize Attributes helper.

        Args:
            element: Form or widget containing the attributes section
        """
        self.element = element
        self.section = element.locator(self.SECTION)
        expect(self.section).to_be_visible()

    def attribute(self, name):
        """
        Get locator for a specific attribute by name.

        Args:
            name: Attribute name (e.g., "tasks", "document")

        Returns:
            Locator: The attribute element
        """
        return self.section.locator(f"{self.ATTRIBUTE}[data-attribute='{name}']")

    def expect_selected(self, name, selected=True):
        """Verify an attribute's selected state."""
        expected = "true" if selected else "false"
        expect(self.attribute(name)).to_have_attribute("data-selected", expected)

    def set_selected(self, name, selected=True):
        """Toggle an attribute only when it is not already in the target state."""
        attr = self.attribute(name)
        expected = "true" if selected else "false"
        current = attr.get_attribute("data-selected")
        if current == expected:
            return

        attr.hover()
        action = self.ADD if selected else self.REMOVE
        expect(attr.locator(action)).to_be_visible()
        attr.click()
        self.expect_selected(name, selected)

    def select(self, defaults, selected):
        """
        Configure attributes by deselecting those not in selected list.

        Args:
            defaults: List of attribute names that are on by default
            selected: List of attribute names that should remain on
        """
        deselect = [a for a in defaults if a not in selected]
        for attribute_name in deselect:
            self.set_selected(attribute_name, False)


class SpinnerButtons(Enum):
    """
    Submit buttons that show loading spinners during submission.

    These buttons change text and show a spinner icon while the form
    is being submitted. The click() method verifies the spinner appears.

    Members:
        CREATE: "Create" → "Creating..." with spinner
        UPLOAD: "Upload" → "Uploading..." with spinner
        UPDATE: "Update" → "Updating..." with spinner

    Usage:
        SpinnerButtons.CREATE.click(form)  # Clicks and verifies spinner
    """

    CREATE = "button[type='submit']:has-text('Create')"
    UPLOAD = "button[type='submit']:has-text('Upload')"
    UPDATE = "button[type='submit']:has-text('Update')"
    UPDATE_SUCCESS = "button[type='submit']:has-text('Updated')"

    def busy(self):
        """Return the button text shown during loading."""
        if self.name == "CREATE":
            return "Creating"
        elif self.name == "UPLOAD":
            return "Uploading"
        elif self.name == "UPDATE":
            return "Updating"

    def click(self, element):
        """
        Click submit button and verify loading spinner appears.

        Args:
            element: Form or widget containing the submit button
        """
        submit_button = element.locator(self.value)
        expect(submit_button).to_be_visible()
        submit_button.click()
        busy_button = element.locator(f"button:has-text('{self.busy()}')")
        try:
            expect(busy_button).to_be_visible(timeout=1000)
            expect(busy_button.locator("[data-icon='spinner']")).to_be_visible()
        except (PlaywrightTimeoutError, AssertionError):
            if self != SpinnerButtons.UPDATE:
                raise
            assert SpinnerButtons.UPDATE_SUCCESS.successful(element)

    def successful(self, element):
        """
        Verify the submit button reached its durable successful message.

        The check icon deliberately fades out, so it is not a stable
        post-response assertion for fast or long-running suites.

        Args:
            element: Form or widget containing the submit button
        """
        successful_button = element.locator(self.value)
        expect(successful_button).to_be_visible()
        return True
