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
from lagniappe.core.tools import database
from lagniappe.core.tools.services import task_queue
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
from lagniappe.core.tools.deferred_jobs.adapters import pages as page_adapters


# @pair ai:page-generation
# @pair pages:form-defaults
# @pair pages:no-form
def test_page_generation_apply_uses_direct_fields_and_form_fallbacks(monkeypatch):
    created = []
    saved = []

    class GeneratedPage:
        @classmethod
        def create(cls, data):
            page = cls()
            page.name = data.get("name")
            page.description = data.get("description")
            page.form = data.get("form")
            page.properties = SimpleNamespace(
                document=SimpleNamespace(html=None),
            )
            page.urlsafe_key = f"page-{len(created) + 1}"
            page.submission = None
            created.append(page)
            return page

        def ai_submission(self, submission):
            self.submission = dict(submission)
            self.name = submission.get("name", self.name)
            self.description = submission.get("description", self.description)

    monkeypatch.setattr(page_adapters.Entities, "PAGE", GeneratedPage)
    monkeypatch.setattr(
        page_adapters.Entities,
        "fetch_one",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        page_adapters.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    monkeypatch.setattr(
        page_adapters.database.get,
        "datastore_key",
        lambda key: f"datastore:{key}",
    )

    category = SimpleNamespace()
    adapter = page_adapters.PageGenerationAdapter()

    without_form = SimpleNamespace(
        ensure_active=lambda: None,
        checkpoint={
            "pages": [
                {
                    "key": "plain-key",
                    "page": {
                        "submission": {
                            "name": "Legacy fallback name",
                            "description": "Legacy fallback description",
                        }
                    },
                }
            ]
        },
        input=lambda name: category if name == "category" else None,
    )
    assert adapter.apply(without_form) == {"page_keys": ["page-1"]}
    assert created[0].name == "Legacy fallback name"
    assert created[0].description == "Legacy fallback description"
    assert created[0].submission is None

    form = SimpleNamespace(
        schema=[
            {"id": "name"},
            {"id": "description"},
            {"id": "input-topic"},
        ]
    )
    with_form = SimpleNamespace(
        ensure_active=lambda: None,
        checkpoint={
            "pages": [
                {
                    "key": "formed-key",
                    "page": {
                        "name": "Direct name",
                        "description": "Direct description",
                        "submission": {
                            "name": "Stale form name",
                            "description": "Stale form description",
                            "input-topic": "Preserved topic",
                        },
                    },
                }
            ]
        },
        input=lambda name: {
            "category": category,
            "form": form,
        }.get(name),
    )
    assert adapter.apply(with_form) == {"page_keys": ["page-2"]}
    assert created[1].name == "Direct name"
    assert created[1].description == "Direct description"
    assert created[1].submission == {
        "name": "Direct name",
        "description": "Direct description",
        "input-topic": "Preserved topic",
    }
    assert len(saved) == 2
