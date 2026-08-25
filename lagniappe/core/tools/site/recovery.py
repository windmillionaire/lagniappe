"""Fail-closed acquisition of complete recovery configuration snapshots."""

from config.recovery import (
    RecoveryConfigurationError,
    build_recovery_snapshot,
    read_recovery_redis_ca,
)
from lagniappe.core.tools.database import site as site_database


# @testable false
# @covered-by lagniappe/core/tools/site/recovery.py::load_recovery_snapshot
# @reason typed failure construction is exercised through the public snapshot loader
class RecoverySnapshotUnavailable(RuntimeError):
    """A recovery export could not be assembled without omitting live state."""

    def __init__(self, public_message):
        super().__init__(public_message)
        self.public_message = public_message


# @testable true
# @tests tests_unit/test_026_site_admin.py::test_recovery_snapshot_merges_live_settings
# @tests tests_unit/test_026_site_admin.py::test_recovery_snapshot_failures_use_safe_public_messages
# @matrix admin : failure-isolation live-settings recovery-export
def load_recovery_snapshot(persisted):
    """Return a canonical snapshot or a safe typed failure."""
    try:
        return build_recovery_snapshot(
            persisted,
            deployment_settings=site_database.deployment(),
            ai_settings=site_database.ai(),
            redis_ca_pem=read_recovery_redis_ca(persisted),
        )
    except Exception as error:
        message = (
            "The recovery snapshot is incomplete."
            if isinstance(error, RecoveryConfigurationError)
            else "The recovery snapshot could not be read."
        )
        raise RecoverySnapshotUnavailable(
            f"{message} No settings were downloaded."
        ) from error
