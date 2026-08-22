"""Deferred-job request identity, authorization, and bounded payload values."""

import hashlib
import json
import uuid

from lagniappe.core import exceptions
from lagniappe.core.definitions import DEFERRED_JOB_PAYLOAD_LIMIT_BYTES

from ..mixins import RelatedEntityMixin
from .base_db import DBProperty


class Actor(RelatedEntityMixin, DBProperty):
    _id = "actor"
    _kind = "user"


class Notification(RelatedEntityMixin, DBProperty):
    _id = "notification"
    _kind = "notification"


class JSONValue(DBProperty):
    """JSON-backed request value that preserves an explicitly empty container."""

    json = True
    _blank_values = (None,)


class JobType(DBProperty):
    _id = "job_type"


class Version(DBProperty):
    _id = "job_version"


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_request_properties_own_identity_and_payload_validation
# @pair deferred-jobs:request-identity
class IdempotencyKey(DBProperty):
    _id = "idempotency_key"

    @staticmethod
    # @testable true
    # @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_request_properties_own_identity_and_payload_validation
    # @pair deferred-jobs:request-identity
    def generate(spec):
        source = ":".join(
            (spec.job_type.value, spec.actor.urlsafe_key, uuid.uuid4().hex)
        )
        return hashlib.sha256(source.encode("utf-8")).hexdigest()


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_request_fingerprint_tracks_the_complete_client_contract
# @features deferred-jobs
# @dimensions operation-fingerprint client-contract routing-identity
class RequestFingerprint(DBProperty):
    _id = "request_fingerprint"

    # @testable true
    # @tests tests_unit/test_023a_deferred_job_properties.py::test_request_fingerprint_tracks_the_complete_client_contract
    # @features deferred-jobs
    # @dimensions operation-fingerprint client-contract routing-identity
    @staticmethod
    def create(*, job_type, actor, authorization, inputs, parameters, client):
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


class StartCompleted(DBProperty):
    _id = "start_completed"


class TelemetryId(DBProperty):
    _id = "telemetry_id"


class Authorization(JSONValue):
    _id = "authorization"


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_request_properties_own_identity_and_payload_validation
# @pair deferred-jobs:input-serialization
class Inputs(JSONValue):
    _id = "inputs"

    @staticmethod
    # @testable true
    # @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_request_properties_own_identity_and_payload_validation
    # @pair deferred-jobs:input-serialization
    def serialize(inputs):
        """Reduce typed entity inputs to the stable persisted reference shape."""
        result = {}
        for name, value in (inputs or {}).items():
            if hasattr(value, "urlsafe_key"):
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


# @testable true
# @tests tests_unit/test_023a_deferred_job_properties.py::test_deferred_job_request_properties_own_identity_and_payload_validation
# @pair deferred-jobs:payload-limit
def validate_payload(**sections):
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
