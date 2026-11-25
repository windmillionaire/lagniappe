"""Public explanations for execution failures. Raw exception text stays in the ledger."""

from enum import Enum
from typing import Literal, TypedDict

from config.form_schema import SchemaValidationError
from lagniappe.core import exceptions

from .actions.common import PAGE_FORM_TYPE_ERROR, TASK_FORM_TYPE_ERROR


class FailureReason(Enum):
    CONFLICT = "A record changed during execution. Refresh the affected records before retrying."
    PERMISSION = "Access to a required record or operation was denied. Check the current permissions."
    MISSING_REFERENCE = "A referenced record is unavailable. Check the action’s references."
    MISSING_FILE = "A referenced report file is unavailable. Check the plan’s input files."
    FORM_TYPE = "The form type does not match the action. Check whether it requires a Page or Task form."
    TASK_ONLY_FIELD = "A Page form contains a Task-only field. Move the field to a Task form or remove it."
    FORM_SCHEMA = "A form definition failed validation. Check its field types, table columns and options."
    VALIDATION = "Validation failed. Check the submitted values and referenced records."
    DEPENDENCY = "A required earlier action did not complete. Review its outcome first."
    UNEXPECTED = "An unexpected error interrupted execution. Retry the plan and check the report if it recurs."
    UNKNOWN = "This run has no recorded public cause. Review the plan and its affected records before retrying."


class ExecutionFailure(TypedDict):
    scope: Literal["action", "batch"]
    code: str


def _known_reason(message: str) -> FailureReason | None:
    if message.startswith("You do not have permission"):
        return FailureReason.PERMISSION
    if message.startswith("Referenced entity not found:") or message == "Missing required entity reference.":
        return FailureReason.MISSING_REFERENCE
    if message == "Referenced report file was not found.":
        return FailureReason.MISSING_FILE
    if message in (PAGE_FORM_TYPE_ERROR, TASK_FORM_TYPE_ERROR):
        return FailureReason.FORM_TYPE
    if message.endswith("is available only on task forms.") or message == "Todo lists are supported only on task forms":
        return FailureReason.TASK_ONLY_FIELD
    return None


def execution_failure(error: Exception, *, scope: Literal["action", "batch"]) -> ExecutionFailure:
    if isinstance(error, exceptions.MutationConflict):
        reason = FailureReason.CONFLICT
    elif isinstance(error, SchemaValidationError):
        reason = _known_reason(str(error)) or FailureReason.FORM_SCHEMA
    elif isinstance(error, exceptions.ValidationError):
        reason = _known_reason(str(error)) or FailureReason.VALIDATION
    else:
        reason = FailureReason.UNEXPECTED
    return {"scope": scope, "code": reason.name}


def public_failure_reason(record: dict[str, object]) -> str | None:
    status = record.get("status")
    if status not in ("failed", "skipped"):
        return None
    failure = record.get("failure")
    if isinstance(failure, dict):
        code = failure.get("code")
        reason = FailureReason.__members__.get(code) if isinstance(code, str) else None
        if reason is not None:
            prefix = "The batch containing this action could not be saved. " if failure.get("scope") == "batch" else ""
            return prefix + reason.value
    # Historical ledgers have only private exception text. Match known diagnostics
    # to fixed explanations without publishing identifiers or submitted values.
    message = record.get("error")
    if isinstance(message, str) or status == "failed":
        reason = _known_reason(message) if isinstance(message, str) else None
        return (reason or FailureReason.UNKNOWN).value
    return None
