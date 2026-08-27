"""Fail-closed ownership tests for local E2E and managed test sessions."""

from pathlib import Path
import os
import subprocess
import sys
import types

import pytest

from runner import test_session


pytestmark = pytest.mark.tooling


class FakeLease:
    def __init__(self):
        self.active = False
        self.handed_off = False

    def __enter__(self):
        self.active = True
        return self

    def assert_active(self):
        if not self.active:
            raise RuntimeError("inactive fake lease")

    def handoff(self):
        self.assert_active()
        self.handed_off = True
        self.active = False

    def __exit__(self, *_args):
        self.active = False


def _identity(pid=4321, *, started="Mon Aug 25 12:00:00 2026"):
    return {
        "pid": pid,
        "pgid": pid,
        "boot_id": "boot-identity",
        "started": started,
        "command_sha256": "command-fingerprint",
    }


def _state(mode="managed-server"):
    owner = _identity()
    return {
        "schema_version": 1,
        "nonce": "nonce-012345678901234567890123",
        "mode": mode,
        "phase": "ready",
        "created_at": "2026-08-25T12:00:00+00:00",
        "heartbeat_at": "2026-08-25T12:00:00+00:00",
        "repository": "/repo",
        "base_url": "http://127.0.0.1:5000",
        "port": 5000,
        "data_namespace": {"project": "project", "prefix": "test-"},
        "artifact_namespaces": ["/repo/reports/test_failures"],
        "command": "run.py test-server --start",
        "recovery_hint": "venv/bin/python run.py test-server --recover",
        "owner": owner,
        "keeper": owner if mode == "managed-server" else None,
        "server": _identity(4322),
        "attachment": None,
    }


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    state_path = tmp_path / "test-session.json"
    lock_path = tmp_path / "test-session.lock"
    monkeypatch.setattr(
        test_session,
        "_state_paths",
        lambda: (state_path, lock_path),
    )
    monkeypatch.setattr(
        test_session,
        "capture_process_identity",
        lambda pid: _identity(pid),
    )
    return state_path, lock_path


# @matrix test-session : concurrency durable-state ownership subprocess
def test_two_subprocess_starts_produce_one_owner(tmp_path):
    script = """
import os
from pathlib import Path
from time import sleep
from types import SimpleNamespace
from runner import test_session

root = Path(os.environ["LAGNIAPPE_SESSION_TEST_ROOT"])
test_session._state_paths = lambda: (
    root / "test-session.json",
    root / "test-session.lock",
)
test_session.SETTINGS = SimpleNamespace(
    test_config={
        "BASE_URL": "http://127.0.0.1:9876",
        "SERVER_PORT": 9876,
        "GOOGLE_CLOUD_PROJECT": "session-test-project",
        "PREFIX": "session_test_",
    },
    GCLOUD_CONFIG={"PROJECT": "session-test-project"},
)

class Lease:
    def __enter__(self): return self
    def assert_active(self): return None
    def __exit__(self, *_args): return None

try:
    authority = test_session.acquire_test_session(
        "local-e2e",
        ["subprocess-test"],
        data_lease_factory=lambda nonce: Lease(),
    )
except test_session.TestSessionBusy:
    print("BUSY", flush=True)
else:
    print("OWNED", flush=True)
    sleep(1)
    authority.rollback_without_cleanup()
"""
    environment = {
        **os.environ,
        "LAGNIAPPE_SESSION_TEST_ROOT": str(tmp_path),
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    }
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    results = [process.communicate(timeout=10) for process in processes]

    assert [process.returncode for process in processes] == [0, 0], results
    assert sorted(stdout.strip() for stdout, _stderr in results) == ["BUSY", "OWNED"]
    assert not (tmp_path / "test-session.json").exists()


# @matrix test-session : mutation-order ownership preflight
def test_busy_session_stops_before_mutation(isolated_state):
    first = test_session.acquire_test_session(
        "local-e2e",
        ["first"],
        data_lease_factory=lambda nonce: FakeLease(),
    )
    second_lease_created = []
    try:
        with pytest.raises(test_session.TestSessionBusy, match="Another local"):
            test_session.acquire_test_session(
                "managed-server",
                ["second"],
                data_lease_factory=lambda nonce: second_lease_created.append(nonce),
            )
        assert second_lease_created == []
    finally:
        first.rollback_without_cleanup()

    managed = test_session.acquire_test_session(
        "managed-server",
        ["managed"],
        data_lease_factory=lambda nonce: FakeLease(),
    )
    try:
        with pytest.raises(test_session.TestSessionBusy):
            test_session.acquire_test_session(
                "local-e2e",
                ["e2e"],
                data_lease_factory=lambda nonce: pytest.fail(
                    "busy local E2E must not acquire the shared data lease"
                ),
            )
    finally:
        managed.rollback_without_cleanup()


# @matrix test-session : managed-start mutation-order ownership
def test_managed_start_conflict_stops_before_mutation(isolated_state, monkeypatch):
    from runner import testing

    first = test_session.acquire_test_session(
        "local-e2e",
        ["first"],
        data_lease_factory=lambda nonce: FakeLease(),
    )
    monkeypatch.setattr(testing, "_configure_test_gcloud", lambda: None)
    monkeypatch.setattr(testing, "require_legacy_test_server_clear", lambda: None)
    for name in (
        "require_server_port_available",
        "ensure_test_frontend_bundle",
        "prepare_test_artifacts",
        "cleanup_test_data",
    ):
        monkeypatch.setattr(
            testing,
            name,
            lambda *_args, _name=name: pytest.fail(
                f"busy managed start reached mutation boundary {_name}"
            ),
        )
    try:
        with pytest.raises(test_session.TestSessionBusy):
            testing.start_managed_test_server()
    finally:
        first.rollback_without_cleanup()


# @matrix test-session : corrupt-state fail-closed schema
def test_corrupt_session_state_fails_closed(isolated_state):
    state_path, _lock_path = isolated_state
    invalid = _state()
    invalid["unexpected"] = True
    with pytest.raises(test_session.TestSessionStateError, match="fields"):
        test_session.validate_session_state(invalid)

    state_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(test_session.TestSessionStateError, match="valid"):
        test_session.load_session_state()


# @matrix test-session : pid-reuse process-start
def test_process_identity_rejects_reused_pid(monkeypatch):
    expected = _identity(started="Mon Aug 25 12:00:00 2026")
    monkeypatch.setattr(
        test_session,
        "capture_process_identity",
        lambda pid: _identity(pid, started="Mon Aug 25 12:00:01 2026"),
    )

    assert test_session.inspect_process_identity(expected) == "mismatch"


# @matrix test-session : command-fingerprint portability process-start
def test_capture_process_identity_uses_portable_ps_fingerprint(monkeypatch):
    values = {
        (4321, "pid"): "4321",
        (4321, "pgid"): "4300",
        (4321, "lstart"): "Mon Aug 25 12:00:00 2026",
        (4321, "command"): "/usr/bin/python -m flask run",
        (1, "lstart"): "Mon Aug 25 10:00:00 2026",
    }
    monkeypatch.setattr(
        test_session,
        "_ps_value",
        lambda pid, field: values[(pid, field)],
    )

    identity = test_session.capture_process_identity(4321)

    assert identity["pid"] == 4321
    assert identity["pgid"] == 4300
    assert identity["started"] == values[(4321, "lstart")]
    assert len(identity["boot_id"]) == 64
    assert len(identity["command_sha256"]) == 64


# @matrix test-session : cross-platform fail-closed port-ownership
def test_occupied_port_is_refused_without_signaling(monkeypatch):
    from runner import testing

    monkeypatch.setattr(testing, "_server_port_in_use", lambda base_url: True)
    monkeypatch.setattr(
        testing.os,
        "kill",
        lambda *_args: pytest.fail("an unverified port listener must not be signaled"),
    )
    monkeypatch.setattr(
        testing.os,
        "killpg",
        lambda *_args: pytest.fail("an unverified port listener must not be signaled"),
    )

    with pytest.raises(RuntimeError, match="unverified process"):
        testing.require_server_port_available("http://127.0.0.1:5000")


# @matrix test-session : health-nonce process-identity readiness
def test_wait_for_session_server_requires_exact_nonce_and_pid(monkeypatch, capsys):
    from runner import testing

    now = [0.0]
    responses = iter(
        [
            {
                "ready": True,
                "mode": "managed-server",
                "session_nonce": "wrong",
                "pid": 4322,
            },
            {
                "ready": True,
                "mode": "managed-server",
                "session_nonce": "nonce",
                "pid": 9999,
            },
        ]
    )
    monkeypatch.setattr(
        "requests.get",
        lambda *_args, **_kwargs: types.SimpleNamespace(
            status_code=200,
            json=lambda: next(responses),
        ),
    )
    monkeypatch.setattr(testing, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        testing,
        "sleep",
        lambda delay: now.__setitem__(0, now[0] + delay),
    )

    assert not testing.wait_for_session_server(
        "http://127.0.0.1:5000",
        "nonce",
        expected_pid=4322,
        expected_mode="managed-server",
        timeout_seconds=1,
    )
    assert "identity mismatch" in capsys.readouterr().out


# @matrix test-session : pid-reuse signal-safety
def test_reused_recorded_pid_is_never_signaled(monkeypatch):
    from runner import testing

    monkeypatch.setattr(test_session, "inspect_process_identity", lambda value: "mismatch")
    monkeypatch.setattr(
        testing.os,
        "killpg",
        lambda *_args: pytest.fail("a reused PID must not be signaled"),
    )

    assert testing._terminate_verified_process_group(_identity()) is False


# @matrix test-session : legacy-migration pid-reuse signal-safety
def test_live_legacy_pid_is_refused_without_signaling(monkeypatch, tmp_path):
    from runner import testing

    pid_path = tmp_path / "test-server.pid"
    pid_path.write_text("4321\n", encoding="utf-8")
    monkeypatch.setattr(
        testing,
        "File",
        types.SimpleNamespace(
            MANAGED_TEST_SERVER_PID=types.SimpleNamespace(value=pid_path)
        ),
    )
    monkeypatch.setattr(
        test_session,
        "capture_process_identity",
        lambda pid: _identity(pid),
    )
    monkeypatch.setattr(
        testing.os,
        "killpg",
        lambda *_args: pytest.fail("legacy PID state must never authorize signaling"),
    )

    with pytest.raises(RuntimeError, match="cannot prove ownership"):
        testing.require_legacy_test_server_clear()
    assert pid_path.exists()


# @matrix test-session : health-nonce recovery signal-safety
def test_recovery_rejects_wrong_health_nonce_without_signaling(monkeypatch):
    from runner import testing

    state = _state()
    state["server"]["pgid"] = state["owner"]["pgid"]
    monkeypatch.setattr(test_session, "inspect_process_identity", lambda value: "match")
    monkeypatch.setattr(testing, "wait_for_session_server", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        testing.os,
        "killpg",
        lambda *_args: pytest.fail("wrong health identity must not be signaled"),
    )

    with pytest.raises(RuntimeError, match="health does not prove ownership"):
        testing._terminate_recoverable_server(state)


# @matrix test-session : mode-isolation teardown
def test_managed_teardown_cannot_touch_local_e2e_owner(monkeypatch):
    from runner import testing

    monkeypatch.setattr(testing, "_configure_test_gcloud", lambda: None)
    monkeypatch.setattr(test_session, "load_session_state", lambda: _state("local-e2e"))
    monkeypatch.setattr(
        testing,
        "cleanup_test_data",
        lambda *_args: pytest.fail("foreign session data must not be cleaned"),
    )
    monkeypatch.setattr(
        testing,
        "_terminate_verified_process_group",
        lambda *_args: pytest.fail("foreign session process must not be signaled"),
    )

    with pytest.raises(RuntimeError, match="not a managed server"):
        testing.teardown_managed_test_server()


# @matrix test-session : browser-attachment mode-isolation teardown
def test_managed_teardown_refuses_live_browser_attachment(
    isolated_state, monkeypatch
):
    from runner import testing

    state = _state()
    state["attachment"] = {
        "id": "attachment-1",
        "command": "browser-review capture",
        "created_at": "2026-08-25T12:00:00+00:00",
        "process": _identity(os.getpid()),
    }
    test_session.write_session_state(state)
    monkeypatch.setattr(testing, "_configure_test_gcloud", lambda: None)
    monkeypatch.setattr(testing, "_session_matches_configuration", lambda value: True)
    monkeypatch.setattr(
        testing,
        "cleanup_test_data",
        lambda *_args: pytest.fail("attached session data must not be cleaned"),
    )
    monkeypatch.setattr(
        testing,
        "_terminate_verified_process_group",
        lambda *_args: pytest.fail("attached session process must not be signaled"),
    )

    with pytest.raises(RuntimeError, match="attachment-1"):
        testing.teardown_managed_test_server()


# @matrix test-session : browser-attachment detach exclusivity
def test_browser_attachment_is_exclusive_and_detaches(
    isolated_state, monkeypatch
):
    from runner import testing

    state = _state()
    test_session.write_session_state(state)
    monkeypatch.setattr(testing, "_verified_managed_state", lambda: state)

    attachment_id = testing.attach_browser_review(["browser-review", "capture"])
    attached = test_session.load_session_state()["attachment"]
    assert attached["id"] == attachment_id
    assert attached["command"] == "browser-review capture"

    with pytest.raises(RuntimeError, match="already attached"):
        testing.attach_browser_review(["browser-review", "capture", "second"])

    assert testing.detach_browser_review(attachment_id) is True
    assert test_session.load_session_state()["attachment"] is None


# @matrix test-session : live-owner recovery
def test_recovery_refuses_while_owner_is_live(monkeypatch):
    from runner import testing

    state = _state()
    monkeypatch.setattr(test_session, "load_session_state", lambda: state)
    monkeypatch.setattr(testing, "_session_matches_configuration", lambda value: True)
    monkeypatch.setattr(test_session, "inspect_process_identity", lambda value: "match")
    monkeypatch.setattr(
        testing,
        "_configure_test_gcloud",
        lambda: pytest.fail("live-owner recovery must stop before provider access"),
    )

    with pytest.raises(RuntimeError, match="still live"):
        testing.recover_managed_test_server()


# @matrix test-session : idempotence recovery
def test_recovery_is_idempotent_without_state(monkeypatch, tmp_path):
    from runner import testing

    pid_path = tmp_path / "test-server.pid"
    monkeypatch.setattr(test_session, "load_session_state", lambda: None)
    monkeypatch.setattr(testing, "_server_port_in_use", lambda base_url: False)
    monkeypatch.setattr(
        testing,
        "File",
        types.SimpleNamespace(
            MANAGED_TEST_SERVER_PID=types.SimpleNamespace(value=pid_path)
        ),
    )

    first = testing.recover_managed_test_server()
    second = testing.recover_managed_test_server()

    assert first == second == {
        "recovered": False,
        "detail": "No recoverable session exists.",
    }


# @matrix test-session : seed-loading lease-ownership
def test_seed_loading_requires_authority_before_import_or_mutation(monkeypatch):
    from testing.utility import test_server_seed

    class RefusingAuthority:
        def assert_active(self, **_kwargs):
            raise RuntimeError("lease lost")

    monkeypatch.setattr(
        test_server_seed,
        "_ensure_testing_environment",
        lambda: pytest.fail("seed environment must not load without authority"),
    )
    with pytest.raises(RuntimeError, match="lease lost"):
        test_server_seed.load_packs(["project-review"], RefusingAuthority())
