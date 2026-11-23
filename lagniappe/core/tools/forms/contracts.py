"""Persisted Form-change vocabulary and value helpers shared below workflows."""
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

from ...exceptions import ValidationError

if TYPE_CHECKING:
    from google.cloud.datastore import Key

    from ...definitions.asset import AssetDefinition
    from ...entities.entity import Entity
    from ...properties.base_schema import FieldDefinition
    from .conversions import FieldChange, MigrationNotice


class ChangeRejection(TypedDict):
    id: str
    error: str


class ChangeStatus(TypedDict):
    id: str
    operation: str | None
    phase: str
    status: str | None
    progress: Mapping[str, object] | None
    error: str | None
    failed_entity: dict[str, object] | None
    can_cancel: bool


class FormPublication(TypedDict):
    draft: Mapping[str, object]
    baseline: str
    image_urls: Mapping[str, str]
    post_commit_complete: NotRequired[bool]
    pending_change: NotRequired[ChangeStatus]
    rejected_change: NotRequired[ChangeRejection]
    form_key: NotRequired[str | None]


class ChangeTarget(TypedDict):
    name: str | None
    schema: list[FieldDefinition]
    assets: dict[str, AssetDefinition]
    generation: int
    version: str | None
    html_fields: dict[str, str]


class PendingFormChange(TypedDict):
    id: str
    digest: str
    source_generation: int
    baseline: str
    zone: str
    operations: list[FieldChange]
    instructions: dict[str, str]
    require_visibility: bool
    phase: str
    applied: bool
    image_urls: dict[str, str]
    attempt_assets: list[dict[str, object]] | None
    target: ChangeTarget
    job: NotRequired[str]
    report: NotRequired[str | None]
    report_fingerprint: NotRequired[str]
    action_id: NotRequired[str]
    scope_fingerprint: NotRequired[str | None]
    resume_checkpoint: NotRequired[dict[str, object]]


PENDING = "pending_form_change"
NOTICE = "pre_migration"
RECEIPT = "form_change_receipt"
ANSWER_FIELDS = (
    "form",
    "submission",
    "generation",
    "completed",
    "completed_submission",
    "assets",
)


def json_value(raw: Mapping[str, object], name: str) -> dict[str, object]:
    value = raw.get(name)
    value = json.loads(value) if isinstance(value, str) else deepcopy(value)
    if value is not None and not isinstance(value, dict):
        raise ValidationError("Saved form change data needs repair.")
    return value or {}


def check_size(raw: Mapping[str, object]) -> None:
    if (
        len(json.dumps(dict(raw), default=str, ensure_ascii=False).encode())
        > 900 * 1024
    ):
        raise ValidationError(
            "A submission or Form is too large to retain its changed values. No further changes were applied."
        )


def needs_ai_value(value: object) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return False
    return not (isinstance(value, dict) and (value == {"rows": []} or value == {"items": []}))


def pending_change(raw: Mapping[str, object]) -> PendingFormChange | None:
    """Decode the migration record written by start_change and its claimed job."""
    value = json_value(raw, PENDING)
    return cast(PendingFormChange, value) if value else None


def migration_notice(raw: Mapping[str, object]) -> MigrationNotice:
    """Read the field-by-field original values retained by convert_submission."""
    return cast("MigrationNotice", json_value(raw, NOTICE))


def persisted_key(entity: Entity) -> Key:
    """Form transactions and exact-state guards require a stored identity."""
    key = entity.key
    if key is None:
        raise ValidationError("This item must be saved before updating its form.")
    return key
