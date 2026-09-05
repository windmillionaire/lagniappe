"""Offline integrity and raw-capture privacy checks for the workflow case library."""

import hashlib
import json
from pathlib import Path
import subprocess

import pytest


pytestmark = pytest.mark.tooling
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LIBRARY_ROOT = REPOSITORY_ROOT / "testing_ai_workflows"
CASES_ROOT = LIBRARY_ROOT / "cases"
BUILD_IGNORE_FILES = (
    "runner/hosted_e2e_container/gcloudignore",
    "runner/mcp_package_container/gcloudignore",
)


def _case_directories():
    return sorted(path for path in CASES_ROOT.iterdir() if path.is_dir())


def _fixture_files(case):
    return sorted(
        path
        for path in (case / "fixtures").rglob("*")
        if path.is_file() and path.name != ".gitkeep"
    )


def test_workflow_cases_have_requests_rubrics_and_substantive_fixtures():
    cases = _case_directories()
    assert cases
    required_fixture_counts = {"06": 1, "07": 1, "08": 5, "12": 3, "13": 1}
    found_fixture_cases = set()
    for case in cases:
        for filename in ("PROMPT.md", "RUBRIC.md"):
            content = (case / filename).read_text(encoding="utf-8")
            assert any(
                line.strip() and not line.lstrip().startswith("#")
                for line in content.splitlines()
            ), f"{case.name}/{filename} has no request or review content"
        assert (case / "fixtures").is_dir(), case.name
        fixtures = _fixture_files(case)
        assert all(path.stat().st_size > 0 for path in fixtures), case.name
        number = case.name.split("-", 1)[0]
        if number in required_fixture_counts:
            found_fixture_cases.add(number)
            assert len(fixtures) >= required_fixture_counts[number], case.name
    assert found_fixture_cases == set(required_fixture_counts)


def test_latest_results_resolve_cases_and_match_current_input_bytes():
    index = json.loads((LIBRARY_ROOT / "latest_results.json").read_text("utf-8"))
    assert index["version"] == 1
    case_ids = [case["id"] for case in index["cases"]]
    assert len(case_ids) == len(set(case_ids))
    assert set(case_ids) == {case.name for case in _case_directories()}
    for entry in index["cases"]:
        case = CASES_ROOT / entry["id"]
        current_inputs = entry["current_inputs"]
        assert current_inputs["prompt_sha256"] == hashlib.sha256(
            (case / "PROMPT.md").read_bytes()
        ).hexdigest(), case.name
        expected_fixtures = {
            path.relative_to(case / "fixtures").as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in _fixture_files(case)
        }
        assert current_inputs["fixtures"] == expected_fixtures, case.name

        number = int(case.name.split("-", 1)[0])
        if 1 <= number <= 11:
            assert entry["latest_results"]["mcp"]["reviewed"] is True, case.name
        if number in {12, 13}:
            historical = entry["latest_results"]["pi-rest"]
            assert historical["reviewed"] is True, case.name
            if historical["run_id"] == "file-use-after-2026-09-03":
                assert historical["inputs_match_current_case"] is False, case.name
            # A later matching Pi or MCP run is valid. Keep its own arm rather
            # than freezing the historical import as the only possible latest run.


def test_raw_workflow_captures_are_ignored_without_hiding_case_material(tmp_path):
    """Use real Git matching, independent of checkout metadata or raw local exports."""
    subprocess.run(
        ["git", "init", "--quiet", "--template=", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    fixture_library = tmp_path / "testing_ai_workflows"
    fixture_library.mkdir()
    (fixture_library / ".gitignore").write_bytes(
        (LIBRARY_ROOT / ".gitignore").read_bytes()
    )
    # Hosted source archives omit the root .gitignore; the library's own policy
    # is explicitly included in those build contexts and must work on its own.
    root_ignore = REPOSITORY_ROOT / ".gitignore"
    if root_ignore.is_file():
        (tmp_path / ".gitignore").write_bytes(root_ignore.read_bytes())
    empty_global_ignore = tmp_path / "empty-global-ignore"
    empty_global_ignore.write_text("", encoding="utf-8")

    private_paths = set()
    public_paths = {
        "testing_ai_workflows/README.md",
        "testing_ai_workflows/ROUND_3.md",
        "testing_ai_workflows/latest_results.json",
        "testing_ai_workflows/comparisons/example.md",
    }
    for case in _case_directories():
        prefix = case.relative_to(REPOSITORY_ROOT).as_posix()
        for arm in ("mcp", "pi-rest", "native", "email"):
            for area in ("baseline", "current", "archive/previous-run"):
                for filename in ("session.jsonl", "SESSION.txt", "screenshot.png"):
                    private_paths.add(f"{prefix}/artifacts/{area}/{arm}/{filename}")
        public_paths.update(f"{prefix}/{name}" for name in ("PROMPT.md", "RUBRIC.md"))
        public_paths.update(
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in _fixture_files(case)
        )
    result = subprocess.run(
        [
            "git",
            "-c",
            f"core.excludesFile={empty_global_ignore}",
            "check-ignore",
            "--no-index",
            "--stdin",
            "-z",
        ],
        cwd=tmp_path,
        input="\0".join(sorted(private_paths | public_paths)) + "\0",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    ignored = set(result.stdout.rstrip("\0").split("\0"))
    assert ignored == private_paths


def test_workflow_library_and_raw_artifacts_stay_out_of_deployment_payloads():
    app_ignore = (REPOSITORY_ROOT / ".gcloudignore").read_text("utf-8").splitlines()
    assert "/testing_ai_workflows/" in app_ignore
    for name in BUILD_IGNORE_FILES:
        rules = (REPOSITORY_ROOT / name).read_text("utf-8").splitlines()
        assert "testing_ai_workflows/cases/*/artifacts/" in rules, name
        assert "!/testing_ai_workflows/.gitignore" in rules, name
