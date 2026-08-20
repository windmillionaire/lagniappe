from playwright.sync_api import expect

from .combobox import Select


class IngressWizard:
    WIDGET = "[data-widget='ImportData']"
    INGRESS_TOGGLE_DESKTOP = "[data-nav='tabs'] button[lp-show='ingress:active']"
    STAGE = "[data-role='stage']"
    PROGRESS = "[data-role='progress']"
    STAGE_BUTTON = "button[data-role='set-stage']"
    NEXT_BUTTON = "button[data-role='next']"
    IMPORT_BUTTON = "button[data-role='import']"
    STOP_BUTTON = "button[data-role='stop']"
    ACTIVE_PROCESS = "[data-process][data-visible='true']"
    ERROR = "[data-role='error']"

    ROW_TYPE_PAGE = "input[name='entity-type'][value='page']"
    ROW_TYPE_TASK = "input[name='entity-type'][value='task']"
    CREATE_PARENT = "[data-option='create-parent']"
    EXISTING_PARENT = "[data-option='existing-parent']"
    USE_COLUMNS_FORM = "[data-option='use-columns']"
    EXISTING_FORM = "[data-option='existing-form']"
    ASSIGN_COLUMNS_TABLE = "[data-section='assign-columns']"
    PAGE_FORM_INDEX = "[data-section='page-form-index']"
    COMPLETED_RESULTS = "[data-role='completed']"

    def __init__(self, container):
        self.container = container
        self.page = container.page

    @classmethod
    def open(cls, user):
        toggle = user.locate(cls.INGRESS_TOGGLE_DESKTOP)
        if toggle.count():
            toggle.click()

        container = user.locate(cls.WIDGET)
        expect(container).to_be_visible()
        wizard = cls(container)
        expect(wizard.stage).to_contain_text("Verify Columns")
        return wizard

    @property
    def stage(self):
        return self.container.locator(self.STAGE)

    @property
    def progress(self):
        return self.container.locator(self.PROGRESS)

    @property
    def active_process(self):
        process = self.stage.locator(self.ACTIVE_PROCESS)
        expect(process).to_be_visible()
        return process

    def process(self, stage_name):
        return self.stage.locator(f"[data-process='{stage_name}']")

    def stage_button(self, stage_name):
        return self.stage.locator(
            f"{self.STAGE_BUTTON}[data-stage='{stage_name}']"
        )

    def expect_stage(self, stage_name, title=None):
        if title:
            expect(self.progress).to_contain_text(title)
        process = self.process(stage_name)
        expect(process).to_be_visible()
        return self

    def section(self, name):
        return self.progress.locator(f"[data-section='{name}']")

    def continue_stage(self, next_stage=None, title=None):
        button = self.active_process.locator(self.NEXT_BUTTON)
        expect(button).to_be_visible()
        with self.page.expect_response("**/next"):
            button.click()
        if next_stage:
            self.expect_stage(next_stage, title)

    def set_stage(self, stage_name, title=None):
        button = self.stage_button(stage_name)
        expect(button).to_be_visible()
        with self.page.expect_response("**/stage"):
            button.click()
        self.expect_stage(stage_name, title)

    def choose_row_type(self, entity_type):
        selector = self.ROW_TYPE_TASK if entity_type == "task" else self.ROW_TYPE_PAGE
        input = self.progress.locator(selector)
        expect(input).to_be_visible()
        with self.page.expect_response("**/update"):
            input.check()

    def choose_parent_mode(self, mode):
        option = self.progress.locator(
            f"input[name='parent-choice'][value='{mode}']"
        )
        expect(option).to_be_visible()
        with self.page.expect_response("**/update"):
            option.check()

    def fill_parent_name(self, name):
        input = self.progress.locator("input[name='parent-name']")
        expect(input).to_be_visible()
        input.fill(name)

    def select_existing_parent(self, name):
        with self.page.expect_response("**/update"):
            Select(self.progress.locator(self.EXISTING_PARENT)).select_by_name(name)

    def fill_model_name(self, name):
        input = self.progress.locator("input[name='model-name']")
        expect(input).to_be_visible()
        input.fill(name)

    def choose_form_mode(self, mode):
        option = self.progress.locator(f"input[name='form-choice'][value='{mode}']")
        expect(option).to_be_visible()
        with self.page.expect_response("**/update"):
            option.check()

    def fill_form_name(self, name):
        input = self.progress.locator("input[name='form-name']")
        expect(input).to_be_visible()
        input.fill(name)

    def select_existing_form(self, name):
        with self.page.expect_response("**/update"):
            Select(self.progress.locator(self.EXISTING_FORM)).select_by_name(name)

    def column_row(self, column_label):
        row = self.progress.get_by_role("row", name=column_label, exact=True)
        expect(row).to_be_visible()
        return row

    def select_column_field(self, column_label, field_name):
        row = self.column_row(column_label)
        Select(row.locator("[lp-select]")).select_by_name(field_name)

    def ignore_column(self, column_label):
        row = self.column_row(column_label)
        checkbox = row.locator("input[type='checkbox']")
        expect(checkbox).to_be_visible()
        with self.page.expect_response("**/update"):
            checkbox.check()

    def choose_page_index_mode(self, mode):
        option = self.progress.locator(
            f"input[name='index-field-choice'][value='{mode}']"
        )
        expect(option).to_be_visible()
        with self.page.expect_response("**/update"):
            option.check()

    def select_page_index_form(self, name):
        with self.page.expect_response("**/get-page-form*"):
            Select(self.progress.locator("[data-option='page-form']")).select_by_name(
                name
            )
        selected_form = self.progress.locator(
            "[data-option='page-form'] input[role='combobox']"
        )
        expect(selected_form).to_have_attribute("placeholder", name)

    def select_index_source(self, name):
        with self.page.expect_response("**/update"):
            Select(self.progress.locator("[data-role='index-from']")).select_by_name(
                name
            )

    def select_index_destination(self, name):
        with self.page.expect_response("**/update"):
            Select(self.progress.locator("[data-role='index-to']")).select_by_name(
                name
            )

    def start_import(self):
        button = self.active_process.locator(self.IMPORT_BUTTON)
        expect(button).to_be_visible()
        with self.page.expect_response("**/import"):
            button.click()
        expect(self.progress).to_contain_text("Import Complete")
