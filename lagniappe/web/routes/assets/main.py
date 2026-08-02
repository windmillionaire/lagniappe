from flask import redirect, request

from lagniappe.core.definitions import Action, AssetTypes, Fetch
from lagniappe.core.definitions.asset import LARGE_ASSET_BYTES
from lagniappe.core.entities import Entities
from lagniappe.core.tools import database, files as file_tools
from lagniappe.web.auth import permission
from lagniappe.web import responses

from . import assets


# @testable false
# @covered-by lagniappe/web/routes/assets/main.py::get_image
# @reason file asset response handling is route-local glue around tested range helpers
def _asset_size(asset):
    if asset.size is not None:
        return asset.size
    return database.assets.file_size(asset.path, asset.visibility.value)


# @testable false
# @covered-by lagniappe/web/routes/assets/main.py::get_image
# @reason large-asset decision is route-local response plumbing
def _large_asset(asset):
    if asset.large is not None:
        return asset.large
    size = _asset_size(asset)
    return bool(size is not None and size > LARGE_ASSET_BYTES)


# @testable false
# @covered-by lagniappe/web/routes/assets/main.py::get_image
# @reason metadata responses are route-local glue for range-capable preview clients
def _asset_metadata_response(asset, mimetype):
    response, status = responses.file_response(
        b"",
        mimetype or asset.content_type or "application/octet-stream",
        accept_ranges=True,
    )
    size = _asset_size(asset)
    if size is not None:
        response.headers["Content-Length"] = str(size)
    return response, status


# @testable false
# @covered-by lagniappe/web/routes/assets/main.py::get_image
# @reason signed URL redirects depend on provider credentials and route permission
def _asset_redirect(asset, mimetype):
    response_type = mimetype or asset.content_type or "application/octet-stream"
    filename = f"{asset.name}.{asset.extension}" if asset.extension else asset.name
    filename = (filename or asset.path.rsplit("/", 1)[-1]).replace('"', "")
    disposition = f'inline; filename="{filename}"'

    if asset.visibility.value == "private":
        url = database.assets.get_signed_url(
            asset.path,
            response_disposition=disposition,
            response_type=response_type,
        )
    else:
        url = asset.url

    return redirect(url), 302


# @testable false
# @covered-by lagniappe/web/routes/assets/main.py::get_image
# @reason file asset response handling is route-local glue around tested range helpers
def _file_response(asset, mimetype):
    size = None
    byte_range = None
    range_header = request.headers.get("Range")

    if range_header:
        size = _asset_size(asset)
        try:
            byte_range = file_tools.parse_byte_range(range_header, size)
        except file_tools.UnsatisfiableByteRange:
            return responses.file_range_not_satisfiable(size, mimetype)

    if byte_range:
        content = database.assets.download_file(
            asset.path,
            asset.visibility.value,
            start=byte_range.start,
            end=byte_range.end,
        )
        if content is None:
            return responses.not_found("Content not found")
        return responses.file_response(
            content,
            mimetype,
            status=206,
            byte_range=byte_range,
            accept_ranges=True,
        )

    if _large_asset(asset):
        return _asset_redirect(asset, mimetype)

    content = asset.get()
    if content is None:
        return responses.not_found("Content not found")
    return responses.file_response(content, mimetype, accept_ranges=True)


# @testable true
# @tests tests_unit/test_008_page_properties.py::test_page_image_asset_lifecycle_and_projections
# @tests tests_e2e/004_projects/test_004e_document_forms.py::test_add_image
# @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_download_uses_original_filename_and_mimetype
# @features file
# @dimensions byte-range etag partial-content
@assets.route("<key>/<name>", methods=["GET", "HEAD"])
@permission(requested=Action.VIEW)
def get_image(key, name, **kwargs):
    entity = Entities.fetch_one(
        kwargs["entity"],
        request=Fetch.direct(),
    )

    asset = entity.get_asset(name)
    if not asset:
        return responses.not_found("Content not found")

    if isinstance(asset, AssetTypes.IMAGE.value):
        if request.method == "HEAD":
            return _asset_metadata_response(asset, asset.content_type)
        if _large_asset(asset):
            return _asset_redirect(asset, asset.content_type)
        content = asset.get()
        if not content:
            return responses.not_found("Content not found")
        return responses.image_response(content, asset.content_type)
    elif isinstance(asset, AssetTypes.FILE.value):
        if request.method == "HEAD":
            return _asset_metadata_response(asset, entity.mimetype)
        return _file_response(asset, entity.mimetype)

    return responses.error("Unsupported asset type")
