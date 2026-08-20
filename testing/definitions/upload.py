from enum import Enum

from ..utility.test_file import TestFile

from .upload_definitions import (
    UploadDefinition,
    UploadMethod,
    UploadType,
)


def _ingress_csv(name, *, rows=2, columns=3):
    return UploadDefinition(
        file=TestFile(f"{name}.csv"),
        method=UploadMethod.FILE_INPUT,
        upload_type=UploadType.FILE,
        filename=name,
        rows=rows,
        columns=columns,
    )


class Uploads(Enum):
    """Predefined upload configurations for testing."""

    csv_file_input = UploadDefinition(
        file=TestFile("sample_data.csv"),
        method=UploadMethod.FILE_INPUT,
        upload_type=UploadType.FILE,
        filename="sample_data",
        rows=10,
        columns=7,
    )

    csv_drag_drop = UploadDefinition(
        file=TestFile("sample_data.csv"),
        method=UploadMethod.DRAG_DROP,
        upload_type=UploadType.FILE,
        filename="sample_data",
        rows=10,
        columns=7,
    )

    csv_paste = UploadDefinition(
        file=TestFile("sample_data.csv"),
        method=UploadMethod.PASTE,
        upload_type=UploadType.FILE,
    )

    ingress_pages_csv = UploadDefinition(
        file=TestFile("ingress_pages.csv"),
        method=UploadMethod.FILE_INPUT,
        upload_type=UploadType.FILE,
        filename="ingress_pages",
        rows=2,
        columns=3,
    )

    ingress_tasks_csv = UploadDefinition(
        file=TestFile("ingress_tasks.csv"),
        method=UploadMethod.FILE_INPUT,
        upload_type=UploadType.FILE,
        filename="ingress_tasks",
        rows=2,
        columns=3,
    )

    ingress_pages_status_csv = _ingress_csv("ingress_pages_status")
    ingress_pages_stages_csv = _ingress_csv("ingress_pages_stages")
    ingress_pages_import_csv = _ingress_csv("ingress_pages_import")
    ingress_pages_stage_nav_csv = _ingress_csv("ingress_pages_stage_nav")
    ingress_pages_error_csv = _ingress_csv("ingress_pages_error")
    ingress_pages_existing_csv = _ingress_csv("ingress_pages_existing")
    ingress_pages_ignored_csv = _ingress_csv("ingress_pages_ignored")
    ingress_tasks_stages_csv = _ingress_csv("ingress_tasks_stages")
    ingress_tasks_page_form_csv = _ingress_csv("ingress_tasks_page_form")

    plain_text_file = UploadDefinition(
        file=TestFile("sample_notes.txt"),
        method=UploadMethod.FILE_INPUT,
        upload_type=UploadType.FILE,
        filename="sample_notes",
    )

    pdf_file = UploadDefinition(
        file=TestFile("sample_document.pdf"),
        method=UploadMethod.FILE_INPUT,
        upload_type=UploadType.FILE,
        filename="sample_document",
    )

    pdf_two_page_file = UploadDefinition(
        file=TestFile("sample_two_page_document.pdf"),
        method=UploadMethod.FILE_INPUT,
        upload_type=UploadType.FILE,
        filename="sample_two_page_document",
    )

    editor_test_image = UploadDefinition(
        file=TestFile("editor_test_image.jpeg"),
        upload_type=UploadType.IMAGE,
        method=UploadMethod.FILE_INPUT,
    )

    def set(self, form):
        """Set all upload fields on the form.

        Args:
            form: Playwright Locator for the upload form element.

        This method:
            1. Sets the file using the configured upload method
            2. Sets the display name if specified
            3. Configures processing options (extract, summarize, etc.)
        """
        if self.value.method == UploadMethod.FILE_INPUT:
            # Find the file input within the form
            file_input = form.locator("input[type='file']")
            self.value.file.input(file_input)
        elif self.value.method == UploadMethod.DRAG_DROP:
            # Drop on the dropzone element
            dropzone = form.locator("[data-role='dropzone']")
            self.value.file.drop(dropzone)
        elif self.value.method == UploadMethod.PASTE:
            self.value.file.paste(form.page)

        if self.value.display_name:
            display_name_input = form.locator('[name="display-name"]')
            display_name_input.fill(self.value.display_name)

        if self.value.processing:
            self.value.processing.set(form)

    @property
    def definition(self):
        return self.value
