"""Structured prompt builder for Gemini content generation."""

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import BinaryIO
    from werkzeug.datastructures import FileStorage
    from lagniappe.core.entities.user import User
    from lagniappe.core.entities.file import File
    from lagniappe.core.properties.file_assets import FilePart

import json
import re
from typing import Self, TypedDict

from lagniappe.core.definitions import FileConsumer, enforce_file_consumer

from .constants import gemini_mimetype
from .guidelines import (
    JSON_OUTPUT_RULES,
    MARKDOWN_GENERATION_RULES,
    TEXT_OUTPUT_RULES,
)


HEADING_RE = re.compile(r"^(#{2,6})\s+(.+?)\s*$", re.MULTILINE)

# These identities are code-authored contracts. Unknown or user-authored prompt types
# intentionally receive no identity and are normalized to ``unknown`` at persistence.
PROMPT_OBSERVABILITY_CONTRACTS = {
    "form conversion": ("forms", "conversion", "form-conversion", 1),
    "file summary": ("files", "summary", "file-summary", 1),
    "ai report": ("reports", "planning", "ai-report", 1),
    "category generation": ("categories", "generation", "category-generation", 1),
    "image aspect ratio": ("images", "aspect-ratio", "image-aspect-ratio", 1),
    "autofill": ("autofill", "generation", "form-autofill", 5),
    "scheduling": ("scheduling", "generation", "schedule-generation", 1),
    "document text": ("documents", "generation", "document-text", 1),
    "project generation": ("projects", "generation", "project-generation", 1),
    "form generation": ("forms", "generation", "form-generation", 1),
}

TOOL_CALL_PLANNING = """
### Tool Call Planning

- Before each tool turn, identify all useful calls whose arguments are already known.
- Request those independent calls together in the same turn, including every
  applicable `get_guidelines` bundle.
- Defer a call only when its arguments depend on an earlier tool result. Do not
  add unnecessary calls merely to form a batch.
- When get_help is available, consult it for questions about Lagniappe features
  and cite the returned topic URLs. General help does not establish the user's
  permission to act on a particular record.
"""


class InlinePart(TypedDict):
    bytes: bytes
    mime_type: str


class OutputFormat(TypedDict):
    type: str
    description: str | None
    requirements: str | None


# @testable true
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_prompt_tracks_context_output_examples_and_attachments
# @tests tests_unit/test_015b_ai_prompt_builders.py::test_prompt_rejects_oversized_inline_file_before_read
# @matrix ai : attachments cache-prefix context output-format prompt service-tier tool-batching tools
class Prompt:
    """Composable prompt that assembles context, instructions, and output format into a single request."""

    mode: str | None
    report_file_refs: tuple[str, ...]
    require_organization: bool

    def __init__(self, intro: str = "", user: User | None = None, type: str | None = None) -> None:
        self.prompt_type = type
        self.intro = intro
        self.context_blocks = []
        self.instruction_blocks = []
        self.output_format: OutputFormat | None = None
        self.examples = []
        self._bytes: list[InlinePart] = []
        self._files: list[FilePart] = []
        self.search = False
        self._tools: list[str] | bool | None = None
        self._user = user
        self._thinking_budget = None
        self._thinking_level = None
        self._max_tool_iterations = None
        self._max_tool_file_parts_per_turn = None
        self._allowed_actions = None
        self._model_tier = "primary"
        self._service_tier = None
        self._response_schema = None
        self._instructions_before_context = False
        contract = PROMPT_OBSERVABILITY_CONTRACTS.get(type) if type is not None else None
        self._observability_contract = (
            {
                "workflow": contract[0],
                "stage": contract[1],
                "id": contract[2],
                "version": contract[3],
            }
            if contract
            else None
        )

    @property
    def observability_contract(self) -> dict[str, str | int]:
        return dict(self._observability_contract or {})

    def set_task(self, intro: str) -> Self:
        """Set the system instruction / high-level task for the prompt."""
        self.intro = intro
        return self

    def _replace_or_append(self, blocks, block, role=None, unique=False):
        if role:
            block["role"] = role
        if unique and role:
            for index, existing in enumerate(blocks):
                if existing.get("role") == role:
                    blocks[index] = block
                    return self
        blocks.append(block)
        return self

    @staticmethod
    def _strip_leading_heading(value):
        text = str(value).strip()
        lines = text.splitlines()
        if lines and lines[0].startswith("#"):
            return "\n".join(lines[1:]).strip()
        return text

    def add_context(self, key: str, value: object, quote: bool = True, role: str | None = None, unique: bool = False) -> Self:
        """Add a labeled context block to the prompt.

        Args:
            key: Context label (underscores become title-cased words).
            value: Context value; dicts/lists are JSON-serialized.
            quote: Whether to wrap the value in code fences.
            role: Optional semantic role for audit/replacement.
            unique: Replace an existing block with the same role.
        """
        if not value:
            return self

        label = key.replace("_", " ").title()

        if isinstance(value, (dict, list)):
            value = json.dumps(value, indent=2, ensure_ascii=False)

        value = f"```\n{value}\n```" if quote else str(value)

        return self._replace_or_append(
            self.context_blocks,
            {"label": label, "value": value},
            role=role,
            unique=unique,
        )

    def add_workspace_concepts(self, concepts: str) -> Self:
        """Add one deduplicated workspace-concepts context block."""
        return self.add_context(
            "lagniappe_concepts",
            self._strip_leading_heading(concepts),
            quote=False,
            role="workspace_concepts",
            unique=True,
        )

    def add_instructions(
        self,
        instructions: str,
        section_title: str | None = None,
        role: str | None = None,
        unique: bool = False,
    ) -> Self:
        """Append an instruction block to the prompt."""
        block = {"title": section_title, "content": instructions.strip()}
        return self._replace_or_append(
            self.instruction_blocks,
            block,
            role=role,
            unique=unique,
        )

    def add_decision_policy(self, instructions: str) -> Self:
        """Append instructions that define decision boundaries."""
        return self.add_instructions(instructions, role="decision_policy")

    def add_preflight_checks(self, instructions: str) -> Self:
        """Append final self-check instructions."""
        return self.add_instructions(
            instructions,
            role="preflight_checks",
            unique=True,
        )

    def add_output_contract(
        self,
        format_type: str,
        description: str | None = None,
        include_requirements: bool = True,
    ) -> Self:
        """Alias for set_output_format, for prompt builders that use semantic roles."""
        return self.set_output_format(
            format_type,
            description=description,
            include_requirements=include_requirements,
        )

    def set_output_format(self, format_type: str, description: str | None = None, include_requirements: bool = True) -> Self:
        """Set the expected output format (JSON, MARKDOWN, IMAGE, or TEXT)."""
        self.output_format = {
            "type": format_type,
            "description": description,
            "requirements": None,
        }

        if not include_requirements:
            return self

        if format_type == "JSON":
            self.output_format["requirements"] = JSON_OUTPUT_RULES
        elif format_type == "MARKDOWN":
            self.output_format["requirements"] = MARKDOWN_GENERATION_RULES
        elif format_type == "TEXT":
            self.output_format["requirements"] = TEXT_OUTPUT_RULES

        return self

    @property
    def response_schema(self) -> dict[str, object] | None:
        return self._response_schema

    def set_response_schema(self, schema: dict[str, object] | None) -> Self:
        """Set the provider-side schema for structured JSON responses."""
        self._response_schema = schema
        return self

    def add_example(self, example: object, title: str | None = None) -> Self:
        """Add an example output to the prompt."""
        self.examples.append({"example": example, "title": title})
        return self

    @property
    def thinking_budget(self) -> int | None:
        return self._thinking_budget

    def set_thinking_budget(self, budget: int | None) -> Self:
        """Set the thinking token budget (0 disables thinking, None uses model default)."""
        self._thinking_budget = budget
        self._thinking_level = None
        return self

    @property
    def thinking_level(self) -> str | None:
        return self._thinking_level

    def set_thinking_level(self, level: str | None) -> Self:
        """Set a model-supported thinking level instead of a token budget."""
        self._thinking_level = level
        self._thinking_budget = None
        return self

    @property
    def max_tool_iterations(self) -> int | None:
        return self._max_tool_iterations

    def set_max_tool_iterations(self, iterations: int) -> Self:
        """Set the maximum function-calling loop iterations for this prompt."""
        self._max_tool_iterations = iterations
        return self

    @property
    def max_tool_file_parts_per_turn(self) -> int | None:
        return self._max_tool_file_parts_per_turn

    def set_max_tool_file_parts_per_turn(self, count: int) -> Self:
        """Limit original file parts attached after one function-call turn."""
        self._max_tool_file_parts_per_turn = count
        return self

    @property
    def allowed_actions(self) -> tuple[str, ...] | None:
        return self._allowed_actions

    def set_allowed_actions(self, actions: Iterable[str] | None) -> Self:
        """Set report action types allowed for prompts that return proposals."""
        self._allowed_actions = tuple(actions or [])
        return self

    @property
    def model_tier(self) -> str:
        return self._model_tier

    def set_model_tier(self, tier: str) -> Self:
        """Select the configured primary or utility model for this prompt."""
        if tier not in ("primary", "utility"):
            raise ValueError("Model tier must be primary or utility.")
        self._model_tier = tier
        return self

    @property
    def service_tier(self) -> str | None:
        return self._service_tier

    def set_service_tier(self, tier: str | None) -> Self:
        """Select an optional Gemini request service tier."""
        if tier is not None and tier not in ("standard", "priority", "flex"):
            raise ValueError("Service tier must be standard, priority, flex, or None.")
        self._service_tier = tier
        return self

    def set_instructions_before_context(self, enabled: bool = True) -> Self:
        """Place stable instructions before request-specific context."""
        self._instructions_before_context = bool(enabled)
        return self

    def enable_search(self) -> Self:
        """Enable Google Search grounding for this prompt."""
        self.search = True
        return self

    def enable_tools(self, *tool_names: str) -> Self:
        """Enable function-calling tools, optionally limited to specific names."""
        self._tools = list(tool_names) if tool_names else True
        return self.add_instructions(
            TOOL_CALL_PLANNING,
            role="tool_call_planning",
            unique=True,
        )

    @property
    def tools(self) -> list[str] | bool | None:
        if self._tools and not self._user:
            raise RuntimeError("Prompt.user must be set when tools are enabled")
        return self._tools

    @property
    def user(self) -> User | None:
        return self._user

    @property
    def bytes(self) -> list[InlinePart]:
        return self._bytes

    def add_bytes(self, file: BinaryIO | FileStorage, mime_type: str | None) -> Self | None:
        """Attach inline file bytes to the prompt.

        Args:
            file: File-like object to read bytes from.
            mime_type: MIME type; normalized to a provider-supported equivalent
                or ignored when unsupported by Gemini.
        """
        mime_type = gemini_mimetype(mime_type)
        if not mime_type:
            return

        enforce_file_consumer(
            file,
            FileConsumer.AI_INLINE,
            filename=getattr(file, "filename", None),
        )
        file.seek(0)
        data = file.read()
        self._bytes.append({"bytes": data, "mime_type": mime_type})
        return self

    @property
    def files(self) -> list[FilePart]:
        return self._files

    def add_file(self, file: File, user: User | None = None) -> Self:
        """Attach a Cloud Storage file reference to the prompt."""
        file_part = file.properties.file.uri_to_ai
        if file_part:
            self._files.append(file_part)
        return self

    def build(self) -> str:
        """Assemble all sections into the final prompt string."""
        sections = []

        def append_context():
            if not self.context_blocks:
                return
            sections.append("## Context\n")
            for context in self.context_blocks:
                sections.append(f"### {context['label']}\n{context['value'].strip()}\n")

        def append_instructions():
            if not self.instruction_blocks:
                return
            sections.append("## Instructions\n")
            for block in self.instruction_blocks:
                sections.append(f"{block['content']}\n")

        if self._instructions_before_context:
            append_instructions()
            append_context()
        else:
            append_context()
            append_instructions()

        if self.output_format:
            sections.append(f"## Output Format: {self.output_format['type']}")
            if self.output_format["description"]:
                sections.append(f"{self.output_format['description']}")
            if self.output_format["requirements"]:
                sections.append(f"{self.output_format['requirements']}")

        if self.examples:
            sections.append("## Example Output\n")
            for e in self.examples:
                example = e.get("example")
                title = e.get("title")
                if title:
                    sections.append(f"### {title}\n")
                if isinstance(example, (dict, list)):
                    sections.append(f"{json.dumps(example, indent=2)}\n")
                else:
                    sections.append(f"{example.strip()}\n")

        return "\n".join(sections).replace("\n\n\n", "\n\n").strip()

    def preview(self) -> str:
        """Build a human-readable prompt preview including the system instruction."""
        sections = []

        if self.intro:
            sections.append(f"## System Instruction\n\n{self.intro.strip()}")

        built = self.build()
        if built:
            sections.append(built)

        return "\n\n".join(sections).strip()

    def audit(self) -> dict[str, object]:
        """Return lightweight prompt composition diagnostics."""
        headings = {}
        for match in HEADING_RE.finditer(self.preview()):
            heading = match.group(2).strip()
            headings[heading] = headings.get(heading, 0) + 1

        return {
            "duplicate_headings": sorted(
                heading for heading, count in headings.items() if count > 1
            ),
        }
