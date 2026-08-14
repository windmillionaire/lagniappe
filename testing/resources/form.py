"""
Helper for the Form entity.

Maps to:
- Entity: lagniappe/core/entities/form.py
- Routes: lagniappe/web/routes/forms/
- Templates: lagniappe/web/templates/forms/
- View: src/script/views/form.mjs
"""

import re
import json

from playwright.sync_api import expect

from lagniappe.core.entities import Entities
from testing.elements import Select
from .core import SiteResource


class Builder:
    PREVIEW_PANEL = "#preview-panel"
    DEFAULT_PANEL = "#default-panel"
    MODEL_PANEL = "#model-panel"
    CONDITION_PANEL = "#condition-panel"
    SETTINGS_PANEL = "#settings-panel"

    FORM_NAME = "#form-name-display"
    COMPONENTS_COLUMN = "#components-column"
    READONLY_NOTICE = "[data-role='readonly-notice']"

    SAVE_BUTTON = "[data-role='save-form']"
    UNSAVED = "[data-role='save-form'][data-kind='unsaved']"
    SAVED = "[data-role='save-form'][data-kind='saved']"

    ADD_BUTTON = "button[data-role='add']"
    PREVIEW_TOGGLE = "#preview-toggle"
    RESTRICT_ACCESS = "[data-role='restrict-access']"
    SPECIFIC_ACCESS_OWNER = "input[data-role='specific-access'][name='owner']"
    RESTRICT_GROUP_INPUT = "[data-role='restrict-group-input']"
    RESTRICTED_GROUP_LIST = "li"
    SCHEMA_INPUT = "input[name='schema']"

    def __init__(self, user):
        self.page = user.page
        self.preview = self.page.locator(self.PREVIEW_PANEL)
        self.default = self.page.locator(self.DEFAULT_PANEL)
        self.model = self.page.locator(self.MODEL_PANEL)
        self.condition = self.page.locator(self.CONDITION_PANEL)
        self.settings = self.page.locator(self.SETTINGS_PANEL)
        self.components = self.page.locator(self.COMPONENTS_COLUMN)

    @property
    def schema(self):
        value = self.page.locator(self.SCHEMA_INPUT).input_value()
        return json.loads(value or "[]")

    def schema_field(self, field_id=None, *, field_type=None, title=None):
        for field in self.schema:
            if field_id:
                if field.get("id") == field_id:
                    return field
                continue
            if field_type and field.get("type") != field_type:
                continue
            if title and field.get("title") != title:
                continue
            return field
        return None

    def select_field(self, field):
        field.locate(self.default if field.id in ["name", "description"] else self.model)
        field.select()
        expect(field.element).to_have_attribute("data-selected", "true")
        return field.element

    def add_field(self, field):
        if field.id in ["name", "description"]:
            field.element = self.default.locator(f"[id='{field.id}']")
        else:
            elements = self.model.locator(".form-element")
            element_count = elements.count()
            component = self.components.locator(field.component)
            component.hover()
            add_button = component.locator(self.ADD_BUTTON)
            expect(add_button).to_be_visible()
            add_button.click()
            expect(elements).to_have_count(element_count + 1)
            field.element = elements.last

        field.select()
        expect(field.element).to_have_attribute("data-selected", "true")
        field.configure(self)
        return field.element

    def open_condition(self, setting, role="add"):
        self.settings.locator(f"[data-setting='{setting}'] [data-role='{role}']").click()
        expect(self.condition).to_be_visible()
        return self.condition

    def save_condition(self):
        self.condition.locator("button[data-role='save']").click()
        expect(
            self.condition.locator("[data-role='title'] [data-kind='success']")
        ).to_be_visible()

    def toggle_preview(self):
        self.page.locator(self.PREVIEW_TOGGLE).click()
        # preview_panel = self.page.locator(self.PREVIEW_PANEL)
        expect(self.preview).to_be_visible()
        expect(self.preview).to_have_attribute("rendered", "")
        return self.preview

    def restrictions(self):
        restrictions = self.page.locator(self.RESTRICT_ACCESS)
        expect(restrictions).to_be_visible()
        return restrictions

    def restrict_to_group(self, group):
        restrictions = self.restrictions()
        group_list = restrictions.locator(Builder.RESTRICTED_GROUP_LIST)
        if group.definition.name in restrictions.inner_text():
            return

        group_input = restrictions.locator(self.RESTRICT_GROUP_INPUT)
        expect(group_input).to_be_visible()
        expect(group_input).to_have_attribute("data-combobox-id", re.compile(".+"))
        with self.page.expect_response("**/restrictions"):
            Select(group_input).select_by_key(
                group.key,
                query=group.definition.name,
            )

        expect(group_list.filter(has_text=group.definition.name)).to_be_visible()
        return restrictions

    def restrict_to_owner(self):
        restrictions = self.restrictions()
        owner_checkbox = restrictions.locator(Builder.SPECIFIC_ACCESS_OWNER)
        if owner_checkbox.is_checked():
            return

        with self.page.expect_response("**/restrictions"):
            owner_checkbox.check()

        expect(owner_checkbox).to_be_checked()
        return restrictions

    def save(self):
        with self.page.expect_response("**/update"):
            self.page.locator(self.SAVE_BUTTON).click()
        expect(self.page.locator(self.SAVED)).to_be_visible()


class Form(SiteResource):
    _initialize = True
    _sync = False

    COMPONENTS_COLUMN = "#components-column"

    SAVE_BUTTON = "#save-toggle"
    SCHEMA_INPUT = "input[name='schema']"

    def _serialize_schema(self, schema=None):
        schema = self.definition.schema or schema
        if not schema:
            return None

        if hasattr(schema, "to_dict"):
            return schema.to_dict()

        return [field.to_dict() for field in schema]

    def create(self):
        """
        Create form entity programmatically.

        Uses the same Entities.FORM.create() path as the route handler
        in lagniappe/web/routes/forms/main.py.
        """
        assert self.definition, "Definition is required to create a form"

        data = {
            "name": self.definition.name,
            "form-type": self.definition.form_type,
        }

        schema = self._serialize_schema()
        if schema:
            data["schema"] = schema

        entity = Entities.FORM.create(data)
        entity.save()
        self.entity = entity
        return self

    @property
    def url_suffix(self):
        return f"forms/{self.key}"

    @property
    def builder(self):
        # super().wait_for_load()
        self.user.go(self)

        return Builder(self.user)
