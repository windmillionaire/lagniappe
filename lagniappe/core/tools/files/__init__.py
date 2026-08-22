"""Lazy public API for file processing utilities."""

from importlib import import_module


_EXPORTS = {
    "ByteRange": ("ranges", "ByteRange"),
    "UnsatisfiableByteRange": ("ranges", "UnsatisfiableByteRange"),
    "parse_byte_range": ("ranges", "parse_byte_range"),
    "determine_encoding": ("utility", "determine_encoding"),
    "determine_mimetype": ("utility", "determine_mimetype"),
    "clean_html": ("html", "clean_html"),
    "htmlize": ("html", "htmlize"),
    "sanitize_html": ("html", "sanitize_html"),
    "strip_tags": ("html", "strip_tags"),
    "create_schema": ("validate", "create_schema"),
    "process_csv": ("validate", "process_csv"),
    "get_file_text": ("extract", "get_file_text"),
    "ocr_file": ("extract", "ocr_file"),
    "start_file_extraction": ("extract", "start_file_extraction"),
    "find_page": ("find_page", "find_page"),
    "extract_ooxml_text": ("ooxml", "extract_ooxml_text"),
    "is_supported_ooxml": ("ooxml", "is_supported_ooxml"),
    "DOCUMENT_AI_MIMETYPES": ("constants", "DOCUMENT_AI_MIMETYPES"),
    "IMAGE_MIMETYPES": ("constants", "IMAGE_MIMETYPES"),
    "PREVIEW_MIMETYPES": ("constants", "PREVIEW_MIMETYPES"),
    "TEXT_MIMETYPES": ("constants", "TEXT_MIMETYPES"),
    "CODE_MIMETYPES": ("constants", "CODE_MIMETYPES"),
    "ENCODINGS": ("constants", "ENCODINGS"),
}

__all__ = list(_EXPORTS)


# @testable infrastructure
def __getattr__(name):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(f"{__name__}.{module_name}"), attribute)
    globals()[name] = value
    return value
