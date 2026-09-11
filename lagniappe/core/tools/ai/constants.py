"""Constants for form components, input types, and supported MIME types."""

AVAILABLE_COMPONENTS = """
- `input`
- `link`
- `textarea`
- `bookmark`
- `checkbox`
- `radio`
- `select`
- `table`
- `location`
- `signature`
- `html`
"""


TABLE_COMPONENTS = """
- `input`
- `link`
- `checkbox`
"""

LINK_TYPES = """
- `out`
- `in`
"""

INPUT_TYPES = """
- `text`
- `tel`
- `number`
- `email`
- `date`
- `time`,
"""

GEMINI_MIMETYPES = {
    # Documents
    "application/pdf",
    "text/plain",
    "text/html",
    "text/css",
    "text/csv",
    "text/xml",
    "text/rtf",
    "application/x-javascript",
    "text/javascript",
    "application/x-python",
    "text/x-python",
    # Images
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/heic",
    "image/heif",
    # Audio
    "audio/wav",
    "audio/mp3",
    "audio/mpeg",
    "audio/aac",
    "audio/ogg",
    "audio/flac",
    # Video
    "video/mp4",
    "video/mpeg",
    "video/mov",
    "video/avi",
    "video/x-flv",
    "video/mpg",
    "video/webm",
    "video/wmv",
    "video/3gpp",
}


GEMINI_MIMETYPE_ALIASES = {
    # Gemini accepts text/plain file parts, while Lagniappe retains these
    # canonical media types for storage, downloads, and previews.
    "text/markdown": "text/plain",
    "text/md": "text/plain",
    "text/vcard": "text/plain",
}


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_file_to_ai_exports_metadata_and_uri_to_ai
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_prompt_normalizes_textual_file_mimetypes_for_gemini
# @tests tests_unit/test_020d_ai_report_prompts.py::test_summarize_report_input_files_saves_missing_summaries
# @matrix ai files : mimetype normalization
def gemini_mimetype(mimetype):
    """Return the provider-supported media type for a Lagniappe MIME type."""
    mimetype = str(mimetype or "").partition(";")[0].strip().lower()
    mimetype = GEMINI_MIMETYPE_ALIASES.get(mimetype, mimetype)
    return mimetype if mimetype in GEMINI_MIMETYPES else None
