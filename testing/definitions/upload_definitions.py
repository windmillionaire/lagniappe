from dataclasses import dataclass
from enum import Enum
from typing import Optional

from playwright.sync_api import expect

from ..utility.test_file import TestFile


class UploadMethod(Enum):
    """How to trigger the file upload."""

    FILE_INPUT = "file_input"  # Set via hidden file input
    DRAG_DROP = "drag_drop"  # Drag and drop onto dropzone
    PASTE = "paste"  # Paste from clipboard


class UploadType(Enum):
    """Type of upload - affects processing behavior."""

    FILE = "file"  # Standard file upload
    IMAGE = "image"  # Image upload with resize/processing


@dataclass
class ProcessingOptions:
    """Options for file processing after upload."""

    extract: bool = False  # Extract text content
    search_text: bool = False  # Index extracted text for search
    summarize: bool = False  # Generate AI summary
    search_summary: bool = False  # Index summary for search

    def set(self, form):
        if self.extract:
            form.locator('[name="extract"]').check()

        if self.search_text:
            search_text_input = form.locator('[name="search-text"]')
            expect(search_text_input).to_be_visible()
            search_text_input.check()

        if self.summarize:
            form.locator('[name="summarize"]').check()

        if self.search_summary:
            search_summary_input = form.locator('[name="search-summary"]')
            expect(search_summary_input).to_be_visible()
            search_summary_input.check()


@dataclass
class UploadDefinition:
    """Definition for a file upload in tests.

    Attributes:
        file: TestFile object
        display_name: Optional custom display name (defaults to filename)
        processing: Processing options for the upload
        upload_type: Type of upload (file or image)
        method: How to trigger the upload (file_input, drag_drop, paste)
    """

    file: TestFile
    upload_type: UploadType
    display_name: Optional[str] = None
    processing: Optional[ProcessingOptions] = None
    method: Optional[UploadMethod] = None
    filename: Optional[str] = None
    rows: Optional[int] = None
    columns: Optional[int] = None
