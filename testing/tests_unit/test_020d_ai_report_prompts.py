"""Focused AI-report characterization coverage."""

import pytest

from lagniappe.core import exceptions
from lagniappe.core.definitions import LARGE_ASSET_BYTES
from lagniappe.core.tools.ai import planner, summarize
from lagniappe.core.tools.ai.reporting.completion import files as organize_completion
from testing.utility.ai_report_fakes import (
    _prompt_context_json,
    _test_file,
    _test_user,
)
from testing.utility.test_entities import TestEntities


# @matrix ai-report : active-request quota search-opt-in service-tier summary-prepass
# @pair files:normalization
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
    assert saved == [first, office, markdown, vcard, second]
    assert generated == [
        "first.pdf",
        "agenda.docx",
        "service-confirmation.md",
        "marisol-vega.vcf",
        "second.pdf",
    ]
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
    assert len(active_checks) == 12

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


# @matrix ai-report : fallback large-file summary-prepass
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
    assert saved == [supported, unsupported]
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


# @matrix ai-report : issue persistence summary-prepass unreadable-pdf
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
