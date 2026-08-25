"""Focused deferred-job behavior tests."""

from datetime import datetime, timezone
import hashlib
from types import SimpleNamespace

import pytest

from lagniappe.core.definitions import (
    DeferredJobInspection,
    DeferredJobPhase,
    FetchReason,
)
from lagniappe.core.mixins.submitter import SubmitterMixin
from lagniappe.core.tools.deferred_jobs.adapters import autofill as autofill_adapters
from lagniappe.core.tools.deferred_jobs.errors import (
    DeferredJobDependencyFailedError,
    DeferredJobDependencyPendingError,
)

pytestmark = pytest.mark.unit


# @pairs ai:autofill deferred-jobs:form-revision
def test_autofill_revision_tracks_only_form_apply_state():
    class Target(SubmitterMixin):
        pass

    target = Target()
    target.form = SimpleNamespace(
        urlsafe_key="form-key",
        version="form-version-one",
        schema=[{"id": "field-one"}, {"id": "name"}],
    )
    target.db = {
        "schema_version": "schema-one",
        "default_submission": {"field-one": "default"},
    }
    target.name = "Original name"
    target.description = "Unmirrored description"
    target.properties = SimpleNamespace(
        submission=SimpleNamespace(value={"field-one": "answer"})
    )

    original = target.autofill_revision
    target.unrelated_task_setting = "changed"
    target.description = "Still unmirrored"
    assert target.autofill_revision == original

    target.properties.submission.value = {"field-one": "new answer"}
    submission_revision = target.autofill_revision
    assert submission_revision != original

    target.name = "Renamed"
    assert target.autofill_revision != submission_revision

    target.name = "Original name"
    target.form.version = "form-version-two"
    assert target.autofill_revision != original


# @pairs ai:collaboration deferred-jobs:status
def test_autofill_status_is_visible_to_target_editor(monkeypatch):
    actor = SimpleNamespace(urlsafe_key="editor-key")
    checked = []
    fetches = []

    class Target:
        def allowed(self, action, *, user):
            checked.append((action, user))
            return True

    target = Target()
    monkeypatch.setattr(autofill_adapters.Entities, "PAGE", Target)
    monkeypatch.setattr(autofill_adapters.Entities, "TASK", type(None))

    def fetch_one(key, request):
        fetches.append(request)
        return target if key == "target-key" else None

    monkeypatch.setattr(autofill_adapters.Entities, "fetch_one", fetch_one)
    job = SimpleNamespace(inputs={"target": {"id": "target-key"}})

    assert autofill_adapters.AutofillAdapter().can_view_status(job, actor)
    assert len(checked) == 1
    assert checked[0][1] is actor
    assert fetches[0].reason is FetchReason.PERMISSION_REQUIREMENTS_MATERIALIZATION


# @matrix deferred-jobs : form-lock terminal-cleanup
def test_autofill_terminal_cleanup_releases_target_lock(monkeypatch):
    target = SimpleNamespace(urlsafe_key="page-key", deferred_job=None)
    context = SimpleNamespace(
        job=SimpleNamespace(
            parameters={},
            urlsafe_key="job-key",
            inputs={"target": {"id": "page-key"}},
        ),
        parameters={},
        input=lambda name: target if name == "target" else None,
    )
    released = []
    monkeypatch.setattr(
        autofill_adapters.Entities,
        "PAGE",
        type(target),
    )
    monkeypatch.setattr(
        autofill_adapters.Entities,
        "fetch_one",
        lambda key, **_kwargs: target if key == "page-key" else None,
    )
    monkeypatch.setattr(
        autofill_adapters,
        "deferred_job_lock_key",
        lambda current: f"lock:{getattr(current, 'urlsafe_key', current)}",
    )
    monkeypatch.setattr(
        autofill_adapters.database,
        "release_deferred_job_lock",
        lambda *values: released.append(values),
    )

    adapter = autofill_adapters.AutofillAdapter()
    adapter.cleanup(context, terminal=False)
    assert released == []

    adapter.cleanup(context, terminal=True)
    assert released == [("lock:page-key", "job-key")]

    missing_context = SimpleNamespace(
        job=SimpleNamespace(
            parameters={},
            urlsafe_key="missing-job-key",
            inputs={"target": {"id": "deleted-page-key"}},
        ),
        parameters={},
        input=lambda _name: None,
    )
    adapter.cleanup(missing_context, terminal=True)
    assert released[-1] == ("lock:deleted-page-key", "missing-job-key")


# @matrix deferred-jobs : active-operation compare-and-delete terminal-cleanup
# @pair pages:create-autofill
def test_autofill_page_operation_reference_is_persisted_and_compare_cleared(
    monkeypatch,
):
    class Page:
        urlsafe_key = "page-key"

        def __init__(self):
            self.deferred_job = None

    page = Page()
    job = SimpleNamespace(
        parameters={"lock_target": True},
        inputs={"target": {"id": page.urlsafe_key}},
        urlsafe_key="job-key",
        idempotency_key="request-key",
        status_revision=2,
    )
    context = SimpleNamespace(
        job=job,
        actor=SimpleNamespace(),
        inputs={"target": page},
        parameters=job.parameters,
        input=lambda name: context.inputs.get(name),
    )
    saved = []
    released = []
    monkeypatch.setattr(autofill_adapters.Entities, "PAGE", Page)
    monkeypatch.setattr(
        autofill_adapters.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: page,
    )
    monkeypatch.setattr(
        autofill_adapters.Entities,
        "save_root",
        lambda entity, **options: saved.append((entity, options)),
    )
    monkeypatch.setattr(
        autofill_adapters,
        "deferred_job_lock_key",
        lambda current: f"lock:{getattr(current, 'urlsafe_key', current)}",
    )
    monkeypatch.setattr(
        autofill_adapters.database,
        "release_deferred_job_lock",
        lambda *values: released.append(values),
    )

    adapter = autofill_adapters.AutofillAdapter()
    adapter.started(context)

    assert page.deferred_job == {
        "key": "job-key",
        "idempotency_key": "request-key",
        "revision": 2,
    }
    assert saved == [(page, {"property_mask": ("deferred_job",)})]

    page.deferred_job = {"key": "newer-job"}
    adapter.cleanup(context, terminal=True)

    assert page.deferred_job == {"key": "newer-job"}
    assert len(saved) == 1
    assert released == [("lock:page-key", "job-key")]

    page.deferred_job = {"key": "job-key"}
    adapter.cleanup(context, terminal=True)

    assert page.deferred_job is None
    assert saved[-1] == (page, {"property_mask": ("deferred_job",)})


# @matrix ai deferred-jobs files : autofill failed pending summary-dependency
def test_autofill_prepare_waits_for_attached_file_summaries(monkeypatch):
    adapter = autofill_adapters.AutofillAdapter()
    phases = []
    context = SimpleNamespace(
        actor=SimpleNamespace(),
        parameters={},
        input=lambda name: SimpleNamespace() if name == "target" else None,
        set_phase=lambda phase, **details: phases.append((phase, details)),
    )
    monkeypatch.setattr(
        autofill_adapters.ai,
        "autofill_summary_dependencies",
        lambda *_args: {
            "complete": [SimpleNamespace()],
            "pending": [SimpleNamespace()],
            "failed": [],
        },
    )
    monkeypatch.setattr(
        autofill_adapters.ai,
        "generate_autofilled_submission",
        lambda _prompt: (_ for _ in ()).throw(
            AssertionError("Gemini must not run before summaries complete")
        ),
    )

    with pytest.raises(
        DeferredJobDependencyPendingError,
        match="still processing",
    ):
        adapter.prepare(context)

    assert phases[-1] == (
        DeferredJobPhase.SUMMARIZING,
        {"completed": 1, "total": 2},
    )

    monkeypatch.setattr(
        autofill_adapters.ai,
        "autofill_summary_dependencies",
        lambda *_args: {
            "complete": [],
            "pending": [],
            "failed": [SimpleNamespace()],
        },
    )
    with pytest.raises(
        DeferredJobDependencyFailedError,
        match="summary failed",
    ):
        adapter.prepare(context)


# @matrix ai deferred-jobs files : autofill checkpoint resume upload
def test_autofill_upload_checkpoint_records_durable_attachment(monkeypatch):
    adapter = autofill_adapters.AutofillAdapter()
    target = SimpleNamespace()
    actor = SimpleNamespace()
    upload = SimpleNamespace(
        filename="assessment evidence.pdf",
        content_type="application/pdf",
    )
    phases = []
    named_keys = []
    context = SimpleNamespace(
        actor=actor,
        job=SimpleNamespace(urlsafe_key="autofill-job-key"),
        parameters={"upload_record": {"token": "signed-upload"}},
        checkpoint={"submission": {"field-one": "Prepared answer"}},
        input=lambda name: target if name == "target" else None,
        set_phase=lambda phase, **details: phases.append((phase, details)),
    )
    monkeypatch.setattr(
        autofill_adapters.storage_assets,
        "direct_upload_file",
        lambda *_args, **_kwargs: upload,
    )
    monkeypatch.setattr(
        autofill_adapters.database,
        "create_named_key",
        lambda kind, identifier: (
            named_keys.append((kind, identifier)) or "named-file-key"
        ),
    )
    monkeypatch.setattr(
        autofill_adapters.database.get,
        "urlsafe_key",
        lambda key: f"encoded:{key}",
    )
    monkeypatch.setattr(
        autofill_adapters.dates,
        "user_today",
        lambda user: datetime(2026, 8, 21, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        autofill_adapters.ai,
        "generate_autofilled_submission",
        lambda _prompt: (_ for _ in ()).throw(
            AssertionError("a resumed checkpoint must not regenerate")
        ),
    )

    assert adapter.checkpoint_ready(context) is False
    checkpoint = adapter.prepare(context)
    context.checkpoint = checkpoint

    identity = hashlib.sha256(b"autofill-job-key").hexdigest()
    assert named_keys == [("file", f"autofill-{identity}")]
    assert checkpoint == {
        "submission": {"field-one": "Prepared answer"},
        "attachment": {
            "key": "encoded:named-file-key",
            "name": "2026-08-21-autofill",
            "filename": "assessment evidence.pdf",
            "mimetype": "application/pdf",
        },
    }
    assert adapter.checkpoint_ready(context) is True
    assert phases == [(DeferredJobPhase.PREPARING_INPUTS, {})]


# @matrix ai deferred-jobs files pages tasks : attachment autofill idempotency inspection naming upload
@pytest.mark.parametrize("target_kind", ["page", "task"])
def test_autofill_uploaded_file_is_attached_to_target(monkeypatch, target_kind):
    class Relation:
        def __init__(self, on_add=None):
            self.value = []
            self.on_add = on_add

        @property
        def keys(self):
            return [value.key for value in self.value]

        def add(self, value):
            if value.key in self.keys:
                return False
            self.value.append(value)
            if self.on_add:
                self.on_add(value)
            return True

    class Target:
        def __init__(self):
            self.key = f"{target_kind}-key"
            self.urlsafe_key = self.key
            self.entity_kind = target_kind
            self.properties = SimpleNamespace(
                submission=SimpleNamespace(value={}),
            )
            self.properties.files = Relation(
                on_add=lambda file: file.properties.tasks.add(self)
            )

        def ai_submission(self, submission):
            self.properties.submission.value = submission

        def save(self):
            raise AssertionError("an autofill attachment must save with its target")

    class Page(Target):
        pass

    class Task(Target):
        pass

    created = []

    class File:
        @classmethod
        def create(cls, page=None, upload=None, data=None, key=None):
            file = cls()
            file.key = key
            file.urlsafe_key = key
            file.upload = upload
            file.data = dict(data or {})
            file.properties = SimpleNamespace(
                pages=Relation(),
                tasks=Relation(),
            )
            if page:
                file.properties.pages.add(page)
            created.append(file)
            return file

    monkeypatch.setattr(autofill_adapters.Entities, "PAGE", Page)
    monkeypatch.setattr(autofill_adapters.Entities, "TASK", Task)
    monkeypatch.setattr(autofill_adapters.Entities, "FILE", File)

    target = Page() if target_kind == "page" else Task()
    upload = SimpleNamespace(
        filename="original.pdf",
        content_type="application/pdf",
    )
    stored = {}
    saved = []
    upload_loads = []

    def fetch_one(key, request):
        del request
        return stored.get(key)

    def save(*entities):
        saved.append(entities)
        for entity in entities:
            if isinstance(entity, File):
                stored["encoded-file-key"] = entity

    monkeypatch.setattr(autofill_adapters.Entities, "fetch_one", fetch_one)
    monkeypatch.setattr(autofill_adapters.Entities, "save", save)
    monkeypatch.setattr(
        autofill_adapters.storage_assets,
        "direct_upload_file",
        lambda record, **_kwargs: upload_loads.append(record) or upload,
    )
    monkeypatch.setattr(
        autofill_adapters.database.get,
        "datastore_key",
        lambda key: "file-key" if key == "encoded-file-key" else None,
    )

    context = SimpleNamespace(
        parameters={"upload_record": {"token": "signed-upload"}},
        checkpoint={
            "submission": {"field-one": "Autofilled answer"},
            "attachment": {
                "key": "encoded-file-key",
                "name": "2026-08-21-autofill",
                "filename": "original.pdf",
                "mimetype": "application/pdf",
            },
        },
        input=lambda name: target if name == "target" else None,
        ensure_active=lambda: None,
    )

    adapter = autofill_adapters.AutofillAdapter()
    result = adapter.apply(context)

    assert len(created) == 1
    assert upload_loads == [{"token": "signed-upload"}]
    assert upload.lagniappe_preserve_source is True
    assert created[0].data == {
        "name": "2026-08-21-autofill",
        "filename": "original.pdf",
        "mimetype": "application/pdf",
    }
    assert saved == [(created[0], target)]
    assert target.properties.submission.value == {"field-one": "Autofilled answer"}
    if target_kind == "page":
        assert created[0].properties.pages.keys == [target.key]
    else:
        assert target.properties.files.keys == [created[0].key]
        assert created[0].properties.tasks.keys == [target.key]
    assert result == {
        "target_key": target.key,
        "target_kind": target_kind,
        "file_key": "file-key",
    }
    assert adapter.inspect(context) is DeferredJobInspection.APPLIED

    adapter.apply(context)
    assert len(created) == 1
    assert upload_loads == [{"token": "signed-upload"}]
