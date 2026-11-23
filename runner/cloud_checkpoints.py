"""Project-private, generation-checked hosted-E2E state for disposable tasks."""

from __future__ import annotations

import json
import os
import uuid
from argparse import Namespace
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Literal, TypedDict, cast

if TYPE_CHECKING:
    from google.cloud.storage import Bucket

class Operation(TypedDict, total=False):
    action: str
    id: str
    settings_version: str
    started: str


class CheckpointDocument(TypedDict):
    schema: int
    project: str
    setup: dict[str, object] | None
    state: dict[str, object] | None
    operation: Operation | None


OBJECT = "hosted-e2e/checkpoint.json"
DOCUMENTS = {"setup.json": "setup", "state.json": "state"}


def _bucket(project, number, *, credentials=None):
    from google.cloud import storage

    bucket = storage.Client(project=project, credentials=credentials).get_bucket(
        f"{project}-lagniappe-operator"
    )
    iam = bucket.iam_configuration
    if (
        str(bucket.project_number) != str(number)
        or iam.public_access_prevention != "enforced"
        or not iam.uniform_bucket_level_access_enabled
    ):
        raise RuntimeError(
            "The checkpoint bucket must be private and owned by the selected project."
        )
    return bucket


class Checkpoint:
    def __init__(self, bucket: Bucket, project: str) -> None:
        self.bucket = bucket
        self.project = project
        self.generation = 0
        self.doc: CheckpointDocument = {
            "schema": 1,
            "project": project,
            "setup": None,
            "state": None,
            "operation": None,
        }
        self.paths: dict[Path, Literal["state", "setup"]] = {}

    def load(self) -> None:
        blob = self.bucket.get_blob(OBJECT)
        if blob is None:
            raise RuntimeError(
                "Initialize the operator checkpoint from the installation first."
            )
        if blob.generation is None:
            raise RuntimeError("Cloud Storage returned a checkpoint without a generation.")
        self.generation = blob.generation
        doc = json.loads(blob.download_as_bytes(if_generation_match=self.generation))
        if (
            not isinstance(doc, dict)
            or set(doc) != set(self.doc)
            or doc["schema"] != 1
            or doc["project"] != self.project
        ):
            raise RuntimeError(
                "The stored checkpoint schema or project does not match."
            )
        for name in ("state", "setup"):
            item = doc[name]
            if item is not None and (
                not isinstance(item, dict) or item.get("schema_version") != 1 or item.get("project") != self.project
            ):
                raise RuntimeError(
                    "The lifecycle document belongs to another schema or project."
                )
        operation = doc["operation"]
        if operation is not None and (
            not isinstance(operation, dict)
            or any(
                not isinstance(value, str)
                for key, value in operation.items()
                if key in Operation.__optional_keys__
            )
        ):
            raise RuntimeError("The stored checkpoint contains an invalid operation.")
        self.doc = cast(CheckpointDocument, doc)

    def save(self) -> None:
        from google.api_core.exceptions import PreconditionFailed

        blob = self.bucket.blob(OBJECT)
        try:
            blob.upload_from_string(
                json.dumps(self.doc),
                content_type="application/json",
                if_generation_match=self.generation,
            )
        except PreconditionFailed:
            raise RuntimeError(
                "Another task changed the operator checkpoint. Read status before retrying."
            ) from None
        if blob.generation is None:
            raise RuntimeError("Cloud Storage returned a checkpoint without a generation.")
        self.generation = blob.generation

    def write(self, path: Path, payload: dict[str, object]) -> None:
        operation = self.doc["operation"]
        if not operation or payload.get("project") != self.project:
            raise RuntimeError(
                "A project-bound operation is required to save lifecycle progress."
            )
        item = deepcopy(payload)
        if self.paths[path] == "state":
            if "settings_version" not in operation:
                raise RuntimeError("Saving lifecycle state requires the operation's settings version.")
            item["cloud_settings_version"] = operation["settings_version"]
        self.doc[self.paths[path]] = item
        self.save()

    @contextmanager
    def operation(
        self,
        action: str,
        receipt: Mapping[str, str],
        recover_generation: int | None = None,
    ) -> Iterator[None]:
        self.load()
        operation = self.doc["operation"]
        if action == "status":
            print(
                f"Checkpoint generation {self.generation}, operation {operation or 'idle'}"
            )
            yield
            return
        if operation and recover_generation != self.generation:
            raise RuntimeError(
                f"Another task holds checkpoint generation {self.generation}. Inspect status before recovery."
            )
        if recover_generation is not None and (
            not operation or recover_generation != self.generation
        ):
            raise RuntimeError("The requested recovery generation is no longer locked.")
        state = self.doc["state"] or {}
        if state.get("status") not in {None, "torn-down"} and (
            state.get("cloud_settings_version") != receipt["version"]
            or state.get("source") != receipt["source"]
        ):
            raise RuntimeError(
                "Restore the active candidate's numeric settings version and checkout its source commit."
            )
        self.doc["operation"] = {
            "action": action,
            "id": uuid.uuid4().hex,
            "settings_version": receipt["version"],
            "started": datetime.now(UTC).isoformat(),
        }
        self.save()
        try:
            yield
        finally:
            self.doc["operation"] = None
            self.save()


ACTIVE: ContextVar[Checkpoint | None] = ContextVar("hosted_checkpoint", default=None)


def seed(root: Path, project: str) -> None:
    """Import the existing verified installation's last completed setup and teardown once."""
    from google.oauth2.credentials import Credentials

    from runner import cloud_settings as settings

    receipt = settings._receipt(root)
    if receipt.get("project") != project or receipt.get("secret") != settings.SECRET:
        raise RuntimeError(
            "Publish or restore the source installation's settings first."
        )
    bundle = settings._local_bundle(root, project, receipt)
    _, dev = settings.validate_bundle(bundle, project)
    target = dev["gcloud_config"]
    token = settings.cli_token(project, target["NAME"], target["ACCOUNT"])
    docs = {}
    for filename, key in DOCUMENTS.items():
        raw = settings._read(root, Path("reports/hosted-e2e") / filename)
        if raw is None:
            raise RuntimeError(
                "The source installation must have both setup and lifecycle state."
            )
        item = json.loads(raw)
        if (
            item.get("schema_version") != 1
            or item.get("project") != project
            or item.get("service") != "e2e"
        ):
            raise RuntimeError(
                "The local lifecycle state does not match the selected project."
            )
        docs[key] = item
    if docs["state"].get("status") != "torn-down":
        raise RuntimeError(
            "Finish the installation's active lifecycle before transferring ownership."
        )
    bucket = _bucket(
        project, docs["setup"]["project_number"], credentials=Credentials(token)
    )
    checkpoint = Checkpoint(bucket, project)
    checkpoint.doc["state"] = docs["state"]
    checkpoint.doc["setup"] = docs["setup"]
    checkpoint.save()
    print(
        f"Initialized the private checkpoint for {project} at generation {checkpoint.generation}."
    )


@contextmanager
def lifecycle(hosted: ModuleType, args: Namespace) -> Iterator[None]:
    project = os.environ.get("LAGNIAPPE_CLOUD_CHECKPOINT_PROJECT")
    if not project or args.action in {"import-results", "validate-release-evidence"}:
        if getattr(args, "recover_generation", None) is not None:
            raise RuntimeError(
                "Checkpoint recovery requires a remote checkpoint project."
            )
        yield
        return

    from runner import cloud_settings as settings

    receipt = settings._receipt(hosted.APP_DIR)
    if (
        receipt.get("project") != project
        or receipt.get("secret") != settings.SECRET
        or hosted.SETTINGS.APP.get("GOOGLE_CLOUD_PROJECT") != project
        or hosted.SETTINGS.GCLOUD_CONFIG.get("PROJECT") != project
        or not settings.VERSION.fullmatch(str(receipt.get("version", "")))
    ):
        raise RuntimeError(
            "Restore the selected project's settings before using its checkpoint."
        )
    if settings._snapshot(hosted.APP_DIR) != receipt.get("fingerprint"):
        raise RuntimeError(
            "Publish or restore local settings edits before starting a remote lifecycle."
        )
    source = settings._source(hosted.APP_DIR)
    if receipt["source"] != source:
        raise RuntimeError(
            "Restore the pinned settings at the current checkout revision first."
        )
    hosted._activate(adc=True)
    infrastructure = hosted._infrastructure()
    checkpoint = Checkpoint(_bucket(project, infrastructure.project_number), project)
    checkpoint.paths = {hosted.SETUP_PATH: "setup", hosted.STATE_PATH: "state"}
    with checkpoint.operation(args.action, receipt, args.recover_generation):
        token = ACTIVE.set(checkpoint)
        try:
            yield
        finally:
            ACTIVE.reset(token)
