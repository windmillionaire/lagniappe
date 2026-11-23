"""Document-scoped recovery pins and retained Storage versions."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..entities.entity import Entity
    from ..entities.user import User
    from ..entities.page import Page
    from ..entities.project import Project

from typing import TypedDict

import hashlib
import re

from itsdangerous import URLSafeTimedSerializer, BadSignature

from lagniappe import CONFIG
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import ValidationError
from .database import assets, utility


class BackupEntry(TypedDict):
    key: str
    name: str
    backup: bool
    created: str


class BackupListing(TypedDict):
    entries: list[BackupEntry]
    cursor: str | None


def _tokens():
    return URLSafeTimedSerializer(CONFIG.SECRET_KEY, salt="document-backup")


def list_backups(entity: Entity, cursor: str | None = None) -> BackupListing:
    if cursor:
        try:
            cursor_record = _tokens().loads(cursor, max_age=3600)
            if cursor_record["owner"] != entity.urlsafe_key:
                raise ValueError()
            cursor = cursor_record["cursor"]
        except (BadSignature, KeyError, TypeError, ValueError) as error:
            raise ValidationError("Invalid or expired backup listing; reopen History.") from error
    iterator = assets.DATA.bucket("private").list_blobs(
        prefix=f"{entity.hash}_document", versions=True, page_size=50,
        max_results=50, page_token=cursor,
    )
    page = next(iterator.pages, ())
    entries: list[BackupEntry] = []
    pattern = re.compile(rf"{re.escape(entity.hash)}_document(?:_[a-f0-9]{{32}})?\.html")
    for blob in page:
        if not pattern.fullmatch(blob.name) or not blob.time_deleted:
            continue
        token = _tokens().dumps({"owner": entity.urlsafe_key, "path": blob.name, "generation": str(blob.generation)})
        entries.append({
            "key": token, "name": "Storage backup", "backup": True,
            "created": blob.time_created.isoformat(),
        })
    entries.sort(key=lambda entry: entry["created"], reverse=True)
    return {"entries": entries, "cursor": _tokens().dumps({
        "owner": entity.urlsafe_key, "cursor": iterator.next_page_token,
    }) if iterator.next_page_token else None}


def read_backup(entity: Entity, token: str) -> str | None:
    try:
        record = _tokens().loads(token, max_age=3600)
        pattern = rf"{re.escape(entity.hash)}_document(?:_[a-f0-9]{{32}})?\.html"
        if record["owner"] != entity.urlsafe_key or not re.fullmatch(pattern, record["path"]):
            raise ValueError()
        generation = int(record["generation"])
        if generation <= 0:
            raise ValueError()
    except (BadSignature, KeyError, TypeError, ValueError) as error:
        raise ValidationError("Invalid or expired backup; reopen the backup list.") from error
    return assets.get_text(record["path"], "private", generation=generation)


def recovery_pin(
    entity: Page | Project, user: User, *, html: str, name: str, operation_id: str
) -> Entity:
    if not isinstance(operation_id, str) or not re.fullmatch(r"[a-f0-9]{64}", operation_id):
        raise ValidationError("Invalid recovery operation")
    if not isinstance(html, str):
        raise ValidationError("Document content must be text")
    content_hash = hashlib.sha256(html.encode()).hexdigest()
    identity = hashlib.sha256(f"{user.hash}:{operation_id}:{content_hash}".encode()).hexdigest()
    key = utility.create_named_key("document_history", f"recovery-{identity}", parent=entity)
    existing = Entities.fetch_one(key, request=Fetch.root())
    if existing:
        return existing
    history = Entities.DOCUMENT_HISTORY.create(entity, name=name, html=html, key=key, allow_empty=True)
    if history is None:
        raise ValidationError("Document history creation did not produce a named version.")
    Entities.save(history)
    return history
