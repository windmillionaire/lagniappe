"""Text extraction from files via Document AI OCR and direct reading."""

from flask_login import current_user
from google.cloud import documentai

from lagniappe import CONFIG

from ... import exceptions
from .constants import DOCUMENT_AI_MIMETYPES


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_extract_update_completes_immediately_for_text_files
# @tests tests_unit/test_006_file_properties.py::test_file_processing_dispatches_summary_before_extraction
# @features file
# @dimensions extract, text-asset, process-complete, deferred-dispatch
def get_file_text(file, *, dispatch=True):
    """Initiate text extraction for a file, dispatching to OCR or a background task.

    Args:
        file: File entity with mimetype and URI accessors.

    Returns:
        Dict with extraction status, and 'text' or 'error' when complete.
    """
    extract = file.properties.extract

    text = file.properties.text

    if text.value:
        extract.status = "Text extraction complete."
        extract.complete = True
    elif text.extractable:
        extract.status = "Extracting text..."
        if dispatch:
            start_file_extraction(file)
    else:
        extract.error = "Unsupported file type."

    return extract


# @testable true
# @tests tests_unit/test_023e_deferred_job_adapters_files.py::test_start_file_extraction_uses_explicit_actor_and_identity
# @features deferred-jobs file
# @dimensions follow-up extraction idempotency
def start_file_extraction(
    file,
    *,
    actor=None,
    idempotency_key=None,
    delay_seconds=5,
):
    """Dispatch extraction for a persisted file with an optional stable identity."""
    from ...definitions import DeferredJobSpec, DeferredJobType
    from ..deferred_jobs.service import DeferredJobs

    return DeferredJobs.start(
        DeferredJobSpec(
            job_type=DeferredJobType.FILE_EXTRACT,
            actor=actor or current_user._get_current_object(),
            inputs={"file": file},
            notification_body=None,
            client={},
            idempotency_key=idempotency_key,
            delay_seconds=delay_seconds,
        )
    )


# Document AI docs: https://cloud.google.com/document-ai/docs/ocr
# @testable false
# @covered-by lagniappe/core/tools/files/extract.py::get_file_text
# @reason Document AI OCR is external-service behavior owned by process/E2E workflows
def ocr_file(file, raise_errors=False):
    """Run Document AI OCR on a GCS file and return the extracted text.

    Args:
        file: File entity with mimetype and URI accessors.

    Returns:
        Extract process property.
    """
    file_uri = file.get_asset("file").uri
    mime_type = file.mimetype
    extract = file.properties.extract

    if file.mimetype not in DOCUMENT_AI_MIMETYPES:
        extract.error = "Unsupported file type."
        return extract

    try:
        client = documentai.DocumentProcessorServiceClient(
            credentials=CONFIG.google_credentials
        )

        name = CONFIG.OCR_PROCESSOR_ID

        mime_type = mime_type if mime_type else "application/octet-stream"
        request = documentai.ProcessRequest(
            name=name,
            gcs_document=documentai.GcsDocument(gcs_uri=file_uri, mime_type=mime_type),
        )

        result = client.process_document(request=request)
        document = result.document

        if document and document.text:
            extract.status = "Text extracted successfully."
            extract.complete = True
            file.text = document.text
        else:
            extract.error = "No text found in document."
    except Exception as e:
        exceptions.capture(e)
        extract.error = str(e)
        if raise_errors:
            raise

    return extract
