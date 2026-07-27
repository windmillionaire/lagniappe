"""HTTP boundaries for oversized AI upload consumers."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from flask import Flask
from werkzeug.exceptions import Forbidden

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    FileConsumer,
    FileConsumerLimitError,
    LARGE_ASSET_BYTES,
)
from lagniappe.web import auth, deferred_autofill
from lagniappe.web.routes.files import main as file_routes
from lagniappe.web.routes.tools import main as tool_routes


pytestmark = pytest.mark.e2e


@pytest.fixture
def route_app():
    app = Flask(__name__)
    app.testing = True
    return app


def _oversized_error(consumer, label):
    return FileConsumerLimitError(
        f"oversized.pdf is too large for {label}. Maximum size is 30 MB.",
        consumer=consumer,
        size=LARGE_ASSET_BYTES + 1,
        max_bytes=LARGE_ASSET_BYTES,
    )


def test_organize_report_accepts_oversized_input(route_app, monkeypatch):
    monkeypatch.setattr(tool_routes, "abort_ai_restricted_action", lambda: None)
    upload = SimpleNamespace(
        filename="oversized.pdf",
        size=LARGE_ASSET_BYTES + 1,
    )
    started = {}
    response = object()

    monkeypatch.setattr(tool_routes, "_uploaded_report_files", lambda: [upload])
    monkeypatch.setattr(tool_routes, "_report_upload_manifest", lambda: [])

    def start_report(tool, instructions, **kwargs):
        started.update(
            {
                "tool": tool,
                "instructions": instructions,
                **kwargs,
            }
        )
        return response

    monkeypatch.setattr(tool_routes, "_start_tool_report", start_report)

    with route_app.test_request_context("/tools/organize", method="POST"):
        result = tool_routes.create_organize_report.__wrapped__()

    assert result is response
    assert started["tool"] == "organize"
    assert started["default_name"] == "Organize: oversized.pdf"
    assert started["input_files"] == [upload]


# @features ai-report
# @dimensions upload
def test_organize_report_rejects_zero_byte_folder_placeholder(route_app):
    with route_app.test_request_context(
        "/tools/organize",
        method="POST",
        data={"tool-files": (BytesIO(b""), "documents")},
    ):
        with pytest.raises(
            exceptions.ValidationError,
            match="Only individual files are supported",
        ):
            tool_routes._uploaded_report_files()


def test_deferred_autofill_returns_422_before_creating_notification(monkeypatch):
    monkeypatch.setattr(
        deferred_autofill.direct_uploads,
        "direct_upload_records",
        lambda *_args, **_kwargs: [{"token": "signed", "filename": "oversized.pdf"}],
    )

    def reject_upload(*_args, **_kwargs):
        raise _oversized_error(FileConsumer.AI_INLINE, "AI autofill attachment")

    monkeypatch.setattr(
        deferred_autofill.storage_assets,
        "direct_upload_file",
        reject_upload,
    )
    monkeypatch.setattr(
        deferred_autofill.Entities.NOTIFICATION,
        "create",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("notification must not be created for a rejected upload")
        ),
    )

    response, status = deferred_autofill.start_deferred_autofill(
        SimpleNamespace(entity_kind="page"),
        SimpleNamespace(),
        {},
    )

    assert status == 422
    assert "too large for AI autofill attachment" in response


# @pair deferred-jobs:form-lock
# @pair deferred-jobs:conflict
# @pair deferred-jobs:quick-edit
def test_deferred_autofill_lock_response_blocks_form_mutations(
    route_app,
    monkeypatch,
):
    descriptor = {
        "locked": True,
        "scope": "form-autofill",
        "operation": "operation-key",
        "revision": 4,
    }
    monkeypatch.setattr(deferred_autofill, "active_lock", lambda _entity: descriptor)
    form = {"role": "autofill-submit"}

    with route_app.test_request_context("/pages/target/update", method="PUT"):
        response, status = deferred_autofill.locked_response(
            SimpleNamespace(),
            form,
        )

    assert status == 409
    assert response.get_json() == {
        **descriptor,
        "deferred": True,
        "message": "Autofill is already running. These changes were not saved.",
    }
    entity = SimpleNamespace(
        form=SimpleNamespace(schema=[{"id": "form-field"}])
    )
    assert deferred_autofill.is_form_field(entity, "form-field")
    assert not deferred_autofill.is_form_field(entity, "task-setting")


# @pair ai:batch-summary
# @pair ai:restriction-gate
# @pair ai:provider-boundary
def test_batch_page_upload_rejects_ai_restricted_actor_before_summary(
    route_app,
    monkeypatch,
):
    restricted_actor = SimpleNamespace(
        properties=SimpleNamespace(
            restrictions=SimpleNamespace(can_use_ai_tools=False),
        ),
    )
    summary_calls = []
    monkeypatch.setattr(auth, "current_user", restricted_actor)
    monkeypatch.setattr(file_routes, "abort_public_user_action", lambda: None)
    monkeypatch.setattr(
        file_routes,
        "_uploaded_page_files",
        lambda: [
            SimpleNamespace(filename="one.pdf"),
            SimpleNamespace(filename="two.pdf"),
        ],
    )
    monkeypatch.setattr(
        file_routes.ai,
        "summarize_report_input_files",
        lambda *_args, **_kwargs: summary_calls.append((_args, _kwargs)),
    )

    with route_app.test_request_context(
        "/files/page-key/upload",
        method="POST",
        data={"summarize": "on"},
    ):
        with pytest.raises(Forbidden):
            file_routes.upload.__wrapped__(
                "page-key",
                entity=SimpleNamespace(),
            )

    assert summary_calls == []
