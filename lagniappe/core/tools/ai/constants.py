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
    "text/md",
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
