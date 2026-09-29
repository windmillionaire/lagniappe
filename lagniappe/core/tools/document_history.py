"""Document-scoped recovery pins and retained Storage versions."""

import hashlib
import re

from itsdangerous import URLSafeTimedSerializer, BadSignature

from lagniappe import CONFIG
from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import ValidationError
from .database import assets, utility


# @testable infrastructure
def _tokens():
    return URLSafeTimedSerializer(CONFIG.SECRET_KEY, salt="document-backup")


# @testable true
# @tests tests_unit/test_010c_document_versions.py::test_storage_backups_are_scoped_paginated_and_generation_bound
# @matrix document-history : backups permissions pagination
def list_backups(entity, cursor=None):
    if cursor:
        try:
            cursor = _tokens().loads(cursor, max_age=3600)
            if cursor["owner"] != entity.urlsafe_key:
                raise ValueError()
            cursor = cursor["cursor"]
        except (BadSignature, KeyError, TypeError, ValueError) as error:
            raise ValidationError("Invalid or expired backup listing; reopen History.") from error
    iterator = assets.DATA.bucket("private").list_blobs(
        prefix=f"{entity.hash}_document", versions=True, page_size=50,
        max_results=50, page_token=cursor,
    )
    page = next(iterator.pages, ())
    entries = []
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


# @testable true
# @tests tests_unit/test_010c_document_versions.py::test_storage_backups_are_scoped_paginated_and_generation_bound
# @matrix document-history : backups permissions generation-pinned
def read_backup(entity, token):
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


# @testable true
# @tests tests_unit/test_010c_document_versions.py::test_recovery_pin_retry_is_scoped_and_keeps_empty_versions
# @matrix document-history : recovery idempotency empty-content
def recovery_pin(entity, user, *, html, name, operation_id):
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
    Entities.save(history)
    return history
