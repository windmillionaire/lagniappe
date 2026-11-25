"""Composable contracts for AI-report proposal display adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..contracts.actions import ActionData, ReportAction
    from .details import ProposalDetailCollector


from dataclasses import dataclass
from enum import Enum
from collections.abc import Callable


class ProposalActionGrouping(Enum):
    """How one proposal action participates in the grouped display tree."""

    REFERENCE = "reference"
    PAGE = "page"
    TASK = "task"
    ATTACHMENT = "attachment"
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
    details: Callable[[ProposalDetailCollector, ActionData, ReportAction], None] | None = None
    grouping: ProposalActionGrouping = ProposalActionGrouping.REFERENCE
    label_detail: str | None = None
    inherited_details: tuple[InheritedProposalDetail, ...] = ()
    hidden: bool = False
    prefer_file_label: bool = False
