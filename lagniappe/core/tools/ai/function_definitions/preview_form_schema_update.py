"""Read-only complete migration preview with bounded, revision-bound pages."""

import base64
import json

from google.genai import types

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import ValidationError
from lagniappe.core.tools.forms import (
    conversions as form_conversions,
    drafts as form_drafts,
    schema_updates as form_schema_updates,
)
from ..references import hash_reference


PREVIEW_FORM_SCHEMA_UPDATE = types.FunctionDeclaration(
    name="preview_form_schema_update",
    description=(
        "Validate proposed exact-ID Form schema operations and discover every affected "
        "Page/Task, including Task completion state. Read-only: does not save, lock, or call AI. "
        "Follow every next_cursor; include_values=true returns original affected AI values and scalar before/after values (clears=true omits after). "
        "Return baseline and scope_fingerprint unchanged in update_form_schema."
    ),
    parameters={
        "type": "object",
        "required": ["id", "operations"],
        "properties": {
            "id": {"type": "string"},
            "operations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["op"],
                    "properties": {
                        "op": {
                            "type": "string",
                            "enum": sorted(form_schema_updates.OPERATIONS),
                        },
                        "schema_id": {"type": "string"},
                        "field": {},
                        "patch": {},
                        "option": {},
                        "ids": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "include_values": {"type": "boolean"},
            "limit": {
                "type": "integer", "minimum": 1, "maximum": 50,
                "description": "Instances per page: 1–50; defaults to 25. Follow every next_cursor.",
            },
            "cursor": {"type": "string"},
        },
    },
)


# @testable true
# @tests tests_unit/test_004l_form_schema_updates.py::test_preview_paginates_and_rejects_stale_cursor
# @matrix form-migration ai : preview pagination read-only complete-scope
def execute_preview_form_schema_update(args, user):
    try:
        form = Entities.fetch_one(args.get("id"), request=Fetch.direct())
        if not isinstance(form, Entities.FORM) or form.db.get("pending_form_change"):
            raise ValidationError("Form is unavailable or already being updated.")
        schema = form_schema_updates.apply_operations(
            form.schema, args.get("operations"), form.form_type
        )
        changes = form_conversions.classify_changes(form.schema, schema)
        scope = form_schema_updates.inspect_scope(
            form, changes, user, include_values=args.get("include_values") is True
        )
        baseline = form_drafts.builder_draft(form)["baseline"]
        identity = form_schema_updates.fingerprint(
            [baseline, schema, scope["scope_fingerprint"]]
        )
        offset = 0
        if args.get("cursor"):
            try:
                token = json.loads(base64.urlsafe_b64decode(args["cursor"].encode()))
                offset = token["offset"]
                if token["identity"] != identity:
                    raise ValidationError(form_schema_updates.STALE_MESSAGE)
                if (
                    not isinstance(offset, int)
                    or isinstance(offset, bool)
                    or offset < 0
                ):
                    raise ValueError("Invalid offset")
            except (ValueError, TypeError, KeyError, UnicodeError) as error:
                raise ValidationError("Invalid schema preview cursor.") from error
        limit = args.get("limit", 25)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 50
        ):
            raise ValidationError("Preview limit must be between 1 and 50.")
        items = []
        size = len(json.dumps(schema).encode())
        for item in scope["instances"][offset : offset + limit]:
            item_size = len(json.dumps(item, ensure_ascii=False).encode())
            if size + item_size > 750 * 1024:
                if not items:
                    raise ValidationError(
                        "A complete affected value is too large for an inline preview. Use the on-site builder; source values cannot be truncated."
                    )
                break
            items.append(item)
            size += item_size
        for item in items:
            entity = Entities.fetch_one(item.pop("id"), request=Fetch.direct())
            form_schema_updates.require_visible(entity, user)
            item.update(entity=hash_reference(entity), name=entity.name, url=entity.url)
            if isinstance(entity, Entities.TASK):
                item["completed"] = bool(entity.completed)
        end = offset + len(items)
        more = end < len(scope["instances"])
        cursor = (
            base64.urlsafe_b64encode(
                json.dumps({"offset": end, "identity": identity}).encode()
            ).decode()
            if more
            else None
        )
        return {
            "form": hash_reference(form),
            "baseline": baseline,
            "scope_fingerprint": scope["scope_fingerprint"],
            "schema": schema,
            "changes": changes,
            "instances": items,
            "total": scope["total"],
            "affected": len(scope["instances"]),
            "returned": len(items),
            "has_more": more,
            "next_cursor": cursor,
            "warning": "Removed and unconvertible values will be cleared. Submission migrations cannot be undone.",
        }
    except ValidationError as error:
        return {"error": str(error)}
