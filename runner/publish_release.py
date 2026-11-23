"""Verify a merged release PR and publish an immutable annotated tag from main."""

import argparse
import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path


# @testable infrastructure
def _run(*args):
    return subprocess.run(
        args, check=True, capture_output=True, text=True
    ).stdout.strip()


# @testable infrastructure
def _api(path):
    env = os.environ.copy()
    if "RELEASE_VALIDATION_TOKEN" in env:
        env["GH_TOKEN"] = env["RELEASE_VALIDATION_TOKEN"]
    return json.loads(subprocess.check_output(["gh", "api", path], env=env))


# @testable true
# @tests tests_tooling/test_016_cloud_operator.py::test_release_rejects_unverified_heads
# @matrix release : protected-branch source-integrity
def verified_version(
    repo: str, sha: str, pr: object, api: Callable[[str], object] = _api
) -> str:
    if (
        not isinstance(pr, dict)
        or not pr.get("merged")
        or pr["merge_commit_sha"] != sha
        or pr["base"]["ref"] != "main"
        or any(pr[k]["repo"]["full_name"] != repo for k in ("base", "head"))
    ):
        raise ValueError(
            "Expected a merged same-repository release PR at the dispatched main revision."
        )
    branch = re.fullmatch(
        r"(?:hotfix|next)/((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))",
        pr["head"]["ref"],
    )
    if not branch:
        raise ValueError("Expected a versioned hotfix or next branch.")
    head = pr["head"]["sha"]
    statuses = api(f"repos/{repo}/commits/{head}/statuses?per_page=100")
    if not isinstance(statuses, list):
        raise ValueError("Expected GitHub commit statuses for the release head.")
    attestations = [
        s for s in statuses if s["context"] == "Source quality and traceability"
    ]
    # The individual statuses endpoint includes the issuer and puts the newest first.
    if not attestations or attestations[0]["state"] != "success":
        raise ValueError(
            "The exact merged PR head needs the hosted release attestation."
        )
    attestation = attestations[0]
    url = re.fullmatch(
        rf"https://github\.com/{re.escape(repo)}/actions/runs/([1-9]\d*)",
        attestation.get("target_url") or "",
    )
    if not url or attestation.get("creator", {}).get("login") != "github-actions[bot]":
        raise ValueError(
            "The release status must come from this repository's GitHub Actions."
        )
    run = api(f"repos/{repo}/actions/runs/{url[1]}")
    if (
        not isinstance(run, dict)
        or run["path"] != ".github/workflows/hosted-e2e.yml"
        or run["head_sha"] != head
        or run["conclusion"] != "success"
        or run["head_repository"]["full_name"] != repo
    ):
        raise ValueError(
            "The trusted hosted validation workflow has not completed for this revision."
        )
    return branch[1]


# @testable true
# @tests tests_tooling/test_016_cloud_operator.py::test_publication_retries_with_annotated_tag
# @matrix release : git-upgrade source-integrity
def publish_tag(repo: str, sha: str, version: str, notes: Path) -> None:
    tag = f"v{version}"
    ref = f"refs/tags/{tag}"
    remote = _run("git", "ls-remote", "--refs", "origin", ref)
    if remote:
        _run("git", "fetch", "--no-tags", "origin", ref)
        if (
            _run("git", "cat-file", "-t", "FETCH_HEAD") != "tag"
            or _run("git", "rev-parse", "FETCH_HEAD^{}") != sha
        ):
            raise ValueError(
                "An existing release tag is lightweight or points to another commit."
            )
    else:
        _run("git", "tag", "-a", tag, sha, "-m", f"Lagniappe {version}")
        _run("git", "push", "origin", ref)
    # A failed lookup is never permission to replace or edit a published release.
    result = subprocess.run(
        [
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            repo,
            "--json",
            "tagName,isDraft,isPrerelease",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        record = json.loads(result.stdout)
        if record != {"tagName": tag, "isDraft": False, "isPrerelease": False}:
            raise ValueError(
                "The existing GitHub Release does not match the expected published release."
            )
    else:
        _run(
            "gh",
            "release",
            "create",
            tag,
            "--repo",
            repo,
            "--verify-tag",
            "--target",
            sha,
            "--title",
            f"Lagniappe {version}",
            "--notes-file",
            str(notes),
        )


# @testable infrastructure
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("sha")
    parser.add_argument("pr", type=int)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if (
        args.pr < 1
        or not re.fullmatch(r"[a-f0-9]{40}", args.sha)
        or _run("git", "rev-parse", "HEAD") != args.sha
    ):
        parser.error("An exact checked-out commit and positive PR number are required.")
    if _api(f"repos/{args.repo}/git/ref/heads/main")["object"]["sha"] != args.sha:
        parser.error("Main has advanced. Review the requested release again.")
    version = verified_version(
        args.repo, args.sha, _api(f"repos/{args.repo}/pulls/{args.pr}")
    )
    notes = Path("documentation/releases") / f"{version}.md"
    if (
        json.loads(Path("package.json").read_text(encoding="utf-8"))["version"]
        != version
        or not notes.is_file()
        or not notes.read_text(encoding="utf-8")
        .strip()
        .startswith(f"# Version {version}\n")
    ):
        parser.error(
            "The merged package version and release notes must match the PR branch."
        )
    if args.publish:
        publish_tag(args.repo, args.sha, version, notes)
    print(f"Verified release v{version} at {args.sha}.")


if __name__ == "__main__":
    main()
