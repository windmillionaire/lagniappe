from playwright.sync_api import expect

from .combobox import Select
from .forms_common import SpinnerButtons


class PermissionsForm:
    """
    Form for managing user permissions.
    """

    PAGE_SELECT = "[data-section='pages'] [data-combobox-id='pages']"
    PAGE_SECTION = "[data-section='pages']"
    CATEGORY_SELECT = "[data-section='categories'] [data-combobox-id='categories']"
    CATEGORY_SECTION = "[data-section='categories']"
    PROJECT_SELECT = "[data-section='projects'] [data-combobox-id='projects']"
    PROJECT_SECTION = "[data-section='projects']"
    GROUP_SELECT = "[data-section='groups'] [data-combobox-id='groups']"
    GROUP_SECTION = "[data-section='groups']"

    def __init__(self, user, group=None, form=None):
        self.form = (
            form if form is not None else user.locate(f"form[data-key='{group.key}']")
        )
        expect(self.form).to_be_visible()
        expect(self.form).to_have_attribute("rendered", "")
        self.group = group
        self.user = user

    def section(self, kind):
        return getattr(self, f"{kind.upper()}_SECTION")

    def select(self, kind):
        return getattr(self, f"{kind.upper()}_SELECT")

    def level_selector(self, kind, name, level):
        return f"{self.section(kind)} li:has-text('{name} input[value='{level}']')"

    def specific_permission_rows(self, resource):
        return self.form.locator(f"{self.section(resource.entity.kind)} li")

    def set(self, resource, level):
        from lagniappe.core.definitions import General, Site
        from testing.definitions import Categories, Groups, Pages, Projects

        if isinstance(resource, (General, Site)):
            self.form.locator(
                f"[data-section='{resource.value}'] input[value='{level.value}']"
            ).check()
        elif isinstance(resource, (Pages, Categories, Projects, Groups)):
            kind = resource.entity.kind

            select = Select(self.form.locator(self.select(kind)))
            select.select_by_name(resource.definition.name)
            rows = self.specific_permission_rows(resource)
            expect(rows).to_have_count(1)
            expect(rows).to_contain_text(resource.definition.name)
            expect(rows).to_have_css("flex-direction", "row")
            expect(rows).to_have_css("flex-wrap", "wrap")
            expect(rows.locator("fieldset")).to_have_css("flex-wrap", "wrap")
            self.form.locator(
                self.level_selector(kind, resource.definition.name, level.value)
            ).check()

    def verify(self, resource, level):
        from lagniappe.core.definitions import General, Site
        from testing.definitions import Categories, Groups, Pages, Projects

        if isinstance(resource, (General, Site)):
            expect(
                self.form.locator(
                    f"[data-section='{resource.value}'] input[value='{level.value}']"
                )
            ).to_be_checked()
        elif isinstance(resource, (Pages, Categories, Projects, Groups)):
            kind = resource.entity.kind

            expect(
                self.form.locator(
                    self.level_selector(kind, resource.definition.name, level.value)
                )
            ).to_be_checked()

    def submit(self):
        route = self.form.get_attribute("data-route") or "/group-permissions/"
        with self.user.page.expect_response(f"**{route}"):
            SpinnerButtons.UPDATE.click(self.form)
            assert SpinnerButtons.UPDATE_SUCCESS.successful(self.form)
