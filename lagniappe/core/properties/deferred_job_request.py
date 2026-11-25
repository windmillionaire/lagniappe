"""Deferred-job request identity, authorization, and bounded payload values."""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from lagniappe.core.entities import types as models
    from collections.abc import Mapping
    from lagniappe.core.definitions.deferred_jobs import DeferredJobSpec


import hashlib
import json
import uuid

from lagniappe.core import exceptions
from lagniappe.core.definitions import DEFERRED_JOB_PAYLOAD_LIMIT_BYTES

from ..mixins import RelatedEntityMixin
from .base_db import DBProperty


type _Actor = models.User
type _Notification = models.Notification


class Actor(RelatedEntityMixin[_Actor], DBProperty[_Actor]):
    _id = "actor"
    _kind = "user"


class Notification(RelatedEntityMixin[_Notification], DBProperty[_Notification]):
    _id = "notification"
    _kind = "notification"


class JSONValue(DBProperty[dict[str, object]]):
    """JSON-backed request value that preserves an explicitly empty container."""

    json = True
    _blank_values = (None,)


class JobType(DBProperty[str]):
    _id = "job_type"


class Version(DBProperty[int]):
    _id = "job_version"


class IdempotencyKey(DBProperty[str]):
    _id = "idempotency_key"

    @staticmethod
    def generate(spec: DeferredJobSpec) -> str:
        source = ":".join(
            (spec.job_type.value, spec.actor.urlsafe_key, uuid.uuid4().hex)
        )
        return hashlib.sha256(source.encode("utf-8")).hexdigest()


class RequestFingerprint(DBProperty[str]):
    _id = "request_fingerprint"

    @staticmethod
    def create(*, job_type: str, actor: str, authorization: Mapping[str, object], inputs: Mapping[str, object], parameters: Mapping[str, object], client: Mapping[str, object] | None) -> str:
        """Hash the complete immutable deferred-operation request contract."""
        payload = json.dumps(
            {
                "job_type": job_type,
                "actor": actor,
                "authorization": authorization,
                "inputs": inputs,
                "parameters": parameters,
                "client": client or {},
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class StartCompleted(DBProperty[bool]):
    _id = "start_completed"


class TelemetryId(DBProperty[str]):
    _id = "telemetry_id"


class Authorization(JSONValue):
    _id = "authorization"


@runtime_checkable
class _EntityReference(Protocol):
    @property
    def entity_kind(self) -> str: ...

    @property
    def urlsafe_key(self) -> str: ...


class Inputs(JSONValue):
    _id = "inputs"

    @staticmethod
    def serialize(inputs: Mapping[str, object] | None) -> dict[str, dict[str, str] | None]:
        """Reduce typed entity inputs to the stable persisted reference shape."""
        result = {}
        for name, value in (inputs or {}).items():
            if isinstance(value, _EntityReference):
                result[name] = {
                    "kind": value.entity_kind,
                    "id": value.urlsafe_key,
                }
            elif isinstance(value, dict) and value.get("kind") and value.get("id"):
                result[name] = {"kind": value["kind"], "id": value["id"]}
            elif value is None:
                result[name] = None
            else:
                raise TypeError(
                    f"Deferred job input {name!r} must be an entity reference"
                )
        return result


class Parameters(JSONValue):
    _id = "parameters"


class Client(JSONValue):
    _id = "client"


def validate_payload(**sections: object) -> int:
    """Validate the complete envelope before its JSON values are persisted."""
    size = len(
        json.dumps(sections, sort_keys=True, separators=(",", ":"), default=str)
        .encode("utf-8")
    )
    if size > DEFERRED_JOB_PAYLOAD_LIMIT_BYTES:
        raise exceptions.ValidationError(
            "Deferred job payload exceeds the 750 KiB persistence limit."
        )
    return size
