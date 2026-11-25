"""Collect dependency changes and command output for Markdown and console reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
import shlex
from typing import TypedDict

from config import Directory


@dataclass
class VersionChange:
    """A before/after dependency version or requested-range change."""

    ecosystem: str
    name: str
    before: str
    after: str
    source: str
    direct: bool = True


@dataclass
class CommandLog:
    """Captured subprocess output for the upgrade report."""

    command: str
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    error: str = ""


@dataclass
class UpgradeReport:
    """State collected while the dependency upgrade runs."""

    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None
    changes: list[VersionChange] = field(default_factory=list)
    command_logs: list[CommandLog] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    report_path: Path | None = None

    def add_change(
        self,
        ecosystem: str,
        name: str,
        before: object,
        after: object,
        source: str,
        *,
        direct: bool = True,
    ) -> None:
        before_text = _version_text(before)
        after_text = _version_text(after)
        if before_text == after_text:
            return
        self.changes.append(
            VersionChange(
                ecosystem=ecosystem,
                name=name,
                before=before_text,
                after=after_text,
                source=source,
                direct=direct,
            )
        )

    def add_error(self, step: str, message: str) -> None:
        self.errors.append(f"{step}: {message}")

    def add_note(self, message: str) -> None:
        self.notes.append(message)

    def record_command(
        self,
        command: list[str] | str,
        returncode: int | None,
        *,
        stdout: str | None = "",
        stderr: str | None = "",
        error: str = "",
    ) -> None:
        self.command_logs.append(
            CommandLog(
                command=_format_command(command),
                returncode=returncode,
                stdout=stdout or "",
                stderr=stderr or "",
                error=error,
            )
        )


def _version_text(value: object) -> str:
    if value is None or value == "":
        return "(missing)"
    return str(value)


def _format_command(command: list[str] | str) -> str:
    if isinstance(command, str):
        return command
    return shlex.join(str(part) for part in command)


def record_mapping_changes(
    report: UpgradeReport,
    ecosystem: str,
    before: dict[str, str],
    after: dict[str, str],
    source: str,
    *,
    direct_names: set[str] | None = None,
    direct: bool = True,
) -> None:
    """Record sorted before/after changes between two version maps."""
    for name in sorted(set(before) | set(after), key=str.lower):
        before_value = before.get(name)
        after_value = after.get(name)
        if before_value == after_value:
            continue
        is_direct = direct if direct_names is None else name in direct_names
        change_source = source
        if direct_names is not None:
            change_source = (
                f"{source} (direct)" if is_direct else f"{source} (transitive)"
            )
        report.add_change(
            ecosystem,
            name,
            before_value,
            after_value,
            change_source,
            direct=is_direct,
        )


def default_upgrade_report_path(timestamp: datetime | None = None) -> Path:
    """Return a timestamped dependency upgrade report path."""
    stamp = (timestamp or datetime.now()).strftime("%Y%m%d_%H%M%S")
    candidate = Directory.REPORTS.value / f"upgrade-{stamp}.md"
    suffix = 2
    while candidate.exists():
        candidate = Directory.REPORTS.value / f"upgrade-{stamp}-{suffix}.md"
        suffix += 1
    return candidate


def _markdown(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _inline_code(value: object) -> str:
    escaped = str(value).replace("`", "\\`")
    return f"`{escaped}`"


def _fenced_text(value: str) -> str:
    return value.rstrip().replace("```", "`` `") or "(no output)"


def _render_change_table(title: str, changes: list[VersionChange]) -> list[str]:
    if not changes:
        return []

    lines = [f"### {title}", ""]
    lines.extend(
        [
            "| Package | Before | After | Source |",
            "| --- | --- | --- | --- |",
        ]
    )
    for change in changes:
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown(change.name),
                    _markdown(change.before),
                    _markdown(change.after),
                    _markdown(change.source),
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


def _changes_by(
    report: UpgradeReport,
    ecosystem: str,
    source: str | None = None,
) -> list[VersionChange]:
    changes = [
        change
        for change in report.changes
        if change.ecosystem == ecosystem and (source is None or change.source == source)
    ]
    return sorted(changes, key=lambda change: change.name.lower())


def _is_warning_line(line: str) -> bool:
    if line.strip() == "npm warn allow-scripts":
        return False
    return bool(re.match(r"^(WARNING:|WARN\b|npm warn\b)", line.strip(), re.IGNORECASE))


class WarningSummary(TypedDict):
    count: int
    commands: list[int]


def _warning_summary(report: UpgradeReport) -> dict[str, WarningSummary]:
    warnings: dict[str, WarningSummary] = {}
    for index, log in enumerate(report.command_logs, start=1):
        for output in (log.stdout, log.stderr, log.error):
            for line in output.splitlines():
                warning = line.strip()
                if not warning or not _is_warning_line(warning):
                    continue
                item = warnings.setdefault(
                    warning,
                    {"count": 0, "commands": []},
                )
                item["count"] += 1
                commands = item["commands"]
                if index not in commands:
                    commands.append(index)
    return warnings


def _render_warnings(report: UpgradeReport) -> list[str]:
    warnings = _warning_summary(report)
    if not warnings:
        return []

    lines = [
        "## Warnings",
        "",
        "| Warning | Count | Commands |",
        "| --- | ---: | --- |",
    ]
    for warning, details in warnings.items():
        commands = details["commands"]
        command_list = ", ".join(f"#{index}" for index in commands)
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown(warning),
                    str(details["count"]),
                    command_list,
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


def render_upgrade_report(report: UpgradeReport) -> str:
    """Render the captured upgrade run as Markdown."""
    status = "completed with errors" if report.errors else "completed"
    finished_at = report.finished_at or datetime.now()
    lines = [
        "# Dependency Upgrade Report",
        "",
        f"- Started: {report.started_at.isoformat(timespec='seconds')}",
        f"- Finished: {finished_at.isoformat(timespec='seconds')}",
        f"- Status: {status}",
        "",
    ]

    change_lines = []
    for title, changes in (
        ("Node.js", _changes_by(report, "node")),
        (
            "npm Exact Direct Packages",
            _changes_by(report, "npm", "package-lock.json (direct)"),
        ),
        (
            "npm Exact Transitive Packages",
            _changes_by(report, "npm", "package-lock.json (transitive)"),
        ),
        (
            "npm Requested Ranges",
            _changes_by(report, "npm", "package.json"),
        ),
        (
            "pip Installed Packages",
            _changes_by(report, "pip", "installed environment"),
        ),
        (
            "requirements-installer.txt Pins",
            _changes_by(report, "pip", "requirements-installer.txt"),
        ),
        (
            "requirements.txt Pins",
            _changes_by(report, "pip", "requirements.txt"),
        ),
        (
            "requirements-dev.txt Pins",
            _changes_by(report, "pip", "requirements-dev.txt"),
        ),
        (
            "build/font-requirements.txt Pins",
            _changes_by(report, "pip", "build/font-requirements.txt"),
        ),
    ):
        change_lines.extend(_render_change_table(title, changes))

    lines.extend(["## Version Changes", ""])
    if change_lines:
        lines.extend(change_lines)
    else:
        lines.extend(["_No version changes recorded._", ""])

    if report.errors:
        lines.extend(["## Errors", ""])
        lines.extend(f"- {_markdown(error)}" for error in report.errors)
        lines.append("")

    if report.notes:
        lines.extend(["## Notes", ""])
        lines.extend(f"- {_markdown(note)}" for note in report.notes)
        lines.append("")

    lines.extend(_render_warnings(report))

    if report.command_logs:
        lines.extend(["## Command Output", ""])
    for index, log in enumerate(report.command_logs, start=1):
        returncode = "not started" if log.returncode is None else str(log.returncode)
        lines.extend(
            [
                f"### {index}. {_inline_code(log.command)}",
                "",
                f"- Exit code: {returncode}",
            ]
        )
        if log.error:
            lines.append(f"- Error: {_markdown(log.error)}")
        lines.extend(
            [
                "",
                "stdout:",
                "",
                "```text",
                _fenced_text(log.stdout),
                "```",
                "",
                "stderr:",
                "",
                "```text",
                _fenced_text(log.stderr),
                "```",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def write_upgrade_report(
    report: UpgradeReport,
    report_path: Path | None = None,
) -> Path:
    """Save the Markdown upgrade report under reports/."""
    report.finished_at = datetime.now()
    path = report_path or default_upgrade_report_path(report.finished_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    report.report_path = path
    path.write_text(render_upgrade_report(report), encoding="utf-8")
    return path


def _console_changes(
    report: UpgradeReport,
    ecosystem: str,
    preferred_sources: tuple[str, ...],
) -> list[VersionChange]:
    for source in preferred_sources:
        changes = _changes_by(report, ecosystem, source)
        if changes:
            return changes
    return []


def _print_console_group(title: str, changes: list[VersionChange]) -> None:
    print(f"\n{title}:")
    if not changes:
        print("  No changes")
        return
    for change in changes:
        print(f"  {change.name}: {change.before} -> {change.after}")


def print_upgrade_summary(
    report: UpgradeReport,
    success: bool,
    report_path: Path,
) -> None:
    """Print the concise console summary for an upgrade run."""
    print("Lagniappe dependency upgrade")
    print("Complete." if success else "Completed with errors.")

    _print_console_group("Node.js", _changes_by(report, "node"))
    _print_console_group(
        "npm packages",
        _console_changes(
            report,
            "npm",
            ("package-lock.json (direct)", "package.json"),
        ),
    )
    _print_console_group(
        "pip packages",
        _console_changes(
            report,
            "pip",
            (
                "installed environment",
                "requirements-installer.txt",
                "requirements.txt",
                "requirements-dev.txt",
            ),
        ),
    )

    if report.errors:
        print("\nErrors:")
        for error in report.errors[:5]:
            print(f"  {error}")
        remaining = len(report.errors) - 5
        if remaining > 0:
            print(f"  ... {remaining} more in the report")

    print(f"\nReport: {report_path}")
