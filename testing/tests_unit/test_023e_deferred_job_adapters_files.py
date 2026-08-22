"""Focused deferred-job behavior tests."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import threading
from types import SimpleNamespace

from google.api_core import exceptions as google_exceptions
from google.genai import errors as genai_errors
import httpx
import pytest

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    AI,
    DeferredJobInspection,
    DeferredJobPhase,
    DeferredJobRunState,
    DeferredJobSpec,
    DeferredJobStatus,
    DeferredJobType,
    FetchReason,
)
from lagniappe.core.entities import Entities
from lagniappe.core.mixins.submitter import SubmitterMixin
from lagniappe.core.properties.deferred_job_dispatch import TaskIdentity
from lagniappe.core.properties.deferred_job_request import RequestFingerprint
from lagniappe.core.properties import deferred_job_lifecycle
from lagniappe.core.tools import database, notification_service, task_queue
from lagniappe.core.tools.ai.prompt import Prompt
from lagniappe.core.tools.ai import observability
from lagniappe.core.tools.database import deferred_jobs as deferred_database
from lagniappe.core.tools.database import utility as database_utility
from lagniappe.core.tools.deferred_jobs import common as deferred_common
from lagniappe.core.tools.deferred_jobs import retry as deferred_retry
from lagniappe.core.tools.deferred_jobs.adapters.base import DeferredJobAdapter
from lagniappe.core.tools.deferred_jobs.context import DeferredJobContext
from lagniappe.core.tools.deferred_jobs.control import (
    DeferredExecutionControl,
    _DeferredLeaseGuard,
)
from lagniappe.core.tools.deferred_jobs.dispatch import DeferredJobDispatch
from lagniappe.core.tools.deferred_jobs.errors import (
    DeferredJobClaimLostError,
    DeferredJobDeadlineError,
    DeferredJobDependencyFailedError,
    DeferredJobDependencyPendingError,
    DeferredJobDriftError,
    DeferredJobInfrastructureError,
    DeferredJobLockedError,
)
from lagniappe.core.tools.deferred_jobs.locks import (
    AUTOFILL_FORM_LOCK_SCOPE,
    active_deferred_job_lock,
    deferred_job_lock_descriptor,
    deferred_job_lock_descriptors,
    deferred_job_lock_key,
)
from lagniappe.core.tools.deferred_jobs.retry import MODEL_BUSY_MESSAGE
from lagniappe.core.tools.deferred_jobs.runner import MISSING_INPUT_MESSAGE
from lagniappe.core.tools.deferred_jobs.service import DeferredJobService, DeferredJobs
from lagniappe.core.tools.files import extract as file_extract
from testing.utility.deferred_job_fakes import (
    ContendedDatastore,
    FakeDatastore,
    FakeTasksClient,
    KeyedDatastore,
    KeyedEntity,
    RecordingAdapter,
    RunnerJob,
    fake_start_entities,
    operation_projection,
    runner,
    terminal_delivery_runner,
)
from testing.utility.test_entities import TestEntities


pytestmark = pytest.mark.unit
from lagniappe.core.tools.deferred_jobs.adapters import files as file_adapters



# @pairs deferred-jobs:checkpoint file:extraction file:text-asset
def test_file_extract_adapter_checkpoints_and_applies_text_asset(monkeypatch):
    adapter = file_adapters.FileExtractAdapter()
    process = SimpleNamespace(
        complete=True,
        error=None,
        section={"status": "Text extracted successfully.", "complete": True},
    )
    prepared_file = SimpleNamespace(assets={})

    def extract(file, *, raise_errors):
        assert file is prepared_file
        assert raise_errors is True
        file.assets["text"] = {
            "type": "text",
            "visibility": "private",
            "path": "files/example/text.txt",
            "fingerprint": "text-fingerprint",
        }
        return process

    monkeypatch.setattr(file_adapters.files, "ocr_file", extract)
    phases = []
    checkpoint = adapter.prepare(
        SimpleNamespace(
            set_phase=phases.append,
            input=lambda name: prepared_file if name == "file" else None,
        )
    )

    assert phases == [DeferredJobPhase.PREPARING_INPUTS]
    assert checkpoint["process"] == process.section
    assert checkpoint["text_asset"] == prepared_file.assets["text"]

    saved = []
    applied_extract = SimpleNamespace(section={})
    applied_file = SimpleNamespace(
        assets={
            "file": {
                "type": "file",
                "visibility": "private",
                "path": "files/example/original.png",
            }
        },
        db={},
        properties=SimpleNamespace(extract=applied_extract),
        save=lambda: saved.append(True),
        urlsafe_key="file-key",
    )
    result = adapter.apply(
        SimpleNamespace(
            checkpoint=checkpoint,
            ensure_active=lambda: None,
            input=lambda name: applied_file if name == "file" else None,
        )
    )

    assert result == {"file_key": "file-key", "complete": True}
    assert json.loads(applied_file.db["assets"])["text"] == checkpoint["text_asset"]
    assert applied_extract.section == checkpoint["process"]
    assert saved == [True]




# @features deferred-jobs file
# @dimensions authorization validation original-asset fingerprint metadata-isolation
def test_file_adapter_drift_tracks_the_original_asset():
    adapter = file_adapters.FileSummarizeAdapter()
    original = SimpleNamespace(fingerprint="original-asset")
    file = SimpleNamespace(
        entity_kind="file",
        fingerprint="file-metadata-before",
        get_asset=lambda name: original if name == "file" else None,
        urlsafe_key="file-key",
    )
    actor = SimpleNamespace(urlsafe_key="actor-key")
    authorization = adapter.authorization(
        DeferredJobSpec(
            job_type=DeferredJobType.FILE_SUMMARIZE,
            actor=actor,
            inputs={"file": file},
        )
    )
    context = SimpleNamespace(
        job=SimpleNamespace(authorization=authorization),
        input=lambda name: file if name == "file" else None,
    )

    file.fingerprint = "file-metadata-after"
    adapter.validate_apply(context)

    original.fingerprint = "replacement-asset"
    with pytest.raises(
        DeferredJobDriftError,
        match="original file changed",
    ):
        adapter.validate_apply(context)




# @features deferred-jobs file
# @dimensions terminal follow-up extraction idempotency summary-first
@pytest.mark.parametrize("status", ["succeeded", "failed"])
def test_file_summary_terminal_cleanup_starts_extraction_once(monkeypatch, status):
    adapter = file_adapters.FileSummarizeAdapter()
    file = Entities.FILE(testing=True)
    actor = SimpleNamespace(urlsafe_key="actor-key")
    parameters = {"extract_after_summary": True}
    context = SimpleNamespace(
        actor=actor,
        parameters=parameters,
        job=SimpleNamespace(
            status=status,
            idempotency_key="summary-operation",
            client={},
        ),
        input=lambda name: file if name == "file" else None,
    )
    starts = []
    monkeypatch.setattr(
        file_adapters.files,
        "start_file_extraction",
        lambda *args, **kwargs: starts.append((args, kwargs)),
    )

    adapter.cleanup(context, terminal=True)
    adapter.cleanup(context, terminal=True)

    assert len(starts) == 1
    args, kwargs = starts[0]
    assert args == (file,)
    assert kwargs["actor"] is actor
    assert kwargs["delay_seconds"] == 0
    assert kwargs["idempotency_key"].startswith("file-extract-follow-up:")
    assert file.properties.extract.status == "Extracting text..."
    assert parameters == {}




# @features deferred-jobs file
# @dimensions summary expected-failure no-duplicate-capture
def test_file_summary_expected_rejection_is_not_reported_twice(monkeypatch):
    file = SimpleNamespace(
        properties=SimpleNamespace(
            summarize=SimpleNamespace(
                complete=None,
                error="PDF exceeds the AI summary page limit.",
            )
        )
    )
    context = SimpleNamespace(
        input=lambda name: file if name == "file" else None,
        set_phase=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        file_adapters.ai,
        "generate_summary",
        lambda *_args, **_kwargs: file.properties.summarize,
    )

    with pytest.raises(
        DeferredJobDependencyFailedError,
        match="page limit",
    ):
        file_adapters.FileSummarizeAdapter().prepare(context)




# @features deferred-jobs file
# @dimensions follow-up extraction idempotency
def test_start_file_extraction_uses_explicit_actor_and_identity(monkeypatch):
    actor = SimpleNamespace(urlsafe_key="actor-key")
    file = SimpleNamespace(urlsafe_key="file-key")
    started = []
    monkeypatch.setattr(
        DeferredJobs,
        "start",
        lambda spec: started.append(spec) or "started",
    )

    result = file_extract.start_file_extraction(
        file,
        actor=actor,
        idempotency_key="follow-up-identity",
        delay_seconds=0,
    )

    assert result == "started"
    assert len(started) == 1
    spec = started[0]
    assert spec.job_type is DeferredJobType.FILE_EXTRACT
    assert spec.actor is actor
    assert spec.inputs == {"file": file}
    assert spec.client == {}
    assert spec.idempotency_key == "follow-up-identity"
    assert spec.delay_seconds == 0
