"""Opt-in live contracts for the runtime Google operations used to size IAM.

These tests are deliberately excluded from ordinary runs. They create only
uniquely named, test-prefixed resources, clean them in ``finally`` blocks, and
must remain sequential with every other E2E or managed-server session.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4
from xml.etree import ElementTree

import pytest
import requests
from playwright.sync_api import expect
from google.api_core.client_options import ClientOptions
from google.auth import impersonated_credentials
from google.auth.transport.requests import Request
from google.cloud import (
    datastore,
    documentai,
    iam_admin_v1,
    resourcemanager_v3,
)
from google.cloud.storage import _signing as storage_signing
from google.cloud.datastore.query import PropertyFilter

from lagniappe import CONFIG
from lagniappe.core.entities import Entities
from lagniappe.core.tools.services import identity_platform
from lagniappe.core.tools.services import places as location
from lagniappe.core.tools.services import task_queue
from lagniappe.core.tools.ai.core import GenAI
from lagniappe.core.tools.database import assets
from lagniappe.core.tools.database.core import DATA

from testing.definitions import SitePages, Users
from testing.elements import Buttons, FormElements

pytestmark = [pytest.mark.e2e, pytest.mark.setup_provider]


def _probe_id():
    return f"setup-runtime-{uuid4().hex}"


def _assert_xml_error_response(response, *, status, code):
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/xml")
    error = ElementTree.fromstring(response.content)
    assert error.findtext("Code") == code
    assert error.findtext("Message")


@pytest.fixture(scope="module", autouse=True)
def require_impersonated_runtime_adc():
    """Keep live runtime contracts scoped to short-lived runtime ADC."""
    credentials = CONFIG.google_credentials
    principal = getattr(credentials, "service_account_email", None) or getattr(
        credentials, "signer_email", None
    )
    assert principal == CONFIG.RUNTIME_SERVICE_ACCOUNT_EMAIL, (
        "The testing configuration did not impersonate the saved runtime "
        f"identity {CONFIG.RUNTIME_SERVICE_ACCOUNT_EMAIL}."
    )


def test_runtime_effective_permissions_exclude_provisioning_authority():
    """Prove the runtime can sign as itself without provisioning resources."""
    project_id = CONFIG.GOOGLE_CLOUD_PROJECT
    runtime_email = CONFIG.RUNTIME_SERVICE_ACCOUNT_EMAIL
    project_resource = f"projects/{project_id}"

    runtime_project_client = resourcemanager_v3.ProjectsClient(
        credentials=CONFIG.google_credentials
    )
    forbidden_project_permissions = {
        "appengine.versions.create",
        "cloudbuild.builds.create",
        "resourcemanager.projects.setIamPolicy",
        "serviceusage.services.enable",
        "storage.buckets.create",
        "storage.buckets.delete",
    }
    effective = runtime_project_client.test_iam_permissions(
        request={
            "resource": project_resource,
            "permissions": sorted(forbidden_project_permissions),
        }
    )
    assert forbidden_project_permissions.isdisjoint(effective.permissions)

    iam_client = iam_admin_v1.IAMClient(credentials=CONFIG.google_credentials)
    service_account_resource = f"projects/{project_id}/serviceAccounts/{runtime_email}"
    service_account_permissions = iam_client.test_iam_permissions(
        request={
            "resource": service_account_resource,
            "permissions": [
                "iam.serviceAccountKeys.create",
                "iam.serviceAccounts.actAs",
                "iam.serviceAccounts.signBlob",
                "iam.serviceAccounts.setIamPolicy",
            ],
        }
    )
    assert set(service_account_permissions.permissions) == {
        "iam.serviceAccounts.actAs",
        "iam.serviceAccounts.signBlob",
    }


# @matrix login : email-password hosted-e2e identity-platform token-verification
def test_runtime_identity_platform_sign_in_reaches_hosted_home(get_user):
    """Sign in through the live provider and deployed application handoff."""
    if not CONFIG.hosted_e2e_runner:
        pytest.skip("requires the hosted App Engine E2E service")

    probe_id = uuid4().hex
    email = f"setup-runtime-auth-{probe_id}@example.test"
    password = f"E2E-{probe_id}-aA1!"
    display_name = f"Runtime Auth {probe_id[:8]}"
    provider_created = False
    local_user = None
    anonymous = None

    try:
        client_config = CONFIG.IDENTITY_PLATFORM_CONFIG
        provider_session = requests.Session()
        sign_up = provider_session.post(
            f"{identity_platform.IDENTITY_TOOLKIT_API}/accounts:signUp",
            params={"key": client_config["apiKey"]},
            json={
                "email": email,
                "password": password,
                "returnSecureToken": True,
            },
            timeout=30,
        )
        assert sign_up.status_code == 200, sign_up.text
        provider_user = sign_up.json()
        provider_created = True
        local_id = provider_user.get("localId")
        assert local_id

        verified = provider_session.post(
            (
                f"{identity_platform.IDENTITY_TOOLKIT_API}/projects/"
                f"{client_config['projectId']}/accounts:update"
            ),
            headers={
                "Authorization": f"Bearer {CONFIG.google_access_token()}",
                "Content-Type": "application/json",
            },
            json={
                "localId": local_id,
                "emailVerified": True,
                "displayName": display_name,
            },
            timeout=30,
        )
        assert verified.status_code == 200, verified.text

        local_user = Entities.USER.create(
            {
                "email": email,
                "name": display_name,
                "admin": True,
            }
        )
        local_user.last_login = datetime.now(timezone.utc)
        local_user.save()

        owner = Users.OWNER.get(None)
        owner.entity.last_login = datetime.now(timezone.utc)
        owner.entity.save()

        anonymous = get_user(Users.ANONYMOUS)
        login_page = anonymous.go(SitePages.LOGIN_PAGE)
        auth_method = anonymous.locate(login_page.AUTH_METHOD_FORM)
        auth_method.locator("[data-role='show-email-check']").click()

        email_form = anonymous.locate(login_page.EMAIL_CHECK_FORM)
        email_form.locator(FormElements.EMAIL).fill(email)
        email_form.locator(Buttons.SIGNIN).click()

        sign_in_form = anonymous.locate(login_page.SIGN_IN_FORM)
        sign_in_form.locator("input[type='password']").fill(password)
        sign_in_form.locator(Buttons.SIGNIN).click()

        anonymous.page.wait_for_url(
            f"{str(CONFIG.APP_URL).rstrip('/')}/",
            timeout=30_000,
        )
        assert anonymous.page.title() == "Home"
        expect(anonymous.page.locator("[lp-view]")).to_have_attribute(
            "initialized", ""
        )
    finally:
        if anonymous and anonymous.page and not anonymous.page.is_closed():
            anonymous.page.close()
        if provider_created:
            identity_platform.delete_account_by_email(email)
        if local_user is not None:
            Entities.delete(local_user)


def test_runtime_datastore_and_all_storage_bucket_operations(monkeypatch):
    """Exercise the exact Datastore and four-bucket object operations used at runtime."""
    probe_id = _probe_id()
    datastore_client = DATA.datastore
    kind = f"{CONFIG.PREFIX}setup-runtime-contract"
    key = datastore_client.key(kind, probe_id)
    entity = datastore.Entity(key=key)
    entity.update({"probe": probe_id, "revision": 1})

    try:
        datastore_client.put(entity)
        assert datastore_client.get(key)["probe"] == probe_id

        query = datastore_client.query(kind=kind)
        query.add_filter(filter=PropertyFilter("probe", "=", probe_id))
        rows = list(query.fetch(limit=2))
        assert [row.key for row in rows] == [key]

        with datastore_client.transaction() as transaction:
            current = datastore_client.get(key, transaction=transaction)
            current["revision"] = 2
            transaction.put(current)

        assert datastore_client.get(key)["revision"] == 2
    finally:
        datastore_client.delete(key)
    assert datastore_client.get(key) is None

    for bucket_role in ("public", "private", "history", "export"):
        bucket = DATA.bucket(bucket_role)
        blob = bucket.blob(f"setup-runtime-contract/{probe_id}.txt")
        try:
            blob.upload_from_string(
                f"{bucket_role}:{probe_id}",
                content_type="text/plain",
                if_generation_match=0,
            )
            blob.reload()
            assert blob.download_as_text() == f"{bucket_role}:{probe_id}"
            if bucket_role == "private":
                signed_url = assets.get_signed_url(blob.name, expires_in=60)
                response = requests.get(signed_url, timeout=30)
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/plain")
                assert int(response.headers["content-length"]) == len(response.content)
                assert response.text == f"{bucket_role}:{probe_id}"

                tampered_suffix = "0" if signed_url[-1] != "0" else "1"
                tampered_url = f"{signed_url[:-1]}{tampered_suffix}"
                tampered_response = requests.get(tampered_url, timeout=30)
                _assert_xml_error_response(
                    tampered_response,
                    status=403,
                    code="SignatureDoesNotMatch",
                )
                issued_at = datetime.now(timezone.utc) - timedelta(minutes=1)
                request_timestamp = issued_at.strftime("%Y%m%dT%H%M%SZ")
                datestamp = issued_at.strftime("%Y%m%d")
                with monkeypatch.context() as controlled_clock:
                    controlled_clock.setattr(
                        storage_signing,
                        "get_v4_now_dtstamps",
                        lambda: (request_timestamp, datestamp),
                    )
                    expired_url = assets.get_signed_url(blob.name, expires_in=1)
                expired_query = parse_qs(urlparse(expired_url).query)
                assert expired_query["X-Goog-Date"] == [request_timestamp]
                assert expired_query["X-Goog-Expires"] == ["1"]
                expired_response = requests.get(expired_url, timeout=30)
                _assert_xml_error_response(
                    expired_response,
                    status=400,
                    code="ExpiredToken",
                )
                assert blob.download_as_text() == f"{bucket_role}:{probe_id}"
        finally:
            if blob.exists():
                blob.delete()
        assert not blob.exists()


def test_runtime_task_create_delete_and_scheduler_oidc_delivery(monkeypatch):
    """Create/delete one delayed task and authenticate the Scheduler target."""
    probe_id = _probe_id()
    endpoint = f"{str(CONFIG.APP_URL).rstrip('/')}/process/jobs/reconcile"
    monkeypatch.setattr(CONFIG, "TASK_QUEUE_ENABLED", True)

    created_task = task_queue.create_task(
        endpoint,
        {"reconcile": False},
        delay_seconds=3600,
        task_id=probe_id,
    )
    try:
        assert created_task == task_queue.task_name(probe_id)
    finally:
        if created_task:
            assert task_queue.delete_task(created_task)

    credentials = impersonated_credentials.IDTokenCredentials(
        CONFIG.google_credentials,
        target_audience=endpoint,
        include_email=True,
    )
    credentials.refresh(Request())
    response = requests.post(
        endpoint,
        headers={"Authorization": f"Bearer {credentials.token}"},
        json={"reconcile": False},
        timeout=30,
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "success": False,
        "error": "Invalid reconcile payload.",
    }


def test_runtime_document_ai_vertex_ai_and_places_operations():
    """Exercise the three runtime consumer APIs with the runtime credential."""
    probe_id = _probe_id()
    sample_pdf = Path(__file__).resolve().parents[2] / "files" / "sample_document.pdf"
    blob = DATA.private_bucket.blob(f"setup-runtime-contract/{probe_id}.pdf")
    try:
        blob.upload_from_filename(
            sample_pdf,
            content_type="application/pdf",
            if_generation_match=0,
        )
        location_id = str(CONFIG.OCR_LOCATION)
        client = documentai.DocumentProcessorServiceClient(
            credentials=CONFIG.google_credentials,
            client_options=ClientOptions(
                api_endpoint=f"{location_id}-documentai.googleapis.com"
            ),
        )
        result = client.process_document(
            request=documentai.ProcessRequest(
                name=CONFIG.OCR_PROCESSOR_ID,
                gcs_document=documentai.GcsDocument(
                    gcs_uri=f"gs://{blob.bucket.name}/{blob.name}",
                    mime_type="application/pdf",
                ),
            )
        )
        assert result.document.text.strip()
    finally:
        if blob.exists():
            blob.delete()

    vertex_response = GenAI().client.models.generate_content(
        model=CONFIG.AI_UTILITY_MODEL,
        contents="Reply with the single word OK.",
    )
    assert vertex_response.text.strip()

    place = location.get_place_details("ChIJN1t_tDeuEmsRUsoyG83frY4")
    assert place["id"] == "ChIJN1t_tDeuEmsRUsoyG83frY4"
    assert place["address"]
