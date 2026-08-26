import json
from types import SimpleNamespace

from lagniappe.core.tools.site import data_protection as protection


class _Blob:
    def download_as_text(self, encoding="utf-8"):
        assert encoding == "utf-8"
        return json.dumps(
            {
                "format": "lagniappe-runtime-recovery-catalog",
                "schema_version": 1,
                "recovery_sets": [
                    {
                        "backup_id": "20260824T120000Z-deadbeef",
                        "snapshot_time": "2026-08-24T11:59:00Z",
                        "entity_count": 12,
                        "asset_count": 3,
                        "root_uri": "gs://must-not-leak/private",
                    }
                ],
            }
        )


class _Admin:
    def get_database(self, *, name):
        assert name.endswith("/databases/(default)")
        return {
            "point_in_time_recovery_enablement": (
                "POINT_IN_TIME_RECOVERY_ENABLED"
            ),
            "earliest_version_time": "2026-08-17T12:00:00Z",
        }

    def list_backup_schedules(self, *, parent):
        assert parent.endswith("/databases/(default)")
        return SimpleNamespace(
            backup_schedules=[
                {"daily_recurrence": {}, "retention": "1209600s"},
                {
                    "weekly_recurrence": {"day": "SUNDAY"},
                    "retention": "8467200s",
                },
            ]
        )

    def list_backups(self, *, parent):
        assert parent.endswith("/locations/-")
        return SimpleNamespace(
            backups=[
                {
                    "name": "projects/test/locations/us/backups/native-id",
                    "state": "READY",
                    "snapshot_time": "2026-08-24T00:00:00Z",
                    "expire_time": "2026-09-07T00:00:00Z",
                    "database": "projects/project-1/databases/(default)",
                },
                {
                    "name": "projects/test/locations/us/backups/scratch-id",
                    "state": "READY",
                    "database": "projects/project-1/databases/scratch-db",
                },
            ]
        )


# @covers lagniappe.core.tools.site.data_protection::data_protection_status
# @matrix admin disaster-recovery : human-readable-timestamps native-backups recovery-catalog sanitization schedules
def test_data_protection_status_is_sanitized_and_read_only(monkeypatch):
    monkeypatch.setattr(protection.CONFIG, "GOOGLE_CLOUD_PROJECT", "project-1")
    monkeypatch.setattr(
        protection.DATA,
        "_private_bucket",
        SimpleNamespace(blob=lambda name: _Blob()),
    )

    result = protection.data_protection_status(admin_client=_Admin())

    assert [item["recurrence"] for item in result["schedules"]] == [
        "Daily",
        "Weekly (Sunday)",
    ]
    assert [item["retention"] for item in result["schedules"]] == [
        "14 days",
        "98 days",
    ]
    assert result["native_backups"][0]["id"] == "native-id"
    assert result["native_backups"][0]["snapshot_time"] == (
        "12:00 AM, 24 Aug 2026 UTC"
    )
    assert result["pitr"] == "Enabled (7-day point-in-time window)"
    assert result["earliest_version_time"] == "12:00 PM, 17 Aug 2026 UTC"
    assert result["recovery_sets"] == [
        {
            "backup_id": "20260824T120000Z-deadbeef",
            "snapshot_time": "11:59 AM, 24 Aug 2026 UTC",
            "entity_count": 12,
            "asset_count": 3,
        }
    ]
    assert result["instructions"] == {
        "create": "./setup.sh backup create",
        "archive": "./setup.sh archive BACKUP_ID",
        "preflight": "./setup.sh restore BACKUP_ID --dry-run",
        "restore": "./setup.sh restore BACKUP_ID",
        "materialize": (
            "./setup.sh backup materialize "
            "projects/PROJECT/locations/LOCATION/backups/BACKUP"
        ),
    }
