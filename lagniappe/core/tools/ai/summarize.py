"""AI-powered file summarization with async task queue support."""

from flask_login import current_user

from ... import exceptions
from ...definitions import FileConsumer, enforce_file_consumer
from ..database import assets as storage_assets
from ..files import extract_ooxml_text, is_supported_ooxml
from ..files.ooxml import OOXMLExtractionError
from .core import ai_model, provider_error_details
from .guidelines import SUMMARY_GENERATION_GUIDELINES
from .prompt import Prompt

EXTRACTED_CONTEXT_LIMIT = 200_000
EXTRACTED_CONTEXT_NOTE = (
    "# This text was automatically extracted from {filename}. Formatting, "
    "formulas, dates, and embedded objects may be incomplete."
)
TRUNCATION_NOTE = "\n\n[Extracted text truncated at 200000 characters.]"
SUMMARY_RETRIEVAL_TERM_COUNT = 2
UNREADABLE_PDF_SUMMARY_ERROR = (
    "This PDF could not be read. It may be encrypted or password-protected."
)
PDF_PAGE_LIMIT_SUMMARY_ERROR = (
    "This PDF has more pages than the AI summary service supports."
)


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_summary_eligibility_includes_ooxml_fallback
# @features ai
# @dimensions summary-prompt ooxml eligibility
def can_summarize_file(file):
    """Return whether a file has an AI-readable original or OOXML fallback."""
    if _file_part(file):
        return True

    return is_supported_ooxml(
        filename=getattr(file, "filename", None),
        mimetype=getattr(file, "mimetype", None),
    )


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_summary_eligibility_includes_ooxml_fallback
# @tests tests_unit/test_006_file_properties.py::test_file_processing_dispatches_summary_before_extraction
# @pairs ai:summary-prompt ai:ooxml ai:eligibility ai:task-queue
def summarize_file(
    file,
    *,
    dispatch=True,
    parameters=None,
    idempotency_key=None,
):
    """Summarize a file synchronously in dev or via task queue in production.

    Args:
        file: The file entity to summarize.
    """
    summarize = file.properties.summarize
    eligible = can_summarize_file(file)

    if eligible:
        summarize.status = "Summarizing file..."
        if dispatch:
            from ...definitions import DeferredJobSpec, DeferredJobType
            from ..deferred_jobs.service import DeferredJobs

            DeferredJobs.start(
                DeferredJobSpec(
                    job_type=DeferredJobType.FILE_SUMMARIZE,
                    actor=current_user._get_current_object(),
                    inputs={"file": file},
                    parameters=dict(parameters or {}),
                    notification_body=None,
                    client={},
                    idempotency_key=idempotency_key,
                    delay_seconds=10,
                )
            )
    else:
        summarize.error = "Unsupported file type."

    return summarize


# @testable false
# @covered-by lagniappe/core/tools/ai/summarize.py::can_summarize_file
# @covered-by lagniappe/core/tools/ai/summarize.py::generate_summary
# @reason file part lookup is exercised through public summarization helpers
def _file_part(file):
    try:
        return file.properties.file.uri_to_ai
    except AttributeError:
        return None


# @testable false
# @covered-by lagniappe/core/tools/ai/summarize.py::generate_summary
# @reason prompt truncation is part of the OOXML fallback prompt contract
def _extracted_context(filename, text):
    label = filename or "the uploaded file"
    context = f"{EXTRACTED_CONTEXT_NOTE.format(filename=label)}\n\n{text.strip()}"
    if len(context) <= EXTRACTED_CONTEXT_LIMIT:
        return context

    cutoff = max(0, EXTRACTED_CONTEXT_LIMIT - len(TRUNCATION_NOTE))
    return f"{context[:cutoff].rstrip()}{TRUNCATION_NOTE}"


# @testable false
# @covered-by lagniappe/core/tools/ai/summarize.py::generate_summary
# @reason asset download and parser errors are surfaced through summary generation
def _add_ooxml_context(prompt, file):
    filename = getattr(file, "filename", None)
    mimetype = getattr(file, "mimetype", None)
    if not is_supported_ooxml(filename=filename, mimetype=mimetype):
        return False

    try:
        asset = file.get_asset("file")
        if asset:
            size = getattr(asset, "size", None)
            if size is None:
                size = storage_assets.file_size(asset.path, asset.visibility.value)
            enforce_file_consumer(
                size,
                FileConsumer.OOXML_EXTRACTION,
                filename=filename,
            )
        content = asset.get() if asset else None
        text = extract_ooxml_text(content, filename=filename, mimetype=mimetype)
    except (AttributeError, OOXMLExtractionError, ValueError) as error:
        raise exceptions.AIException(
            f"Could not extract text from {filename or 'Office file'}."
        ) from error

    if not str(text or "").strip():
        raise exceptions.AIException(
            f"No extractable text found in {filename or 'Office file'}."
        )

    prompt.add_context(
        "extracted_file_text",
        _extracted_context(filename, text),
    )
    return True


# @testable false
# @covered-by lagniappe/core/tools/ai/summarize.py::generate_summary
# @reason provider classification is exercised through summary error handling
def _is_unreadable_pdf_error(file, error):
    """Return whether Gemini rejected a PDF because it has no readable pages."""
    if getattr(file, "mimetype", None) != "application/pdf":
        return False

    details = provider_error_details(error)
    message = details.get("message") or details.get("raw") or ""
    return str(details.get("code")) == "400" and (
        "document has no pages" in message.casefold()
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/summarize.py::generate_summary
# @reason exact provider classification is exercised through summary error handling
def _is_pdf_page_limit_error(file, error):
    """Return whether Gemini rejected a PDF for exceeding its page limit."""
    if getattr(file, "mimetype", None) != "application/pdf":
        return False

    details = provider_error_details(error)
    message = details.get("message") or details.get("raw") or ""
    return str(details.get("code")) == "400" and (
        "exceeds the supported page limit" in message.casefold()
    )


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_summary_generation_updates_file_status_from_model_result
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_ai_summary_generation_uses_docx_text_fallback
# @tests tests_unit/test_015_ai_tools.py::test_ai_summary_generation_reports_ooxml_extraction_errors
# @tests tests_unit/test_015_ai_tools.py::test_ai_summary_generation_marks_unreadable_pdf_without_capture
# @tests tests_unit/test_015_ai_tools.py::test_ai_summary_generation_marks_pdf_page_limit_without_capture
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_ai_summary_generation_rejects_oversized_ooxml_before_download
# @tests tests_unit/test_015_ai_tools.py::test_ai_summary_generation_populates_file_search_cache
# @features ai
# @dimensions summary-prompt status errors cache quota ooxml docx unreadable-pdf pdf-page-limit
def generate_summary(
    file,
    raise_quota=False,
    raise_errors=False,
    service_tier=None,
):
    """Generate a summary and two reusable workspace retrieval terms."""
    summarize = file.properties.summarize

    try:
        intro = (
            "You are a summary generation AI. Generate a concise summary of the "
            "attached file."
        )
        prompt = Prompt(intro, type="file summary")
        prompt.add_instructions(SUMMARY_GENERATION_GUIDELINES)
        prompt.set_output_format(
            "JSON",
            description=(
                "Return the user-facing summary and exactly two broad, "
                "independently useful workspace search terms."
            ),
        )
        prompt.set_response_schema(_summary_response_schema())
        prompt.set_model_tier("utility")
        if service_tier:
            prompt.set_service_tier(service_tier)
        prompt.add_file(file)
        if not prompt.files:
            _add_ooxml_context(prompt, file)

        summary, retrieval_terms = ai_model.generate_content(
            prompt,
            validator=_summary_and_retrieval_terms,
        )
        summarize.status = "Summary generated successfully."
        summarize.enabled = True
        summarize.search = True
        summarize.retrieval_terms = retrieval_terms or None
        summarize.complete = True
        file.summary = summary
        return summarize
    except exceptions.AIQuotaError as e:
        if raise_quota:
            raise
        exceptions.capture(e)
        summarize.error = f"AI unable to generate summary: {str(e)}"
        return summarize
    except exceptions.AIException as e:
        if raise_errors:
            raise
        exceptions.capture(e)
        summarize.error = f"AI unable to generate summary: {str(e)}"
        return summarize
    except Exception as e:
        if _is_pdf_page_limit_error(file, e):
            summarize.status = "PDF exceeds the AI summary page limit."
            summarize.error = PDF_PAGE_LIMIT_SUMMARY_ERROR
            return summarize
        if _is_unreadable_pdf_error(file, e):
            summarize.status = "PDF could not be read."
            summarize.error = UNREADABLE_PDF_SUMMARY_ERROR
            return summarize
        if raise_errors:
            raise
        exceptions.capture(e)
        summarize.error = f"Summary generation failed. {str(e)}"
        return summarize


# @testable false
# @covered-by lagniappe/core/tools/ai/summarize.py::generate_summary
# @reason provider schema and term cardinality are asserted through summary generation
def _summary_response_schema():
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "retrieval_terms": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": SUMMARY_RETRIEVAL_TERM_COUNT,
                "maxItems": SUMMARY_RETRIEVAL_TERM_COUNT,
            },
        },
        "required": ["summary", "retrieval_terms"],
        "propertyOrdering": ["summary", "retrieval_terms"],
        "additionalProperties": False,
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/summarize.py::generate_summary
# @reason response cleanup is observed through stored summary and retrieval terms
def _summary_and_retrieval_terms(response):
    if isinstance(response, str):
        summary = response.strip()
        terms = []
    elif isinstance(response, dict):
        summary = str(response.get("summary") or "").strip()
        terms = _clean_retrieval_terms(response.get("retrieval_terms"))
    else:
        summary = ""
        terms = []
    if not summary:
        raise exceptions.AIException("AI did not return a file summary.")
    return summary, terms


# @testable false
# @covered-by lagniappe/core/tools/ai/summarize.py::generate_summary
# @reason term cleanup is observed through stored summary retrieval metadata
def _clean_retrieval_terms(values):
    if not isinstance(values, list):
        return []
    terms = []
    seen = set()
    for value in values:
        term = str(value or "").strip()
        normalized = term.casefold()
        if not term or len(term) > 80 or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(term)
        if len(terms) == SUMMARY_RETRIEVAL_TERM_COUNT:
            break
    return terms
