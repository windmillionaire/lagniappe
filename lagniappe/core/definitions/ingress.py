"""Durable CSV ingress workflow contracts."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


INGRESS_FORMAT_VERSION = 1
INGRESS_BATCH_SIZE = 25


# @testable true
# @tests tests_unit/test_006d_ingress_service.py::test_transition_table_covers_every_ingress_stage
# @pair ingress:transition-contract
class IngressStage(Enum):
    """Strict, ordered stages of the CSV import workflow."""

    PROCESS_CSV = auto()
    CHOOSE_TYPE = auto()
    CHOOSE_PARENT = auto()
    CHOOSE_FORM = auto()
    ASSIGN_COLUMNS = auto()
    VERIFY_IMPORT = auto()
    IMPORTING = auto()
    COMPLETED = auto()


CONFIGURATION_STAGES = (
    IngressStage.PROCESS_CSV,
    IngressStage.CHOOSE_TYPE,
    IngressStage.CHOOSE_PARENT,
    IngressStage.CHOOSE_FORM,
    IngressStage.ASSIGN_COLUMNS,
    IngressStage.VERIFY_IMPORT,
)


# @testable infrastructure
class IngressRunStatus(Enum):
    """Durable execution states for an ingress import."""

    IDLE = "idle"
    QUEUED = "queued"
    # Read-compatible states from the former worker-lease implementation.
    RUNNING = "running"
    STOP_REQUESTED = "stop_requested"
    STOPPED = "stopped"
    FAILED = "failed"
    COMPLETED = "completed"


# @testable infrastructure
class IngressAction(Enum):
    """Actions the current durable state permits a client to request."""

    NAVIGATE = "navigate"
    ADVANCE = "advance"
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    DELETE_IMPORTED = "delete_imported"


# Machine-readable transition inventory. Runtime guards in IngressService apply
# prerequisite and cursor/status checks that cannot be represented here.
INGRESS_TRANSITIONS = {
    "create": (None, IngressStage.PROCESS_CSV),
    "navigate": (CONFIGURATION_STAGES, CONFIGURATION_STAGES),
    "advance": (
        CONFIGURATION_STAGES[:-1],
        CONFIGURATION_STAGES[1:],
    ),
    "start": (IngressStage.VERIFY_IMPORT, IngressStage.IMPORTING),
    "finish": (IngressStage.IMPORTING, IngressStage.COMPLETED),
}


# @testable infrastructure
class IngressError(ValueError):
    """Base error for an ingress contract violation."""


# @testable infrastructure
class IngressFormatError(IngressError):
    """The persisted ingress record is not supported by this service."""


# @testable infrastructure
class IngressTransitionError(IngressError):
    """The requested state transition is not valid from the current state."""


# @testable infrastructure
@dataclass(frozen=True)
class IngressMutationPlan:
    """Serializable row mutation description plus executable entity objects."""

    row_index: int
    idempotency_key: str
    result: dict[str, Any]
    entities: tuple[Any, ...] = field(default=(), repr=False, compare=False)

    # @testable infrastructure
    def to_dict(self):
        return {
            "row_index": self.row_index,
            "idempotency_key": self.idempotency_key,
            "result": self.result,
            "entities": [
                {
                    "kind": getattr(entity, "entity_kind", None)
                    or getattr(entity, "kind", None),
                    "id": getattr(entity, "urlsafe_key", None),
                }
                for entity in self.entities
            ],
        }


# @testable infrastructure
@dataclass(frozen=True)
class IngressBatchResult:
    """Outcome returned by one worker batch."""

    state: str
    processed: int
    total: int
    results: tuple[dict[str, Any], ...] = ()
    dispatch_next: bool = False
    reason: str | None = None


# @testable infrastructure
@dataclass(frozen=True)
class IngressProgress:
    """Server-owned ingress state projected to web clients."""

    stage: str
    run_status: str
    processed: int
    total: int
    error: str | None
    stopped: bool
    actions: tuple[str, ...]
    poll_after_ms: int | None

    # @testable infrastructure
    def to_dict(self):
        return {
            "stage": self.stage,
            "run_status": self.run_status,
            "processed": self.processed,
            "total": self.total,
            "error": self.error,
            "stopped": self.stopped,
            "actions": list(self.actions),
            "poll_after_ms": self.poll_after_ms,
        }
