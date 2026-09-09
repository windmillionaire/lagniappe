"""2.0.0 single-owner Files and materialized local restriction lists."""

from .base import MigrationDataError
from ..core import KINDS


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_file_migration_normalizes_history_and_preserves_conflicts
# @matrix files migrations : single-owner history conflict idempotence
# @pair database-migrations:actionable-links
def migrate_file_ownership(context):
    from ..migrations import _file_record_reference, _result, scan_kind

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

    # @testable false
    # @covered-by lagniappe/core/tools/database/migration_steps/v2_0_permissions.py::migrate_file_ownership
    # @reason row adapter preserves conflicting legacy records for explicit repair
    def transform(row):
        candidates = set(references.get(row.key, ()))
        candidates.update(row.get("pages") or [])
        candidates.update(row.get("tasks") or [])
        candidates.update(key for key in (row.get("page"), row.get("task")) if key)
        candidates = {histories[key].get("task") or key.parent if key in histories else key
                      for key in candidates}
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


# @testable true
# @tests tests_unit/test_009g_restriction_reconciliation.py::test_restrictions_migration_only_persists_local_sources
# @matrix permissions migrations : local-restrictions owner-only idempotence
def migrate_local_restrictions(context):
    from ..migrations import _result, scan_kind

    result = _result("RST-001", "Materialized local restrictions")
    groups = {row.key: row.get("hash") for row in context.query_factory(KINDS.users).fetch_iter()
              if row.get("type") in {"group", "public_group"}}

    # @testable false
    # @covered-by lagniappe/core/tools/database/migration_steps/v2_0_permissions.py::migrate_local_restrictions
    # @reason row adapter materializes local groups without following any Form relation
    def transform(row):
        stored = row.get("restricted_to") or []
        if stored == ["owner"]:
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
