#!/usr/bin/env python3
"""Export the active local Codex transcript and a readable statistics summary."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO


ARCHIVE_NAME = "CODEX_ARCHIVE.jsonl"
SUMMARY_NAME = "CODEX_SESSION.txt"
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


class ExportError(RuntimeError):
    """An expected export failure with a user-actionable message."""


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _token_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return None


def _normalized_usage(value: Any) -> dict[str, int] | None:
    usage = _mapping(value)
    normalized = {
        key: token
        for key in TOKEN_FIELDS
        if (token := _token_value(usage.get(key))) is not None
    }
    return normalized or None


@dataclass
class TranscriptStats:
    record_count: int = 0
    archived_bytes: int = 0
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    session_meta: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    effort: str | None = None
    message_roles: Counter[str] = field(default_factory=Counter)
    fallback_message_roles: Counter[str] = field(default_factory=Counter)
    tool_calls: dict[str, str] = field(default_factory=dict)
    tool_results: set[str] = field(default_factory=set)
    token_usage: dict[str, int] | None = None
    ignored_incomplete_tail: bool = False

    def consume(self, record: dict[str, Any], line_number: int) -> None:
        self.record_count += 1

        timestamp = _text(record.get("timestamp"))
        if timestamp:
            if self.first_timestamp is None:
                self.first_timestamp = timestamp
            self.last_timestamp = timestamp

        record_type = _text(record.get("type")) or ""
        payload = _mapping(record.get("payload"))

        if record_type == "session_meta" and not self.session_meta:
            self.session_meta = payload.copy()

        if record_type == "turn_context":
            self.model = _text(payload.get("model")) or self.model
            self.effort = _text(payload.get("effort")) or self.effort

        if record_type == "response_item":
            self._consume_response_item(payload, line_number)

        if record_type == "event_msg":
            self._consume_event_message(payload)

        usage = self._usage_from_record(record_type, payload)
        if usage is not None:
            self.token_usage = usage

    def _consume_response_item(
        self, payload: dict[str, Any], line_number: int
    ) -> None:
        item_type = _text(payload.get("type")) or ""

        if item_type == "message":
            role = (_text(payload.get("role")) or "other").lower()
            self.message_roles[role] += 1
            return

        identity = _text(payload.get("call_id")) or _text(payload.get("id"))
        if item_type.endswith("_call_output"):
            self.tool_results.add(identity or f"result-line:{line_number}")
            return

        if item_type.endswith("_call"):
            call_key = identity or f"call-line:{line_number}"
            tool_name = _text(payload.get("name"))
            if tool_name is None:
                tool_name = item_type.removesuffix("_call") or "unknown"
            self.tool_calls.setdefault(call_key, tool_name)

    def _consume_event_message(self, payload: dict[str, Any]) -> None:
        event_type = _text(payload.get("type")) or ""
        if event_type == "user_message":
            self.fallback_message_roles["user"] += 1
        elif event_type in {"agent_message", "assistant_message"}:
            self.fallback_message_roles["assistant"] += 1

    @staticmethod
    def _usage_from_record(
        record_type: str, payload: dict[str, Any]
    ) -> dict[str, int] | None:
        if record_type == "token_usage_record":
            return _normalized_usage(payload.get("thread_token_usage"))

        if record_type == "event_msg" and payload.get("type") == "token_count":
            info = _mapping(payload.get("info"))
            return _normalized_usage(info.get("total_token_usage"))

        return None

    @property
    def messages(self) -> Counter[str]:
        if self.message_roles:
            return self.message_roles
        return self.fallback_message_roles


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export the active local Codex chat to CODEX_ARCHIVE.jsonl and "
            "CODEX_SESSION.txt."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="destination directory (default: current directory)",
    )
    parser.add_argument(
        "--archive-name",
        default=ARCHIVE_NAME,
        help=f"archive filename (default: {ARCHIVE_NAME})",
    )
    parser.add_argument(
        "--summary-name",
        default=SUMMARY_NAME,
        help=f"summary filename (default: {SUMMARY_NAME})",
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="explicit Codex transcript path; normally auto-detected",
    )
    parser.add_argument(
        "--session-id",
        help="explicit Codex session/thread ID; normally read from the environment",
    )
    return parser.parse_args(argv)


def _validate_output_name(name: str, option: str) -> str:
    path = Path(name)
    if not name or path.name != name or name in {".", ".."}:
        raise ExportError(f"{option} must be a filename, not a path: {name!r}")
    return name


def _candidate_roots(codex_home: Path) -> list[Path]:
    return [
        root
        for root in (
            codex_home / "sessions",
            codex_home / "archived_sessions",
        )
        if root.is_dir()
    ]


def _session_id_from_file(path: Path) -> str | None:
    try:
        with path.open("rb") as transcript:
            for _ in range(50):
                line = transcript.readline()
                if not line:
                    break
                try:
                    record = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(record, dict) or record.get("type") != "session_meta":
                    continue
                return _text(_mapping(record.get("payload")).get("id"))
    except OSError:
        return None
    return None


def _find_by_session_ids(codex_home: Path, session_ids: list[str]) -> Path:
    roots = _candidate_roots(codex_home)
    if not roots:
        raise ExportError(
            f"No local session directories exist under {codex_home}. "
            "This exporter requires a local Codex transcript."
        )

    candidates: dict[Path, Path] = {}
    for session_id in session_ids:
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise ExportError(f"Invalid Codex session identifier: {session_id!r}")
        for root in roots:
            for path in root.rglob(f"*{session_id}*.jsonl"):
                if path.is_file():
                    candidates[path.resolve()] = path

    paths = sorted(candidates)
    if len(paths) == 1:
        return paths[0]

    if len(paths) > 1:
        exact = [path for path in paths if _session_id_from_file(path) in session_ids]
        if len(exact) == 1:
            return exact[0]
        listed = "\n  ".join(str(path) for path in (exact or paths))
        raise ExportError(
            "More than one transcript matches the active session; refusing to guess:\n"
            f"  {listed}\nPass --source PATH to select one explicitly."
        )

    joined = ", ".join(session_ids)
    raise ExportError(
        f"No local Codex transcript matches session identifier(s): {joined}. "
        "Pass --source PATH if you know the transcript location."
    )


def locate_source(explicit_source: Path | None, explicit_id: str | None) -> Path:
    if explicit_source is not None:
        source = explicit_source.expanduser().resolve()
        if not source.is_file():
            raise ExportError(f"Transcript does not exist or is not a file: {source}")
        return source

    session_ids: list[str] = []
    for value in (
        explicit_id,
        os.environ.get("CODEX_SESSION_ID"),
        os.environ.get("CODEX_THREAD_ID"),
    ):
        if value and value not in session_ids:
            session_ids.append(value)

    if not session_ids:
        raise ExportError(
            "No active Codex session identifier is available. Run this inside a local "
            "Codex chat, or pass --source PATH."
        )

    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return _find_by_session_ids(codex_home.expanduser().resolve(), session_ids)


def _write_snapshot(
    source: Path, archive_stream: BinaryIO, stats: TranscriptStats
) -> None:
    with source.open("rb") as transcript:
        snapshot_size = os.fstat(transcript.fileno()).st_size
        remaining = snapshot_size
        line_number = 0

        while remaining:
            raw_line = transcript.readline(remaining)
            if not raw_line:
                raise ExportError("The source transcript changed while it was being read.")

            line_number += 1
            remaining -= len(raw_line)
            final_fragment = remaining == 0 and not raw_line.endswith(b"\n")

            try:
                record = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                if final_fragment:
                    stats.ignored_incomplete_tail = True
                    break
                raise ExportError(
                    f"Invalid JSON in transcript {source} at line {line_number}: {exc}"
                ) from exc

            if not isinstance(record, dict):
                raise ExportError(
                    f"Transcript record at line {line_number} is not a JSON object."
                )

            archive_stream.write(raw_line)
            stats.archived_bytes += len(raw_line)
            if not raw_line.endswith(b"\n"):
                archive_stream.write(b"\n")
                stats.archived_bytes += 1
            stats.consume(record, line_number)

        if stats.record_count == 0:
            raise ExportError(f"Transcript contains no complete JSON records: {source}")

        archive_stream.flush()
        os.fsync(archive_stream.fileno())


def _fmt_number(value: int | None) -> str:
    return f"{value:,}" if value is not None else "Unavailable"


def _fmt_meta(value: Any) -> str:
    if value is None or value == "":
        return "Unavailable"
    return str(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def render_summary(
    stats: TranscriptStats, source: Path, archive_path: Path
) -> str:
    meta = stats.session_meta
    messages = stats.messages
    known_roles = ("user", "assistant", "developer", "system")
    other_messages = sum(
        count for role, count in messages.items() if role not in known_roles
    )
    total_messages = sum(messages.values())
    tool_counts = Counter(stats.tool_calls.values())

    lines = [
        "Session Info",
        "",
        " Source:",
        f" {source}",
        " Archive:",
        f" {archive_path}",
        f" ID: {_fmt_meta(meta.get('id'))}",
        f" Started: {_fmt_meta(meta.get('timestamp') or stats.first_timestamp)}",
        f" Snapshot Through: {_fmt_meta(stats.last_timestamp)}",
        f" Exported: {_utc_now()}",
        f" Working Directory: {_fmt_meta(meta.get('cwd'))}",
        f" Model: {_fmt_meta(stats.model)}",
        f" Reasoning Effort: {_fmt_meta(stats.effort)}",
        f" Codex Version: {_fmt_meta(meta.get('cli_version'))}",
        f" Records: {stats.record_count:,}",
        "",
        "Messages",
        f" Total: {total_messages:,}",
        f" User: {messages.get('user', 0):,}",
        f" Assistant: {messages.get('assistant', 0):,}",
        f" Developer: {messages.get('developer', 0):,}",
        f" System: {messages.get('system', 0):,}",
    ]
    if other_messages:
        lines.append(f" Other: {other_messages:,}")
    lines.append(
        f" Tools: {len(stats.tool_calls):,} calls, {len(stats.tool_results):,} results"
    )

    if tool_counts:
        lines.extend(["", "Tool Calls"])
        for name, count in sorted(tool_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f" {name}: {count:,}")

    lines.extend(["", "Tokens"])
    usage = stats.token_usage
    if usage is None:
        lines.append(" Unavailable (no cumulative token record in transcript)")
    else:
        input_tokens = usage.get("input_tokens")
        cached_tokens = usage.get("cached_input_tokens")
        cache_write_tokens = usage.get("cache_write_input_tokens")
        output_tokens = usage.get("output_tokens")
        reasoning_tokens = usage.get("reasoning_output_tokens")
        total_tokens = usage.get("total_tokens")
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens

        lines.append(f" Input: {_fmt_number(input_tokens)}")
        if cached_tokens is not None:
            cached_suffix = ""
            if input_tokens:
                cached_suffix = f" ({cached_tokens / input_tokens:.1%})"
            lines.append(f"   Cached: {_fmt_number(cached_tokens)}{cached_suffix}")
            if input_tokens is not None:
                uncached_tokens = max(input_tokens - cached_tokens, 0)
                lines.append(f"   Uncached: {_fmt_number(uncached_tokens)}")
        if cache_write_tokens:
            lines.append(f"   Cache Write: {_fmt_number(cache_write_tokens)}")
        lines.append(f" Output: {_fmt_number(output_tokens)}")
        if reasoning_tokens is not None:
            lines.append(f"   Reasoning: {_fmt_number(reasoning_tokens)}")
        lines.append(f" Total: {_fmt_number(total_tokens)}")

    lines.extend(
        [
            "",
            "Cost",
            " Total: Unavailable (not recorded in Codex transcript)",
            "",
            "Notes",
            " Tool counts are unique top-level call records in the saved transcript.",
            " The snapshot excludes records written after export began.",
        ]
    )
    if stats.ignored_incomplete_tail:
        lines.append(" An incomplete trailing source record was safely omitted.")

    return "\n".join(lines) + "\n"


def _new_temp_file(destination: Path) -> tuple[int, Path]:
    file_descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    return file_descriptor, Path(raw_path)


def export(args: argparse.Namespace) -> tuple[Path, Path, TranscriptStats]:
    source = locate_source(args.source, args.session_id)
    output_dir = args.output_dir.expanduser().resolve()
    archive_name = _validate_output_name(args.archive_name, "--archive-name")
    summary_name = _validate_output_name(args.summary_name, "--summary-name")
    if archive_name == summary_name:
        raise ExportError("Archive and summary filenames must be different.")

    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_dir.is_dir():
        raise ExportError(f"Output path is not a directory: {output_dir}")

    archive_path = output_dir / archive_name
    summary_path = output_dir / summary_name
    for destination in (archive_path, summary_path):
        if destination.exists() and destination.is_dir():
            raise ExportError(f"Output path is a directory: {destination}")
        if destination.resolve() == source:
            raise ExportError(f"Refusing to overwrite the source transcript: {destination}")

    archive_fd: int | None = None
    summary_fd: int | None = None
    archive_temp: Path | None = None
    summary_temp: Path | None = None
    stats = TranscriptStats()

    try:
        archive_fd, archive_temp = _new_temp_file(archive_path)
        with os.fdopen(archive_fd, "wb") as archive_stream:
            archive_fd = None
            _write_snapshot(source, archive_stream, stats)

        summary = render_summary(stats, source, archive_path)
        summary_fd, summary_temp = _new_temp_file(summary_path)
        with os.fdopen(summary_fd, "w", encoding="utf-8", newline="\n") as summary_stream:
            summary_fd = None
            summary_stream.write(summary)
            summary_stream.flush()
            os.fsync(summary_stream.fileno())

        os.replace(archive_temp, archive_path)
        archive_temp = None
        os.replace(summary_temp, summary_path)
        summary_temp = None
    finally:
        if archive_fd is not None:
            os.close(archive_fd)
        if summary_fd is not None:
            os.close(summary_fd)
        for temporary in (archive_temp, summary_temp):
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

    return archive_path, summary_path, stats


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        archive_path, summary_path, stats = export(args)
    except (ExportError, OSError) as exc:
        print(f"export-chat: {exc}", file=sys.stderr)
        return 2

    total_tokens = None if stats.token_usage is None else stats.token_usage.get("total_tokens")
    print(f"Archive: {archive_path}")
    print(f"Summary: {summary_path}")
    print(f"Records: {stats.record_count:,}")
    print(f"Tool calls: {len(stats.tool_calls):,}")
    print(f"Total tokens: {_fmt_number(total_tokens)}")
    print("Snapshot note: later tool output and assistant confirmation are not included.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
