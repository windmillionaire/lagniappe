"""File processing utilities: validation, text extraction, and MIME handling."""

from .ranges import ByteRange, UnsatisfiableByteRange, parse_byte_range
from .utility import determine_encoding, determine_mimetype, htmlize
from .validate import create_schema, process_csv
from .extract import get_file_text, ocr_file, start_file_extraction
from .find_page import find_page
from .ooxml import extract_ooxml_text, is_supported_ooxml
from .constants import (
    DOCUMENT_AI_MIMETYPES,
    IMAGE_MIMETYPES,
    PREVIEW_MIMETYPES,
    TEXT_MIMETYPES,
    CODE_MIMETYPES,
    ENCODINGS,
)

__all__ = [
    "determine_encoding",
    "determine_mimetype",
    "ByteRange",
    "UnsatisfiableByteRange",
    "parse_byte_range",
    "get_file_text",
    "start_file_extraction",
    "ocr_file",
    "DOCUMENT_AI_MIMETYPES",
    "IMAGE_MIMETYPES",
    "PREVIEW_MIMETYPES",
    "TEXT_MIMETYPES",
    "CODE_MIMETYPES",
    "ENCODINGS",
    "create_schema",
    "process_csv",
    "find_page",
    "htmlize",
    "extract_ooxml_text",
    "is_supported_ooxml",
]
