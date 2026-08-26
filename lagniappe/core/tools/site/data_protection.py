"""Read-only disaster-recovery status for the administrator view."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re

from google.protobuf.json_format import MessageToDict

from lagniappe import CONFIG
from lagniappe.core.tools.database.core import DATA


RUNTIME_CATALOG_OBJECT = "data-lifecycle/recovery-catalog.json"


# @testable false
# @covered-by lagniappe/core/tools/site/data_protection.py::data_protection_status
# @reason provider timestamp normalization is exercised by the public status projection
def _timestamp(value):
    """Return a readable provider timestamp while preserving unknown values."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value).strip()
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text

    suffix = ""
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
        suffix = " UTC"
    time = moment.strftime("%I:%M %p").lstrip("0")
    return f"{time}, {moment.strftime('%d %b %Y')}{suffix}"


# @testable false
# @covered-by lagniappe/core/tools/site/data_protection.py::data_protection_status
# @reason provider message normalization is exercised by the public status projection
def _message(value):
    if isinstance(value, dict):
        return dict(value)
    return MessageToDict(getattr(value, "_pb", value), preserving_proto_field_name=True)


# @testable false
# @covered-by lagniappe/core/tools/site/data_protection.py::data_protection_status
# @reason schedule formatting is exercised by the public status projection
def _schedule(payload):
    recurrence = "Daily" if "daily_recurrence" in payload else "Weekly"
    weekly = payload.get("weekly_recurrence") or {}
    day = str(weekly.get("day") or "").title()
    retention = str(payload.get("retention") or "")
    if retention.endswith("s") and retention[:-1].isdigit():
        seconds = int(retention[:-1])
        retention = (
            f"{seconds // 86400} days"
            if seconds % 86400 == 0
            else retention
        )
    return {
        "recurrence": f"{recurrence}{f' ({day})' if day else ''}",
        "retention": retention or "Unknown",
    }


# @testable false
# @covered-by lagniappe/core/tools/site/data_protection.py::data_protection_status
# @reason backup formatting is exercised by the public status projection
def _backup(payload, project_id):
    resource_name = str(payload.get("name") or "").strip()
    expected = re.compile(
        rf"projects/{re.escape(project_id)}/locations/[A-Za-z0-9._-]+/"
        r"backups/[A-Za-z0-9._-]+"
    )
    return {
        "id": resource_name.rsplit("/", 1)[-1],
        "state": str(payload.get("state") or "Unknown").removeprefix("STATE_").title(),
        "snapshot_time": _timestamp(payload.get("snapshot_time")),
        "expire_time": _timestamp(payload.get("expire_time")),
        "prepare_command": (
            f"./setup.sh backup prepare {resource_name.rsplit('/', 1)[-1]}"
            if expected.fullmatch(resource_name)
            else None
        ),
    }


# @testable true
# @tests tests_unit/test_024_data_protection_status.py::test_data_protection_status_is_sanitized_and_read_only
# @matrix admin disaster-recovery : human-readable-timestamps native-backups recovery-catalog sanitization schedules
def data_protection_status(admin_client=None):
    """Return provider metadata and a sanitized manual-backup catalog."""
    project_id = CONFIG.GOOGLE_CLOUD_PROJECT
    if admin_client is None:
        from google.cloud import firestore_admin_v1

        admin_client = firestore_admin_v1.FirestoreAdminClient(
            credentials=CONFIG.google_credentials
        )
    database = f"projects/{project_id}/databases/(default)"
    database_payload = _message(admin_client.get_database(name=database))
    pitr_state = str(
        database_payload.get("point_in_time_recovery_enablement") or ""
    ).upper()
    pitr_enabled = pitr_state.endswith("ENABLED")
    earliest_version_time = database_payload.get("earliest_version_time")
    schedules = admin_client.list_backup_schedules(parent=database)
    schedule_values = getattr(schedules, "backup_schedules", schedules)
    backups = admin_client.list_backups(parent=f"projects/{project_id}/locations/-")
    backup_values = getattr(backups, "backups", backups)
    backup_payloads = [_message(item) for item in backup_values]
    backup_payloads = [
        item
        for item in backup_payloads
        if not item.get("database") or item.get("database") == database
    ]

    recovery_sets = []
    try:
        raw = DATA.private_bucket.blob(RUNTIME_CATALOG_OBJECT).download_as_text(
            encoding="utf-8"
        )
        catalog = json.loads(raw)
        if (
            catalog.get("format") == "lagniappe-runtime-recovery-catalog"
            and catalog.get("schema_version") == 1
        ):
            allowed = {
                "backup_id",
                "snapshot_time",
                "completed_at",
                "application_version",
                "entity_count",
                "asset_count",
                "consistency",
            }
            recovery_sets = [
                {key: item[key] for key in allowed if key in item}
                for item in catalog.get("recovery_sets") or []
                if isinstance(item, dict)
            ]
            for item in recovery_sets:
                for key in ("snapshot_time", "completed_at"):
                    if key in item:
                        item[key] = _timestamp(item[key])
    except Exception:
        recovery_sets = []

    return {
        "database": "(default)",
        "pitr": (
            "Enabled (7-day point-in-time window)"
            if pitr_enabled
            else "Disabled"
        ),
        "earliest_version_time": _timestamp(earliest_version_time),
        "schedules": [_schedule(_message(item)) for item in schedule_values],
        "native_backups": [_backup(item, project_id) for item in backup_payloads],
        "recovery_sets": recovery_sets,
        "instructions": {
            "create_manual": "./setup.sh backup create",
        },
    }


__all__ = ["data_protection_status"]
