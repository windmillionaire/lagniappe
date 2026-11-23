"""Fail-closed acquisition of complete recovery configuration snapshots."""

from collections.abc import Mapping

from config.recovery import (
    RecoveryConfigurationError,
    build_recovery_snapshot,
    read_recovery_redis_ca,
)
from lagniappe.core.tools.database import site as site_database


class RecoverySnapshotUnavailable(RuntimeError):
    """A recovery export could not be assembled without omitting live state."""

    def __init__(self, public_message: str) -> None:
        super().__init__(public_message)
        self.public_message = public_message


def load_recovery_snapshot(persisted: Mapping[str, object]) -> dict[str, object]:
    """Return a canonical snapshot or a safe typed failure."""
    try:
        return build_recovery_snapshot(
            persisted,
            deployment_settings=site_database.deployment(),
            ai_settings=site_database.ai(),
            public_page_settings=site_database.public_pages(),
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
