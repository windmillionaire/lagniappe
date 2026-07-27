"""Structural evidence helpers for the final full-suite E2E baseline."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from enum import Enum
import hashlib
import json
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
EVIDENCE_JSON = Path("reports/test_runs/structural_evidence_latest.json")
EVIDENCE_MARKDOWN = Path("reports/test_runs/structural_evidence_latest.md")
_TIMING_KEY_PARTS = ("duration", "elapsed", "latency", "timing")
COMPONENT_REFRESH_INSTRUMENTATION = r"""
(components, stats) => {
    for (const [componentName, component] of Object.entries(components)) {
        if (typeof component.refresh === "function") {
            const componentRefresh = component.refresh.bind(component);
            component.refresh = async (...args) => {
                stats.component_refreshes[componentName] =
                    (stats.component_refreshes[componentName] || 0) + 1;
                return await componentRefresh(...args);
            };
        }
        for (const [widgetName, widget] of Object.entries(component.widgets)) {
            if (typeof widget.refresh !== "function") continue;
            const widgetRefresh = widget.refresh.bind(widget);
            widget.refresh = async (...args) => {
                const label = `${componentName}:${widgetName}`;
                stats.widget_reconciliations[label] =
                    (stats.widget_reconciliations[label] || 0) + 1;
                return await widgetRefresh(...args);
            };
        }
    }
}
""".strip()


def stable_key(value: Any) -> str | None:
    """Return a stable printable identifier for a datastore key-like value."""
    if value is None:
        return None
    if hasattr(value, "key"):
        return stable_key(value.key)
    if hasattr(value, "to_legacy_urlsafe"):
        encoded = value.to_legacy_urlsafe()
        return encoded.decode() if isinstance(encoded, bytes) else str(encoded)
    return str(value)


def _json_default(value: Any) -> Any:
    if isinstance(value, bytes):
        return {
            "byte_length": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    key = stable_key(value)
    if key is not None:
        return key
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize evidence values deterministically for byte counts and hashes."""
    return json.dumps(
        value,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _relation_size(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (list, tuple, set)):
        return len(value)
    return 1


def dataset_inventory(rows_by_kind: Mapping[str, Iterable[Any]]) -> dict[str, Any]:
    """Summarize the accumulated E2E datastore without retaining row contents."""
    materialized = {kind: list(rows) for kind, rows in rows_by_kind.items()}
    entity_types: Counter[str] = Counter()
    projects: dict[str, str] = {}
    project_tasks: Counter[str] = Counter()
    task_shape = Counter()
    page_shape = Counter()
    relation_references = Counter()

    for rows in materialized.values():
        for row in rows:
            entity_type = str(row.get("type") or "untyped")
            entity_types[entity_type] += 1

            if entity_type == "project":
                projects[stable_key(getattr(row, "key", None)) or "-"] = str(
                    row.get("name") or "Unnamed project"
                )
            elif entity_type == "task":
                project_key = stable_key(row.get("project"))
                if project_key:
                    project_tasks[project_key] += 1
                    task_shape["with_project"] += 1
                if row.get("completed"):
                    task_shape["completed"] += 1
                if row.get("page"):
                    task_shape["with_page"] += 1
                if row.get("form"):
                    task_shape["with_form"] += 1
                if row.get("model"):
                    task_shape["with_model_task"] += 1
            elif entity_type == "page":
                if row.get("form"):
                    page_shape["with_form"] += 1
                if row.get("model"):
                    page_shape["with_primary_category"] += 1
                if row.get("categories"):
                    page_shape["with_additional_categories"] += 1
                if row.get("files"):
                    page_shape["with_files"] += 1

            for relation in (
                "categories",
                "files",
                "form",
                "model",
                "page",
                "project",
                "tasks",
                "users",
            ):
                relation_references[relation] += _relation_size(row.get(relation))

    project_sizes = sorted(project_tasks.values())
    top_projects = [
        {
            "key": key,
            "name": projects.get(key, "Unknown project"),
            "task_count": count,
        }
        for key, count in project_tasks.most_common(10)
    ]
    return {
        "total_rows": sum(len(rows) for rows in materialized.values()),
        "datastore_kinds": {
            kind: len(rows) for kind, rows in sorted(materialized.items())
        },
        "entity_types": dict(sorted(entity_types.items())),
        "task_shape": dict(sorted(task_shape.items())),
        "page_shape": dict(sorted(page_shape.items())),
        "relation_references": dict(sorted(relation_references.items())),
        "project_task_distribution": {
            "total_projects": len(projects),
            "projects_with_tasks": len(project_sizes),
            "projects_without_tasks": max(0, len(projects) - len(project_sizes)),
            "minimum": project_sizes[0] if project_sizes else 0,
            "median": median(project_sizes) if project_sizes else 0,
            "maximum": project_sizes[-1] if project_sizes else 0,
            "top_projects": top_projects,
        },
    }


def entity_load_summary(loads: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate structured ``Entities`` load traces without losing callers."""
    rows = [dict(load) for load in loads]
    callers: dict[str, dict[str, int]] = {}
    signatures: Counter[tuple[Any, ...]] = Counter()
    for row in rows:
        caller = str(row.get("caller") or "-")
        caller_row = callers.setdefault(
            caller,
            {
                "calls": 0,
                "datastore_requests": 0,
                "first_batch_keys": 0,
                "related_batch_keys": 0,
            },
        )
        caller_row["calls"] += 1
        caller_row["datastore_requests"] += int(row.get("db_reads") or 0)
        caller_row["first_batch_keys"] += int(row.get("first_batch_keys") or 0)
        caller_row["related_batch_keys"] += int(
            row.get("related_batch_keys") or 0
        )
        signatures[
            (
                caller,
                row.get("operation"),
                tuple(row.get("primary") or ()),
                tuple(row.get("secondary") or ()),
                tuple(row.get("related") or ()),
            )
        ] += 1

    repeated = [
        {
            "caller": signature[0],
            "operation": signature[1],
            "occurrences": count,
            "primary": list(signature[2]),
            "secondary": list(signature[3]),
            "related": list(signature[4]),
        }
        for signature, count in signatures.items()
        if count > 1
    ]
    return {
        "calls": len(rows),
        "datastore_requests": sum(int(row.get("db_reads") or 0) for row in rows),
        "first_batch_calls": sum(
            int(row.get("first_batch_calls") or 0) for row in rows
        ),
        "related_batch_calls": sum(
            int(row.get("related_batch_calls") or 0) for row in rows
        ),
        "first_batch_keys": sum(
            int(row.get("first_batch_keys") or 0) for row in rows
        ),
        "related_batch_keys": sum(
            int(row.get("related_batch_keys") or 0) for row in rows
        ),
        "callers": dict(sorted(callers.items())),
        "repeated_load_signatures": sorted(
            repeated,
            key=lambda row: (-row["occurrences"], row["caller"]),
        ),
    }


def prompt_evidence(prompt: Any, *, provider_tokens: Any = None) -> dict[str, Any]:
    """Describe and fingerprint one prompt without persisting its text."""
    built = prompt.build()
    intro = str(getattr(prompt, "intro", "") or "")
    contexts = list(getattr(prompt, "context_blocks", ()) or ())
    instructions = list(getattr(prompt, "instruction_blocks", ()) or ())
    inline_parts = [
        {
            "mime_type": part.get("mime_type"),
            "byte_length": len(part.get("bytes") or b""),
            "sha256": hashlib.sha256(part.get("bytes") or b"").hexdigest(),
        }
        for part in (getattr(prompt, "bytes", ()) or ())
    ]
    file_parts = list(getattr(prompt, "files", ()) or ())
    tools = getattr(prompt, "tools", None)
    response_schema = getattr(prompt, "response_schema", None)
    fingerprint_payload = {
        "intro": intro,
        "contents": built,
        "inline_parts": inline_parts,
        "file_parts": file_parts,
        "tools": tools,
        "response_schema": response_schema,
        "output_format": getattr(prompt, "output_format", None),
        "model_tier": getattr(prompt, "model_tier", None),
    }
    fingerprint_bytes = canonical_json_bytes(fingerprint_payload)
    return {
        "prompt_type": getattr(prompt, "prompt_type", None),
        "request_sha256": hashlib.sha256(fingerprint_bytes).hexdigest(),
        "request_fingerprint_bytes": len(fingerprint_bytes),
        "system_instruction_bytes": len(intro.encode("utf-8")),
        "content_bytes": len(built.encode("utf-8")),
        "context_blocks": len(contexts),
        "context_bytes": sum(
            len(str(block.get("value") or "").encode("utf-8"))
            for block in contexts
        ),
        "instruction_blocks": len(instructions),
        "instruction_bytes": sum(
            len(str(block.get("content") or "").encode("utf-8"))
            for block in instructions
        ),
        "inline_parts": inline_parts,
        "inline_bytes": sum(part["byte_length"] for part in inline_parts),
        "file_reference_count": len(file_parts),
        "file_reference_bytes": len(canonical_json_bytes(file_parts)),
        "tool_count": len(tools) if isinstance(tools, list) else int(bool(tools)),
        "tools": list(tools) if isinstance(tools, list) else tools,
        "response_schema_bytes": len(canonical_json_bytes(response_schema)),
        "provider_token_count": provider_tokens,
        "provider_token_source": (
            "provider count response"
            if provider_tokens is not None
            else "not requested by the deterministic local collector"
        ),
    }


def full_e2e_collection_state(
    *,
    expected_files: Iterable[str],
    selected_files: Iterable[str],
    keyword: str = "",
    mark_expression: str = "not unfinished",
) -> dict[str, Any]:
    """Classify whether pytest selected the complete E2E file set."""
    expected = sorted(set(expected_files))
    selected = sorted(set(selected_files))
    reasons = []
    if expected != selected:
        reasons.append("selected E2E files do not match the repository E2E file set")
    if keyword:
        reasons.append("a -k expression filtered the collection")
    if (mark_expression or "").strip() not in {"", "not unfinished"}:
        reasons.append("a non-default marker expression filtered the collection")
    return {
        "full_e2e_run": not reasons,
        "expected_files": len(expected),
        "selected_files": len(selected),
        "reasons": reasons,
    }


def _timing_paths(value: Any, path: str = "$") -> list[str]:
    paths = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            normalized = str(key).lower().replace("-", "_")
            if any(part in normalized for part in _TIMING_KEY_PARTS):
                paths.append(child_path)
            paths.extend(_timing_paths(child, child_path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            paths.extend(_timing_paths(child, f"{path}[{index}]"))
    return paths


def assert_no_timing_metrics(record: Mapping[str, Any]) -> None:
    """Reject evidence records that accidentally introduce timing measurements."""
    paths = _timing_paths(record)
    if paths:
        raise ValueError("Timing metrics are not allowed: " + ", ".join(paths))


def _markdown_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "—"
    return str(value)


def render_markdown(record: Mapping[str, Any]) -> str:
    """Render a compact human-readable companion to the structured record."""
    dataset = record.get("dataset") or {}
    workflows = record.get("workflows") or {}
    lines = [
        "# Full-suite structural evidence",
        "",
        f"- Generated: {_markdown_value(record.get('generated_at'))}",
        f"- E2E clean before evidence check: {_markdown_value(record.get('suite_clean'))}",
        f"- Accumulated datastore rows: {_markdown_value(dataset.get('total_rows'))}",
        "- Timing metrics: deliberately excluded",
        "",
        "## Dataset",
        "",
        "```json",
        json.dumps(dataset, indent=2, sort_keys=True, default=_json_default),
        "```",
    ]
    for name, workflow in workflows.items():
        lines.extend(
            [
                "",
                f"## {name.replace('_', ' ').title()}",
                "",
                "```json",
                json.dumps(workflow, indent=2, sort_keys=True, default=_json_default),
                "```",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def write_evidence(
    record: Mapping[str, Any],
    *,
    json_path: Path = EVIDENCE_JSON,
    markdown_path: Path = EVIDENCE_MARKDOWN,
) -> tuple[Path, Path]:
    """Atomically write the latest JSON and Markdown evidence artifacts."""
    assert_no_timing_metrics(record)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "structural-evidence-baseline",
        **record,
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)

    json_temporary = json_path.with_suffix(json_path.suffix + ".tmp")
    markdown_temporary = markdown_path.with_suffix(markdown_path.suffix + ".tmp")
    json_temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    markdown_temporary.write_text(render_markdown(payload), encoding="utf-8")
    json_temporary.replace(json_path)
    markdown_temporary.replace(markdown_path)
    return json_path, markdown_path
