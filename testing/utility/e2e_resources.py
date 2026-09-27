"""Run-local enum identities shared by coordinated pytest processes."""

from contextlib import contextmanager
import json
import os
from pathlib import Path


_active = None


# @testable infrastructure
@contextmanager
def resource_registry():
    """Serialize lazy fixture creation, including recursive prerequisites."""
    global _active
    if _active is not None:
        yield _active
        return
    from testing.utility.e2e_worker import context
    directory = context().get("resource_registry")
    if not directory:
        yield None
        return
    # Both local and hosted coordinated workers run on the same Linux host.
    import fcntl
    root = Path(directory)
    with (root / "resources.lock").open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / "resources.json"
        rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        _active = rows
        try:
            yield rows
        finally:
            # Retain completed prerequisites even if a later creation fails.
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(rows), encoding="utf-8")
            temporary.replace(path)
            _active = None


# @testable true
# @tests tests_unit/test_031_e2e_resources.py::test_enum_identity_is_reused_after_forgetting_and_across_process_state
# @matrix testing : parallel-e2e
def resolve_resource(member, user, create=True):
    resource = member.value
    resource.user = user
    if not os.environ.get("LAGNIAPPE_E2E_WORKER_CONTEXT"):
        if not resource.key and create:
            resource.create()
        return resource
    identity = f"{type(member).__name__}.{member.name}"
    with resource_registry() as rows:
        if rows is not None and identity in rows:
            resource.key = rows[identity]
        if not resource.key and create:
            resource.create()
        if rows is not None and resource.key:
            rows[identity] = resource.key
    return resource


# @testable infrastructure
def publish_resource_keys():
    """Publish identities captured by browser creation stories at teardown."""
    if not os.environ.get("LAGNIAPPE_E2E_WORKER_CONTEXT"):
        return
    from enum import Enum
    from testing import definitions
    with resource_registry() as rows:
        if rows is None:
            return
        for enum in vars(definitions).values():
            if not isinstance(enum, type) or not issubclass(enum, Enum):
                continue
            for member in enum:
                key = getattr(member.value, "_key", None)
                if key:
                    rows[f"{enum.__name__}.{member.name}"] = key
