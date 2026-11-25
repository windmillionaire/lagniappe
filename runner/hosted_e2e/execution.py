"""Dispatch a hosted test selection and wait for its Cloud Run execution."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence

from .evidence import results
from .runtime import (
    EXECUTION_RE,
    HostedE2EError,
    HostedE2EInfrastructure,
    _activate,
    _describe,
    _environment,
    _gcloud,
    _infrastructure,
    _json_result,
    _state_ready,
    _write_json,
)


def _execution_name(payload, *output, environment="standard"):
    selected = _environment(environment)
    prefix = f"{selected.job}-"
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    name = metadata.get("name") if isinstance(metadata, dict) else None
    if isinstance(name, str) and "/" in name:
        name = name.rsplit("/", 1)[-1]
    if (
        isinstance(name, str)
        and name.startswith(prefix)
        and EXECUTION_RE.fullmatch(name)
    ):
        return name
    escaped_prefix = re.escape(prefix)
    patterns = (
        rf"\bexecutions/(?P<name>{escaped_prefix}[a-z0-9-]*[a-z0-9])\b",
        rf"\bExecution\s+\[?(?P<name>{escaped_prefix}[a-z0-9-]*[a-z0-9])\]?",
        rf"\bexecutions\s+describe\s+(?P<name>{escaped_prefix}[a-z0-9-]*[a-z0-9])\b",
    )
    for value in output:
        for pattern in patterns:
            match = re.search(pattern, value or "")
            if match and EXECUTION_RE.fullmatch(match.group("name")):
                return match.group("name")
    return None


def _wait_for_execution(
    infrastructure: HostedE2EInfrastructure,
    execution: str,
    *,
    timeout: float = 9000,
    poll_interval=5,
    report_interval=300,
    report: bool = True,
    monotonic: Callable[[], float] = time.monotonic,
    sleep=time.sleep,
):
    """Wait for one Cloud Run execution and report useful periodic status."""
    started = monotonic()
    deadline = started + timeout
    visibility_deadline = started + 120
    next_report = started
    previous_phase = None

    while True:
        payload = _describe(
            [
                "run",
                "jobs",
                "executions",
                "describe",
                execution,
                f"--region={infrastructure.region}",
                f"--project={infrastructure.project}",
            ]
        )
        now = monotonic()
        if payload is None:
            if now >= visibility_deadline:
                raise HostedE2EError(
                    f"Cloud Run execution {execution} did not become visible."
                )
            phase = "STARTING"
            terminal = False
            exit_status = None
            task_count = 1
            succeeded = running = failed = 0
            message = "Waiting for Cloud Run to publish execution status."
        else:
            status = payload.get("status")
            status = status if isinstance(status, dict) else {}
            spec = payload.get("spec")
            spec = spec if isinstance(spec, dict) else {}
            conditions = status.get("conditions")
            conditions = conditions if isinstance(conditions, list) else []
            completed = next(
                (
                    condition
                    for condition in conditions
                    if isinstance(condition, dict)
                    and condition.get("type") == "Completed"
                ),
                {},
            )
            completed_status = str(completed.get("status") or "Unknown")
            terminal = bool(status.get("completionTime")) or completed_status in {
                "True",
                "False",
            }
            task_count = int(spec.get("taskCount") or 1)
            succeeded = int(status.get("succeededCount") or 0)
            running = int(status.get("runningCount") or 0)
            failed = int(status.get("failedCount") or 0)
            message = str(completed.get("message") or "").strip()
            if terminal:
                exit_status = 0 if completed_status == "True" and not failed else 1
                phase = "PASSED" if exit_status == 0 else "FAILED"
            else:
                exit_status = None
                started_condition = any(
                    isinstance(condition, dict)
                    and condition.get("type") == "Started"
                    and condition.get("status") == "True"
                    for condition in conditions
                )
                phase = "RUNNING" if running or started_condition else "STARTING"

        should_report = report and (
            now >= next_report or phase != previous_phase or terminal
        )
        if should_report:
            elapsed = max(0, int(now - started))
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours:
                elapsed_label = f"{hours}h {minutes}m {seconds}s"
            elif minutes:
                elapsed_label = f"{minutes}m {seconds}s"
            else:
                elapsed_label = f"{seconds}s"
            if task_count == 1:
                detail = (
                    f"completed after {elapsed_label}"
                    if terminal
                    else f"{elapsed_label} elapsed"
                )
            else:
                detail = (
                    f"{succeeded}/{task_count} tasks succeeded, "
                    f"{running} running, {failed} failed"
                )
            print(
                f"[{hours:02d}:{minutes:02d}:{seconds:02d}] {phase}: {detail}",
                flush=True,
            )
            if terminal and message:
                print(f"  {message}", flush=True)
            while next_report <= now:
                next_report += report_interval
            previous_phase = phase

        if terminal:
            return payload, exit_status
        if now >= deadline:
            raise HostedE2EError(
                f"Cloud Run execution {execution} did not finish within "
                f"{timeout} seconds."
            )
        sleep(poll_interval)


def execute(
    *,
    targets: Sequence[str] = (),
    import_results: bool = True,
    progress: bool = True,
    environment: str = "standard",
    experiments: bool | str = False,
) -> dict[str, object]:
    """Execute the shared Cloud Run job and normally import its evidence."""
    from testing.utility.hosted_e2e_job import validate_focused_targets

    selected = _environment(environment)
    targets = tuple(targets or ())
    if experiments:
        if targets:
            raise HostedE2EError("--experiments cannot be combined with --target")
        if experiments not in {True, "pilot", "all"}:
            raise HostedE2EError("Unknown coordinated E2E scope")
        if experiments != "all":
            from runner.e2e_pilot import TARGETS
            targets = TARGETS
    if targets:
        try:
            targets = validate_focused_targets(targets)
        except RuntimeError as error:
            raise HostedE2EError(str(error)) from error
    suite = "e2e" if experiments == "all" else "focused" if targets else "all"

    _activate(adc=import_results)
    infrastructure = _infrastructure()
    state = _state_ready(infrastructure)
    # Cloud Run's execution override uses gcloud's UpdateAction parser, which
    # rejects repeated list entries such as separate ``--target`` tokens.
    # ``argparse`` accepts the equivalent equals form inside the container.
    job_arguments = (["--experiments=all"] if experiments == "all" else ["--experiments"]) if experiments else [f"--target={target}" for target in targets]
    result = _gcloud(
        "run",
        "jobs",
        "execute",
        selected.job,
        f"--region={infrastructure.region}",
        f"--project={infrastructure.project}",
        f"--args={','.join(job_arguments)}",
        "--async",
        "--format=json",
        check=False,
        timeout=300,
    )
    payload = {}
    if result.stdout.strip():
        try:
            payload = _json_result(result, "Cloud Run execution")
        except HostedE2EError:
            if result.returncode == 0:
                raise
    execution = _execution_name(
        payload,
        result.stdout,
        result.stderr,
        environment=selected.name,
    )
    if execution is None:
        raise HostedE2EError(
            result.stderr.strip() or "Cloud Run did not identify the job execution."
        )
    state["last_execution"] = execution
    state["last_suite"] = suite
    state["last_targets"] = list(targets)
    _write_json(selected.state_path, state, owner_only=True)
    if progress:
        print(f"Hosted E2E execution: {execution}", flush=True)
        print(
            "Progress updates will be printed every 5 minutes and when status changes.",
            flush=True,
        )
    _provider_status, exit_status = _wait_for_execution(
        infrastructure,
        execution,
        report=progress,
    )
    if not import_results:
        return {"execution": execution, "exit_status": exit_status, "suite": suite}
    manifest = results(
        execution=execution,
        latest=False,
        merge=True,
        environment=selected.name,
    )
    return manifest
