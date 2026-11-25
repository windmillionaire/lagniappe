"""2.0.0 single-owner Files and materialized local restriction lists."""

from .base import MigrationContext, MigrationResult

from .base import MigrationDataError, _file_record_reference, _result, scan_kind
from ..core import KINDS


def migrate_file_ownership(context: MigrationContext) -> MigrationResult:
    result = _result("FIL-001", "Single-owner Files")
    owners = {row.key: row for row in context.query_factory(KINDS.instances).fetch_iter()
              if row.get("type") in {"page", "task"}}
    histories = {row.key: row for row in context.query_factory(KINDS.history).fetch_iter()
                 if row.get("type") == "task_history"}
    references = {}
    for row in [*owners.values(), *histories.values()]:
        if row.get("type") not in {"task", "task_history"}:
            continue
        owner_key = row.key if row.get("type") == "task" else row.get("task") or row.key.parent
        for file_key in row.get("files") or []:
            references.setdefault(file_key, set()).add(owner_key)

    def transform(row):
        # Singular links are authoritative after FIL-001. Historical snapshots
        # may still reference a File that has since moved to another owner.
        explicit = {key for key in (row.get("page"), row.get("task")) if key}
        candidates = set() if explicit else set(references.get(row.key, ()))
        legacy = set(row.get("pages") or []) | set(row.get("tasks") or [])
        legacy = {histories[key].get("task") or key.parent if key in histories else key
                  for key in legacy}
        candidates.update(legacy)
        candidates.update(explicit)
        candidates = {histories[key].get("task") or key.parent if key in histories else key
                      for key in candidates}
        # An interim build mirrored a singular Task's Page in File.page.
        # A legacy plural Page link is an independent attachment, so never
        # collapse that conflict merely because it is also the Task's Page.
        task_key = row.get("task")
        if task_key in histories:
            task_key = histories[task_key].get("task") or task_key.parent
        task = owners.get(task_key)
        mirrored_page = row.get("page")
        if (task and task.get("type") == "task" and mirrored_page
                and mirrored_page == task.get("page") and mirrored_page not in legacy):
            candidates.discard(mirrored_page)
        if len(candidates) > 1:
            raise MigrationDataError("File has multiple owners; repair its Page/Task references before retrying")
        desired = {}
        if candidates:
            owner_key = next(iter(candidates))
            owner = owners.get(owner_key)
            if not owner:
                raise MigrationDataError("File owner is missing or is not a live Page/Task")
            desired[owner["type"]] = owner_key
            required = [row.get("hash"), "models", *(owner.get("requires") or [])]
            required.append(owner.get("hash"))
            desired["requires"] = list(dict.fromkeys(value for value in required if value))
        changed = any(name in row for name in ("pages", "tasks")) or any(row.get(k) != v for k, v in desired.items())
        row.pop("pages", None)
        row.pop("tasks", None)
        row.update(desired)
        return changed

    scan_kind(
        result, context, KINDS.files, lambda row: row.get("type") == "file",
        transform, reference=_file_record_reference,
    )
    return result


def migrate_local_restrictions(context: MigrationContext) -> MigrationResult:
    result = _result("RST-001", "Materialized local restrictions")
    groups = {row.key: row.get("hash") for row in context.query_factory(KINDS.users).fetch_iter()
              if row.get("type") in {"group", "public_group"}}

    def transform(row):
        stored = row.get("restricted_to") or []
        if stored in (["owner"], ["admin"]):
            desired = stored
        else:
            keys = row.get("groups") or []
            if any(not groups.get(key) for key in keys):
                raise MigrationDataError("A restricted group is missing; repair the reference before retrying")
            hashes = {groups[key] for key in keys}
            desired = ["owner", *sorted(hashes - {"owner"})] if hashes else []
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
