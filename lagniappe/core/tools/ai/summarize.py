"""AI-powered file summarization with async task queue support."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...entities.file import File
    from ...entities.user import User
    from ...properties.file_options import Summarize

from ... import exceptions
from ...definitions import FileConsumer, enforce_file_consumer
from ..database import assets as storage_assets
from ..files.ooxml import extract_ooxml, is_supported_ooxml
from ..files.ooxml import OOXMLExtractionError, OOXMLTruncationReason
from .core import ai_model
from .guidelines import SUMMARY_GENERATION_GUIDELINES
from .prompt import Prompt
from .provider_policy import provider_error_details

EXTRACTED_CONTEXT_LIMIT = 200_000
EXTRACTED_CONTEXT_NOTE = (
    "# This text was automatically extracted from {filename}. Formatting, "
    "formulas, dates, and embedded objects may be incomplete."
)
TRUNCATION_NOTES = {
    OOXMLTruncationReason.OUTPUT: (
        "\n\n[Extracted text is partial because the prompt-text limit was reached.]"
    ),
    OOXMLTruncationReason.XML_BYTES: (
        "\n\n[Extracted text is partial because the XML processing limit was reached.]"
    ),
    OOXMLTruncationReason.ELEMENTS: (
        "\n\n[Extracted text is partial because the XML element limit was reached.]"
    ),
    OOXMLTruncationReason.SHEETS: (
        "\n\n[Extracted text is partial because the worksheet limit was reached.]"
    ),
    OOXMLTruncationReason.ROWS: (
        "\n\n[Extracted text is partial because the worksheet row limit was reached.]"
    ),
    OOXMLTruncationReason.CELLS: (
        "\n\n[Extracted text is partial because the worksheet cell limit was reached.]"
    ),
    OOXMLTruncationReason.DEADLINE: (
        "\n\n[Extracted text is partial because the extraction time limit was reached.]"
    ),
}
SUMMARY_RETRIEVAL_TERM_COUNT = 2
UNREADABLE_PDF_SUMMARY_ERROR = (
    "This PDF could not be read. It may be encrypted or password-protected."
)
PDF_PAGE_LIMIT_SUMMARY_ERROR = (
    "This PDF has more pages than the AI summary service supports."
)


def can_summarize_file(file: File) -> bool:
    """Return whether a file has an AI-readable original or OOXML fallback."""
    if _file_part(file):
        return True

    return is_supported_ooxml(
        filename=getattr(file, "filename", None),
        mimetype=getattr(file, "mimetype", None),
    )


def summarize_file(
    file: File,
    *,
    actor: User | None = None,
    dispatch: bool = True,
    parameters: dict[str, object] | None = None,
    idempotency_key: str | None = None,
) -> Summarize:
    """Prepare summary status and optionally queue work for an explicit actor."""
    if dispatch and (actor is None or not getattr(actor, "is_authenticated", False)):
        raise exceptions.ValidationError("File processing requires an authenticated actor.")
    summarize = file.properties.summarize
    eligible = can_summarize_file(file)

    if eligible:
        summarize.status = "Summarizing file..."
        if dispatch:
            assert actor is not None
            from ...definitions import DeferredJobSpec, DeferredJobType
            from ..deferred_jobs.service import DeferredJobs

            DeferredJobs.start(
                DeferredJobSpec(
                    job_type=DeferredJobType.FILE_SUMMARIZE,
                    actor=actor,
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


def _file_part(file):
    try:
        return file.properties.file.uri_to_ai
    except AttributeError:
        return None


def _extracted_context_header(filename):
    label = filename or "the uploaded file"
    return f"{EXTRACTED_CONTEXT_NOTE.format(filename=label)}\n\n"


def _extracted_context(filename, result):
    header = _extracted_context_header(filename)
    text = result.text.strip()
    note = TRUNCATION_NOTES.get(result.truncation_reason, "")
    if note:
        cutoff = max(0, EXTRACTED_CONTEXT_LIMIT - len(header) - len(note))
        text = text[:cutoff].rstrip()
    context = f"{header}{text}{note}"
    if len(context) <= EXTRACTED_CONTEXT_LIMIT:
        return context

    return context[:EXTRACTED_CONTEXT_LIMIT].rstrip()


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
        text_limit = EXTRACTED_CONTEXT_LIMIT - len(_extracted_context_header(filename))
        result = extract_ooxml(
            content,
            filename=filename,
            mimetype=mimetype,
            max_characters=text_limit,
        )
    except (AttributeError, OOXMLExtractionError, ValueError) as error:
        raise exceptions.AIException(
            f"Could not extract text from {filename or 'Office file'}."
        ) from error

    if result is None or not str(result.text or "").strip():
        raise exceptions.AIException(
            f"No extractable text found in {filename or 'Office file'}."
        )

    prompt.add_context(
        "extracted_file_text",
        _extracted_context(filename, result),
    )
    return True


def _is_unreadable_pdf_error(file, error):
    """Return whether Gemini rejected a PDF because it has no readable pages."""
    if getattr(file, "mimetype", None) != "application/pdf":
        return False

    details = provider_error_details(error)
    message = details.get("message") or details.get("raw") or ""
    return str(details.get("code")) == "400" and (
        "document has no pages" in message.casefold()
    )


def _is_pdf_page_limit_error(file, error):
    """Return whether Gemini rejected a PDF for exceeding its page limit."""
    if getattr(file, "mimetype", None) != "application/pdf":
        return False

    details = provider_error_details(error)
    message = details.get("message") or details.get("raw") or ""
    return str(details.get("code")) == "400" and (
        "exceeds the supported page limit" in message.casefold()
    )


def generate_summary(
    file: File,
    raise_quota: bool = False,
    raise_errors: bool = False,
    service_tier: str | None = None,
) -> Summarize:
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
