from dataclasses import dataclass, field
from enum import Enum
import random
import string

from playwright.sync_api import Locator, expect

from ..elements.combobox import Select
from lagniappe.core.definitions.identifiers import short_uuid


@dataclass
class SchemaField:
    type: str
    component: str
    _id: str = None
    title: str = None
    required: bool = False
    placeholder: str = ""
    visibility: list[dict] = field(default_factory=list)
    _element: Locator = None

    @property
    def id(self):
        if not self._id:
            suffix = "".join(
                random.choices(string.ascii_lowercase + string.digits, k=4)
            )
            self._id = f"{self.type.lower()}-{suffix}"
        return self._id

    @id.setter
    def id(self, value: str):
        self._id = value

    def to_dict(self):
        base = {
            "id": self.id,
            "type": self.type,
            "title": self.title,
        }
        if self.placeholder:
            base["placeholder"] = self.placeholder
        if self.required:
            base["required"] = True
        if self.visibility:
            base["visibility"] = self.visibility
        return base

    @classmethod
    def from_dict(cls, data: dict) -> "SchemaField":
        """Create a SchemaField subclass instance from a JSON schema dict."""
        field_type = data["type"]
        common = {
            "_id": data.get("id"),
            "title": data.get("title"),
            "required": data.get("required", False),
            "placeholder": data.get("placeholder", ""),
            "visibility": data.get("visibility", []),
        }

        if field_type == "input":
            input_map = {
                "text": TextInputField,
                "tel": PhoneInputField,
                "number": NumberInputField,
                "email": EmailInputField,
                "date": DateInputField,
                "time": TimeInputField,
            }
            input_type = data.get("input", "text")
            field_cls = input_map.get(input_type)
            if not field_cls:
                raise ValueError(f"Unknown input type: {input_type}")
            return field_cls(**common)

        type_map = {
            "textarea": TextareaField,
            "checkbox": CheckboxField,
            "radio": RadioField,
            "select": SelectField,
            "table": TableField,
            "link": LinkField,
            "location": LocationField,
            "signature": SignatureField,
            "html": HtmlField,
            "status": StatusField,
            "bookmark": BookmarkField,
        }

        field_cls = type_map.get(field_type)
        if not field_cls:
            raise ValueError(f"Unknown field type: {field_type}")

        if field_type == "checkbox":
            common["checked"] = data.get("checked", False)
        elif field_type in ("radio", "select"):
            common["options"] = data.get("options", [])
            if field_type == "select":
                common["multiple"] = data.get("multiple", False)
        elif field_type == "table":
            common["columns"] = [cls.from_dict(col) for col in data.get("columns", [])]
        elif field_type == "link":
            common["location"] = data.get("location")
        elif field_type == "status":
            common["status"] = data.get("status", [])

        return field_cls(**common)

    @property
    def element(self):
        assert self._element, "Element is not set"
        return self._element

    @element.setter
    def element(self, value: Locator):
        self.id = value.get_attribute("id")
        self._element = value

    def select(self):
        self.element.click()

    def locate(self, panel: Locator):
        self.element = panel.locator(f"[id^='{self.id}']")
        return self.element

    def configure(self, builder):
        assert self.title, "Field title is required"

        self._set_title(builder)
        if self.required:
            builder.settings.locator("input[name='required']").check()
        if self.placeholder:
            self._set_placeholder(builder)

    def _set_title(self, builder):
        title_input = builder.settings.locator("input[name='title']")
        expect(title_input).to_be_visible()
        title_input.click()
        title_input.press("Control+A")
        title_input.press_sequentially(self.title)
        expect(title_input).to_have_value(self.title)
        expect(self.element).to_contain_text(self.title)

    def _set_placeholder(self, builder):
        placeholder_input = builder.settings.locator("input[name='placeholder']")
        expect(placeholder_input).to_be_visible()
        placeholder_input.click()
        placeholder_input.press("Control+A")
        placeholder_input.press_sequentially(self.placeholder)
        expect(
            self.element.locator(
                f'[data-placeholder^="{self.placeholder}"], [placeholder^="{self.placeholder}"]'
            )
        ).to_be_visible()


@dataclass
class LinkField(SchemaField):
    type: str = "link"
    component: str = "[data-type='link']"
    location: str = None
    column_type: str = "External Link"

    def to_dict(self):
        base = super().to_dict()
        if self.location:
            base["location"] = self.location
        return base

    def configure(self, builder):
        assert self.location, "Location is required"

        super().configure(builder)
        self._set_location(builder)

    def _set_location(self, builder):
        builder.settings.locator(f"[type='radio'][value='{self.location}']").check()

        if self.location == "out":
            expect(self.element.locator("[data-icon='out']")).to_be_visible()
        elif self.location == "in":
            expect(self.element.locator("[data-icon='in']")).to_be_visible()


@dataclass
class LocationField(SchemaField):
    type: str = "location"
    component: str = "[data-type='location']"


@dataclass
class TextareaField(SchemaField):
    type: str = "textarea"
    component: str = "[data-type='textarea']"


@dataclass
class BookmarkField(SchemaField):
    type: str = "bookmark"
    component: str = "[data-type='bookmark']"


@dataclass
class CheckboxField(SchemaField):
    checked: bool = False
    type: str = "checkbox"
    component: str = "[data-type='checkbox']"
    column_type: str = "Checkbox"

    def to_dict(self):
        base = super().to_dict()
        if self.checked:
            base["checked"] = True
        return base

    def configure(self, builder):
        super().configure(builder)

        if self.checked:
            builder.settings.locator("input[name='checked']").check()
            expect(self.element.locator("input[type='checkbox']")).to_be_checked()


@dataclass
class OptionField(SchemaField):
    options: list = field(default_factory=list)

    @staticmethod
    def _option_label(opt):
        return opt["label"] if isinstance(opt, dict) else opt

    def to_dict(self):
        base = super().to_dict()
        if self.options:
            base["options"] = [
                opt
                if isinstance(opt, dict)
                else {"label": opt, "value": f"o{short_uuid()}"}
                for opt in self.options
            ]
        return base

    def configure(self, builder):
        super().configure(builder)
        if self.options:
            self._set_options(builder)

    def _set_options(self, builder):
        options = builder.settings.locator("[data-setting='options']")
        options.locator("[data-role='add']").click()
        expect(builder.condition).to_be_visible()

        for option in self.options:
            label = self._option_label(option)
            builder.condition.locator("input[name='option-name']").fill(label)
            builder.condition.locator("button:has-text('Add Option')").click()
            if self.type == "radio":
                expect(self.element).to_contain_text(label)
            expect(options).to_contain_text(label)

        builder.condition.locator("[data-role='close']").click()
        expect(builder.condition).not_to_be_visible()


@dataclass
class RadioField(OptionField):
    type: str = "radio"
    component: str = "[data-type='radio']"


@dataclass
class SelectField(OptionField):
    type: str = "select"
    component: str = "[data-type='select']"
    multiple: bool = False

    def to_dict(self):
        base = super().to_dict()
        if self.multiple:
            base["multiple"] = True
        return base

    def configure(self, builder):
        super().configure(builder)
        if self.multiple:
            builder.settings.locator("input[name='multiple']").check()


@dataclass
class TableField(SchemaField):
    type: str = "table"
    component: str = "[data-type='table']"
    columns: dict = field(default_factory=dict)

    def to_dict(self):
        base = super().to_dict()
        if self.columns:
            base["columns"] = [column.to_dict() for column in self.columns]
        return base

    def configure(self, builder):
        super().configure(builder)
        if self.columns:
            self._set_columns(builder)

    def _set_columns(self, builder):
        columns = builder.settings.locator("[data-setting='columns']")
        columns.locator("[data-role='add']").click()
        expect(builder.condition).to_be_visible()

        for column_definition in self.columns:
            type_select = Select(
                builder.condition.locator("[data-combobox-id]"),
            )
            type_select.select_by_name(column_definition.column_type)

            name_input = builder.condition.locator("input[name='column-name']")
            name_input.fill(column_definition.title)

            builder.condition.locator("button:has-text('Add Column')").click()
            expect(builder.settings).to_contain_text(column_definition.title)
            expect(self.element).to_contain_text(column_definition.title)

        builder.condition.locator("[data-role='close']").click()
        expect(builder.condition).not_to_be_visible()


@dataclass
class SignatureField(SchemaField):
    type: str = "signature"
    component: str = "[data-type='signature']"


@dataclass
class HtmlField(SchemaField):
    type: str = "html"
    component: str = "[data-type='html']"

    def configure(self, builder):
        super().configure(builder)
        self._set_html(builder)

    def _set_html(self, builder):
        builder.settings.locator("[data-setting='html'] [data-role='edit']").click()


@dataclass
class StatusField(SchemaField):
    type: str = "status"
    component: str = "[data-type='status']"
    status: list = field(default_factory=list)

    def to_dict(self):
        base = super().to_dict()
        if self.status:
            base["status"] = self.status
        return base


@dataclass
class InputField(SchemaField):
    type: str = "input"
    component: str = '[data-type="input"]'
    input: str = None
    icon: str = None

    def to_dict(self):
        base = super().to_dict()
        if self.input:
            base["input"] = self.input
        return base

    def configure(self, builder):
        assert self.input, "Input type is required"

        super().configure(builder)
        self._set_input(builder)

    def _set_input(self, builder):
        builder.settings.locator(f"[type='radio'][value='{self.input}']").check()

        expect(self.element.locator(f"[data-icon='{self.icon}']")).to_be_visible()


@dataclass
class TextInputField(InputField):
    input: str = "text"
    icon: str = "text"
    column_type: str = "Text"


@dataclass
class PhoneInputField(InputField):
    input: str = "tel"
    icon: str = "tel"
    column_type: str = "Phone Number"


@dataclass
class NumberInputField(InputField):
    input: str = "number"
    icon: str = "number"
    column_type: str = "Number"


@dataclass
class EmailInputField(InputField):
    input: str = "email"
    icon: str = "email"
    column_type: str = "Email"


@dataclass
class DateInputField(InputField):
    input: str = "date"
    icon: str = "date"
    column_type: str = "Date"


@dataclass
class TimeInputField(InputField):
    input: str = "time"
    icon: str = "time"
    column_type: str = "Time"


class SchemaFields(Enum):
    TEXT_INPUT = TextInputField
    PHONE_INPUT = PhoneInputField
    NUMBER_INPUT = NumberInputField
    EMAIL_INPUT = EmailInputField
    DATE_INPUT = DateInputField
    TIME_INPUT = TimeInputField
    TEXTAREA = TextareaField
    CHECKBOX = CheckboxField
    RADIO = RadioField
    SELECT = SelectField
    TABLE = TableField
    LINK = LinkField
    LOCATION = LocationField
    SIGNATURE = SignatureField
    HTML = HtmlField
    STATUS = StatusField
    BOOKMARK = BookmarkField

    def get(self, **kwargs):
        return self.value(**kwargs)


class CommonFormFields(Enum):
    INPUT = InputField.component
    LINK = LinkField.component
    LOCATION = LocationField.component
    TEXTAREA = TextareaField.component
    CHECKBOX = CheckboxField.component
    RADIO = RadioField.component
    SELECT = SelectField.component
    TABLE = TableField.component


class PageFormFields(Enum):
    BOOKMARK = BookmarkField.component


class TaskFormFields(Enum):
    SIGNATURE = SignatureField.component
    HTML = HtmlField.component
