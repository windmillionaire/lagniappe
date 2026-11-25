"""Strict wire contract for adaptive browser polling."""

from typing import Literal, TypedDict, overload

from dataclasses import dataclass

from .projections import CHANNEL_REVISION_PATHS


POLL_PROTOCOL_VERSION = 1
MAX_POLL_SUBSCRIPTIONS = 64
MAX_POLL_KEY_LENGTH = 512
MAX_POLL_IDENTIFIER_LENGTH = MAX_POLL_KEY_LENGTH + 128
MAX_POLL_CLIENT_ID_LENGTH = 128
MAX_POLL_CURSOR_LENGTH = 512
MAX_POLL_STATE_TOKEN_LENGTH = 128
MAX_POLL_REVISION = 9_007_199_254_740_991
POLL_TYPES = frozenset(
    {"entity", "channel", "form-lock", "document", "operation", "ingress"}
)
POLL_CHANNELS = frozenset(CHANNEL_REVISION_PATHS)


class PollContractError(ValueError):
    """A safe, field-addressed public polling contract failure."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


class ChannelDescriptor(TypedDict):
    id: str
    type: Literal["channel"]
    channel: str
    revision: str | None


class KeyDescriptor(TypedDict):
    id: str
    type: Literal["entity", "form-lock", "ingress"]
    key: str
    revision: str | None


class OperationDescriptor(TypedDict):
    id: str
    type: Literal["operation"]
    key: str
    revision: int


class DocumentDescriptor(TypedDict):
    id: str
    type: Literal["document"]
    key: str
    sync_id: str
    generation: str | None
    presence_digest: str | None
    revision: int


type PollDescriptor = ChannelDescriptor | KeyDescriptor | OperationDescriptor | DocumentDescriptor


class ClientNotificationState(TypedDict):
    generation: str | None
    revision: int | None
    seed: bool


@dataclass(frozen=True)
class PollRequest:
    """Canonical polling request consumed by the route executor."""

    version: int
    client_id: str
    subscriptions: tuple[PollDescriptor, ...]
    closed_documents: tuple[str, ...]
    notification_state: ClientNotificationState | None


def _field(path, name):
    return f"{path}.{name}" if path else name


def _object(value, path):
    if not isinstance(value, dict):
        raise PollContractError(path, "type")
    return value


def _fields(value, path, required, optional=()):
    allowed = frozenset((*required, *optional))
    for name in required:
        if name not in value:
            raise PollContractError(_field(path, name), "missing")
    for name in value:
        if name not in allowed:
            raise PollContractError(_field(path, name), "unexpected")


@overload
def _string(value: object, path: str, *, maximum: int, nullable: Literal[False] = False) -> str: ...
@overload
def _string(value: object, path: str, *, maximum: int, nullable: bool) -> str | None: ...
def _string(value: object, path: str, *, maximum: int, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str):
        raise PollContractError(path, "type")
    if not value.strip():
        raise PollContractError(path, "blank")
    if len(value) > maximum:
        raise PollContractError(path, "limit")
    return value


def _revision_integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PollContractError(path, "type")
    if value < 0:
        raise PollContractError(path, "state")
    if value > MAX_POLL_REVISION:
        raise PollContractError(path, "limit")
    return value


def _document_id(value: object, path: str) -> str:
    value = _string(value, path, maximum=MAX_POLL_KEY_LENGTH)
    if not value.endswith(":document"):
        raise PollContractError(path, "unsupported")
    return value


def _descriptor(raw: object, index: int, identifiers: set[str]) -> PollDescriptor:
    path = f"subscriptions[{index}]"
    value = _object(raw, path)
    for name in ("id", "type", "revision"):
        if name not in value:
            raise PollContractError(_field(path, name), "missing")

    identifier = _string(
        value["id"],
        _field(path, "id"),
        maximum=MAX_POLL_IDENTIFIER_LENGTH,
    )
    if identifier in identifiers:
        raise PollContractError(_field(path, "id"), "duplicate")

    subscription_type = _string(
        value["type"],
        _field(path, "type"),
        maximum=32,
    )
    if subscription_type not in POLL_TYPES:
        raise PollContractError(_field(path, "type"), "unsupported")

    typed_fields = ("channel",) if subscription_type == "channel" else ("key",)
    if subscription_type == "document":
        typed_fields = ("key", "sync_id", "generation", "presence_digest")
    _fields(value, path, ("id", "type", "revision", *typed_fields))

    revision_path = _field(path, "revision")
    if subscription_type in {"operation", "document"}:
        revision = _revision_integer(value["revision"], revision_path)
        key = _string(value["key"], _field(path, "key"), maximum=MAX_POLL_KEY_LENGTH)
        if subscription_type == "document":
            normalized: PollDescriptor = {
                "id": identifier,
                "type": "document",
                "key": key,
                "revision": revision,
                "sync_id": _document_id(value["sync_id"], _field(path, "sync_id")),
                "generation": _string(
                    value["generation"], _field(path, "generation"),
                    maximum=MAX_POLL_STATE_TOKEN_LENGTH, nullable=True,
                ),
                "presence_digest": _string(
                    value["presence_digest"], _field(path, "presence_digest"),
                    maximum=MAX_POLL_STATE_TOKEN_LENGTH, nullable=True,
                ),
            }
        else:
            normalized = {"id": identifier, "type": "operation", "key": key, "revision": revision}
    else:
        revision = _string(
            value["revision"], revision_path, maximum=MAX_POLL_CURSOR_LENGTH,
            nullable=subscription_type != "form-lock",
        )
        if subscription_type == "channel":
            channel = _string(value["channel"], _field(path, "channel"), maximum=64)
            if channel not in POLL_CHANNELS:
                raise PollContractError(_field(path, "channel"), "unsupported")
            normalized = {"id": identifier, "type": "channel", "channel": channel, "revision": revision}
        else:
            assert subscription_type == "entity" or subscription_type == "ingress" or subscription_type == "form-lock"
            key = _string(value["key"], _field(path, "key"), maximum=MAX_POLL_KEY_LENGTH)
            normalized = {"id": identifier, "type": subscription_type, "key": key, "revision": revision}
    identifiers.add(identifier)
    return normalized


def _notification_state(raw: object) -> ClientNotificationState:
    path = "notification_state"
    value = _object(raw, path)
    _fields(value, path, ("generation", "revision", "seed"))
    seed = value["seed"]
    if not isinstance(seed, bool):
        raise PollContractError(_field(path, "seed"), "type")

    generation = _string(
        value["generation"],
        _field(path, "generation"),
        maximum=MAX_POLL_STATE_TOKEN_LENGTH,
        nullable=True,
    )
    revision = value["revision"]
    if revision is not None:
        revision = _revision_integer(revision, _field(path, "revision"))

    cold = seed and generation is None and revision is None
    warm = not seed and generation is not None and revision is not None
    if not cold and not warm:
        raise PollContractError(path, "state")
    return {"generation": generation, "revision": revision, "seed": seed}


def parse_poll_request(payload: object) -> PollRequest:
    """Parse one exact version-1 request or raise a safe contract error."""
    value = _object(payload, "request")
    _fields(
        value,
        "",
        ("version", "client_id", "subscriptions", "closed_documents"),
        ("notification_state",),
    )

    version = value["version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise PollContractError("version", "type")
    if version != POLL_PROTOCOL_VERSION:
        raise PollContractError("version", "unsupported")

    client_id = _string(
        value["client_id"],
        "client_id",
        maximum=MAX_POLL_CLIENT_ID_LENGTH,
    )
    subscriptions = value["subscriptions"]
    if not isinstance(subscriptions, list):
        raise PollContractError("subscriptions", "type")
    if len(subscriptions) > MAX_POLL_SUBSCRIPTIONS:
        raise PollContractError("subscriptions", "limit")

    identifiers = set()
    normalized = tuple(
        _descriptor(descriptor, index, identifiers)
        for index, descriptor in enumerate(subscriptions)
    )

    closed = value["closed_documents"]
    if not isinstance(closed, list):
        raise PollContractError("closed_documents", "type")
    if len(closed) > MAX_POLL_SUBSCRIPTIONS:
        raise PollContractError("closed_documents", "limit")
    closed_documents = []
    closed_identifiers = set()
    for index, raw in enumerate(closed):
        path = f"closed_documents[{index}]"
        sync_id = _document_id(raw, path)
        if sync_id in closed_identifiers:
            raise PollContractError(path, "duplicate")
        closed_identifiers.add(sync_id)
        closed_documents.append(sync_id)

    notification_state = (
        _notification_state(value["notification_state"])
        if "notification_state" in value
        else None
    )
    return PollRequest(
        version=version,
        client_id=client_id,
        subscriptions=normalized,
        closed_documents=tuple(closed_documents),
        notification_state=notification_state,
    )
