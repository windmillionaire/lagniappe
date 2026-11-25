"""Reconcile the Document AI OCR processor selected by the installation."""

from __future__ import annotations

from config import constants
from installer import FORMATTER
from installer.errors import classify_provider_error, retry_provider_call
from installer.package_install import install_if_missing
from installer.state import record_mutation


def create_ocr_processor() -> bool | None:
    from config import SETTINGS

    f = FORMATTER.initialize()

    with f.progress(
        text="Configure OCR processor",
        success_text='OCR processor configured',
    ) as sp:
        install_if_missing(
            "google.cloud.documentai",
            "Google Document AI",
            package_name="google-cloud-documentai",
        )
        install_if_missing(
            "google.api_core", "Google API Core", package_name="google-api-core"
        )
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai
        from google.api_core import exceptions as api_exceptions

        project_id = str(SETTINGS.GCLOUD_CONFIG["PROJECT"])
        location = str(SETTINGS.APP["OCR_LOCATION"])

        try:
            opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
            client = documentai.DocumentProcessorServiceClient(client_options=opts)
            parent = client.common_location_path(project_id, location)
            display_name = SETTINGS.APP.get(
                "OCR_PROCESSOR", constants.DEFAULT_OCR_PROCESSOR_NAME
            )
            saved_processor = SETTINGS.APP.get("OCR_PROCESSOR_ID")
            if isinstance(saved_processor, str) and saved_processor:
                try:
                    processor = client.get_processor(name=saved_processor)
                    if processor.display_name != display_name:
                        raise RuntimeError(
                            "Saved OCR processor display name does not match "
                            "the provider resource."
                        )
                    sp.ok()
                    record_mutation(
                        "reconcile OCR processor",
                        action="existing",
                        resource="document-ai-processor",
                        identifier=processor.name,
                    )
                    return True
                except api_exceptions.NotFound:
                    pass

            if not saved_processor:
                processor_list = client.list_processors(parent=parent)
                for processor in processor_list.processors:
                    if processor.display_name == display_name:
                        SETTINGS.APP["OCR_PROCESSOR_ID"] = processor.name
                        SETTINGS.APP["OCR_PROCESSOR"] = processor.display_name
                        SETTINGS.save()
                        record_mutation(
                            "reconcile OCR processor",
                            action="existing",
                            resource="document-ai-processor",
                            identifier=processor.name,
                        )
                        sp.ok()
                        return True

            processor = retry_provider_call(
                lambda: client.create_processor(
                    parent=parent,
                    processor=documentai.Processor(
                        display_name=display_name,
                        type_="OCR_PROCESSOR",
                    ),
                ),
                description=f"Create OCR processor {display_name}",
            )
            processor = retry_provider_call(
                lambda: client.get_processor(name=processor.name),
                description=f"Verify OCR processor {processor.name}",
            )

            SETTINGS.APP["OCR_PROCESSOR_ID"] = processor.name
            SETTINGS.APP["OCR_PROCESSOR"] = processor.display_name
            record_mutation(
                "reconcile OCR processor",
                action="created",
                resource="document-ai-processor",
                identifier=processor.name,
            )
            SETTINGS.save()
            sp.ok()
        except Exception as e:
            sp.write(f.error("Failed to create OCR processor.", e), raw=True)
            sp.fail()
            raise classify_provider_error(
                e,
                message="Failed to reconcile the OCR processor.",
            ) from e
