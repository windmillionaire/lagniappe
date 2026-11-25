"""Stream and capture upgrade commands and run them in the selected nvm shell."""

from __future__ import annotations

import codecs
from contextlib import suppress
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import threading
import time

from runner.context import NODE_CLI, NPM_CLI

from .reporting import UpgradeReport, _format_command


def _stop_command(process):
    if os.name == "posix":
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=3)
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    else:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            timeout=10,
        )
        if process.poll() is None:
            process.kill()
    process.wait(timeout=5)


def run_command(
    command: list[str],
    check: bool = True,
    capture: bool = False,
    report: UpgradeReport | None = None,
    timeout: float = 900,
) -> subprocess.CompletedProcess:
    """Stream commands and prompts, retaining output even on timeout or cancel."""
    print(f"\n  $ {_format_command(command)}", flush=True)
    output = {"stdout": [], "stderr": []}
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL if capture else None,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=os.name == "posix",
        )
    except OSError as e:
        if report is not None:
            report.record_command(command, None, error=str(e))
        raise

    def drain(pipe, name, destination):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        with pipe:
            while chunk := pipe.read1(65536):
                text = decoder.decode(chunk)
                output[name].append(text)
                if not capture:
                    destination.write(text)
                    destination.flush()
            text = decoder.decode(b"", final=True)
            output[name].append(text)
            if not capture:
                destination.write(text)
                destination.flush()

    readers = [
        threading.Thread(target=drain, args=(process.stdout, "stdout", sys.stdout), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, "stderr", sys.stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()
    started = time.monotonic()
    failure = None
    try:
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                process.wait(timeout=min(30, remaining))
                break
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - started
                if elapsed >= timeout:
                    raise subprocess.TimeoutExpired(command, timeout) from None
                print(f"  Still running ({elapsed:.0f}s)...", flush=True)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        failure = error
        _stop_command(process)
    finally:
        for reader in readers:
            reader.join(timeout=3)
        if any(reader.is_alive() for reader in readers):
            _stop_command(process)
            for reader in readers:
                reader.join(timeout=3)
        stdout, stderr = "".join(output["stdout"]), "".join(output["stderr"])
        if report is not None:
            report.record_command(
                command, process.returncode, stdout=stdout, stderr=stderr,
                error="Interrupted" if isinstance(failure, KeyboardInterrupt) else str(failure or ""),
            )
    if failure:
        if isinstance(failure, subprocess.TimeoutExpired):
            raise subprocess.TimeoutExpired(failure.cmd, failure.timeout, stdout, stderr) from failure
        raise failure
    if check and process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def run_nvm_command(
    args: list[str],
    *,
    check: bool = True,
    capture: bool = False,
    report: UpgradeReport | None = None,
    timeout: float = 900,
) -> subprocess.CompletedProcess:
    """Run node/npm commands in an nvm shell so they use the latest version.

    nvm is shell-scoped: `nvm use` only affects that shell. Direct subprocess
    calls use whatever node is currently on PATH (often the
    old default). This wraps commands with nvm setup so they see the upgraded
    version.
    """
    nvm_script = Path.home() / ".nvm" / "nvm.sh"
    if not nvm_script.exists():
        return run_command(args, check=check, capture=capture, report=report, timeout=timeout)
    shell_args = list(args)
    if shell_args and shell_args[0] in {NODE_CLI, NPM_CLI}:
        shell_args[0] = Path(shell_args[0]).name
    cmd_str = " ".join(shlex.quote(a) for a in shell_args)
    shell_script = (
        f"source {shlex.quote(str(nvm_script))} "
        f"&& nvm use --silent node && exec {cmd_str}"
    )
    return run_command(
        ["bash", "-lc", shell_script], check=check, capture=capture,
        report=report, timeout=timeout,
    )
