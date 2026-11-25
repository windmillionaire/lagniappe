"""Coordinate Node.js, npm, and Python dependency upgrades."""

from __future__ import annotations

import codecs
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import TypedDict
from urllib.request import Request, urlopen

from config import Directory
from runner.context import NODE_CLI, NPM_CLI

from .commands import run_command, run_nvm_command
from .node import (
    NODE_COMMAND,
    NODE_DOCKERFILE_PATH,
    NODE_VERSION_PIN_PATH,
    resolve_node_image,
    update_node_version_pin,
    upgrade_node,
)
from .npm import (
    NPM_COMMAND,
    read_package_json_specs,
    read_package_lock_versions,
    upgrade_npm_packages,
)
from .python_packages import (
    PIP_COMMAND,
    REQUIREMENTS_PATHS,
    check_pip_environment,
    collect_pip_installed_versions,
    get_requirement_targets,
    record_pip_version_changes,
    update_requirements_files,
    upgrade_pip_packages,
)
from .reporting import (
    CommandLog,
    UpgradeReport,
    VersionChange,
    WarningSummary,
    default_upgrade_report_path,
    print_upgrade_summary,
    record_mapping_changes,
    render_upgrade_report,
    write_upgrade_report,
)

__all__ = [
    "NODE_COMMAND",
    "NODE_DOCKERFILE_PATH",
    "NODE_VERSION_PIN_PATH",
    "NPM_COMMAND",
    "PIP_COMMAND",
    "REQUIREMENTS_PATHS",
    "CommandLog",
    "UpgradeReport",
    "VersionChange",
    "WarningSummary",
    "check_pip_environment",
    "collect_pip_installed_versions",
    "default_upgrade_report_path",
    "get_requirement_targets",
    "print_upgrade_summary",
    "read_package_json_specs",
    "read_package_lock_versions",
    "record_mapping_changes",
    "record_pip_version_changes",
    "render_upgrade_report",
    "resolve_node_image",
    "run_command",
    "run_nvm_command",
    "update_node_version_pin",
    "update_requirements_files",
    "upgrade_all",
    "upgrade_node",
    "upgrade_npm_packages",
    "upgrade_pip_packages",
    "write_upgrade_report",
    # Existing callers could also import these names from the single-file runner.
    "Directory",
    "NODE_CLI",
    "NPM_CLI",
    "Path",
    "Request",
    "TypedDict",
    "annotations",
    "codecs",
    "dataclass",
    "datetime",
    "field",
    "hashlib",
    "json",
    "os",
    "re",
    "shlex",
    "shutil",
    "signal",
    "subprocess",
    "suppress",
    "sys",
    "tempfile",
    "threading",
    "time",
    "urlopen",
]


def upgrade_all(*, only: str | None = None) -> int:
    """Run selected upgrade steps with visible progress and a durable report."""
    report = UpgradeReport()
    success = True
    interrupted = False
    steps = [
        ("node", "Node.js", upgrade_node),
        ("npm", "npm packages", upgrade_npm_packages),
        ("python", "Python packages", upgrade_pip_packages),
        ("python", "Python dependency check", check_pip_environment),
        ("python", "Requirements files", update_requirements_files),
    ]
    steps = [item for item in steps if only is None or item[0] == only]
    try:
        for index, (_, step_name, step) in enumerate(steps, start=1):
            print(f"\n[{index}/{len(steps)}] {step_name}", flush=True)
            started = time.monotonic()
            try:
                step_ok = step(report)
                if not step_ok and report.errors:
                    success = False
                    break
            except Exception as error:
                report.add_error(step_name, str(error))
                success = False
                break
            print(f"  Finished in {time.monotonic() - started:.1f}s", flush=True)
    except KeyboardInterrupt:
        interrupted = True
        success = False
        report.add_error("Cancelled", "Interrupted by the user; completed changes are retained.")
    finally:
        success = success and not report.errors
        report_path = write_upgrade_report(report)
        print_upgrade_summary(report, success, report_path)
    if interrupted:
        return 130
    return 0 if success else 1
