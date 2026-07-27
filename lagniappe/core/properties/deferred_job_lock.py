"""Persisted fields for one target-scoped deferred-job lock."""

from .base_db import DBProperty


class Target(DBProperty):
    _id = "target"


class Operation(DBProperty):
    _id = "operation"


class IdempotencyKey(DBProperty):
    _id = "idempotency_key"


class Scope(DBProperty):
    _id = "scope"
