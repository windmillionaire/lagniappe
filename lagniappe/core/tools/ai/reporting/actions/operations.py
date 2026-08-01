"""Shared entity resolution, serialization, and compensation primitives."""

from lagniappe.core import exceptions
from lagniappe.core.definitions import (
    Action,
    Fetch,
    FetchReason,
    MutationIntent,
)
from lagniappe.core.entities import Entities
from lagniappe.core.tools import cache

from ...debug import ai_debug

TASK_FORM_TYPE_ERROR = "Create task actions require a task form."
PAGE_FORM_TYPE_ERROR = "Add form to page actions require a page form."
SUBMISSION_UPDATE_ROWS_ERROR = "Submission update action requires at least one update."


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason permission failures are covered through runner action handlers
def _require_allowed(allowed, message):
    if not allowed:
        raise exceptions.ValidationError(message)


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason action data extraction is exercised by each handler
def _data(action):
    data = action.get("data") or {}
    if not isinstance(data, dict):
        raise exceptions.ValidationError("Action data must be an object.")
    return data


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/files.py::_move_file
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
# @tests tests_unit/test_020_ai_reports.py::test_run_report_moves_file_by_exact_source_attachment_name
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
# @covered-by lagniappe/core/tools/ai/reporting/actions/files.py::_move_file
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
# @covered-by lagniappe/core/tools/ai/reporting/actions/files.py::_move_file
# @reason fallback file matching is exercised through public file move tests
def _endpoint_file_entities(endpoint):
    try:
        files = list(endpoint.files or [])
    except AttributeError:
        files = []
    return [file for file in files if isinstance(file, Entities.FILE)]


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/files.py::_move_file
# @reason fallback file matching is exercised through public file move tests
def _file_matches_labels(file, labels):
    for value in [file.name, file.filename, getattr(file, "display_name", None)]:
        if value and str(value).strip().casefold() in labels:
            return True
    return False


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/files.py::_move_file
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
# @covered-by lagniappe/core/tools/ai/reporting/actions/files.py::_move_file
# @reason reference alias lookup is covered through endpoint resolution tests
def _first_data_reference(data, *roots):
    for root in roots:
        for key in (root, f"{root}_id", f"{root}_ref", f"{root}_action"):
            value = data.get(key)
            if value:
                return value
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/files.py::_move_file
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
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
# @covered-by lagniappe/core/tools/ai/reporting/actions/files.py::_move_file
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason attachment mutation is covered through move and undo tests
def _remove_file_from_endpoint(file, endpoint):
    if isinstance(endpoint, Entities.PAGE):
        return file.properties.pages.remove(endpoint)
    if isinstance(endpoint, Entities.TASK):
        return endpoint.properties.files.remove(file)
    return False


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/files.py::_move_file
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason attachment mutation is covered through move and undo tests
def _add_file_to_endpoint(file, endpoint):
    if isinstance(endpoint, Entities.PAGE):
        return file.properties.pages.add(endpoint)
    if isinstance(endpoint, Entities.TASK):
        return endpoint.properties.files.add(file)
    return False


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_resolves_task_page_by_exact_page_name_when_reference_is_wrong_kind
# @tests tests_unit/test_020_ai_reports.py::test_run_report_resolves_attachment_page_from_single_prior_task_when_reference_is_file
# @tests tests_unit/test_020_ai_reports.py::test_run_report_resolves_attachment_page_by_exact_page_name_when_reference_missing
# @tests tests_unit/test_020_ai_reports.py::test_run_report_rejects_category_used_as_attachment_page
# @pair tasks:page-reference
# @pair tasks:repair
# @pair files:page-reference
# @pair files:repair
# @pair files:prior-task-page
# @pair files:exact-page-name
# @pair ai-report:validation
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
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_resolve_action_page
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
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_resolve_action_page
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
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_resolve_action_page
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
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_resolve_action_page
# @reason page-name matching is covered through task creation and attachment tests
def _page_name_matches(page, page_name=None):
    if not page:
        return False
    if not page_name:
        return True
    return _normalized_lookup_name(page.name) == _normalized_lookup_name(page_name)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_resolve_action_page
# @reason lookup normalization is covered through task creation and attachment tests
def _normalized_lookup_name(value):
    return " ".join(str(value or "").strip().casefold().split())


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/tasks.py::_record_completed_task_event
# @reason save-list deduplication supports report-run action results
def _unique_entities(entities):
    unique = []
    seen = set()
    for entity in entities:
        if entity is None:
            continue
        key = getattr(entity, "key", None) or id(entity)
        if key in seen:
            continue
        seen.add(key)
        unique.append(entity)
    return unique


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason page form inheritance is verified through report-run page creation tests
def _category_form(category):
    if category is None:
        return None

    form_property = getattr(getattr(category, "properties", None), "form", None)
    if form_property is not None and getattr(form_property, "is_set", False):
        form = form_property.value
        if form is not None:
            return form

    form = getattr(category, "form", None)
    if form is not None:
        return form

    form_key = _stored_relation_key(category, "form")
    if not form_key:
        return None

    form = Entities.fetch_one(form_key, request=Fetch.direct())
    return form if isinstance(form, Entities.FORM) else None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason result diagnostics are asserted through deterministic run results
def _file_summary_result(file):
    summarize = getattr(getattr(file, "properties", None), "summarize", None)
    result = {
        "enabled": bool(getattr(summarize, "enabled", False)),
        "complete": bool(getattr(summarize, "complete", False)),
        "present": bool(getattr(file, "summary", None)),
    }
    status = getattr(summarize, "status", None)
    error = getattr(summarize, "error", None)
    if status:
        result["status"] = status
    if error:
        result["error"] = error
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/tasks.py::_create_task
# @covered-by lagniappe/core/tools/ai/reporting/actions/tasks.py::_record_completed_task_event
# @reason task structure diagnostics are asserted through deterministic run results
def _task_structure_result(task, project=None, model=None, form=None):
    result = {}
    project = project or _safe_entity_relation(task, "project")
    model = model or _safe_entity_relation(task, "model")
    form = form or _safe_entity_relation(task, "form")
    if project is not None:
        result["project"] = _entity_result(project)
    if model is not None:
        result["model"] = _entity_result(model, parent=project)
    if form is not None:
        result["form"] = _entity_result(form)
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_task_structure_result
# @reason relation access failures are represented by omitted diagnostics
def _safe_entity_relation(entity, name):
    try:
        return getattr(entity, name, None)
    except Exception:
        return None


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason submission diagnostics are asserted through deterministic run results
def _submission_result(entity, empty_reason=None):
    submission = getattr(entity, "submission", None)
    field_count = len(submission) if isinstance(submission, dict) else 0
    result = {
        "created": field_count > 0,
        "field_count": field_count,
    }
    if empty_reason and field_count == 0:
        result["empty_reason"] = empty_reason
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/tasks.py::_record_completed_task_event
# @reason telemetry is provider-facing; behavior is covered by runner result tests
def _capture_missing_task_submission(action, data, report, page, project, model, form):
    ai_debug(
        "report_runner.create_task.missing_submission",
        report=_diagnostic_entity(report),
        action={
            "id": action.get("id"),
            "type": action.get("type"),
            "display_label": action.get("display_label"),
            "data_keys": sorted((data or {}).keys()),
            "completed_on": (
                data.get("completed_on")
                or data.get("completed-on")
                or data.get("completed")
            ),
        },
        page=_diagnostic_entity(page),
        project=_diagnostic_entity(project),
        model=_diagnostic_entity(model),
        form=_diagnostic_entity(form),
        form_schema=_diagnostic_schema(form),
        files=_diagnostic_file_refs(data),
    )
    exceptions.capture(
        "AI report create_task used a task form but omitted submission data.",
        context={
            "ai_report_runner": {
                "operation": "create_task_missing_submission",
                "report": _diagnostic_entity(report),
                "action": {
                    "id": action.get("id"),
                    "type": action.get("type"),
                    "display_label": action.get("display_label"),
                    "data_keys": sorted((data or {}).keys()),
                    "completed_on": (
                        data.get("completed_on")
                        or data.get("completed-on")
                        or data.get("completed")
                    ),
                    "submission_key_present": "submission" in data,
                },
                "page": _diagnostic_entity(page),
                "project": _diagnostic_entity(project),
                "model": _diagnostic_entity(model),
                "form": _diagnostic_entity(form),
                "form_schema": _diagnostic_schema(form),
                "files": _diagnostic_file_refs(data),
            }
        },
        level="warning",
    )


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_capture_missing_task_submission
# @reason compact diagnostic projection is exercised through runner telemetry
def _diagnostic_entity(entity):
    if entity is None:
        return None
    details = {
        "kind": getattr(entity, "kind", None),
        "name": getattr(entity, "name", None),
        "hash": getattr(entity, "hash", None),
        "id": getattr(entity, "urlsafe_key", None),
        "key": str(getattr(entity, "key", "")) or None,
    }
    form_type = getattr(entity, "form_type", None)
    if form_type:
        details["form_type"] = form_type
    return details


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/tasks.py::_create_task
# @covered-by lagniappe/core/tools/ai/reporting/actions/entities.py::_add_form_to_page
# @reason mismatched form type behavior is covered through public report runner tests
def _require_form_type(form, expected_type, message):
    if form is None:
        return
    form_type = getattr(form, "form_type", None)
    if form_type and form_type != expected_type:
        raise exceptions.ValidationError(message)


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_capture_missing_task_submission
# @reason compact diagnostic projection is exercised through runner telemetry
def _diagnostic_schema(form):
    schema = getattr(form, "schema", None) or []
    fields = []
    for field in schema:
        if not isinstance(field, dict):
            continue
        fields.append(
            {
                "id": field.get("id"),
                "type": field.get("type"),
                "input": field.get("input"),
                "title": field.get("title") or field.get("label"),
            }
        )
    return fields


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_capture_missing_task_submission
# @reason compact diagnostic projection is exercised through runner telemetry
def _diagnostic_file_refs(data):
    files = []
    if data.get("file"):
        files.append(data.get("file"))
    files.extend(data.get("files") or [])
    return files


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason created-reference bookkeeping is verified through ordered runner tests
def _remember_created(created, action, entity):
    for key in [action.get("id"), entity.key, entity.urlsafe_key]:
        if key:
            created[key] = entity


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason attachment target serialization is verified through report run outputs
def _attachment_target_result(action, to_save):
    if action.get("type") not in {"attach_file_to_page", "attach_file_to_task"}:
        return None
    if len(to_save) < 2:
        return None
    return _entity_result(to_save[1])


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason attachment metadata is verified through grouped result tests
def _action_attachment_results(action, to_save):
    return []


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason result serialization is exercised through report run outputs
def _entity_result(entity, parent=None):
    result = {
        "id": entity.urlsafe_key,
        "kind": entity.kind,
        "name": _entity_result_name(entity),
    }
    if (
        isinstance(entity, Entities.MODEL_TASK)
        or getattr(entity, "kind", None) == "model"
    ):
        parent = parent or _safe_entity_relation(entity, "project")
        if parent is not None:
            result["parent"] = _entity_result(parent)
        else:
            project_key = _stored_relation_key(entity, "project")
            if project_key:
                exceptions.capture(
                    "AI report serialized a model task without its project attached.",
                    context={
                        "ai_report_runner": {
                            "operation": "model_task_project_relation_missing",
                            "model": _diagnostic_entity(entity),
                            "project_key": str(project_key),
                        }
                    },
                    level="warning",
                )
    try:
        result["url"] = entity.url
    except Exception:
        pass
    return result


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_entity_result
# @reason telemetry-only relation key projection is covered by result serialization
def _stored_relation_key(entity, name):
    relation = getattr(getattr(entity, "properties", None), name, None)
    if relation is not None:
        try:
            key = relation.key
        except Exception:
            key = None
        if key:
            return key

    db = getattr(entity, "db", None)
    if isinstance(db, dict):
        return db.get(name)
    return None


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_entity_result
# @reason fallback naming is exercised through task-history report results
def _entity_result_name(entity):
    try:
        name = entity.name
    except AttributeError:
        name = None
    return name or "Task history"


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
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
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
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


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @reason file-reference lookup is exercised by attach action tests
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
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_resolve_report_file
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
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_resolve_report_file
# @reason helper behavior is covered through public report runner file matching tests
def _unique_values(values):
    unique = []
    seen = set()
    for value in values:
        key = value if isinstance(value, (str, int, float, tuple)) else id(value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_adds_form_to_existing_page_with_undo
# @pair ai-report:page-form
# @pair ai-report:undo
def _undo_add_form_to_page_action(action, user):
    previous = action.get("previous") or {}
    if previous.get("had_form"):
        return {"note": "Page already had this form; nothing changed."}

    page = _load_result_entity(action.get("entity"))
    if page is None:
        return {"note": "Page already missing."}
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to restore this page's form.",
    )

    previous_details = previous.get("form")
    previous_form = _load_result_entity(previous_details)
    if previous_details and previous_form is None:
        return {"note": "Previous page form is no longer available."}

    current_owners = list(page.page_list_owners)
    page.form = previous_form
    if previous_form is not None:
        for category in page.page_list_owners:
            if isinstance(category, Entities.CATEGORY):
                category.properties.forms.add(previous_form)
    page.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-page-current-owner",
            )
            for owner in current_owners
        )
    )
    Entities.save(*_unique_entities([page, previous_form, *current_owners]))
    return {
        "entity": _entity_result(page),
        "target": _entity_result(previous_form) if previous_form else None,
        "note": "Restored previous page form.",
    }


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_adds_page_category_without_changing_primary_with_undo
# @pair ai-report:add-category
# @pair ai-report:undo
def _undo_add_category_action(action, user):
    previous = action.get("previous") or {}
    if previous.get("had_category"):
        return {"note": "Category was already present; nothing removed."}

    page = _load_result_entity(action.get("entity"))
    category = _load_result_entity(action.get("target"))
    if page is None or category is None:
        return {"note": "Page or category already missing."}
    _require_allowed(
        page.allowed(Action.EDIT, user=user),
        "You do not have permission to remove this category from the page.",
    )
    _require_allowed(
        category.allowed(Action.EDIT, user=user),
        "You do not have permission to undo this category add.",
    )

    current_owners = list(page.page_list_owners)
    category_key = getattr(category, "key", None)
    page.categories = [
        existing
        for existing in page.categories or []
        if getattr(existing, "key", None) != category_key
    ]
    page.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-page-current-owner",
            )
            for owner in current_owners
        )
    )
    Entities.save(*_unique_entities([page, category, *current_owners]))
    return {
        "entity": _entity_result(page),
        "target": _entity_result(category),
        "note": "Removed added page category.",
    }


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_moves_entities_updates_schema_and_patches_submissions_with_undo
# @tests tests_unit/test_020_ai_reports.py::test_run_report_moves_file_and_records_manual_page_cleanup_with_undo
# @pair ai-report:moves
# @pair ai-report:move-file
# @pair ai-report:undo
def _undo_move_action(action, user):
    entity = _load_result_entity(action.get("entity"))
    if entity is None:
        return {"note": "Moved entity already missing."}
    if action.get("type") == "move_file":
        return _undo_file_move(action, entity, user)
    _require_allowed(
        entity.allowed(Action.EDIT, user=user),
        "You do not have permission to undo this move.",
    )

    if action.get("type") == "move_page":
        return _undo_page_move(action, entity, user)
    return _undo_task_move(action, entity, user)


# @testable true
# @tests tests_unit/test_020_ai_reports.py::test_run_report_renames_entity_without_submission_and_undoes
# @pair ai-report:rename
# @pair ai-report:undo
def _undo_rename_entity(action, user):
    entity = _load_result_entity(action.get("entity"))
    if entity is None:
        return {"note": "Renamed entity is missing."}
    _require_allowed(
        entity.allowed(Action.EDIT, user=user),
        "You do not have permission to restore this entity name.",
    )
    previous_name = (action.get("before") or {}).get("name")
    entity.name = previous_name
    Entities.save(entity)
    return {
        "entity": _entity_result(entity),
        "note": "Restored previous entity name.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_undo_move_action
# @reason page move restoration is covered through public undo tests
def _undo_page_move(action, page, user):
    previous = action.get("previous") or {}
    previous_model = _load_result_entity(previous.get("model"))
    previous_categories = [
        category
        for category in (
            _load_result_entity(category)
            for category in previous.get("categories") or []
        )
        if category is not None
    ]
    if previous_model is not None:
        _require_allowed(
            previous_model.allowed(Action.EDIT, user=user),
            "You do not have permission to move this page back.",
        )

    current_owners = list(page.page_list_owners)
    page.model = previous_model
    page.categories = previous_categories
    page.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-page-current-owner",
            )
            for owner in current_owners
        )
    )
    Entities.save(
        *_unique_entities([page, previous_model, *previous_categories, *current_owners])
    )
    return {
        "entity": _entity_result(page),
        "target": _entity_result(previous_model) if previous_model else None,
        "note": "Restored previous page category.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_undo_move_action
# @reason task move restoration is covered through public undo tests
def _undo_task_move(action, task, user):
    previous = action.get("previous") or {}
    previous_page = _load_result_entity(previous.get("page"))
    if previous_page is None:
        return {"entity": _entity_result(task), "note": "Previous page is missing."}
    _require_allowed(
        previous_page.allowed(Action.EDIT, user=user),
        "You do not have permission to move this task back.",
    )

    current_owners = list(task.task_list_owners)
    task.page = previous_page
    task.add_mutation_intents(
        *(
            MutationIntent.touch(
                owner,
                reason="report-task-current-owner",
            )
            for owner in current_owners
        )
    )
    Entities.save(*_unique_entities([task, previous_page, *current_owners]))
    return {
        "entity": _entity_result(task),
        "target": _entity_result(previous_page),
        "note": "Restored previous task page.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/reporting/actions/operations.py::_undo_move_action
# @reason file move restoration is covered through public undo tests
def _undo_file_move(action, file, user):
    previous = action.get("previous") or {}
    source = _load_result_entity(previous.get("source"))
    target = _load_result_entity(previous.get("target"))
    if source is None:
        return {"entity": _entity_result(file), "note": "Previous source is missing."}
    if target is None:
        return {"entity": _entity_result(file), "note": "Previous target is missing."}
    _require_allowed(
        source.allowed(Action.EDIT, user=user),
        "You do not have permission to move this file back.",
    )
    _require_allowed(
        target.allowed(Action.EDIT, user=user),
        "You do not have permission to unlink this file from its target.",
    )

    _remove_file_from_endpoint(file, target)
    _add_file_to_endpoint(file, source)
    Entities.save(*_unique_entities([file, source, target]))
    return {
        "entity": _entity_result(file),
        "target": _entity_result(source),
        "note": "Restored previous file attachment.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason created-entity deletion is exercised through public undo tests
def _undo_created_result_entity(action, report, user):
    entity = _load_result_entity(action.get("entity"))
    if entity is None:
        return {"note": "Entity already missing."}
    _require_allowed(
        entity.allowed(Action.DELETE, user=user)
        or entity.allowed(Action.EDIT, user=user),
        "You do not have permission to delete this report-created entity.",
    )
    touched = _detach_report_files_before_delete(entity, action, report)
    if touched:
        Entities.save(*touched)
    deleted = _entity_result(entity)
    Entities.delete(entity)
    return {"entity": deleted, "note": "Deleted report-created entity."}


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason attachment unlinking is exercised through public undo tests
def _undo_attachment_action(action, user):
    file = _load_result_entity(action.get("entity"))
    target = _load_result_entity(action.get("target"))
    if file is None or target is None:
        return {"note": "Attachment target already missing."}
    _require_allowed(
        target.allowed(Action.EDIT, user=user),
        "You do not have permission to unlink this attachment.",
    )
    if (action.get("before") or {}).get("linked"):
        return {
            "entity": _entity_result(file),
            "target": _entity_result(target),
            "note": "Attachment already existed; nothing removed.",
        }
    if action.get("type") == "attach_file_to_page":
        changed = _remove_file_page_reference(file, target)
    else:
        changed = _remove_task_file_reference(target, file)
    if changed:
        Entities.save(file, target)
    return {
        "entity": _entity_result(file),
        "target": _entity_result(target),
        "note": (
            "Removed report-created file link." if changed else "Link already gone."
        ),
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason file summary restoration is owned by public report compensation
def _undo_summarize_file(action, user):
    file = _load_result_entity(action.get("entity"))
    if file is None:
        return {"note": "Summarized file is missing."}
    _require_allowed(
        file.allowed(Action.EDIT, user=user),
        "You do not have permission to restore this file summary.",
    )
    before = action.get("before") or {}
    previous = before.get("summarize") or {}
    file.summary = before.get("summary")
    summarize = file.properties.summarize
    for name in ("enabled", "search", "status", "error", "complete"):
        setattr(summarize, name, previous.get(name))
    Entities.save(file)
    return {
        "entity": _entity_result(file),
        "note": "Restored previous file summary state.",
    }


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason result entity loading is exercised through public undo tests
def _load_result_entity(details):
    if not isinstance(details, dict) or not details.get("id"):
        return None
    return _fetch_report_entity(details["id"])


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::run_report
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
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


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason report file preservation is exercised through public undo tests
def _detach_report_files_before_delete(entity, action, report):
    touched = []
    if isinstance(entity, Entities.PAGE):
        for file in report.input_files:
            if _remove_file_page_reference(file, entity):
                touched.append(file)
    elif isinstance(entity, (Entities.TASK, Entities.TASK_HISTORY)):
        files = _action_attachment_entities(action)
        if not files:
            files = list(getattr(entity, "files", []) or [])
        for file in files:
            if _remove_task_file_reference(entity, file):
                touched.append(file)
            if isinstance(entity, Entities.TASK_HISTORY):
                task = getattr(entity, "task", None)
                if task and _remove_history_task_file_reference(task, file, entity):
                    touched.append(file)
        if touched:
            touched.append(entity)
    return touched


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason attachment loading is exercised through public undo tests
def _action_attachment_entities(action):
    entities = []
    for attachment in action.get("attachments") or []:
        entity = _load_result_entity(attachment.get("entity"))
        if entity is not None:
            entities.append(entity)
    return entities


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason relationship cleanup is exercised through public undo tests
def _remove_file_page_reference(file, page):
    before = list(file.db.get("pages") or [])
    after = [key for key in before if key != page.key]
    changed = before != after
    if after:
        file.db["pages"] = after
    else:
        file.db.pop("pages", None)
    return changed


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason relationship cleanup is exercised through public undo tests
def _remove_task_file_reference(task, file, *, remove_task_attachment=True):
    task_before = list(task.db.get("files") or [])
    task_after = [key for key in task_before if key != file.key]
    file_before = list(file.db.get("tasks") or [])
    file_after = [key for key in file_before if key != task.key]
    changed = file_before != file_after
    if remove_task_attachment:
        changed = changed or task_before != task_after
        if task_after:
            task.db["files"] = task_after
        else:
            task.db.pop("files", None)
    if file_after:
        file.db["tasks"] = file_after
    else:
        file.db.pop("tasks", None)
    return changed


# @testable false
# @covered-by lagniappe/core/tools/ai/report_runner.py::undo_report
# @reason history parent reverse-link cleanup is exercised through public undo tests
def _remove_history_task_file_reference(task, file, history):
    if file.key in list(task.db.get("files") or []):
        return False

    for linked in getattr(file, "tasks", []) or []:
        if getattr(linked, "key", None) == getattr(history, "key", None):
            continue
        if getattr(linked, "entity_kind", None) != "task_history":
            continue
        if getattr(getattr(linked, "task", None), "key", None) == task.key:
            return False

    return _remove_task_file_reference(task, file, remove_task_attachment=False)
