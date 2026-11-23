"""External file download helpers."""

from io import BytesIO

from ..http import BOOKMARK_IMAGE_POLICY, OutboundResult, UserFetchPolicy, fetch_user_content


class DownloadedImage(BytesIO):
    content_type: str | None


# @testable false
# @covered-by lagniappe/core/properties/user_entity.py::ProfilePhoto.save_google_photo
# @covered-by lagniappe/core/properties/form_links.py::Bookmark.validate_submission
# @reason external image fetch is owned by profile/bookmark image workflows
def download_image(url: str, *, policy: UserFetchPolicy = BOOKMARK_IMAGE_POLICY) -> OutboundResult:
    """Download and verify a bounded raster image through the shared boundary."""
    return fetch_user_content(url, policy)


# @testable false
# @covered-by lagniappe/core/properties/user_entity.py::ProfilePhoto.save_google_photo
# @covered-by lagniappe/core/properties/form_links.py::Bookmark.validate_submission
# @reason file wrapping is exercised through profile/bookmark asset persistence
def downloaded_image_file(result: OutboundResult) -> DownloadedImage | None:
    """Wrap a successful typed image result for existing asset APIs."""
    if not result.ok:
        return None
    file = DownloadedImage(result.body)
    file.content_type = result.media_type
    return file
