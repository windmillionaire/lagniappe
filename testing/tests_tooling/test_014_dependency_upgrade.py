"""Dependency maintenance remains observable, cancellable, and scoped."""

import json
import hashlib
import io
import os
import queue
import subprocess
import sys
import threading

import pytest

from runner import upgrade

pytestmark = pytest.mark.tooling


# @matrix dependencies : node-version pinning upgrade
def test_node_alignment_failure_preserves_all_declarations(monkeypatch, tmp_path):
    pin = tmp_path / ".nvmrc"
    package = tmp_path / "package.json"
    docker = tmp_path / upgrade.NODE_DOCKERFILE_PATH
    docker.parent.mkdir(parents=True)
    pin.write_text("26.5.0\n")
    package.write_text('{"engines":{"node":">=26.5.0"}}')
    docker.write_text("FROM node:26.5.0-bookworm-slim@sha256:" + "a" * 64 + " AS node-runtime\n")
    before = {path: path.read_bytes() for path in (pin, package, docker)}

    def unavailable(version):
        raise OSError("image has not been published")

    monkeypatch.setattr(upgrade, "resolve_node_image", unavailable)
    report = upgrade.UpgradeReport()
    assert not upgrade.update_node_version_pin("26.8.2", report, pin)
    assert "image has not been published" in report.errors[0]
    assert {path: path.read_bytes() for path in before} == before


# @matrix dependencies : node-version pinning upgrade
def test_node_image_lookup_verifies_registry_digest(monkeypatch):
    content = json.dumps({"schemaVersion": 2, "manifests": [{"platform": {"os": "linux", "architecture": "amd64"}}]}).encode()
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    requests = []
    invalid = False

    def open_response(request, *, timeout):
        assert timeout == 30
        requests.append(request)
        if isinstance(request, str):
            return io.BytesIO(b'{"token":"public-registry-token"}')
        response = io.BytesIO(content)
        response.headers = {"Docker-Content-Digest": "sha256:wrong" if invalid else digest}
        return response

    monkeypatch.setattr(upgrade, "urlopen", open_response)
    assert upgrade.resolve_node_image("26.8.2") == f"node:26.8.2-bookworm-slim@{digest}"
    assert requests[1].full_url.endswith("/manifests/26.8.2-bookworm-slim")
    invalid = True
    with pytest.raises(ValueError, match="digest verification"):
        upgrade.resolve_node_image("26.8.2")


# @matrix dependencies : subprocess-output cancellation
def test_dependency_command_streams_prompts_and_preserves_output():
    child = (
        "import sys; sys.stdout.write('Ready' + '? '); sys.stdout.flush(); "
        "answer = input(); print('ANSWER ' + answer); "
        "print('child warning', file=sys.stderr)"
    )
    harness = (
        "import json, sys; from runner.upgrade import run_command; "
        f"result = run_command([sys.executable, '-u', '-c', {child!r}]); "
        "print('RESULT ' + json.dumps([result.stdout, result.stderr]))"
    )
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", harness],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        prompts = queue.Queue()

        def observe_prompt():
            captured = b""
            while not captured.endswith(b"Ready? "):
                chunk = process.stdout.read(1)
                if not chunk:
                    break
                captured += chunk
            prompts.put(captured)

        observer = threading.Thread(target=observe_prompt, daemon=True)
        observer.start()
        captured = prompts.get(timeout=10)
        observer.join(timeout=1)
        assert captured.endswith(b"Ready? "), "Prompt was not visible before input"
        # The child cannot finish until the already-visible prompt is answered.
        assert process.poll() is None
        process.stdin.write(b"yes\n")
        process.stdin.flush()
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr.decode()
        text = (captured + stdout).decode()
        result_line = next(line for line in text.splitlines() if line.startswith("RESULT "))
        assert json.loads(result_line.removeprefix("RESULT ")) == [
            "Ready? ANSWER yes\n", "child warning\n"
        ]
        assert stderr == b"child warning\n"
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


# @matrix dependencies : subprocess-output timeout cancellation
@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group contract")
def test_dependency_command_timeout_preserves_output_and_stops_children(tmp_path):
    pid_path = tmp_path / "child.pid"
    child = (
        "import subprocess, sys, time; from pathlib import Path; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        f"Path({str(pid_path)!r}).write_text(str(child.pid)); "
        "print('started child', flush=True); time.sleep(60)"
    )
    report = upgrade.UpgradeReport()
    with pytest.raises(subprocess.TimeoutExpired) as failure:
        upgrade.run_command(
            [sys.executable, "-u", "-c", child], timeout=1, report=report,
        )
    assert failure.value.stdout == "started child\n"
    assert report.command_logs[-1].stdout == "started child\n"
    assert "timed out" in report.command_logs[-1].error
    state = subprocess.run(
        ["ps", "-p", pid_path.read_text(), "-o", "stat="],
        capture_output=True, text=True, check=False,
    )
    assert not state.stdout.strip() or state.stdout.strip().startswith("Z")


# @matrix dependencies : upgrade failure-propagation package-lock
def test_npm_upgrade_uses_one_bounded_lookup_and_preserves_package_metadata(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(upgrade.Path, "home", lambda: tmp_path)
    package = {"name": "example", "version": "2.1.1", "scripts": {"test": "keep"},
               "dependencies": {"example": "^1.0.0"}}
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(package))
    commands = []

    def execute(command, **options):
        commands.append((command, options))
        if "--jsonUpgraded" in command:
            assert options["capture"] is True
            assert options["timeout"] == 90
            return subprocess.CompletedProcess(command, 0, '{"example":"^2.0.0"}', "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(upgrade, "run_command", execute)
    report = upgrade.UpgradeReport()
    assert upgrade.upgrade_npm_packages(report)
    saved = json.loads(package_path.read_text())
    assert saved == {**package, "dependencies": {"example": "^2.0.0"}}
    assert len(commands) == 3
    assert "--jsonUpgraded" in commands[0][0]
    assert "--no-interactive" in commands[0][0]
    assert commands[1][0] == [upgrade.NPM_COMMAND, "install"]
    assert commands[2][0] == [upgrade.NPM_COMMAND, "audit"]
    assert [(change.name, change.before, change.after) for change in report.changes] == [
        ("example", "^1.0.0", "^2.0.0")
    ]


# @matrix dependencies : upgrade failure-propagation package-lock
@pytest.mark.parametrize("returncode, output", [(1, "registry unavailable"), (0, "invalid JSON")])
def test_npm_lookup_failure_does_not_modify_or_install_dependencies(monkeypatch, tmp_path, returncode, output):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(upgrade.Path, "home", lambda: tmp_path)
    package_path = tmp_path / "package.json"
    original = '{"version":"2.1.1","dependencies":{"example":"^1.0.0"}}'
    package_path.write_text(original)
    commands = []

    def execute(command, **options):
        commands.append(command)
        return subprocess.CompletedProcess(command, returncode, output, "")

    monkeypatch.setattr(upgrade, "run_command", execute)
    report = upgrade.UpgradeReport()
    assert not upgrade.upgrade_npm_packages(report)
    assert package_path.read_text() == original
    assert len(commands) == 1
    assert report.errors


# @matrix dependencies : failure-propagation upgrade-report cancellation package-lock
@pytest.mark.parametrize("failure", [KeyboardInterrupt, subprocess.TimeoutExpired])
def test_npm_interruption_records_completed_file_changes(monkeypatch, tmp_path, failure):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(upgrade.Path, "home", lambda: tmp_path)
    package_path = tmp_path / "package.json"
    package_path.write_text('{"dependencies":{"example":"^1.0.0"}}')

    def execute(command, **options):
        if "--jsonUpgraded" in command:
            return subprocess.CompletedProcess(command, 0, '{"example":"^2.0.0"}', "")
        (tmp_path / "package-lock.json").write_text(json.dumps({
            "packages": {"node_modules/example": {"version": "2.0.0"}},
        }))
        if failure is KeyboardInterrupt:
            raise KeyboardInterrupt
        raise subprocess.TimeoutExpired(command, 900)

    monkeypatch.setattr(upgrade, "run_command", execute)
    report = upgrade.UpgradeReport()
    with pytest.raises(failure):
        upgrade.upgrade_npm_packages(report)
    changes = {(change.source, change.after) for change in report.changes}
    assert ("package.json", "^2.0.0") in changes
    assert ("package-lock.json (direct)", "2.0.0") in changes


# @matrix dependencies : failure-propagation upgrade-report
def test_dependency_upgrade_stops_on_failure_and_saves_report(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(upgrade, "upgrade_node", lambda report: True)

    def fail(report):
        report.add_error("npm", "registry unavailable")
        return False

    def unexpected(report):
        pytest.fail("Python updates must not continue after npm fails")

    monkeypatch.setattr(upgrade, "upgrade_npm_packages", fail)
    monkeypatch.setattr(upgrade, "upgrade_pip_packages", unexpected)
    report_path = tmp_path / "report.md"
    monkeypatch.setattr(upgrade, "default_upgrade_report_path", lambda timestamp: report_path)
    assert upgrade.upgrade_all() == 1
    assert "registry unavailable" in report_path.read_text()
    output = capsys.readouterr().out
    assert "[1/5] Node.js" in output
    assert "[2/5] npm packages" in output
    assert "more in the report" not in output


# @matrix dependencies : cancellation upgrade-report
def test_dependency_upgrade_saves_report_on_interrupt(monkeypatch, tmp_path):
    def interrupt(report):
        report.record_command(["example"], -15, stdout="Partial command output")
        raise KeyboardInterrupt

    monkeypatch.setattr(upgrade, "upgrade_npm_packages", interrupt)
    report_path = tmp_path / "report.md"
    monkeypatch.setattr(upgrade, "default_upgrade_report_path", lambda timestamp: report_path)
    assert upgrade.upgrade_all(only="npm") == 130
    report = report_path.read_text()
    assert "Interrupted by the user" in report
    assert "Partial command output" in report
