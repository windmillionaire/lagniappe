"""Follow-up migrations for File Page ancestry and canonical restrictions."""

from .base import MigrationContext, MigrationResult

from .base import MigrationDataError, _file_record_reference, _result, scan_kind
from ..core import KINDS


def migrate_file_pages(context: MigrationContext) -> MigrationResult:
    result = _result("FIL-002", "File Page ancestry")
    owners = {
        row.key: row
        for row in context.query_factory(KINDS.instances).fetch_iter()
        if row.get("type") in {"page", "task"}
    }
    histories = {
        row.key: row
        for row in context.query_factory(KINDS.history).fetch_iter()
        if row.get("type") == "task_history"
    }

    def transform(row):
        task_key, page_key = row.get("task"), row.get("page")
        if task_key in histories:
            task_key = histories[task_key].get("task") or task_key.parent
        task = owners.get(task_key) if task_key else None
        if task_key:
            if not task or task.get("type") != "task":
                raise MigrationDataError("File Task is missing or is not a live Task")
            task_page_key = task.get("page")
            if not task_page_key:
                raise MigrationDataError("File Task has no Page; repair the Task before retrying")
            if page_key and page_key != task_page_key:
                raise MigrationDataError("File has conflicting Page/Task owners; repair its references before retrying")
        else:
            task_page_key = None
        owner_page_key = task_page_key or page_key
        page = owners.get(owner_page_key) if owner_page_key else None
        if owner_page_key and (not page or page.get("type") != "page"):
            raise MigrationDataError("File Page is missing or is not a live Page")
        if not owner_page_key:
            # Staged upload/report Files remain private and unattached.
            if "task_page" not in row:
                return False
            row.pop("task_page")
            row["requires"] = [value for value in (row.get("hash"), "models") if value]
            return True
        if page is None:
            raise MigrationDataError("File Page is missing or is not a live Page")
        owner = task or page
        required = [row.get("hash"), "models", *(owner.get("requires") or [])]
        required.extend((page.get("hash"), owner.get("hash")))
        required = list(dict.fromkeys(value for value in required if value))
        desired = {"task": task_key, "task_page": task_page_key} if task_key else {"page": page_key}
        desired["requires"] = required
        removed = {"page", "task", "task_page"} - desired.keys()
        changed = any(name in row for name in removed) or any(row.get(name) != value for name, value in desired.items())
        if task_key and "task_page" not in row.exclude_from_indexes:
            row.exclude_from_indexes.add("task_page")
            changed = True
        for name in removed:
            row.pop(name, None)
        row.update(desired)
        return changed

    scan_kind(
        result, context, KINDS.files, lambda row: row.get("type") == "file",
        transform, reference=_file_record_reference,
    )
    return result


def migrate_canonical_restrictions(context: MigrationContext) -> MigrationResult:
    result = _result("RST-002", "Canonical restriction groups")
    groups = {
        row.key: row.get("hash")
        for row in context.query_factory(KINDS.users).fetch_iter()
        if row.get("type") in {"group", "public_group"}
    }

    def transform(row):
        stored = row.get("restricted_to") or []
        if not isinstance(stored, list) or any(not isinstance(value, str) or not value for value in stored):
            raise MigrationDataError("Local restrictions must be an array of group hashes")
        if set(stored) == {"owner"}:
            desired = ["admin"]
        elif stored:
            desired = sorted(set(stored) - {"owner"})
        else:
            keys = row.get("groups") or []
            if any(not groups.get(key) for key in keys):
                raise MigrationDataError("A restricted group is missing; repair the reference before retrying")
            desired = sorted({groups[key] for key in keys})
        if stored == desired:
            return False
        if desired:
            row["restricted_to"] = desired
        else:
            row.pop("restricted_to", None)
        return True

    scan_kind(result, context, KINDS.models, lambda row: row.get("type") == "form", transform)
    scan_kind(result, context, KINDS.instances, lambda row: row.get("type") == "page", transform)
    return result
