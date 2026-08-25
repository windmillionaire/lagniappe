"""Focused deferred-job behavior tests."""

import json
from types import SimpleNamespace

import pytest

from lagniappe.core.definitions import (
    DeferredJobPhase,
    DeferredJobSpec,
    DeferredJobType,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools.deferred_jobs.adapters import files as file_adapters
from lagniappe.core.tools.deferred_jobs.errors import (
    DeferredJobDependencyFailedError,
    DeferredJobDriftError,
)
from lagniappe.core.tools.deferred_jobs.service import DeferredJobs
from lagniappe.core.tools.files import extract as file_extract

pytestmark = pytest.mark.unit


# @matrix file : extraction text-asset
# @pair deferred-jobs:checkpoint
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


# @matrix deferred-jobs file : authorization fingerprint metadata-isolation original-asset validation
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


# @matrix deferred-jobs file : extraction follow-up idempotency summary-first terminal
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


# @matrix deferred-jobs file : expected-failure no-duplicate-capture summary
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


# @matrix deferred-jobs file : extraction follow-up idempotency
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
