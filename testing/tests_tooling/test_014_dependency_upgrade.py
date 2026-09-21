"""Dependency maintenance remains observable, cancellable, and scoped."""

import hashlib
import io
import json
import os
from pathlib import Path
import queue
import stat
import subprocess
import sys
import threading

import pytest

from runner import upgrade

pytestmark = pytest.mark.tooling


@pytest.fixture
def node_declarations(monkeypatch, tmp_path):
    paths = {
        "pin": tmp_path / ".nvmrc",
        "package": tmp_path / "package.json",
        "docker": tmp_path / upgrade.NODE_DOCKERFILE_PATH,
        "lock": tmp_path / "package-lock.json",
    }
    paths["docker"].parent.mkdir(parents=True)
    paths["pin"].write_bytes(b"26.5.0\r\n")
    paths["package"].write_text(
        '{"name":"example","engines":{"node":">=26.5.0","npm":">=11"}}'
    )
    paths["lock"].write_text(
        '{"lockfileVersion":3,"packages":{"":{"engines":{"node":">=26.5.0"}},'
        '"node_modules/example":{"version":"1.0.0"}}}'
    )
    paths["docker"].write_text(
        "FROM node:26.5.0-bookworm-slim@sha256:" + "a" * 64 + " AS node-runtime\n"
        "FROM python:3.14-slim\n"
    )
    for path in paths.values():
        path.chmod(0o640)
    monkeypatch.setattr(
        upgrade, "resolve_node_image",
        lambda _version: "node:26.8.2-bookworm-slim@sha256:" + "b" * 64,
    )
    return paths


# @matrix dependencies : node-version pinning upgrade
def test_node_alignment_failure_preserves_all_declarations(monkeypatch, node_declarations):
    before = {path: path.read_bytes() for path in node_declarations.values()}

    def unavailable(version):
        raise OSError("image has not been published")

    monkeypatch.setattr(upgrade, "resolve_node_image", unavailable)
    report = upgrade.UpgradeReport()
    assert not upgrade.update_node_version_pin("26.8.2", report, node_declarations["pin"])
    assert "image has not been published" in report.errors[0]
    assert {path: path.read_bytes() for path in before} == before
    assert report.changes == []


# @matrix dependencies : node-version pinning upgrade
@pytest.mark.parametrize("with_lock", [False, True])
def test_node_alignment_publishes_all_declarations_and_skips_unchanged_files(
    monkeypatch, tmp_path, node_declarations, with_lock
):
    paths = node_declarations
    if not with_lock:
        paths["lock"].unlink()
    before_files = set(tmp_path.rglob("*"))
    report = upgrade.UpgradeReport()

    assert upgrade.update_node_version_pin("v26.8.2", report, paths["pin"])

    assert paths["pin"].read_bytes() == b"26.8.2\n"
    assert json.loads(paths["package"].read_text()) == {
        "name": "example", "engines": {"node": ">=26.8.2", "npm": ">=11"},
    }
    assert paths["docker"].read_text() == (
        "FROM node:26.8.2-bookworm-slim@sha256:" + "b" * 64 + " AS node-runtime\n"
        "FROM python:3.14-slim\n"
    )
    if with_lock:
        assert json.loads(paths["lock"].read_text()) == {
            "lockfileVersion": 3,
            "packages": {
                "": {"engines": {"node": ">=26.8.2"}},
                "node_modules/example": {"version": "1.0.0"},
            },
        }
    else:
        assert not paths["lock"].exists()
    if os.name == "posix":
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o640 for path in paths.values() if path.exists())
    assert set(tmp_path.rglob("*")) == before_files
    assert report.errors == []
    assert {change.name for change in report.changes} == {
        "Node.js pin", "Node.js engine", "Hosted Node image",
    }

    monkeypatch.setattr(
        upgrade.tempfile, "mkdtemp",
        lambda **_kwargs: pytest.fail("unchanged declarations must not be staged"),
    )
    unchanged_report = upgrade.UpgradeReport()
    assert upgrade.update_node_version_pin("26.8.2", unchanged_report, paths["pin"])
    assert unchanged_report.changes == []
    assert unchanged_report.errors == []


# @matrix dependencies : node-version pinning upgrade
@pytest.mark.parametrize("existing_pin", [False, True])
@pytest.mark.parametrize(
    "failure",
    ["stage-backup", "stage-content", "publish-pin", "publish-package", "publish-docker", "publish-lock"],
)
def test_node_alignment_restores_declarations_on_publication_failure(
    monkeypatch, tmp_path, node_declarations, existing_pin, failure
):
    paths = node_declarations
    if not existing_pin:
        paths["pin"].unlink()
    before = {path: path.read_bytes() if path.exists() else None for path in paths.values()}
    before_files = set(tmp_path.rglob("*"))
    copy2, write_bytes, replace = upgrade.shutil.copy2, Path.write_bytes, Path.replace

    def fail_backup(source, destination):
        if failure == "stage-backup" and source == paths["lock"]:
            assert {path: path.read_bytes() if path.exists() else None for path in before} == before
            raise OSError("injected staging failure")
        return copy2(source, destination)

    def fail_content(path, content):
        if failure == "stage-content" and path.name == "new" and path.parent.name.startswith(".package-lock.json-"):
            assert {path: path.read_bytes() if path.exists() else None for path in before} == before
            raise OSError("injected staging failure")
        return write_bytes(path, content)

    def fail_publication(path, destination):
        if failure.startswith("publish-") and path.name == "new" and destination == paths[failure.removeprefix("publish-")]:
            if failure != "publish-pin":
                assert paths["pin"].read_bytes() == b"26.8.2\n"
            raise OSError("injected publication failure")
        return replace(path, destination)

    monkeypatch.setattr(upgrade.shutil, "copy2", fail_backup)
    monkeypatch.setattr(Path, "write_bytes", fail_content)
    monkeypatch.setattr(Path, "replace", fail_publication)
    report = upgrade.UpgradeReport()

    assert not upgrade.update_node_version_pin("26.8.2", report, paths["pin"])

    assert {path: path.read_bytes() if path.exists() else None for path in before} == before
    assert set(tmp_path.rglob("*")) == before_files
    if os.name == "posix":
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o640 for path in before if path.exists())
    assert any("injected" in error for error in report.errors)
    assert report.changes == []


# @matrix dependencies : node-version pinning upgrade cancellation
def test_node_alignment_interrupt_restores_declarations(monkeypatch, tmp_path, node_declarations):
    paths = node_declarations
    before = {path: path.read_bytes() for path in paths.values()}
    before_files = set(tmp_path.rglob("*"))
    replace = Path.replace

    def interrupt_after_replace(path, destination):
        result = replace(path, destination)
        if path.name == "new" and destination == paths["package"]:
            raise KeyboardInterrupt
        return result

    monkeypatch.setattr(Path, "replace", interrupt_after_replace)
    report = upgrade.UpgradeReport()
    with pytest.raises(KeyboardInterrupt):
        upgrade.update_node_version_pin("26.8.2", report, paths["pin"])
    assert {path: path.read_bytes() for path in before} == before
    assert set(tmp_path.rglob("*")) == before_files
    assert report.changes == []


# @matrix dependencies : node-version pinning upgrade
@pytest.mark.parametrize("existing_pin", [False, True])
def test_node_alignment_retains_backups_when_restoration_fails(
    monkeypatch, tmp_path, node_declarations, existing_pin
):
    paths = node_declarations
    if not existing_pin:
        paths["pin"].unlink()
    before = {path: path.read_bytes() if path.exists() else None for path in paths.values()}
    failed_target = paths["package"] if existing_pin else paths["pin"]
    replace, unlink = Path.replace, Path.unlink

    def fail_replace(path, destination):
        if path.name == "new" and destination == paths["lock"]:
            raise OSError("injected publication failure")
        if path.name == "previous" and destination == failed_target:
            raise OSError("injected restore failure")
        return replace(path, destination)

    def fail_unlink(path, *args, **kwargs):
        if path == failed_target:
            raise OSError("injected removal failure")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_unlink)
    report = upgrade.UpgradeReport()
    assert not upgrade.update_node_version_pin("26.8.2", report, paths["pin"])

    if existing_pin:
        assert json.loads(failed_target.read_text())["engines"]["node"] == ">=26.8.2"
    else:
        assert failed_target.read_bytes() == b"26.8.2\n"
    assert all(path.read_bytes() == content for path, content in before.items() if path != failed_target)
    recovery = next(error for error in report.errors if "restoration was incomplete" in error)
    assert str(failed_target) in recovery
    directories = [path for path in tmp_path.rglob(".*-*") if path.is_dir()]
    assert directories and all(str(path) in recovery for path in directories)
    if existing_pin:
        backups = list(tmp_path.rglob("previous"))
        assert any(path.read_bytes() == before[failed_target] and str(path) in recovery for path in backups)
    else:
        assert "previously absent" in recovery
    assert report.changes == []


# @matrix dependencies : node-version pinning upgrade
def test_node_alignment_cleanup_failure_does_not_hide_success(monkeypatch, node_declarations):
    paths = node_declarations

    def fail_cleanup(directory):
        raise OSError("injected cleanup failure")

    monkeypatch.setattr(upgrade.shutil, "rmtree", fail_cleanup)
    report = upgrade.UpgradeReport()
    assert upgrade.update_node_version_pin("26.8.2", report, paths["pin"])
    assert paths["pin"].read_bytes() == b"26.8.2\n"
    assert report.errors == []
    assert report.changes
    assert any("injected cleanup failure" in note and str(paths["pin"].parent) in note for note in report.notes)


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
    assert requests[0] == (
        "https://auth.docker.io/token?service=registry.docker.io"
        "&scope=repository:library/node:pull"
    )
    assert requests[1].full_url == (
        "https://registry-1.docker.io/v2/library/node/manifests/"
        "26.8.2-bookworm-slim"
    )
    assert requests[1].get_header("Authorization") == "Bearer public-registry-token"
    assert requests[1].get_header("Accept") == (
        "application/vnd.oci.image.index.v1+json, "
        "application/vnd.docker.distribution.manifest.list.v2+json"
    )
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


# @matrix dependencies : subprocess-output isolation
def test_dependency_command_capture_closes_stdin_and_retains_output():
    child = (
        "import sys; data = sys.stdin.buffer.read(); "
        "print('stdin closed' if not data else 'stdin open'); "
        "print('captured warning', file=sys.stderr)"
    )
    harness = (
        "import json, sys; from runner.upgrade import run_command; "
        f"result = run_command([sys.executable, '-u', '-c', {child!r}], "
        "capture=True, timeout=5); "
        "print('RESULT ' + json.dumps([result.stdout, result.stderr]))"
    )
    # Nonempty parent stdin distinguishes DEVNULL from inherited stdin, even
    # when pytest itself runs with no interactive input available.
    result = subprocess.run(
        [sys.executable, "-u", "-c", harness],
        input="must not reach the captured child\n",
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    assert result.returncode == 0
    result_line = next(line for line in result.stdout.splitlines() if line.startswith("RESULT "))
    assert json.loads(result_line.removeprefix("RESULT ")) == [
        "stdin closed\n", "captured warning\n"
    ]
    assert result.stderr == ""


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
    package = {
        "name": "example",
        "version": "2.1.1",
        "scripts": {"test": "keep"},
        "dependencies": {"example": "^1.0.0"},
        "devDependencies": {"test-helper": "~3.0.0"},
        "optionalDependencies": {"optional-tool": "1.x"},
    }
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(package))
    commands = []

    def execute(command, **options):
        commands.append((command, options))
        if "--jsonUpgraded" in command:
            assert options["capture"] is True
            assert options["timeout"] == 90
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "example": "^2.0.0",
                        "test-helper": "~4.0.0",
                        "optional-tool": "2.x",
                        "undeclared": "^9.0.0",
                    }
                ),
                "",
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(upgrade, "run_command", execute)
    report = upgrade.UpgradeReport()
    assert upgrade.upgrade_npm_packages(report)
    saved = json.loads(package_path.read_text())
    assert saved == {
        **package,
        "dependencies": {"example": "^2.0.0"},
        "devDependencies": {"test-helper": "~4.0.0"},
        "optionalDependencies": {"optional-tool": "2.x"},
    }
    assert len(commands) == 3
    assert "--jsonUpgraded" in commands[0][0]
    assert "--no-interactive" in commands[0][0]
    assert commands[1][0] == [upgrade.NPM_COMMAND, "install"]
    assert commands[2][0] == [upgrade.NPM_COMMAND, "audit"]
    assert {
        (change.name, change.before, change.after)
        for change in report.changes
    } == {
        ("example", "^1.0.0", "^2.0.0"),
        ("test-helper", "~3.0.0", "~4.0.0"),
        ("optional-tool", "1.x", "2.x"),
    }


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
