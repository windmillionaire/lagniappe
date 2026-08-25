from ..mixins import ColumnMixin
from ..tools.ai import summarize_file
from ..tools.files import get_file_text
from .base_process import ProcessProperty
from .base_property import Property


# @testable false
# @covered-by lagniappe/core/properties/file_options.py::Extract.update
# @covered-by lagniappe/core/properties/file_options.py::Summarize.update
# @reason small submitted-field guard is owned by option update behavior
def _has_any(form_data, *field_names):
    return any(form_data.get(name) is not None for name in field_names)


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_extract_process
# @matrix file : extract process
class Extract(ProcessProperty):
    """Text extraction options (OCR via Document AI).

    When complete, stores the extracted text on the entity. Attributes:
    enabled, search (include in search cache), status.
    """

    process_id = "options"
    section_id = "extract"
    attributes = ("status", "enabled", "search")

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_extract_process
    # @tests tests_unit/test_006_file_properties.py::test_extract_update_completes_immediately_for_text_files
    # @tests tests_unit/test_006_file_properties.py::test_file_update_preserves_processing_options_when_controls_absent
    # @tests tests_unit/test_006_file_properties.py::test_file_processing_dispatches_summary_before_extraction
    # @matrix file : deferred-dispatch extract option-preservation process-complete text-asset update
    def update(self, data):
        if not _has_any(data, "enable-extract", "extract", "search-text"):
            return False

        self.enabled = (
            data.get("enable-extract") is not None or data.get("extract") is not None
        )
        self.search = data.get("search-text") is not None

        if self.enabled and not self.complete and not self.error:
            process = get_file_text(self.entity, dispatch=False)
            return bool(
                not process.complete
                and not process.error
                and process.status == "Extracting text..."
            )
        return False


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_summarize_process
# @matrix file : process summarize
class Summarize(ProcessProperty):
    """AI summarization options.

    When complete, stores the generated summary on the entity.
    Attributes: enabled, search (include in search cache), status, and the two
    broad retrieval terms selected with an AI-generated summary.
    """

    process_id = "options"
    section_id = "summarize"
    attributes = ("status", "enabled", "search", "retrieval_terms")

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_summarize_process
    # @tests tests_unit/test_006_file_properties.py::test_summarize_update_uses_enable_field_name
    # @tests tests_unit/test_006_file_properties.py::test_summarize_update_upload_search_summary_remains_opt_in
    # @tests tests_unit/test_006_file_properties.py::test_summarize_update_starts_without_browser_routing_identity
    # @tests tests_unit/test_006_file_properties.py::test_file_update_preserves_processing_options_when_controls_absent
    # @tests tests_unit/test_006_file_properties.py::test_file_processing_dispatches_summary_before_extraction
    # @matrix file : deferred-dispatch option-preservation search-opt-in summarize update
    def update(self, data):
        if not _has_any(data, "enable-summarize", "summarize", "search-summary"):
            return False

        self.enabled = (
            data.get("enable-summarize") is not None
            or data.get("summarize") is not None
        )
        self.search = (
            data.get("search-summary") is not None
            or (
                data.get("enable-summarize") is not None
                and data.get("summarize") is None
            )
        )

        if self.enabled and not self.complete and not self.error:
            process = summarize_file(self.entity, dispatch=False)
            return bool(
                not process.complete
                and not process.error
                and process.status == "Summarizing file..."
            )
        return False


# @testable true
# @tests tests_unit/test_006_file_properties.py::test_file_processing_dispatches_summary_before_extraction
# @matrix deferred-jobs file : deferred-dispatch extraction-follow-up post-save-dispatch summary-first
def dispatch_file_processing(file, request):
    """Start persisted file work, chaining extraction behind summarization."""
    if request.get("summarize"):
        return summarize_file(
            file,
            parameters=(
                {"extract_after_summary": True}
                if request.get("extract")
                else {}
            ),
        )
    if request.get("extract"):
        return get_file_text(file)
    return None


# @testable false
# @covered-by lagniappe/core/properties/file_options.py::Options.value
class Options(ColumnMixin, Property):
    """Aggregated file processing options (extract, summarize).

    Get:
        value (dict): The process options dict from entity storage.
    """

    _id = "options"

    # @testable true
    # @tests tests_unit/test_006_file_properties.py::test_options
    # @matrix file : extract options summarize
    @property
    def value(self):
        if self.is_set:
            return self._value

        self._value = self.entity.get_process(self.id)

        return self._value

    @property
    def preload(self):
        return self.value
