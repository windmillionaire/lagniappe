"""Focused contracts for lockless create-page autofill."""

from types import SimpleNamespace

import pytest

from lagniappe.core.tools import deferred_job_adapters


pytestmark = pytest.mark.unit


# @pairs deferred-jobs:form-lock pages:create-autofill
def test_create_page_autofill_explicitly_opts_out_of_target_lock():
    adapter = deferred_job_adapters.AutofillAdapter()
    spec = SimpleNamespace(
        inputs={"target": SimpleNamespace(urlsafe_key="new-page")},
        parameters={"lock_target": False},
    )
    job = SimpleNamespace(urlsafe_key="operation", idempotency_key="request")

    assert adapter.start_lock(spec, job) is None


# @pairs deferred-jobs:form-revision pages:create-autofill
def test_lockless_create_page_autofill_keeps_revision_drift_guard(monkeypatch):
    target = SimpleNamespace(autofill_revision="revision-one")
    context = SimpleNamespace(
        parameters={"lock_target": False},
        job=SimpleNamespace(
            urlsafe_key="operation",
            authorization={"form_revision": "revision-one"},
        ),
        input=lambda name: target if name == "target" else None,
    )
    monkeypatch.setattr(
        deferred_job_adapters,
        "active_deferred_job_lock",
        lambda _target: (_ for _ in ()).throw(
            AssertionError("lockless create autofill queried a target lock")
        ),
    )

    deferred_job_adapters.AutofillAdapter().validate_apply(context)

    target.autofill_revision = "revision-two"
    with pytest.raises(deferred_job_adapters.DeferredJobDriftError):
        deferred_job_adapters.AutofillAdapter().validate_apply(context)
