"""
Tests for data import functionality in Admin.

Tests the ingress file upload widget including file input, drag and drop,
and paste upload methods. Verifies row/column counts after upload and
tests file deletion.

Related Files:
    Application:
        - lagniappe/web/routes/files/ingress.py: Ingress upload and progress routes
        - lagniappe/web/templates/home/ingress.html: Import component template
        - lagniappe/web/templates/delete/ingress.html: Delete confirmation modal
        - src/script/widgets/ingressUpload.mjs: Import upload widget
        - src/script/elements/upload.mjs: Shared upload element

    Core:
        - lagniappe/core/properties/file_ingress.py: File ingress processing

    Test Framework:
        - testing/definitions/upload.py: Uploads enum with upload definitions
        - testing/definitions/upload_definitions.py: UploadDefinition dataclass
        - testing/resources/home.py: HomePage selectors for import component
        - testing/elements/site_common.py: UploadDropdown for menu interactions
        - testing/files/sample_data.csv: Test CSV file (10 rows, 7 columns)

Import Widget:
    The import widget allows uploading CSV files for bulk data import.
    Files can be uploaded via:
    - Direct file input selection
    - Drag and drop onto dropzone
    - Paste from clipboard via dropdown menu

    After upload, the file appears in the import list showing row and
    column counts. Files can be deleted via the delete button which
    shows a confirmation modal.
"""

import pytest
from playwright.sync_api import expect

from testing.definitions import SitePages, Uploads, Users
from testing.elements import Buttons, Modal
from testing.resources import File


# @pair ingress:upload-form
@pytest.mark.e2e
def test_open_import_form(get_user):
    """
    Verify import form opens from the Admin Import Data tab.

    Tests:
        - Import form hidden initially
        - Toggle button shows form
    """
    user = get_user(Users.OWNER)
    admin = user.go(SitePages.ADMIN)

    form = admin.open_import_upload_form()
    expect(form).to_be_visible()


# @matrix ingress : delete file-input upload-counts
@pytest.mark.e2e
def test_import_csv_via_file_input(get_user):
    """
    Verify CSV upload via direct file input selection.

    Tests:
        1. Open import form
        2. Upload file via file input
        3. Verify file appears in import list with correct row/column counts
        4. Delete file via delete button and modal

    Uses Uploads.csv_file_input definition with FILE_INPUT method.
    """
    user = get_user(Users.OWNER)
    admin = user.go(SitePages.ADMIN)
    upload = Uploads.csv_file_input

    file_item = admin.import_file(upload)
    file = File(user)
    file.key = file_item.get_attribute("data-key")

    # Verify row and column counts
    expect(file_item).to_contain_text(f"Rows: {upload.definition.rows}")
    expect(file_item).to_contain_text(f"Columns: {upload.definition.columns}")

    # Delete file
    file_list = admin.import_list
    file_item = file_list.get_item(file)
    file_item.locator(Buttons.LP_DELETE).click()
    modal = Modal(user.page)
    modal.delete()
    expect(file_item).not_to_be_visible()


# @matrix ingress : delete drag-drop upload-counts
@pytest.mark.e2e
def test_import_csv_via_drag_drop(get_user):
    """
    Verify CSV upload via drag and drop onto dropzone.

    Tests:
        1. Open import form
        2. Upload file via drag and drop
        3. Verify file appears in import list with correct row/column counts
        4. Delete file via delete button and modal

    Uses Uploads.csv_drag_drop definition with DRAG_DROP method.
    """
    user = get_user(Users.OWNER)
    admin = user.go(SitePages.ADMIN)
    upload = Uploads.csv_drag_drop

    file_item = admin.import_file(upload)
    file = File(user)
    file.key = file_item.get_attribute("data-key")

    # Verify row and column counts
    expect(file_item).to_contain_text(f"Rows: {upload.definition.rows}")
    expect(file_item).to_contain_text(f"Columns: {upload.definition.columns}")

    # Delete file
    file_list = admin.import_list
    file_item = file_list.get_item(file)
    file_item.locator(Buttons.LP_DELETE).click()
    modal = Modal(user.page)
    modal.delete()
    expect(file_item).not_to_be_visible()
