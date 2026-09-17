"""Registration of the built-in deferred-job strategy cohort."""

from .autofill import AutofillAdapter
from .email import EmailIngestAdapter
from .files import FileExtractAdapter, FileSummarizeAdapter
from .form_change import FormChangeAdapter
from .reports import (
    AIReportAdapter,
    ReportExecutionAdapter,
)


# @testable infrastructure
# @covered-by lagniappe/core/tools/deferred_jobs/adapters/registry.py::DeferredJobAdapterRegistry.adapter
def register_adapters(registry):
    """Register the clean-cutover deferred workflow cohort."""
    for adapter in (
        EmailIngestAdapter(),
        AIReportAdapter(),
        ReportExecutionAdapter(),
        AutofillAdapter(),
        FileExtractAdapter(),
        FileSummarizeAdapter(),
        FormChangeAdapter(),
    ):
        registry.register(adapter)
