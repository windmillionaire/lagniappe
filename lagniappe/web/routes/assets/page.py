from flask import request

from flask_login import current_user

from lagniappe.core import exceptions
from lagniappe.core.definitions import AI, Action, Resource
from lagniappe.core.tools import ai
from lagniappe.web.auth import (
    abort_public_user_action,
    permission,
    require_ai_access,
)
from lagniappe.web import responses
from lagniappe.web import direct_uploads

from . import assets


# @testable true
# @tests tests_unit/test_008_page_properties.py::test_page_image_asset_lifecycle_and_projections
# @tests tests_e2e/005_pages/test_005f_page_image.py::test_add_image_to_page
# @pairs page:asset-lifecycle pages:image-add
@assets.route("<key>/add-page-image", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def add_page_image(key, **kwargs):
    abort_public_user_action()

    page = kwargs["entity"]

    file = request.files.get("page-photo") or direct_uploads.direct_upload_file(
        "page-photo"
    )
    if not file:
        return responses.error("no file uploaded")

    try:
        page.properties.image.delete()
        page.image = file
    except Exception as e:
        return responses.error(str(e), exception=e)

    page.save()

    return responses.page_image(page)


# @testable false
# @covered-by lagniappe/web/routes/assets/page.py::add_page_image
# @reason route permission mirrors the final page image upload endpoint
@assets.route("<key>/add-page-image/direct-upload", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def add_page_image_direct(key, **kwargs):
    abort_public_user_action()

    return direct_uploads.direct_upload_response()


# @testable true
# @tests tests_unit/test_008_page_properties.py::test_page_image_asset_lifecycle_and_projections
# @tests tests_e2e/005_pages/test_005f_page_image.py::test_remove_image_from_page
# @pairs page:asset-lifecycle pages:image-remove
@assets.route("<key>/remove-page-image", methods=["DELETE"])
@permission(Resource.PAGE, Action.EDIT)
def remove_page_image(key, **kwargs):
    abort_public_user_action()

    page = kwargs["entity"]

    page.properties.image.delete()
    page.save()

    return responses.page_image(page)


# @testable true
# @tests tests_unit/test_008_page_properties.py::test_page_image_asset_lifecycle_and_projections
# @tests tests_e2e/005_pages/test_005f_page_image.py::test_generate_image_on_page
# @pairs page:asset-lifecycle pages:image-generate
@assets.route("<key>/generate-page-image", methods=["POST"])
@permission(Resource.PAGE, Action.EDIT)
def generate_page_image(key, **kwargs):
    require_ai_access(AI.CREATE)

    page = kwargs["entity"]

    generate_data = {
        "user_prompt": request.form.get("prompt"),
    }

    if request.form.get("info"):
        generate_data["page_details"] = page.to_ai(user=current_user)

    prompt = ai.page_image_generation_prompt(**generate_data)

    try:
        image = ai.generate_ai_image(prompt)

        page.properties.image.delete()
        page.image = image
        page.save()

        return responses.page_image(page)
    except exceptions.AIException as e:
        return responses.error(str(e), exception=e)
    except Exception as e:
        return responses.error("Image generation failed. Please try again.", exception=e)
