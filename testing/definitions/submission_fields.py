from dataclasses import dataclass
from enum import Enum
from typing import Any
from datetime import datetime
from playwright.sync_api import Locator, expect

from ..elements.combobox import Select
from .schema_fields import SchemaField


def format_date(value):
    return datetime.strptime(value, "%Y-%m-%d").strftime("%b %d, %Y")


def format_time(value):
    return datetime.strptime(value, "%H:%M").strftime("%I:%M %p").lstrip("0")


def format_phone(value):
    if not value:
        return ""

    digits = "".join(filter(str.isdigit, value))

    if len(digits) == 10:  # Standard US number
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits.startswith("1"):  # US number with country code
        return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"

    return value


def format_number(value):
    if not value:
        return ""

    if isinstance(value, int):
        return f"{value:.0f}"
    elif isinstance(value, float):
        return f"{value:.2f}"
    else:
        return str(value)


@dataclass
class SubmissionField:
    id: str = None
    element: Locator = None
    submission_value: Any = None
    field: SchemaField = None

    def get_element(self, form: Locator):
        return form.locator(f"[id^='{self.id}'].form-element")

    def set_submission_value(self, form: Locator):
        self.element = self.get_element(form)
        expect(self.element).to_be_visible()
        self.value = self.submission_value

    def verify_submission_value(self, form: Locator):
        self.element = self.get_element(form)
        expect(self.element).to_be_visible()
        expect(self.element).to_contain_text(str(self.submission_value))
        return True

    @property
    def label(self):
        return self.element.locator("[data-role='label']")

    @property
    def read(self):
        return self.element.locator("[data-role='read']")

    def _switch_to_edit(self):
        if self.read.is_visible():
            self.label.click()
            expect(self.read).not_to_be_visible()


class SubmissionInputField(SubmissionField):
    @property
    def value(self):
        return self.element.locator("input").input_value()

    @value.setter
    def value(self, value):
        self._switch_to_edit()
        field = self.element.locator("input")
        field.fill(str(value))
        expect(field).to_have_value(str(value))

    def verify_submission_value(self, form: Locator):
        self.element = self.get_element(form)
        expect(self.element).to_be_visible()
        if self.field and self.field.input == "date":
            expect(self.element).to_contain_text(format_date(self.submission_value))
        elif self.field and self.field.input == "time":
            expect(self.element).to_contain_text(format_time(self.submission_value))
        elif self.field and self.field.input == "tel":
            expect(self.element).to_contain_text(format_phone(self.submission_value))
        elif self.field and self.field.input == "number":
            expect(self.element).to_contain_text(format_number(self.submission_value))
        elif self.element.locator("input").count() > 0:
            expect(self.element.locator("input")).to_have_value(
                str(self.submission_value)
            )
        else:
            expect(self.element).to_contain_text(str(self.submission_value))
        return True


class SubmissionTextarea(SubmissionField):
    @property
    def value(self):
        return self.element.locator("textarea").input_value()

    @value.setter
    def value(self, value):
        self._switch_to_edit()
        field = self.element.locator("textarea")
        field.fill(str(value))
        expect(field).to_have_value(str(value))


class SubmissionCheckbox(SubmissionField):
    @property
    def value(self):
        return self.element.locator("input[type='checkbox']").is_checked()

    @value.setter
    def value(self, value):
        checkbox = self.element.locator("input[type='checkbox']")
        if value:
            checkbox.check()
        else:
            checkbox.uncheck()

    def verify_submission_value(self, form: Locator):
        self.element = self.get_element(form)
        expect(self.element).to_be_visible()
        checkbox = self.element.locator("input[type='checkbox']")
        if self.submission_value:
            expect(checkbox).to_be_checked()
        else:
            expect(checkbox).not_to_be_checked()
        return True


class SubmissionRadio(SubmissionField):
    @property
    def value(self):
        return self.element.locator("input[type='radio']:checked").get_attribute(
            "value"
        )

    @value.setter
    def value(self, value):
        self.element.locator(f"label:has-text('{value}')").click()

    def verify_submission_value(self, form: Locator):
        self.element = self.get_element(form)
        expect(self.element).to_be_visible()
        radio = self.element.locator("input[type='radio']:checked")
        label = radio.locator("xpath=ancestor::label[1]")
        expect(label).to_contain_text(self.submission_value)
        return True


class SubmissionSelect(SubmissionField):
    @property
    def value(self):
        return self.element.locator("[data-combobox-id]").inner_text()

    @value.setter
    def value(self, value):
        select = Select(self.element)
        if isinstance(value, list):
            panel = select.open()
            for v in value:
                option = panel.locator(f"[role='option']:has-text('{v}')")
                expect(option).to_be_visible()
                option.click()
            select.blur()
        else:
            select.select_by_name(value)

    def verify_submission_value(self, form: Locator):
        self.element = self.get_element(form)
        expect(self.element).to_be_visible()
        if isinstance(self.submission_value, list):
            for v in self.submission_value:
                expect(self.element).to_contain_text(v)
        else:
            expect(self.element).to_contain_text(self.submission_value)
        return True


class SubmissionTable(SubmissionField):
    pass


class SubmissionLink(SubmissionField):
    @property
    def value(self):
        url = self.element.locator("input[type='url']").input_value()
        title = self.element.locator("input[type='text']").input_value()
        return {"url": url, "title": title}

    @value.setter
    def value(self, value):
        url = self.element.locator("input[type='url']")
        title = self.element.locator("input[type='text']")
        url.fill(value["url"])
        title.fill(value["title"])
        expect(url).to_have_value(value["url"])
        expect(title).to_have_value(value["title"])

    def verify_submission_value(self, form: Locator):
        self.element = self.get_element(form)
        expect(self.element).to_be_visible()
        link = self.element.locator("a").filter(has_text=self.submission_value["title"])
        expect(link).to_be_visible()
        expect(link).to_have_attribute("href", self.submission_value["url"])
        return True


class SubmissionBookmark(SubmissionField):
    @property
    def value(self):
        url = self.element.locator("input[type='url']").input_value()
        title = self.element.locator("input[type='text']").input_value()
        return {"url": url, "title": title}

    @value.setter
    def value(self, value):
        self.element.locator("input[type='url']").fill(value["url"])
        self.element.locator("input[type='text']").fill(value["title"])

    def set_submission_value(self, form: Locator):
        self.element = self.get_element(form)
        expect(self.element).to_be_visible()
        self.value = self.submission_value

        if "choices" in self.submission_value:
            choices = self.element.locator("[data-element='choices'] label").all()
            for choice, setting in zip(choices, self.submission_value["choices"]):
                if not setting:
                    choice.click()


class SubmissionLocation(SubmissionField):
    def set_submission_value(self, form: Locator):
        self.element = self.get_element(form)
        expect(self.element).to_be_visible()

        value = self.submission_value
        if isinstance(value, dict):
            query = value.get("query") or value.get("address") or value.get("name")
            address2 = value.get("address2")
        else:
            query = value
            address2 = None

        select = Select(self.element)
        select.input.click()
        expect(select.input).to_be_focused()
        select.input.fill(query)
        select.panel.locator("[role='option']").first.click()

        if address2:
            self.element.locator("input[aria-label='Apt, suite, unit']").fill(address2)

        select.blur()

    def verify_submission_value(self, form: Locator):
        self.element = self.get_element(form)
        expect(self.element).to_be_visible()

        if isinstance(self.submission_value, dict):
            expected = (
                self.submission_value.get("name")
                or self.submission_value.get("address")
                or self.submission_value.get("query")
            )
            address2 = self.submission_value.get("address2")
        else:
            expected = self.submission_value
            address2 = None

        expect(self.element).to_contain_text(expected)
        if address2:
            expect(self.element).to_contain_text(address2)
        return True


class SubmissionSignature(SubmissionField):
    pass


class SubmissionFields(Enum):
    INPUT = SubmissionInputField
    TEXTAREA = SubmissionTextarea
    CHECKBOX = SubmissionCheckbox
    RADIO = SubmissionRadio
    SELECT = SubmissionSelect
    TABLE = SubmissionTable
    LINK = SubmissionLink
    BOOKMARK = SubmissionBookmark
    LOCATION = SubmissionLocation
    SIGNATURE = SubmissionSignature

    def get(self, field: SchemaField | str, value: Any = None, **kwargs):
        submission_value = kwargs.pop("submission_value", value)
        assert not kwargs, f"Unexpected arguments: {', '.join(kwargs)}"

        if isinstance(field, str):
            return self.value(id=field, submission_value=submission_value)

        assert field.id, "Field ID is required"
        return self.value(
            id=field.id,
            submission_value=submission_value,
            field=field,
        )
