"""Composable contracts for AI-report proposal display adapters."""

from dataclasses import dataclass
from enum import Enum
from typing import Callable


class ProposalActionGrouping(Enum):
    """How one proposal action participates in the grouped display tree."""

    REFERENCE = "reference"
    PAGE = "page"
    TASK = "task"
    PAGE_ATTACHMENT = "page-attachment"
    TASK_ATTACHMENT = "task-attachment"
    PAGE_FORM = "page-form"
    PAGE_CATEGORY = "page-category"
    FILE_MOVE = "file-move"
    FILE_SUMMARY = "file-summary"
    SCHEMA = "schema"
    REVIEW = "review"


@dataclass(frozen=True)
class InheritedProposalDetail:
    """A detail copied from an action referenced by another action."""

    reference_roots: tuple[str, ...]
    label: str
    value_roots: tuple[str, ...]


@dataclass(frozen=True)
class ProposalActionDisplay:
    """Display behavior registered for one proposal action type."""

    action_type: str
    prefix: str
    details: Callable | None = None
    grouping: ProposalActionGrouping = ProposalActionGrouping.REFERENCE
    label_detail: str | None = None
    inherited_details: tuple[InheritedProposalDetail, ...] = ()
    hidden: bool = False
    prefer_file_label: bool = False
