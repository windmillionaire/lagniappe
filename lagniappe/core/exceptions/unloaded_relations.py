import traceback
from pathlib import Path

from flask import has_request_context, request

from lagniappe import CONFIG
from . import UnloadedRelationError, capture

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _unloaded_relations_tracing_enabled():
    return bool(
        getattr(CONFIG, "CAPTURE_UNLOADED_RELATIONS", False)
        or getattr(CONFIG, "STRICT_RELATION_LOADS", False)
    )


# @testable false
# @covered-by lagniappe/core/exceptions/unloaded_relations.py::capture_unloaded_relation
# @reason relation diagnostics need defensive attribute access
def _safe_attr(item, attr, default=None):
    try:
        return getattr(item, attr, default)
    except Exception as error:
        return f"<{type(error).__name__}: {error}>"


# @testable false
# @covered-by lagniappe/core/exceptions/unloaded_relations.py::capture_unloaded_relation
# @reason relation diagnostics should not depend on loaded entity instances
def _debug_key(key):
    kind = _safe_attr(key, "kind")
    key_name = _safe_attr(key, "name")
    key_id = _safe_attr(key, "id")
    if kind and (key_name or key_id):
        return f"{kind}:{key_name or key_id}"
    return str(key)


# @testable false
# @covered-by lagniappe/core/exceptions/unloaded_relations.py::capture_unloaded_relation
# @reason request context formatting is diagnostic plumbing
def _request_context():
    if not has_request_context():
        return None

    return {
        "method": request.method,
        "path": request.full_path.rstrip("?"),
        "endpoint": request.endpoint,
        "rule": getattr(request.url_rule, "rule", None),
    }


# @testable false
# @covered-by lagniappe/core/exceptions/unloaded_relations.py::capture_unloaded_relation
# @reason caller formatting is diagnostic plumbing
def _caller_location():
    skip_prefixes = (
        "lagniappe/core/mixins/related.py:",
        "lagniappe/core/exceptions/unloaded_relations.py:",
        "lagniappe/core/entities/entity.py:",
        "lagniappe/core/properties/base_property.py:",
    )
    for frame in reversed(traceback.extract_stack()[:-1]):
        path = Path(frame.filename).resolve()
        try:
            path = path.relative_to(PROJECT_ROOT)
        except ValueError:
            pass
        location = f"{path}:{frame.lineno} {frame.name}"
        if location.startswith(skip_prefixes):
            continue
        return location
    return "-"


# @testable false
# @covered-by lagniappe/core/exceptions/unloaded_relations.py::capture_unloaded_relation
# @reason context formatting is diagnostic plumbing
def _entity_context(entity):
    if not entity:
        return None

    db = _safe_attr(entity, "db", {}) or {}
    kind = _safe_attr(entity, "kind") or _safe_attr(entity, "entity_kind")
    return {
        "class": f"{type(entity).__module__}.{type(entity).__name__}",
        "kind": kind,
        "name": _safe_attr(entity, "name"),
        "id": _safe_attr(entity, "id"),
        "hash": _safe_attr(entity, "hash"),
        "urlsafe_key": _safe_attr(entity, "urlsafe_key"),
        "db_keys": sorted(str(key) for key in db.keys()),
    }


# @testable false
# @covered-by lagniappe/core/exceptions/unloaded_relations.py::capture_unloaded_relation
# @reason context formatting is diagnostic plumbing
def _property_context(prop):
    return {
        "class": f"{type(prop).__module__}.{type(prop).__name__}",
        "id": _safe_attr(prop, "id"),
        "label": _safe_attr(prop, "label"),
        "db_key": _safe_attr(prop, "db_key"),
        "kind": _safe_attr(prop, "kind"),
    }


# @testable true
# @tests tests_unit/test_001_test_general_and_utilities.py::test_related_list_value_reports_unloaded_relation_without_loading
# @tests tests_unit/test_001_test_general_and_utilities.py::test_related_single_value_reports_unloaded_relation_without_loading
# @tests tests_unit/test_001_test_general_and_utilities.py::test_related_value_strict_mode_raises_after_reporting
# @matrix relations : diagnostics strict-mode unloaded-fallback
def capture_unloaded_relation(prop, *, relation_type, keys):
    """Capture a diagnostic when relation access would have lazy-loaded."""
    if not _unloaded_relations_tracing_enabled():
        return

    key_labels = [_debug_key(key) for key in keys if key]
    context = {
        "relation_type": relation_type,
        "entity": _entity_context(_safe_attr(prop, "entity")),
        "property": _property_context(prop),
        "keys": key_labels,
        "key_count": len(key_labels),
        "caller": _caller_location(),
        "request": _request_context(),
        "fallback": [] if relation_type == "list" else None,
        "hint": (
            "Fetch the owning entity at the required depth, or include the "
            "related entities in the same Entities.fetch request."
        ),
    }
    entity = context["entity"] or {}
    prop_info = context["property"] or {}
    message = (
        "Unloaded relation access: "
        f"{entity.get('kind') or entity.get('class')}.{prop_info.get('id')} "
        f"has {len(key_labels)} stored key(s) but no attached value."
    )
    error = UnloadedRelationError(message)
    capture(error, context, level="warning")
    if getattr(CONFIG, "STRICT_RELATION_LOADS", False):
        raise error
