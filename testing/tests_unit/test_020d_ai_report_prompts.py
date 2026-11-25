"""Focused AI-report characterization coverage."""

from collections import Counter
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock, get_ident
from types import SimpleNamespace

from google.genai import errors
import pytest

from lagniappe.core import exceptions
from lagniappe.core.definitions import LARGE_ASSET_BYTES
from lagniappe.core.tools.ai import planner, summarize
from lagniappe.core.tools.ai.observability import ai_execution_context, current_execution_control
from lagniappe.core.tools.ai.reporting.completion import files as organize_completion
from lagniappe.core.tools.deferred_jobs.control import DeferredExecutionControl
from lagniappe.core.tools.deferred_jobs.errors import DeferredJobClaimLostError
from testing.utility.ai_report_fakes import (
    _prompt_context_json,
    _test_file,
    _test_user,
)
from testing.utility.test_entities import TestEntities


@pytest.mark.unit
def test_summarize_report_input_files_saves_missing_summaries(monkeypatch):
    user = _test_user("summary-prepass-owner")
    first = _test_file("first.pdf", "application/pdf")
    office = _test_file(
        "agenda.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    markdown = _test_file("service-confirmation.md", "text/markdown")
    vcard = _test_file("marisol-vega.vcf", "text/vcard")
    second = _test_file("second.pdf", "application/pdf")
    existing = _test_file("existing.pdf", "application/pdf")
    unsupported = _test_file("archive.zip", "application/zip")
    existing.summary = "Already summarized."
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Summary prepass",
            "hash": "summary-prepass-report",
            "parent": user,
            "user": user,
            "input_files": [
                first,
                office,
                markdown,
                vcard,
                existing,
                unsupported,
                second,
            ],
        },
    )
    generated = []
    saved = []
    active_checks = []

    def fake_generate_summary(file, raise_quota=False, service_tier=None):
        assert raise_quota is True
        assert service_tier == "priority"
        generated.append(file.filename)
        file.summary = f"Summary for {file.filename}"
        return file.properties.summarize

    monkeypatch.setattr(organize_completion, "generate_summary", fake_generate_summary)

    summarized = organize_completion.summarize_report_input_files(
        report,
        save=saved.append,
        service_tier="priority",
        ensure_active=lambda: active_checks.append(True),
    )

    assert summarized == [first, office, markdown, vcard, second]
    assert Counter(saved) == Counter([first, office, markdown, vcard, second])
    assert Counter(generated) == Counter([
        "first.pdf",
        "agenda.docx",
        "service-confirmation.md",
        "marisol-vega.vcf",
        "second.pdf",
    ])
    assert first.properties.summarize.enabled is True
    assert first.properties.summarize.search is True
    assert first.properties.summarize.complete is True
    assert office.properties.summarize.enabled is True
    assert office.properties.summarize.search is True
    assert office.properties.summarize.complete is True
    assert markdown.properties.summarize.enabled is True
    assert markdown.properties.summarize.search is True
    assert markdown.properties.summarize.complete is True
    assert vcard.properties.summarize.enabled is True
    assert vcard.properties.summarize.search is True
    assert vcard.properties.summarize.complete is True
    assert second.properties.summarize.enabled is True
    assert second.properties.summarize.search is True
    assert second.properties.summarize.complete is True
    assert existing.summary == "Already summarized."
    assert unsupported.summary is None
    assert active_checks

    unindexed = _test_file("unindexed.pdf", "application/pdf")
    unindexed_report = TestEntities.get(
        "REPORT",
        {
            "name": "Summary prepass without search",
            "hash": "summary-prepass-unindexed-report",
            "parent": user,
            "user": user,
            "input_files": [unindexed],
        },
    )

    def no_quota_summary(file, raise_quota=False):
        assert raise_quota is False
        file.summary = "Unindexed summary."
        return file.properties.summarize

    monkeypatch.setattr(organize_completion, "generate_summary", no_quota_summary)

    summarized = organize_completion.summarize_report_input_files(
        unindexed_report, search=False, raise_quota=False
    )

    assert summarized == [unindexed]
    assert unindexed.summary == "Unindexed summary."
    assert unindexed.properties.summarize.enabled is True
    assert unindexed.properties.summarize.search is False
    assert unindexed.properties.summarize.complete is True

    third = _test_file("third.pdf", "application/pdf")
    fourth = _test_file("fourth.pdf", "application/pdf")
    quota_report = TestEntities.get(
        "REPORT",
        {
            "name": "Summary prepass quota",
            "hash": "summary-prepass-quota-report",
            "parent": user,
            "user": user,
            "input_files": [third, fourth],
        },
    )
    quota_saved = []

    def quota_after_first(file, raise_quota=False):
        if file is fourth:
            raise exceptions.AIQuotaError("quota busy")
        file.summary = "Third summary."
        return file.properties.summarize

    monkeypatch.setattr(organize_completion, "generate_summary", quota_after_first)

    with pytest.raises(exceptions.AIQuotaError):
        organize_completion.summarize_report_input_files(
            quota_report, save=quota_saved.append
        )

    assert quota_saved == [third]
    assert third.summary == "Third summary."
    assert third.properties.summarize.enabled is True
    assert third.properties.summarize.search is True
    assert third.properties.summarize.complete is True
    assert fourth.summary is None
    retried = []

    def finish(file, **kwargs):
        retried.append(file)
        file.summary = "Fourth summary."

    monkeypatch.setattr(organize_completion, "generate_summary", finish)
    assert organize_completion.summarize_report_input_files(quota_report, save=quota_saved.append) == [fourth]
    assert retried == [fourth] and quota_saved == [third, fourth]


@pytest.mark.unit
def test_summarize_report_input_files_falls_back_for_large_files(monkeypatch):
    user = _test_user("large-summary-owner")
    supported = _test_file("large-source.pdf", "application/pdf")
    unsupported = _test_file("large-source.zip", "application/zip")
    small = _test_file("small-source.zip", "application/zip")
    supported.test_spec["asset_sizes"] = {"file": LARGE_ASSET_BYTES + 1}
    unsupported.test_spec["asset_sizes"] = {"file": LARGE_ASSET_BYTES + 1}
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Large summary fallback",
            "hash": "large-summary-report",
            "parent": user,
            "user": user,
            "input_files": [supported, unsupported, small],
        },
    )
    generated = []
    saved = []

    def no_summary(file, raise_quota=False):
        assert raise_quota is True
        generated.append(file.filename)
        file.properties.summarize.error = "Provider did not return a summary."
        return file.properties.summarize

    monkeypatch.setattr(organize_completion, "generate_summary", no_summary)

    summarized = organize_completion.summarize_report_input_files(
        report, save=saved.append
    )

    assert generated == ["large-source.pdf"]
    assert summarized == [supported, unsupported]
    assert Counter(saved) == Counter([supported, unsupported])
    assert supported.summary == organize_completion.OVERSIZED_REPORT_SUMMARY
    assert unsupported.summary == organize_completion.OVERSIZED_REPORT_SUMMARY
    assert small.summary is None
    assert supported.properties.summarize.error is None
    assert supported.properties.summarize.complete is True
    assert unsupported.properties.summarize.complete is True

    prompt_files = _prompt_context_json(
        planner.report_prompt(report, user),
        "Report Input Files",
    )
    by_filename = {item["filename"]: item for item in prompt_files}
    assert by_filename["large-source.pdf"]["summary"] == (
        organize_completion.OVERSIZED_REPORT_SUMMARY
    )
    assert by_filename["large-source.pdf"]["large"] is True
    assert by_filename["large-source.zip"]["display_name"] == "large-source"


@pytest.mark.unit
def test_parallel_file_summaries_keep_job_control_and_checkpoint_on_caller(monkeypatch):
    files = [_test_file(f"receipt-{index}.pdf") for index in range(8)]
    progress, saved = [], []
    control = DeferredExecutionControl(
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
        active_check=lambda: True, progress_callback=progress.append,
    )
    coordinator = get_ident()
    barrier = Barrier(4, timeout=5)
    lock = Lock()
    active = peak = 0

    def generate(file, **_options):
        nonlocal active, peak
        assert current_execution_control() is control
        control.before_provider("initial")
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait()
        file.summary = file.filename
        control.set_phase("validating")
        with lock:
            active -= 1

    def save(file):
        assert get_ident() == coordinator
        saved.append(file)

    monkeypatch.setattr(organize_completion, "generate_summary", generate)
    with ai_execution_context(execution_control=control):
        result = organize_completion.summarize_report_input_files(
            SimpleNamespace(input_files=files), save=save, ensure_active=control.ensure_active,
        )
    control.before_provider("initial")
    assert result == files and Counter(saved) == Counter(files)
    assert peak == 4
    assert [entry["phase"] for entry in progress] == ["summarizing", "generating"]


@pytest.mark.unit
def test_cancelled_summary_does_not_save_or_dispatch_more_files(monkeypatch):
    files = [_test_file(f"receipt-{index}.pdf") for index in range(8)]
    saved, started = [], []
    active = True

    def check():
        if not active:
            raise DeferredJobClaimLostError("cancelled")

    def generate(file, **_options):
        nonlocal active
        started.append(file)
        file.summary = file.filename
        active = False

    monkeypatch.setattr(organize_completion, "generate_summary", generate)
    with pytest.raises(DeferredJobClaimLostError):
        organize_completion.summarize_report_input_files(
            SimpleNamespace(input_files=files), save=saved.append, ensure_active=check,
        )
    assert 1 <= len(started) <= 4
    assert saved == []


@pytest.mark.unit
@pytest.mark.parametrize("token_count,direct", [(32_000, True), (32_001, False), (None, False), ("unavailable", False)])
def test_mixed_upload_budget_counts_all_originals_in_one_primary_request(monkeypatch, token_count, direct):
    from lagniappe.core.tools.ai import core

    pdf = _test_file("invoice.pdf", "application/pdf")
    note = _test_file("purchase.json", "application/json")
    for file in [pdf, note]:
        file.test_spec["asset_sizes"] = {"file": 20_000}
    counts = []

    def count_tokens(*, model, contents, config):
        counts.append(model)
        assert [item.file_data.file_uri for item in contents] == [
            "gs://private-bucket/invoice.pdf", "gs://private-bucket/purchase.json",
        ]
        assert [item.file_data.mime_type for item in contents] == ["application/pdf", "text/plain"]
        assert config.http_options.retry_options.attempts == 1
        if token_count == "unavailable":
            raise errors.ServerError(503, {"error": {"message": "Service unavailable"}})
        return SimpleNamespace(total_tokens=token_count)

    monkeypatch.setattr(core, "runtime_ai_settings", lambda: {"AI_MODEL": "configured-primary"})
    monkeypatch.setattr(core.GenAI, "_client", SimpleNamespace(models=SimpleNamespace(count_tokens=count_tokens)))
    assert organize_completion.use_original_report_files(SimpleNamespace(input_files=[pdf, note])) is direct
    assert counts == ["configured-primary"]


@pytest.mark.unit
@pytest.mark.parametrize("reason", ["large", "unknown size", "unsupported", "existing summary"])
def test_unsuitable_bundles_reuse_summary_path_without_provider_preflight(monkeypatch, reason):
    mimetype = "application/zip" if reason == "unsupported" else "text/plain"
    file = _test_file("upload", mimetype)
    if reason != "unknown size":
        file.test_spec["asset_sizes"] = {"file": LARGE_ASSET_BYTES + 1 if reason == "large" else 100}
    if reason == "existing summary":
        file.summary = "Previously saved summary"

    monkeypatch.setattr(planner.ai_model, "count_file_tokens", lambda *_: pytest.fail("Unnecessary count"))
    assert not organize_completion.use_original_report_files(SimpleNamespace(input_files=[file]))


@pytest.mark.unit
def test_unreadable_pdf_is_saved_skipped_and_reported(monkeypatch):
    user = _test_user("unreadable-pdf-owner")
    file = _test_file("locked-policy.pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Unreadable PDF report",
            "hash": "unreadable-pdf-report",
            "parent": user,
            "user": user,
            "input_files": [file],
        },
    )
    generated = []
    saved = []

    def unreadable_summary(target, raise_quota=False):
        assert raise_quota is True
        generated.append(target.filename)
        target.properties.summarize.status = "PDF could not be read."
        target.properties.summarize.error = summarize.UNREADABLE_PDF_SUMMARY_ERROR
        return target.properties.summarize

    monkeypatch.setattr(organize_completion, "generate_summary", unreadable_summary)

    summarized = organize_completion.summarize_report_input_files(
        report, save=saved.append
    )
    retried = organize_completion.summarize_report_input_files(
        report, save=saved.append
    )

    assert summarized == []
    assert retried == []
    assert generated == ["locked-policy.pdf"]
    assert saved == [file]

    prompt_files = _prompt_context_json(
        planner.report_prompt(report, user),
        "Report Input Files",
    )
    warning = (
        "Could not read locked-policy.pdf. The PDF may be encrypted or "
        "password-protected."
    )
    assert prompt_files[0]["summary_warning"] == warning
