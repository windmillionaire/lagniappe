"""Internal worker protocol. Workers never acquire, renew or release the lease."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import signal
import threading

from runner.test_session import inspect_process_identity


def context():
    return json.loads(Path(os.environ["LAGNIAPPE_E2E_WORKER_CONTEXT"]).read_text(encoding="utf-8"))


def assert_owner(record):
    from lagniappe.core.tools.hosted_e2e.lease import e2e_lease_active

    if inspect_process_identity(record["owner"]) != "match" or not e2e_lease_active(record["run_id"]):
        raise RuntimeError("E2E worker coordinator or lease is no longer active")


@contextmanager
def worker_runtime():
    from lagniappe import CONFIG
    from lagniappe.core.entities import Entities
    from testing.utility.e2e_runtime import (
        E2ERuntime, validate_hosted_e2e_health,
    )

    record = context()
    if not CONFIG.testing or CONFIG.PREFIX != "test-" or record["base_url"] != CONFIG.BASE_URL:
        raise RuntimeError("E2E worker environment does not match its coordinator")
    assert_owner(record)
    stopped = threading.Event()

    def monitor():
        while not stopped.wait(1):
            try:
                assert_owner(record)
            except Exception:
                # Kill the worker's own group, including browsers. An orphan must
                # not keep renewing the outer lease or continue the next test.
                os.killpg(os.getpid(), signal.SIGTERM)
                return

    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    try:
        cookies = ()
        if CONFIG.hosted_e2e_runner:
            validate_hosted_e2e_health()
            cookies = tuple(record.get("browser_cookies", ()))
            if len(cookies) != 1:
                raise RuntimeError("Hosted E2E worker requires the coordinator's run cookie")
        else:
            from runner.testing import wait_for_session_server
            if not wait_for_session_server(record["base_url"], record["run_id"],
                                           expected_pid=record["server_pid"],
                                           expected_mode="local-e2e", timeout_seconds=2):
                raise RuntimeError("E2E worker inherited a different local server")
        Entities.initialize()
        yield E2ERuntime(run_id=record["run_id"], browser_cookies=cookies)
        assert_owner(record)
    finally:
        stopped.set()
        watcher.join(timeout=2)


_REDACT_PATTERNS = (
    re.compile(r"https?://\S+", re.IGNORECASE),
    re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\b(?:lgn_|lgmo_|AIza|sk-|ghp_|gho_|ya29\.)[A-Za-z0-9._~-]{8,}"),
)


def _format_target_nodeid(nodeid: str) -> str:
    cleaned = str(nodeid or "").strip()
    if cleaned and not cleaned.startswith("testing/"):
        return f"testing/{cleaned}"
    return cleaned


def _redacted_diagnostic(traceback_text: object, *, limit: int = 160) -> str:
    if not isinstance(traceback_text, str) or not traceback_text.strip():
        return ""
    lines = [line.strip() for line in traceback_text.splitlines() if line.strip()]
    chosen = next((line for line in reversed(lines) if line.startswith("E ")), "")
    chosen = chosen[1:].strip() if chosen else (lines[-1] if lines else "")
    for pattern in _REDACT_PATTERNS:
        chosen = pattern.sub("[redacted]", chosen)
    chosen = " ".join(chosen.split())
    if len(chosen) > limit:
        return chosen[: limit - 1].rstrip() + "…"
    return chosen


def _first_failure_fields(outcomes) -> dict[str, str]:
    for failed_nodeid, row in outcomes.items():
        if not isinstance(row, dict) or row.get("outcome") != "failed":
            continue
        target = _format_target_nodeid(failed_nodeid)
        diagnostic = _redacted_diagnostic(row.get("traceback"))
        if not diagnostic and row.get("failed_phase"):
            diagnostic = f"failed during {row['failed_phase']}"
        return {
            "first_failed_nodeid": target,
            "first_failed_diagnostic": diagnostic,
            "first_failed_rerun": (
                f"venv/bin/python run.py hosted-e2e execute --target {target}"
            ),
        }
    return {}


def write_progress(outcomes, nodeid):
    record = context()
    counts = {state: sum(row["outcome"] == state for row in outcomes.values())
              for state in ("passed", "failed", "skipped")}
    payload = {
        **counts,
        "completed": sum(counts.values()),
        "total": len(record["nodeids"]),
        "last_nodeid": nodeid,
        **_first_failure_fields(outcomes),
    }
    path = Path(record["artifacts"]) / "progress.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)


def write_results(session, outcomes, exitstatus):
    record = context()
    selected = [item.nodeid for item in session.items]
    path = Path(record["artifacts"]) / "outcomes.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "attempt": record["attempt"], "snapshot": record["snapshot"],
        "batch": record["batch"], "exit_status": int(exitstatus),
        "selected": selected, "outcomes": outcomes,
    }), encoding="utf-8")
    temporary.replace(path)
