"""External file download helpers."""

from io import BytesIO
from time import sleep

import requests

from lagniappe.core import exceptions


# @testable false
# @covered-by lagniappe/core/properties/user_entity.py::ProfilePhoto
# @covered-by lagniappe/core/properties/form_links.py::Bookmark.validate_submission
# @reason external image fetch is owned by profile/bookmark image workflows
def download_image(url):
    """Download an image URL and return a success/error result."""
    sleep(0.3)
    try:
        response = requests.get(url, timeout=2)
        response.raise_for_status()
        if not response.content or len(response.content) < 500:
            return {"success": False, "error": "no image file found"}
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            return {"success": False, "error": "not an image file"}
        file = BytesIO(response.content)
        file.seek(0)
        file.content_type = content_type
        return {"success": True, "file": file}
    except requests.exceptions.RequestException as error:
        return {"success": False, "error": str(error)}
    except Exception as error:
        exceptions.capture(error, {"function": "download_image", "url": url})
        return {"success": False, "error": str(error)}
