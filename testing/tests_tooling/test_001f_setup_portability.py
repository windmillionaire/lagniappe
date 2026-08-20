"""Repository-health checks for the ordinary installer portability contract."""

import ast
import json
from pathlib import Path
import re

import pytest


pytestmark = pytest.mark.tooling
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _python_sources(*relative_roots):
    sources = []
    for relative_root in relative_roots:
        path = REPOSITORY_ROOT / relative_root
        if path.is_file():
            sources.append(path)
        else:
            sources.extend(sorted(path.rglob("*.py")))
    return sources


def _call_mode(call, *, path_method):
    positional_index = 0 if path_method else 1
    if len(call.args) > positional_index:
        value = call.args[positional_index]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    for keyword in call.keywords:
        if keyword.arg == "mode":
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    return "r"


def _has_encoding(call):
    return any(keyword.arg == "encoding" for keyword in call.keywords)


def test_release_setup_uses_central_tools_and_portable_npm_scripts():
    from runner import context as runner_context

    assert runner_context.REPOSITORY_ROOT == REPOSITORY_ROOT
    assert set(runner_context.TOOL_PATHS) == {"gcloud", "git", "node", "npm"}
    for executable in runner_context.TOOL_PATHS.values():
        if executable is not None:
            assert Path(executable).is_absolute()

    release_sources = [
        path
        for path in _python_sources("installer", "runner", "run.py")
        if path != REPOSITORY_ROOT / "runner" / "context.py"
    ] + [
        REPOSITORY_ROOT / relative
        for relative in (
            "config/__init__.py",
            "config/deployment.py",
        )
    ]
    raw_tool_argument = re.compile(
        r"""\[\s*["'](?:gcloud|git|node|npm)["']\s*,"""
    )
    for path in release_sources:
        source = path.read_text(encoding="utf-8")
        assert "shutil.which(" not in source, path
        assert "shell=True" not in source, path
        assert "os.system(" not in source, path
        assert not raw_tool_argument.search(source), path

    package = json.loads(
        (REPOSITORY_ROOT / "package.json").read_text(encoding="utf-8")
    )
    assert package["scripts"]["build"] == "node build/run-rollup.mjs production"
    assert package["scripts"]["dev"] == "node build/run-rollup.mjs development"
    for script in (package["scripts"]["build"], package["scripts"]["dev"]):
        assert "rm -rf" not in script
        assert "NODE_ENV=" not in script

    rollup_runner = (REPOSITORY_ROOT / "build/run-rollup.mjs").read_text(
        encoding="utf-8"
    )
    assert "rmSync(" in rollup_runner
    assert re.search(r"spawnSync\(\s*process\.execPath", rollup_runner)


def test_setup_config_and_report_text_io_declares_utf8():
    sources = _python_sources(
        "installer",
        "runner",
        "config",
        "run.py",
        "testing/utility",
    )
    missing = []
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if isinstance(call.func, ast.Attribute) and call.func.attr in {
                "read_text",
                "write_text",
            }:
                if not _has_encoding(call):
                    missing.append(f"{path.relative_to(REPOSITORY_ROOT)}:{call.lineno}")
                continue

            path_method = (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "open"
                and not (
                    isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "os"
                )
            )
            builtin_open = isinstance(call.func, ast.Name) and call.func.id == "open"
            if not path_method and not builtin_open:
                continue
            if "b" in _call_mode(call, path_method=path_method):
                continue
            if not _has_encoding(call):
                missing.append(f"{path.relative_to(REPOSITORY_ROOT)}:{call.lineno}")

    assert missing == []
