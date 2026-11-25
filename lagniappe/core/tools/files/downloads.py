"""External file download helpers."""

from io import BytesIO

from ..http import BOOKMARK_IMAGE_POLICY, OutboundResult, UserFetchPolicy, fetch_user_content


class DownloadedImage(BytesIO):
    content_type: str | None


def download_image(url: str, *, policy: UserFetchPolicy = BOOKMARK_IMAGE_POLICY) -> OutboundResult:
    """Download and verify a bounded raster image through the shared boundary."""
    return fetch_user_content(url, policy)


def downloaded_image_file(result: OutboundResult) -> DownloadedImage | None:
    """Wrap a successful typed image result for existing asset APIs."""
    if not result.ok:
        return None
    file = DownloadedImage(result.body)
    file.content_type = result.media_type
    return file
