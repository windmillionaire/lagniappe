"""Cross-machine lease for the one shared test-prefixed data set."""

from __future__ import annotations

import hashlib
import re
import secrets
import threading

from lagniappe import CONFIG


DEFAULT_LEASE_SECONDS = 15 * 60
DEFAULT_HEARTBEAT_SECONDS = 60
DEFAULT_DEPLOYMENT_BINDING_SECONDS = 2 * 60 * 60
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")

_COMPARE_EXPIRE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""

_COMPARE_DELETE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


# @testable false
# @covered-by lagniappe/core/tools/hosted_e2e/lease.py::acquire_e2e_lease
# @reason lazy Redis adapter owned by the public lease operations
def _redis_client(client=None):
    if client is not None:
        return client
    from lagniappe.core.tools.cache.core import cache

    return cache.redis


# @testable false
# @covered-by lagniappe/core/tools/hosted_e2e/lease.py::acquire_e2e_lease
# @reason common validation owned by the public lease operations
def _validate_run_id(run_id: str) -> str:
    run_id = str(run_id or "").strip()
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("E2E run ID is missing or invalid.")
    return run_id


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_e2e_lease_key_is_outside_test_cleanup_prefix
# @features hosted-e2e
# @dimensions lease prefix-isolation
def e2e_lease_key(*, project_id=None, prefix=None) -> str:
    """Return a reserved key that cannot match ordinary test-data cleanup."""
    project_id = str(project_id or CONFIG.GOOGLE_CLOUD_PROJECT or "").strip()
    prefix = str(prefix if prefix is not None else CONFIG.PREFIX)
    if not project_id or not prefix:
        raise RuntimeError("E2E lease requires a project and nonempty test prefix.")
    digest = hashlib.sha256(f"{project_id}\0{prefix}".encode()).hexdigest()[:20]
    return f"lagniappe:e2e:lease:{digest}"


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_e2e_lease_acquire_heartbeat_and_owner_release
# @features hosted-e2e
# @dimensions lease concurrency expiry ownership
def acquire_e2e_lease(run_id: str, *, ttl=DEFAULT_LEASE_SECONDS, client=None) -> bool:
    run_id = _validate_run_id(run_id)
    return bool(
        _redis_client(client).set(
            e2e_lease_key(),
            run_id,
            nx=True,
            ex=int(ttl),
        )
    )


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_e2e_lease_acquire_heartbeat_and_owner_release
# @features hosted-e2e
# @dimensions lease ownership
def current_e2e_lease(*, client=None) -> str | None:
    value = _redis_client(client).get(e2e_lease_key())
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return str(value) if value else None


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_e2e_lease_acquire_heartbeat_and_owner_release
# @features hosted-e2e
# @dimensions lease ownership
def e2e_lease_active(run_id: str, *, client=None) -> bool:
    return current_e2e_lease(client=client) == _validate_run_id(run_id)


# @testable false
# @covered-by lagniappe/core/tools/hosted_e2e/lease.py::bind_e2e_deployment
# @reason deployment-key derivation is owned by the public binding contract
def _deployment_lease_key(version: str, source: str) -> str:
    version = str(version or "").strip()
    source = str(source or "").strip().casefold()
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", version):
        raise ValueError("E2E deployment version is invalid.")
    if not re.fullmatch(r"[0-9a-f]{7,64}", source):
        raise ValueError("E2E deployment source is invalid.")
    digest = hashlib.sha256(f"{version}\0{source}".encode()).hexdigest()[:24]
    return f"{e2e_lease_key()}:deployment:{digest}"


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_e2e_lease_acquire_heartbeat_and_owner_release
# @features hosted-e2e
# @dimensions lease deployment-binding ownership
def bind_e2e_deployment(
    run_id: str,
    version: str,
    source: str,
    *,
    ttl=DEFAULT_DEPLOYMENT_BINDING_SECONDS,
    client=None,
) -> bool:
    """Bind one deployed server to the run that currently owns the lease."""
    run_id = _validate_run_id(run_id)
    redis_client = _redis_client(client)
    if not e2e_lease_active(run_id, client=redis_client):
        return False
    return bool(
        redis_client.set(
            _deployment_lease_key(version, source),
            run_id,
            ex=int(ttl),
        )
    )


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_e2e_lease_acquire_heartbeat_and_owner_release
# @features hosted-e2e
# @dimensions lease deployment-binding ownership
def e2e_deployment_lease_active(
    version: str,
    source: str,
    *,
    run_id: str | None = None,
    client=None,
) -> bool:
    """Return whether this deployment is bound to the current lease owner."""
    redis_client = _redis_client(client)
    bound = redis_client.get(_deployment_lease_key(version, source))
    if isinstance(bound, bytes):
        bound = bound.decode("utf-8")
    if not bound:
        return False
    if run_id is not None and str(bound) != _validate_run_id(run_id):
        return False
    return e2e_lease_active(str(bound), client=redis_client)


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_e2e_lease_acquire_heartbeat_and_owner_release
# @features hosted-e2e
# @dimensions lease expiry ownership
def heartbeat_e2e_lease(
    run_id: str,
    *,
    ttl=DEFAULT_LEASE_SECONDS,
    client=None,
) -> bool:
    run_id = _validate_run_id(run_id)
    result = _redis_client(client).eval(
        _COMPARE_EXPIRE,
        1,
        e2e_lease_key(),
        run_id,
        int(ttl),
    )
    return bool(result)


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_e2e_lease_acquire_heartbeat_and_owner_release
# @features hosted-e2e
# @dimensions lease ownership
def release_e2e_lease(run_id: str, *, client=None) -> bool:
    run_id = _validate_run_id(run_id)
    result = _redis_client(client).eval(
        _COMPARE_DELETE,
        1,
        e2e_lease_key(),
        run_id,
    )
    return bool(result)


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_e2e_lease_acquire_heartbeat_and_owner_release
# @features hosted-e2e
# @dimensions lease authentication replay
def consume_e2e_bootstrap_token(
    token_digest: str,
    run_id: str,
    *,
    ttl=10 * 60,
    client=None,
) -> bool:
    """Consume one verified ID token once for the lease-owning run."""
    run_id = _validate_run_id(run_id)
    token_digest = str(token_digest or "").casefold()
    if not re.fullmatch(r"[0-9a-f]{64}", token_digest):
        raise ValueError("E2E token digest is invalid.")
    redis_client = _redis_client(client)
    if not e2e_lease_active(run_id, client=redis_client):
        return False
    exchange_digest = hashlib.sha256(
        f"{run_id}\0{token_digest}".encode("utf-8")
    ).hexdigest()
    key = f"{e2e_lease_key()}:bootstrap:{exchange_digest}"
    return bool(redis_client.set(key, run_id, nx=True, ex=int(ttl)))


# @testable true
# @tests tests_unit/test_017_cache_query.py::test_e2e_lease_acquire_heartbeat_and_owner_release
# @features hosted-e2e
# @dimensions lease concurrency heartbeat ownership
class E2ELease:
    """Acquire, heartbeat, and owner-release the shared test-data lease."""

    # @testable false
    # @covered-by lagniappe/core/tools/hosted_e2e/lease.py::E2ELease.__enter__
    # @reason constructor state is exercised by the context-manager contract
    def __init__(
        self,
        run_id: str | None = None,
        *,
        ttl=DEFAULT_LEASE_SECONDS,
        heartbeat_seconds=DEFAULT_HEARTBEAT_SECONDS,
        client=None,
    ):
        self.run_id = _validate_run_id(run_id or secrets.token_urlsafe(32))
        self.ttl = int(ttl)
        self.heartbeat_seconds = int(heartbeat_seconds)
        self.client = client
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = None

    # @testable true
    # @tests tests_unit/test_017_cache_query.py::test_e2e_lease_acquire_heartbeat_and_owner_release
    # @features hosted-e2e
    # @dimensions lease concurrency heartbeat ownership
    def __enter__(self):
        if not acquire_e2e_lease(
            self.run_id,
            ttl=self.ttl,
            client=self.client,
        ):
            owner = current_e2e_lease(client=self.client) or "unknown"
            raise RuntimeError(
                "Another local or hosted E2E session owns the shared test "
                f"data lease ({owner})."
            )
        self._thread = threading.Thread(
            target=self._heartbeat,
            name="lagniappe-e2e-lease",
            daemon=True,
        )
        self._thread.start()
        return self

    # @testable false
    # @covered-by lagniappe/core/tools/hosted_e2e/lease.py::E2ELease.__enter__
    # @reason daemon loop is owned by the lease context-manager lifecycle
    def _heartbeat(self):
        while not self._stop.wait(self.heartbeat_seconds):
            try:
                active = heartbeat_e2e_lease(
                    self.run_id,
                    ttl=self.ttl,
                    client=self.client,
                )
            except Exception:
                active = False
            if not active:
                self._lost.set()
                return

    # @testable true
    # @tests tests_unit/test_017_cache_query.py::test_e2e_lease_acquire_heartbeat_and_owner_release
    # @features hosted-e2e
    # @dimensions lease ownership
    def assert_active(self):
        if self._lost.is_set() or not e2e_lease_active(
            self.run_id,
            client=self.client,
        ):
            raise RuntimeError("The shared E2E data lease was lost during the run.")

    # @testable true
    # @tests tests_unit/test_017_cache_query.py::test_e2e_lease_acquire_heartbeat_and_owner_release
    # @features hosted-e2e
    # @dimensions lease ownership
    def __exit__(self, exc_type, exc_value, traceback):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        try:
            release_e2e_lease(self.run_id, client=self.client)
        finally:
            self._thread = None


__all__ = [
    "E2ELease",
    "acquire_e2e_lease",
    "bind_e2e_deployment",
    "consume_e2e_bootstrap_token",
    "current_e2e_lease",
    "e2e_deployment_lease_active",
    "e2e_lease_active",
    "e2e_lease_key",
    "heartbeat_e2e_lease",
    "release_e2e_lease",
]
