"""Readiness of composite indexes submitted by an App Engine deployment."""

from collections.abc import Mapping, Sequence
import json
import time
from typing import Any

from runner.context import GCLOUD_CLI, format_command
from runner.presentation import output
from runner.process import run_command


type IndexDefinition = tuple[str, bool, tuple[tuple[str, str], ...]]

# Match the wait allowed for index builds during a database restore.
INDEX_BUILD_TIMEOUT = 6 * 60 * 60
POLL_INTERVAL = 15


def _definition(row: Mapping[str, Any], *, deployed: bool) -> IndexDefinition:
    """Match index.yaml's shorthand against Datastore Admin's ordered definition."""
    if deployed:
        ancestor = {"NONE": False, "ALL_ANCESTORS": True}[row["ancestor"]]
        properties = tuple((p["name"], p["direction"]) for p in row["properties"])
    else:
        ancestor = row.get("ancestor", False)
        properties = tuple(
            (p["name"], {"asc": "ASCENDING", "desc": "DESCENDING"}[p.get("direction", "asc")])
            for p in row["properties"]
        )
    return row["kind"], ancestor, properties


def _describe(index: IndexDefinition) -> str:
    kind, ancestor, properties = index
    fields = ", ".join(f"{name} {direction}" for name, direction in properties)
    return f"{kind} ({fields})" + (" with ancestors" if ancestor else "")


def wait_for_indexes(manifest: Mapping[str, object], project_args: Sequence[str]) -> None:
    """Wait for required indexes on the same project targeted by app deploy."""
    indexes = manifest.get("indexes")
    if not isinstance(indexes, list):
        raise ValueError("index.yaml must contain an indexes list.")
    required = {_definition(index, deployed=False) for index in indexes}
    if not required:
        return

    command = [GCLOUD_CLI or "gcloud", "datastore", "indexes", "list", *project_args]
    deadline = time.monotonic() + INDEX_BUILD_TIMEOUT
    last_pending = None
    while True:
        result = run_command([*command, "--format=json"])
        rows = json.loads(result.stdout)
        if not isinstance(rows, list):
            raise ValueError("Expected a list of Datastore indexes from gcloud.")
        states = {_definition(row, deployed=True): row.get("state") for row in rows}
        pending = []
        for index in sorted(required):
            state = states.get(index, "MISSING")
            if state == "READY":
                continue
            if state not in ("MISSING", "CREATING"):
                raise RuntimeError(
                    f"Required Datastore index {_describe(index)} has state {state!r}. "
                    f"Inspect it with {format_command(command)} before retrying deployment."
                )
            pending.append(index)
        if not pending:
            return

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                f"Timed out waiting for {len(pending)} required Datastore indexes. "
                f"Still waiting for {_describe(pending[0])}. "
                f"Check {format_command(command)} and retry deployment when ready."
            )
        if len(pending) != last_pending:
            output(f"Waiting for Datastore indexes ({len(required) - len(pending)} of {len(required)} ready).")
            last_pending = len(pending)
        time.sleep(min(POLL_INTERVAL, remaining))
