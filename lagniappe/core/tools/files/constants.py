"""MIME type mappings and encoding constants for file handling."""

ENCODINGS = ["utf-8", "utf-8-sig", "cp1252", "utf-16", "ascii", "iso-8859-1"]

TEXT_MIMETYPES = {
    "txt": "text/plain",
    "md": "text/markdown",
    "py": "text/x-python",
    "js": "text/javascript",
    "html": "text/html",
    "htm": "text/html",
    "css": "text/css",
    "json": "application/json",
    "xml": "application/xml",
    "yaml": "text/yaml",
    "yml": "text/yaml",
    "csv": "text/csv",
    "rtf": "application/rtf",
    "vcf": "text/vcard",
}

CODE_MIMETYPES = {
    "text/x-python",
    "text/javascript",
    "text/css",
    "application/json",
    "application/xml",
    "text/yaml",
}

IMAGE_MIMETYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/svg+xml",
    "image/bmp",
    "image/tiff",
    "image/x-icon",
    "image/vnd.microsoft.icon",
    "image/avif",
    "image/apng",
}

DOCUMENT_AI_MIMETYPES = {
    "application/pdf",
    "image/gif",
    "image/tiff",
    "image/jpeg",
    "image/png",
    "image/bmp",
    "image/webp",
}

PREVIEW_MIMETYPES = {
    # Images
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
    # Documents
    "application/pdf",
    # "text/plain",
    # "text/html",
    # "text/css",
    # "text/javascript",
    # "application/json",
    # "text/xml",
    # "application/xml",
    # Media
    "video/mp4",
    "video/webm",
    "video/ogg",
    "audio/mp3",
    "audio/mpeg",
    "audio/wav",
    "audio/ogg",
}
