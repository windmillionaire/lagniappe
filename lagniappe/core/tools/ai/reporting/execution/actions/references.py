"""Entity, page, and file reference resolution for report actions."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache

from .common import (
    _first_data_reference,
    _normalized_lookup_name,
    _unique_entities,
    _unique_values,
)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/files.py::_move_file
# @reason file reference resolution is exercised through public file move tests
def _resolve_file_entity(data, created, source=None):
    reference = (
        data.get("file")
        or data.get("file_id")
        or data.get("file_ref")
        or data.get("file_action")
    )
    if reference:
        try:
            return _resolve_entity(reference, created, expected=Entities.FILE)
        except exceptions.ValidationError:
            file = _resolve_file_from_source(data, source, reference)
            if file is not None:
                return file
            raise

    file = _resolve_file_from_source(data, source)
    if file is not None:
        return file
    return _resolve_entity(reference, created, expected=Entities.FILE)


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_moves_file_by_exact_source_attachment_name
# @pair ai-report:readable-file-fallback
# @pair files:readable-file-fallback
def _resolve_file_from_source(data, source, reference=None):
    labels = _move_file_label_candidates(data, reference)
    if not labels or source is None:
        return None

    matches = [
        file
        for file in _endpoint_file_entities(source)
        if _file_matches_labels(file, labels)
    ]
    matches = _unique_entities(matches)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise exceptions.ValidationError(
            "File move file reference matched multiple source files."
        )
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/files.py::_move_file
# @reason fallback file matching is exercised through public file move tests
def _move_file_label_candidates(data, reference=None):
    candidates = []
    for value in [
        reference,
        data.get("display_name"),
        data.get("file_name"),
        data.get("file_label"),
        data.get("file_display"),
        data.get("filename"),
        data.get("name"),
    ]:
        if isinstance(value, dict):
            for key in ("display_name", "file_name", "file_label", "filename", "name"):
                if value.get(key):
                    candidates.append(value[key])
        elif value:
            candidates.append(value)
    return {
        str(candidate).strip().casefold()
        for candidate in candidates
        if str(candidate).strip()
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/files.py::_move_file
# @reason fallback file matching is exercised through public file move tests
def _endpoint_file_entities(endpoint):
    try:
        files = list(endpoint.files or [])
    except AttributeError:
        files = []
    return [file for file in files if isinstance(file, Entities.FILE)]


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/files.py::_move_file
# @reason fallback file matching is exercised through public file move tests
def _file_matches_labels(file, labels):
    for value in [file.name, file.filename, getattr(file, "display_name", None)]:
        if value and str(value).strip().casefold() in labels:
            return True
    return False


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/files.py::_move_file
# @reason endpoint resolution is covered through public file move tests
def _resolve_file_endpoint(data, created, endpoint):
    if endpoint == "source":
        page_roots = ("from_page", "source_page", "page_from")
        task_roots = ("from_task", "source_task", "task_from")
    else:
        page_roots = ("to_page", "target_page", "destination_page", "page")
        task_roots = ("to_task", "target_task", "destination_task", "task")

    page_ref = _first_data_reference(data, *page_roots)
    task_ref = _first_data_reference(data, *task_roots)
    if bool(page_ref) == bool(task_ref):
        raise exceptions.ValidationError(
            f"File move {endpoint} requires exactly one page or task reference."
        )
    if page_ref:
        return _resolve_entity(page_ref, created, expected=Entities.PAGE)
    return _resolve_entity(task_ref, created, expected=Entities.TASK)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/files.py::_move_file
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason attachment mutation is covered through move and undo tests
def _file_attached_to_endpoint(file, endpoint):
    if isinstance(endpoint, Entities.PAGE):
        return endpoint.key in list(file.db.get("pages") or [])
    if isinstance(endpoint, Entities.TASK):
        return endpoint.key in list(file.db.get("tasks") or []) or file.key in list(
            endpoint.db.get("files") or []
        )
    return False


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/files.py::_move_file
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason attachment mutation is covered through move and undo tests
def _remove_file_from_endpoint(file, endpoint):
    if isinstance(endpoint, Entities.PAGE):
        return file.properties.pages.remove(endpoint)
    if isinstance(endpoint, Entities.TASK):
        return endpoint.properties.files.remove(file)
    return False


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/files.py::_move_file
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason attachment mutation is covered through move and undo tests
def _add_file_to_endpoint(file, endpoint):
    if isinstance(endpoint, Entities.PAGE):
        return file.properties.pages.add(endpoint)
    if isinstance(endpoint, Entities.TASK):
        return endpoint.properties.files.add(file)
    return False


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_resolves_task_page_by_exact_page_name_when_reference_is_wrong_kind
# @tests tests_unit/test_020g_ai_report_actions_tasks.py::test_run_report_resolves_attachment_page_from_single_prior_task_when_reference_is_file
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_resolves_attachment_page_by_exact_page_name_when_reference_missing
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_rejects_category_used_as_attachment_page
# @pair tasks:page-reference
# @pair tasks:repair
# @pair files:page-reference
# @pair files:repair
# @pair files:prior-task-page
# @pair files:exact-page-name
# @pair ai-report:attachment
# @pair ai-report:exact-page-name
# @pair ai-report:page-reference
# @pair ai-report:prior-task-page
# @pair ai-report:repair
# @pair ai-report:task-history
# @pair ai-report:validation
# @pair task-completion:page-reference
# @pair task-completion:repair
# @pair task-completion:task-history
# @pair tasks:task-history
def _resolve_action_page(data, created, user):
    reference = (
        data.get("page")
        or data.get("page_id")
        or data.get("page_ref")
        or data.get("page_action")
    )
    page_name = data.get("page_name") or data.get("page-name")

    if reference:
        key = _reference_key(reference)
        entity = created.get(key)
        if entity is None:
            entity = _fetch_report_entity(key, derived_page=True)
        if entity is None:
            named_page = _resolve_page_by_exact_name(page_name, user)
            if named_page is not None:
                return named_page

            if page_name:
                context_page = _page_from_created_context(created, page_name)
                if context_page is not None:
                    return context_page

            raise exceptions.ValidationError(f"Referenced entity not found: {key}")
        if isinstance(entity, Entities.PAGE):
            return entity

        derived_page = _page_from_non_page_reference(entity, page_name)
        if derived_page is not None:
            return derived_page

        named_page = _resolve_page_by_exact_name(page_name, user)
        if named_page is not None:
            return named_page

        context_page = _page_from_created_context(created, page_name)
        if context_page is not None:
            return context_page

        entity_name = getattr(entity, "name", None) or page_name or "The destination"
        entity_kind = (
            getattr(entity, "kind", None)
            or getattr(entity, "entity_kind", None)
            or "record"
        )
        raise exceptions.ValidationError(
            f"{entity_name} is a {entity_kind}, not a page."
        )

    named_page = _resolve_page_by_exact_name(page_name, user)
    if named_page is not None:
        return named_page

    raise exceptions.ValidationError("Missing required entity reference.")


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/references.py::_resolve_action_page
# @reason non-page page inference is covered through task creation and attachment tests
def _page_from_non_page_reference(entity, page_name=None):
    if isinstance(entity, (Entities.TASK, Entities.TASK_HISTORY)):
        page = getattr(entity, "page", None)
        if page and _page_name_matches(page, page_name):
            return page
    if isinstance(entity, Entities.FILE):
        pages = [
            page
            for page in getattr(entity, "pages", []) or []
            if _page_name_matches(page, page_name)
        ]
        if len(pages) == 1:
            return pages[0]
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/references.py::_resolve_action_page
# @reason unique prior page inference is covered through report-run attachment tests
def _page_from_created_context(created, page_name=None):
    candidates = {}
    for entity in created.values():
        page = None
        if isinstance(entity, Entities.PAGE):
            page = entity
        elif isinstance(entity, (Entities.TASK, Entities.TASK_HISTORY)):
            page = getattr(entity, "page", None)
        elif isinstance(entity, Entities.FILE):
            pages = [
                linked_page
                for linked_page in getattr(entity, "pages", []) or []
                if _page_name_matches(linked_page, page_name)
            ]
            if len(pages) == 1:
                page = pages[0]

        if page and _page_name_matches(page, page_name):
            candidates[getattr(page, "key", id(page))] = page

    return next(iter(candidates.values())) if len(candidates) == 1 else None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/references.py::_resolve_action_page
# @reason exact page-name fallback is covered through task creation and attachment tests
def _resolve_page_by_exact_name(page_name, user):
    if not page_name:
        return None

    restrictions = getattr(getattr(user, "properties", None), "restrictions", None)
    required = getattr(restrictions, "search", [])
    belongs_to = getattr(restrictions, "belongs_to", [])
    results, _total = cache.search(
        page_name,
        required,
        belongs_to,
        kinds=["page"],
        limit=10,
    )
    normalized_name = _normalized_lookup_name(page_name)
    matches = [
        result
        for result in results
        if result.get("kind") == "page"
        and _normalized_lookup_name(result.get("name")) == normalized_name
    ]
    if not matches:
        return None
    if len(matches) > 1:
        raise exceptions.ValidationError(
            f"Page name {page_name!r} matched multiple pages."
        )

    page = Entities.fetch_one(matches[0]["id"], request=Fetch.direct())
    return page if isinstance(page, Entities.PAGE) else None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/references.py::_resolve_action_page
# @reason page-name matching is covered through task creation and attachment tests
def _page_name_matches(page, page_name=None):
    if not page:
        return False
    if not page_name:
        return True
    return _normalized_lookup_name(page.name) == _normalized_lookup_name(page_name)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason reference resolution is exercised through ordered runner tests
def _resolve_entity(reference, created, expected=None, optional=False):
    if not reference:
        if optional:
            return None
        raise exceptions.ValidationError("Missing required entity reference.")

    key = _reference_key(reference)
    entity = created.get(key)
    if entity is None:
        entity = _fetch_report_entity(key)

    if entity is None:
        if optional:
            return None
        raise exceptions.ValidationError(f"Referenced entity not found: {key}")

    if expected and not isinstance(entity, expected):
        raise exceptions.ValidationError(
            f"Referenced entity {key} is not a {expected.entity_kind}."
        )
    return entity


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @reason reference normalization is covered through runner reference tests
def _reference_key(reference):
    if isinstance(reference, dict):
        reference = (
            reference.get("action") or reference.get("id") or reference.get("key")
        )
    if isinstance(reference, str) and reference.startswith("$"):
        return reference[1:]
    if isinstance(reference, str) and reference.startswith("action:"):
        return reference.split(":", 1)[1]
    return reference


# @testable true
# @tests tests_unit/test_020g_ai_report_actions_files.py::test_run_report_resolves_report_file_by_exact_url_and_file_prefix
# @pair ai-report:deterministic-run
# @pair ai-report:exact-id
# @pair ai-report:report-file-reference
# @pair files:deterministic-run
# @pair files:exact-id
# @pair files:report-file-reference
def _resolve_report_file(reference, report):
    if isinstance(reference, dict):
        reference = (
            reference.get("file")
            or reference.get("id")
            or reference.get("key")
            or reference.get("url")
            or reference.get("href")
        )

    references = _report_file_reference_candidates(reference)
    for file in report.input_files:
        if any(
            candidate in {file.urlsafe_key, file.key, file.name, file.filename}
            for candidate in references
        ):
            return file

    raise exceptions.ValidationError("Referenced report file was not found.")


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/actions/references.py::_resolve_report_file
# @reason helper behavior is covered through public report runner file matching tests
def _report_file_reference_candidates(reference):
    if reference is None:
        return []
    candidates = [reference]
    if isinstance(reference, str):
        text = reference.strip()
        if text and text != reference:
            candidates.append(text)
        if text.startswith("file:"):
            candidates.append(text.split(":", 1)[1])
        if "/files/" in text:
            path = text.split("/files/", 1)[1].split("?", 1)[0].split("#", 1)[0]
            file_id = path.strip("/").split("/", 1)[0]
            if file_id:
                candidates.append(file_id)
    return _unique_values(candidates)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason result entity loading is exercised through public undo tests
def _load_result_entity(details):
    if not isinstance(details, dict) or not details.get("id"):
        return None
    return _fetch_report_entity(details["id"])


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/execution/runner.py::run_report
# @covered-by lagniappe/core/tools/ai/reporting/execution/undo.py::undo_report
# @reason polymorphic report references are exercised through run and undo tests
def _fetch_report_entity(identifier, *, derived_page=False):
    entity = Entities.fetch_one(identifier, request=Fetch.root())
    if entity is None:
        return None

    if derived_page and not isinstance(entity, Entities.PAGE):
        request = Fetch.nested(because=FetchReason.DERIVED_PAGE_SAVE_REQUIREMENTS)
    elif isinstance(entity, (Entities.TASK, Entities.TASK_HISTORY)):
        request = Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS)
    else:
        request = Fetch.direct()

    return Entities.fetch_one(entity, request=request)
