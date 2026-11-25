"""Opaque OAuth transitions, exact client binding, and service identity."""

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, UTC
import hashlib
import io
import json
import threading
from types import SimpleNamespace

import pytest

from config.remote_mcp import (
    ACCESS_SECONDS,
    CODE_SECONDS,
    REFRESH_RACE_GRACE_SECONDS,
    REFRESH_RACE_MAX_MINTS,
    REFRESH_SECONDS,
    CLIENT_ID,
    REDIRECT_URI,
)
from lagniappe.core.tools.auth import remote_mcp as auth
from lagniappe.core.tools.database import remote_mcp as store


pytestmark = pytest.mark.unit
NOW = datetime(2026, 9, 5, tzinfo=UTC)
VERIFIER = "v" * 43


class Actor:
    key = "pilot-user-key"
    urlsafe_key = "pilot-user-key"
    email = "pilot@example.com"
    is_authenticated = True
    is_active = True
    is_public = False


@pytest.fixture
def oauth(monkeypatch):
    monkeypatch.setattr(auth.CONFIG, "AI_ENABLED", True)
    monkeypatch.setattr(auth.CONFIG, "EXTERNAL_AI_ENABLED", True)
    monkeypatch.setattr(auth.CONFIG, "APP_URL", "https://lagniappe.test")
    monkeypatch.setattr(auth.CONFIG, "CUSTOM_DOMAIN", "")
    monkeypatch.setattr(auth.CONFIG, "MCP_RESOURCE", "https://pilot.run.app/mcp")
    monkeypatch.setattr(
        auth.CONFIG, "MCP_SERVICE_ACCOUNT",
        "lagniappe-mcp@pilot-project.iam.gserviceaccount.com",
    )
    config = {**auth.settings(), "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI}
    monkeypatch.setattr(auth, "_client_cache", None)
    monkeypatch.setattr(auth, "_certificate_cache", None)
    monkeypatch.setattr(auth, "_now", lambda now=None: now or NOW)
    monkeypatch.setattr(auth.Entities, "USER", Actor)
    actor = Actor()
    monkeypatch.setattr(
        auth.Entities,
        "fetch_one",
        lambda key, **kwargs: actor if key == actor.key else None,
    )
    rows, lock = {}, threading.RLock()

    def atomic(operation):
        with lock:
            staged = deepcopy(rows)
            records = SimpleNamespace(
                get=lambda name: deepcopy(staged.get(name)),
                put=lambda name, value: staged.__setitem__(name, deepcopy(dict(value))),
            )
            result = operation(records)
            rows.clear()
            rows.update(staged)
            return result

    monkeypatch.setattr(store, "atomic", atomic)
    monkeypatch.setattr(store, "read", lambda name: deepcopy(rows.get(name)))
    document = {
        "client_id": config["client_id"],
        "redirect_uris": [config["redirect_uri"]],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_methods_supported": ["none", "private_key_jwt"],
        "token_endpoint_auth_method": "private_key_jwt",
    }
    downloads = []

    def fetch(url, policy):
        downloads.append((url, policy))
        return SimpleNamespace(
            ok=True,
            http_status=200,
            redirect_count=0,
            body=json.dumps(document).encode(),
        )

    monkeypatch.setattr(auth, "fetch_user_content", fetch)
    request = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "resource": config["resource"],
        "response_type": "code",
        "state": "opaque-state",
        "code_challenge_method": "S256",
        "code_challenge": base64.urlsafe_b64encode(
            hashlib.sha256(VERIFIER.encode()).digest()
        )
        .decode()
        .rstrip("="),
    }
    return SimpleNamespace(
        config=config,
        actor=actor,
        rows=rows,
        document=document,
        downloads=downloads,
        request=request,
    )


def _code(oauth):
    pending = auth.begin_authorization(oauth.request)
    target, response = auth.consent(pending, oauth.actor, allow=True)
    assert target == oauth.config["redirect_uri"]
    assert response["state"] == "opaque-state"
    assert response["iss"] == oauth.config["issuer"]
    return {
        "grant_type": "authorization_code",
        "client_id": oauth.config["client_id"],
        "redirect_uri": target,
        "resource": oauth.config["resource"],
        "code": response["code"],
        "code_verifier": VERIFIER,
    }


def _refresh(oauth, token):
    return {
        "grant_type": "refresh_token",
        "client_id": oauth.config["client_id"],
        "resource": oauth.config["resource"],
        "refresh_token": token,
    }


def test_cimd_is_exact_bounded_cached_and_accepts_public_method_intersection(
    oauth, monkeypatch
):
    auth.client_metadata(oauth.config["client_id"])
    auth.client_metadata(oauth.config["client_id"])
    assert len(oauth.downloads) == 1
    url, policy = oauth.downloads[0]
    assert url == oauth.config["client_id"]
    assert (
        policy.max_redirects == 0
        and policy.max_bytes == 32768
        and policy.deadline == 10
    )
    with pytest.raises(auth.OAuthError):
        auth.client_metadata("https://attacker.test/client.json")
    assert len(oauth.downloads) == 1
    for field, value in (
        ("client_id", "https://attacker.test/client.json"),
        ("redirect_uris", ["https://chatgpt.com/wrong"]),
        ("token_endpoint_auth_methods_supported", ["private_key_jwt"]),
        ("token_endpoint_auth_methods_supported", "none"),
        ("grant_types", ["client_credentials"]),
        ("response_types", ["token"]),
    ):
        original = oauth.document[field]
        oauth.document[field] = value
        monkeypatch.setattr(auth, "_client_cache", None)
        with pytest.raises(auth.OAuthError):
            auth.client_metadata(oauth.config["client_id"])
        oauth.document[field] = original
    for response in (
        SimpleNamespace(ok=False, http_status=302, redirect_count=0, body=b""),
        SimpleNamespace(ok=True, http_status=200, redirect_count=1, body=b"{}"),
        SimpleNamespace(
            ok=True, http_status=200, redirect_count=0, body=b'{"a":1,"a":2}'
        ),
        SimpleNamespace(ok=True, http_status=200, redirect_count=0, body=b"not json"),
    ):
        monkeypatch.setattr(auth, "fetch_user_content", lambda *args, response=response: response)
        with pytest.raises(auth.OAuthError):
            auth.client_metadata(oauth.config["client_id"])


def test_authorization_requires_exact_bindings_state_and_s256(oauth):
    for field in oauth.request:
        invalid = {key: value for key, value in oauth.request.items() if key != field}
        with pytest.raises(auth.OAuthError):
            auth.begin_authorization(invalid)
    for field, value in (
        ("client_id", "https://attacker.test/client.json"),
        ("redirect_uri", oauth.config["redirect_uri"] + "/"),
        ("resource", oauth.config["resource"] + "/"),
        ("scope", "mcp:use admin"),
        ("state", ""),
        ("state", "s" * 1025),
        ("state", "line\nbreak"),
        ("code_challenge_method", "plain"),
        ("code_challenge", "a" * 42),
        ("response_type", "token"),
    ):
        with pytest.raises(auth.OAuthError):
            auth.begin_authorization({**oauth.request, field: value})
    assert not oauth.rows


@pytest.mark.parametrize("client", ["chatgpt", "codex"])
@pytest.mark.parametrize("scope", [None, "", "mcp:use"])
def test_authorization_without_scopes_preserves_consent_and_token_lifecycle(
    oauth, client, scope
):
    from config.remote_mcp import CODEX_CLIENT_ID

    existing = auth.exchange_token(_code(oauth))
    request = dict(oauth.request)
    if client == "codex":
        request.update(
            client_id=CODEX_CLIENT_ID, redirect_uri="http://127.0.0.1:38417/callback"
        )
    if scope is not None:
        request["scope"] = scope
    pending = auth.begin_authorization(request)
    target, denied = auth.consent(pending, oauth.actor, allow=False)
    assert target == request["redirect_uri"]
    assert denied == {
        "error": "access_denied",
        "state": request["state"],
        "iss": oauth.config["issuer"],
    }
    assert auth.authenticate_access(existing["access_token"])[0] is oauth.actor

    pending = auth.begin_authorization(request)
    target, allowed = auth.consent(pending, oauth.actor, allow=True)
    token = auth.exchange_token({
        "grant_type": "authorization_code",
        "client_id": request["client_id"],
        "redirect_uri": target,
        "resource": request["resource"],
        "code": allowed["code"],
        "code_verifier": VERIFIER,
    })
    assert "scope" not in token
    assert all("scope" not in row for row in oauth.rows.values())
    assert auth.authenticate_access(token["access_token"])[0] is oauth.actor
    refreshed = auth.exchange_token({
        "grant_type": "refresh_token",
        "client_id": request["client_id"],
        "resource": request["resource"],
        "refresh_token": token["refresh_token"],
    })
    assert "scope" not in refreshed
    assert refreshed["refresh_token"] != token["refresh_token"]
    assert auth.authenticate_access(refreshed["access_token"])[0] is oauth.actor


def test_existing_scoped_credentials_survive_scope_removal(oauth):
    parameters = _code(oauth)
    # Reproduce records issued before scope negotiation was removed, including
    # an outstanding authorization code and already-issued token family.
    for row in oauth.rows.values():
        row["scope"] = "mcp:use"
    token = auth.exchange_token(parameters)
    for row in oauth.rows.values():
        row["scope"] = "mcp:use"
    assert auth.authenticate_access(token["access_token"])[0] is oauth.actor
    refreshed = auth.exchange_token({
        **_refresh(oauth, token["refresh_token"]), "scope": "mcp:use"
    })
    assert "scope" not in refreshed
    assert auth.authenticate_access(refreshed["access_token"])[0] is oauth.actor
    assert auth.authenticate_access(token["access_token"])[0] is oauth.actor
    auth.connection_status(oauth.actor, revoke=True)
    for result in (token, refreshed):
        with pytest.raises(auth.OAuthError):
            auth.authenticate_access(result["access_token"])


def test_consent_deny_and_pending_replay_do_not_issue_tokens(oauth):
    pending = auth.begin_authorization(oauth.request)
    target, result = auth.consent(pending, oauth.actor, allow=False)
    assert target == oauth.config["redirect_uri"]
    assert result == {
        "error": "access_denied",
        "state": "opaque-state",
        "iss": oauth.config["issuer"],
    }
    assert len(oauth.rows) == 1
    with pytest.raises(auth.OAuthError):
        auth.consent(pending, oauth.actor, allow=True)
    pending = auth.begin_authorization(oauth.request)
    with pytest.raises(auth.OAuthError):
        auth.consent(pending, oauth.actor, allow=True, now=NOW + timedelta(hours=1))


def test_code_is_single_use_and_refresh_replay_revokes_the_family(oauth):
    parameters = _code(oauth)

    def redeem():
        try:
            return auth.exchange_token(parameters)
        except auth.OAuthError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: redeem(), range(2)))
    assert sum(result is not None for result in results) == 1
    first = next(result for result in results if result)
    assert first["expires_in"] == ACCESS_SECONDS
    second = auth.exchange_token(_refresh(oauth, first["refresh_token"]), now=NOW)
    assert first["refresh_token"] != second["refresh_token"]
    assert auth.authenticate_access(first["access_token"], now=NOW)[0] is oauth.actor
    assert auth.authenticate_access(second["access_token"], now=NOW)[0] is oauth.actor
    # Replay past the concurrent-refresh grace window revokes the entire family.
    after_grace = NOW + timedelta(seconds=REFRESH_RACE_GRACE_SECONDS)
    with pytest.raises(auth.OAuthError):
        auth.exchange_token(
            _refresh(oauth, first["refresh_token"]),
            now=after_grace,
        )
    for value in (first, second):
        with pytest.raises(auth.OAuthError):
            auth.authenticate_access(value["access_token"], now=after_grace)
    persisted = repr(oauth.rows)
    for secret in (
        parameters["code"],
        parameters["code_verifier"],
        first["access_token"],
        first["refresh_token"],
        second["refresh_token"],
    ):
        assert secret not in persisted


def test_concurrent_refresh_burst_succeeds_without_revoking_and_bounds_reuse(oauth):
    first = auth.exchange_token(_code(oauth), now=NOW)
    refresh_at = NOW + timedelta(minutes=30)

    def race_refresh():
        return auth.exchange_token(
            _refresh(oauth, first["refresh_token"]),
            now=refresh_at,
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        burst = list(pool.map(lambda _: race_refresh(), range(3)))

    assert len({entry["access_token"] for entry in burst}) == 3
    assert len({entry["refresh_token"] for entry in burst}) == 3
    for entry in burst:
        assert auth.authenticate_access(entry["access_token"], now=refresh_at)[0] is oauth.actor

    # Any sibling refresh token returned by the racing burst cleanly rotates to generation 3.
    third_at = refresh_at + timedelta(minutes=30)
    third = auth.exchange_token(_refresh(oauth, burst[-1]["refresh_token"]), now=third_at)
    assert auth.authenticate_access(third["access_token"], now=third_at)[0] is oauth.actor

    # Replaying an older generation (gen 1 when grant is gen 3) revokes immediately,
    # even within the grace window of the latest rotation.
    with pytest.raises(auth.OAuthError):
        auth.exchange_token(
            _refresh(oauth, first["refresh_token"]),
            now=third_at + timedelta(seconds=1),
        )
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(third["access_token"], now=third_at + timedelta(seconds=1))

    # Reusing a stale sibling gen-2 refresh token past the grace window also revokes the family.
    fresh = auth.exchange_token(_code(oauth), now=NOW)
    t0 = NOW + timedelta(minutes=2)
    gen2_a = auth.exchange_token(_refresh(oauth, fresh["refresh_token"]), now=t0)
    gen2_b = auth.exchange_token(
        _refresh(oauth, fresh["refresh_token"]),
        now=t0 + timedelta(seconds=2),
    )
    t1 = t0 + timedelta(minutes=5)
    gen3 = auth.exchange_token(_refresh(oauth, gen2_a["refresh_token"]), now=t1)
    assert auth.authenticate_access(gen3["access_token"], now=t1)[0] is oauth.actor
    with pytest.raises(auth.OAuthError):
        auth.exchange_token(
            _refresh(oauth, gen2_b["refresh_token"]),
            now=t1 + timedelta(seconds=REFRESH_RACE_GRACE_SECONDS),
        )
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(
            gen3["access_token"],
            now=t1 + timedelta(seconds=REFRESH_RACE_GRACE_SECONDS),
        )

    # Exceeding the concurrent-refresh burst cap revokes the grant family.
    capped = auth.exchange_token(_code(oauth), now=NOW)
    cap_time = NOW + timedelta(minutes=6)
    latest = auth.exchange_token(_refresh(oauth, capped["refresh_token"]), now=cap_time)
    for _ in range(REFRESH_RACE_MAX_MINTS):
        latest = auth.exchange_token(
            _refresh(oauth, capped["refresh_token"]),
            now=cap_time + timedelta(seconds=1),
        )
    with pytest.raises(auth.OAuthError):
        auth.exchange_token(
            _refresh(oauth, capped["refresh_token"]),
            now=cap_time + timedelta(seconds=2),
        )
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(latest["access_token"], now=cap_time + timedelta(seconds=2))


def test_token_exchange_rejects_wrong_binding_expiry_and_scope_expansion(oauth, monkeypatch):
    parameters = _code(oauth)
    for field, value in (
        ("code_verifier", "x" * 43),
        ("code_verifier", "v" * 42),
        ("resource", oauth.config["issuer"]),
        ("redirect_uri", "https://chatgpt.com/wrong"),
        ("client_id", "wrong"),
        ("scope", "mcp:use admin"),
    ):
        with pytest.raises(auth.OAuthError):
            auth.exchange_token({**parameters, field: value})
    with pytest.raises(auth.OAuthError):
        auth.exchange_token(parameters, now=NOW + timedelta(seconds=CODE_SECONDS))
    tokens = auth.exchange_token(parameters)
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(tokens["refresh_token"])
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(
            tokens["access_token"], now=NOW + timedelta(seconds=ACCESS_SECONDS)
        )
    refreshed = auth.exchange_token(
        _refresh(oauth, tokens["refresh_token"]), now=NOW + timedelta(days=29)
    )
    # RFC 8707: refresh_token may omit resource (inheriting the grant's bound resource),
    # while an explicit mismatched resource is still rejected with invalid_target.
    with pytest.raises(auth.OAuthError) as bad_refresh_target:
        auth.exchange_token(
            {**_refresh(oauth, refreshed["refresh_token"]), "resource": oauth.config["issuer"]},
            now=NOW + timedelta(days=29, minutes=1),
        )
    assert bad_refresh_target.value.code == "invalid_target"
    refreshed_without_resource = auth.exchange_token(
        {
            "grant_type": "refresh_token",
            "client_id": oauth.config["client_id"],
            "refresh_token": refreshed["refresh_token"],
        },
        now=NOW + timedelta(days=29, minutes=2),
    )
    assert auth.authenticate_access(
        refreshed_without_resource["access_token"],
        now=NOW + timedelta(days=29, minutes=3),
    )[0] is oauth.actor
    with pytest.raises(auth.OAuthError):
        auth.exchange_token(
            _refresh(oauth, refreshed_without_resource["refresh_token"]),
            now=NOW + timedelta(seconds=REFRESH_SECONDS),
        )
    oauth.actor.is_active = False
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(tokens["access_token"])
    oauth.actor.is_active = True
    monkeypatch.setattr(auth.CONFIG, "MCP_RESOURCE", "https://changed.run.app/mcp")
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(tokens["access_token"])


def test_oauth_user_and_workload_identity_are_both_required(oauth, monkeypatch):
    tokens = auth.exchange_token(_code(oauth))
    claims = {
        "iss": "https://accounts.google.com",
        "aud": oauth.config["issuer"] + "/api/v1",
        "email": oauth.config["service_account"],
        "email_verified": True,
        "sub": "123456789",
    }
    calls = []

    def verify(token, request, audience):
        calls.append((token, audience))
        return claims

    monkeypatch.setattr(auth.id_token, "verify_oauth2_token", verify)
    assert (
        auth.authenticate_envelope("workload-proof", tokens["access_token"])[0]
        is oauth.actor
    )
    assert calls == [("workload-proof", oauth.config["issuer"] + "/api/v1")]
    for field, value in (
        ("iss", "wrong"),
        ("aud", "wrong"),
        ("email", "other@example.com"),
        ("email_verified", False),
        ("sub", ""),
    ):
        original = claims[field]
        claims[field] = value
        with pytest.raises(auth.OAuthError):
            auth.authenticate_envelope("workload-proof", tokens["access_token"])
        claims[field] = original
    oauth.actor.is_public = True
    assert auth.eligible_user(oauth.actor) is False
    with pytest.raises(auth.OAuthError):
        auth.authenticate_envelope("workload-proof", tokens["access_token"])
    oauth.actor.is_public = False
    monkeypatch.setattr(auth.CONFIG, "EXTERNAL_AI_ENABLED", False)
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(tokens["access_token"])


def test_workload_certificates_are_bounded_cached_and_fail_closed(monkeypatch):
    monkeypatch.setattr(auth, "_certificate_cache", None)
    clock = [100.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: clock[0])
    downloads = []
    response = SimpleNamespace(
        ok=True, http_status=200, redirect_count=0, body=b'{"key":"public-certificate"}'
    )

    def fetch(url, policy):
        downloads.append((url, policy))
        return response

    monkeypatch.setattr(auth, "fetch_user_content", fetch)
    for url, method in (
        ("https://attacker.test/certs", "GET"),
        (auth._CERTIFICATE_URL, "POST"),
    ):
        with pytest.raises(auth.OAuthError):
            auth._certificate_request(url, method)
    assert not downloads
    assert auth._certificate_request(auth._CERTIFICATE_URL).data == response.body
    assert auth._certificate_request(auth._CERTIFICATE_URL).status == 200
    assert len(downloads) == 1
    url, policy = downloads[0]
    assert url == "https://www.googleapis.com/oauth2/v1/certs"
    assert policy.max_bytes == 65536 and policy.max_redirects == 0
    assert (policy.connect_timeout, policy.read_timeout, policy.deadline) == (2, 3, 5)

    clock[0] += 300
    response = SimpleNamespace(ok=False, http_status=503, redirect_count=0, body=b"")
    with pytest.raises(auth.OAuthError):
        auth._certificate_request(auth._CERTIFICATE_URL)
    with pytest.raises(auth.OAuthError):
        auth._certificate_request(auth._CERTIFICATE_URL)
    assert len(downloads) == 2  # No stale keys and no repeated fetch on failure.
    clock[0] += 5
    response = SimpleNamespace(
        ok=True,
        http_status=200,
        redirect_count=0,
        body=b'{"next":"rotated-certificate"}',
    )
    assert auth._certificate_request(auth._CERTIFICATE_URL).data == response.body
    assert len(downloads) == 3
    for body in (b"not json", b'{"key":"a","key":"b"}', b'{"key":null}', b"{}"):
        clock[0] += 300
        response = SimpleNamespace(
            ok=True, http_status=200, redirect_count=0, body=body
        )
        with pytest.raises(auth.OAuthError):
            auth._certificate_request(auth._CERTIFICATE_URL)


def test_cached_certificates_still_verify_each_signature_and_user_grant(
    oauth, monkeypatch
):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from google.auth import crypt, jwt

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    signer = crypt.RSASigner(key, key_id="pilot-certificate")
    public_key = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    calls = []

    def fetch(url, policy):
        calls.append(url)
        return SimpleNamespace(
            ok=True,
            http_status=200,
            redirect_count=0,
            body=json.dumps({signer.key_id: public_key}).encode(),
        )

    tokens = auth.exchange_token(_code(oauth))
    monkeypatch.setattr(auth, "fetch_user_content", fetch)
    timestamp = int(datetime.now(UTC).timestamp())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": oauth.config["issuer"] + "/api/v1",
        "email": oauth.config["service_account"],
        "email_verified": True,
        "sub": "123456789",
        "iat": timestamp - 1,
        "exp": timestamp + 300,
    }
    workload = jwt.encode(signer, claims).decode()
    assert (
        auth.authenticate_envelope(workload, tokens["access_token"])[0] is oauth.actor
    )
    assert (
        auth.authenticate_envelope(workload, tokens["access_token"])[0] is oauth.actor
    )
    for field, value in (
        ("aud", "wrong"),
        ("email", "other@example.com"),
        ("exp", timestamp - 1),
    ):
        invalid = jwt.encode(signer, {**claims, field: value}).decode()
        with pytest.raises(auth.OAuthError):
            auth.authenticate_envelope(invalid, tokens["access_token"])
    header, payload, signature = workload.split(".")
    tampered = ".".join(
        (header, payload, ("A" if signature[0] != "A" else "B") + signature[1:])
    )
    with pytest.raises(auth.OAuthError):
        auth.authenticate_envelope(tampered, tokens["access_token"])
    auth.connection_status(oauth.actor, revoke=True)
    with pytest.raises(auth.OAuthError):
        auth.authenticate_envelope(workload, tokens["access_token"])
    assert calls == [auth._CERTIFICATE_URL]


def test_oauth_outcomes_log_only_closed_categories_after_workload_verification(oauth, monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr(auth.LOGGER.handlers[0], "stream", output)
    claims = {
        "iss": "https://accounts.google.com", "aud": oauth.config["issuer"] + "/api/v1",
        "email": oauth.config["service_account"], "email_verified": True, "sub": "123456789",
    }
    monkeypatch.setattr(auth.id_token, "verify_oauth2_token", lambda *args, **kwargs: claims)
    opaque_user_token = "lgmo_a_" + "x" * 43
    with pytest.raises(auth.OAuthError):
        auth.authenticate_envelope("private-workload-proof", opaque_user_token)
    assert [json.loads(line) for line in output.getvalue().splitlines()] == [{
        "severity": "INFO", "event": "remote_mcp_auth", "outcome": "workload_verified",
    }]

    claims["email"] = "wrong-service@example.com"
    with pytest.raises(auth.OAuthError):
        auth.authenticate_envelope("private-workload-proof", opaque_user_token)
    auth.log_outcome(opaque_user_token)
    auth.log_outcome("https://private.example/secret")
    auth.log_outcome({"unexpected": "private-value"})
    assert len(output.getvalue().splitlines()) == 1
    auth.log_outcome("invalid_grant")
    assert json.loads(output.getvalue().splitlines()[-1])["outcome"] == "invalid_grant"
    assert auth.LOGGER.propagate is False


def test_revocation_is_private_and_reconnect_replaces_only_the_old_family(oauth):
    old = auth.exchange_token(_code(oauth))
    new = auth.exchange_token(_code(oauth))
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(old["access_token"])
    auth.revoke_token(old["refresh_token"], oauth.config["client_id"])
    auth.revoke_token("unknown", oauth.config["client_id"])
    assert auth.authenticate_access(new["access_token"])[0] is oauth.actor
    assert auth.connection_status(oauth.actor)["active"]
    assert not auth.connection_status(oauth.actor, revoke=True)["active"]
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(new["access_token"])


def test_oauth_store_uses_one_transaction_and_unindexed_records(monkeypatch):
    from google.cloud.datastore import Key

    puts, reads = [], []

    class Transaction:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def put(self, value):
            puts.append(value)

    transaction = Transaction()
    datastore = SimpleNamespace(
        transaction=lambda: transaction,
        get=lambda key, **kwargs: reads.append(kwargs["transaction"]),
    )
    monkeypatch.setattr(store, "DATA", SimpleNamespace(datastore=datastore))
    monkeypatch.setattr(
        store,
        "create_named_key",
        lambda kind, name: Key(kind, name, project="test-project"),
    )

    def change(records):
        records.get("c-digest")
        records.put("c-digest", {"user": "user-key", "expires_at": NOW})

    store.atomic(change)
    assert reads == [transaction]
    assert puts[0].key.name == "c-digest"
    assert set(puts[0].exclude_from_indexes) == {"user", "expires_at"}


def test_oauth_secrets_are_redacted_from_diagnostics():
    from lagniappe.core.exceptions.request import sanitize_error_context

    value = {
        "message": "rejected lgmo_a_" + "s" * 43,
        "state": "secret-state",
        "code_verifier": VERIFIER,
        "X-Lagniappe-MCP-Token": "secret",
        "assignment": "code_verifier=pkce-verifier state=oauth-state code_challenge=pkce-challenge",
        "quoted": "{'code_verifier': 'quoted-verifier', 'state': 'quoted-state'}",
        "http.url": "https://lagniappe.test/oauth/authorize?state=url-state&code_challenge=url-challenge",
        "url.full": "https://lagniappe.test/oauth/authorize?state=full-url-state",
        "http.query": "state=query-state&code_challenge=query-challenge",
    }
    sanitized = repr(sanitize_error_context(value))
    assert "secret-state" not in sanitized and VERIFIER not in sanitized
    assert "lgmo_a_" not in sanitized
    for secret in (
        "pkce-verifier",
        "oauth-state",
        "pkce-challenge",
        "quoted-verifier",
        "quoted-state",
        "url-state",
        "url-challenge",
        "query-state",
        "query-challenge",
    ):
        assert secret not in sanitized


def test_codex_loopback_grants_coexist_and_cannot_cross_clients(oauth):
    from config.remote_mcp import CODEX_CLIENT_ID

    request = {
        **oauth.request,
        "client_id": CODEX_CLIENT_ID,
        "redirect_uri": "http://127.0.0.1:54321/callback",
    }
    chatgpt = auth.exchange_token(_code(oauth))
    downloads_before = len(oauth.downloads)
    pending = auth.begin_authorization(request)
    target, response = auth.consent(pending, oauth.actor, allow=True)
    assert target == request["redirect_uri"]
    assert response["iss"] == oauth.config["issuer"]
    assert len(oauth.downloads) == downloads_before  # pre-registered, no CIMD fetch
    exchange = {
        "grant_type": "authorization_code", "client_id": CODEX_CLIENT_ID,
        "redirect_uri": target, "resource": oauth.config["resource"],
        "code": response["code"], "code_verifier": VERIFIER,
    }
    for replacement in (
        {"client_id": oauth.config["client_id"]},
        {"redirect_uri": "http://127.0.0.1:54322/callback"},
        {"code_verifier": "x" * 43},
    ):
        with pytest.raises(auth.OAuthError):
            auth.exchange_token({**exchange, **replacement})
    codex = auth.exchange_token(exchange)
    for tokens in (chatgpt, codex):
        assert auth.authenticate_access(tokens["access_token"])[0] is oauth.actor
    assert auth.connection_status(oauth.actor)["active"]
    assert auth.connection_status(oauth.actor, client_id=CODEX_CLIENT_ID)["active"]
    # A wrong client's refresh or revoke must not affect either grant.
    with pytest.raises(auth.OAuthError):
        auth.exchange_token(_refresh(oauth, codex["refresh_token"]))
    auth.revoke_token(codex["access_token"], oauth.config["client_id"])
    assert auth.authenticate_access(codex["access_token"])[0] is oauth.actor
    rotated = auth.exchange_token({
        **_refresh(oauth, codex["refresh_token"]), "client_id": CODEX_CLIENT_ID,
    })
    auth.connection_status(oauth.actor, client_id=CODEX_CLIENT_ID, revoke=True)
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(rotated["access_token"])
    assert auth.authenticate_access(chatgpt["access_token"])[0] is oauth.actor
    with pytest.raises(auth.OAuthError):
        auth.begin_authorization({**request, "client_id": "unregistered"})


def test_antigravity_cimd_grants_coexist_with_chatgpt_and_codex(oauth, monkeypatch):
    from config.remote_mcp import ANTIGRAVITY_CLIENT_ID, ANTIGRAVITY_REDIRECT_URI

    documents = {
        oauth.config["client_id"]: oauth.document,
        ANTIGRAVITY_CLIENT_ID: {
            "client_id": ANTIGRAVITY_CLIENT_ID,
            "redirect_uris": [ANTIGRAVITY_REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    }

    def fetch(url, policy):
        oauth.downloads.append((url, policy))
        return SimpleNamespace(
            ok=True,
            http_status=200,
            redirect_count=0,
            body=json.dumps(documents[url]).encode(),
        )

    monkeypatch.setattr(auth, "fetch_user_content", fetch)
    chatgpt = auth.exchange_token(_code(oauth))
    request = {
        **oauth.request,
        "client_id": ANTIGRAVITY_CLIENT_ID,
        "redirect_uri": ANTIGRAVITY_REDIRECT_URI,
    }
    pending = auth.begin_authorization(request)
    target, response = auth.consent(pending, oauth.actor, allow=True)
    assert target == ANTIGRAVITY_REDIRECT_URI
    assert response["iss"] == oauth.config["issuer"]
    antigravity = auth.exchange_token({
        "grant_type": "authorization_code",
        "client_id": ANTIGRAVITY_CLIENT_ID,
        "redirect_uri": target,
        "resource": oauth.config["resource"],
        "code": response["code"],
        "code_verifier": VERIFIER,
    })
    assert auth.authenticate_access(antigravity["access_token"])[0] is oauth.actor
    assert auth.authenticate_access(chatgpt["access_token"])[0] is oauth.actor
    assert auth.connection_status(oauth.actor)["active"]
    assert auth.connection_status(oauth.actor, client_id=ANTIGRAVITY_CLIENT_ID)["active"]
    # Revoking Antigravity leaves ChatGPT intact.
    auth.connection_status(oauth.actor, client_id=ANTIGRAVITY_CLIENT_ID, revoke=True)
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(antigravity["access_token"])
    assert auth.authenticate_access(chatgpt["access_token"])[0] is oauth.actor


def test_claude_claude_code_and_pi_cimd_grants_coexist_and_verify_published_redirects(
    oauth, monkeypatch
):
    from config.remote_mcp import (
        CLAUDE_CLIENT_ID,
        CLAUDE_CODE_CLIENT_ID,
        CLAUDE_REDIRECT_URI,
        PI_CLIENT_ID,
    )

    documents = {
        oauth.config["client_id"]: oauth.document,
        CLAUDE_CLIENT_ID: {
            "client_id": CLAUDE_CLIENT_ID,
            "redirect_uris": [CLAUDE_REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        CLAUDE_CODE_CLIENT_ID: {
            "client_id": CLAUDE_CODE_CLIENT_ID,
            "redirect_uris": ["http://localhost/callback", "http://127.0.0.1/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        PI_CLIENT_ID: {
            "client_id": PI_CLIENT_ID,
            "redirect_uris": ["http://127.0.0.1/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "token_endpoint_auth_methods_supported": ["none"],
        },
    }

    def fetch(url, policy):
        oauth.downloads.append((url, policy))
        return SimpleNamespace(
            ok=True,
            http_status=200,
            redirect_count=0,
            body=json.dumps(documents[url]).encode(),
        )

    monkeypatch.setattr(auth, "fetch_user_content", fetch)
    chatgpt = auth.exchange_token(_code(oauth))

    # Pi's mocked CIMD above omits localhost, so localhost must be rejected while 127.0.0.1 succeeds.
    with pytest.raises(auth.OAuthError) as missing_localhost:
        auth.begin_authorization({
            **oauth.request,
            "client_id": PI_CLIENT_ID,
            "redirect_uri": "http://localhost:8765/callback",
        })
    assert missing_localhost.value.code == "invalid_client"

    issued = {}
    for client_id, redirect_uri in (
        (CLAUDE_CLIENT_ID, CLAUDE_REDIRECT_URI),
        (CLAUDE_CODE_CLIENT_ID, "http://localhost:54321/callback"),
        (PI_CLIENT_ID, "http://127.0.0.1:8765/callback"),
    ):
        pending = auth.begin_authorization({
            **oauth.request,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
        })
        target, response = auth.consent(pending, oauth.actor, allow=True)
        assert target == redirect_uri
        assert response["iss"] == oauth.config["issuer"]
        tokens = auth.exchange_token({
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": target,
            "resource": oauth.config["resource"],
            "code": response["code"],
            "code_verifier": VERIFIER,
        })
        assert auth.authenticate_access(tokens["access_token"])[0] is oauth.actor
        assert auth.connection_status(oauth.actor, client_id=client_id)["active"]
        issued[client_id] = tokens

    # Revoking Claude Code leaves ChatGPT, Claude, and Pi active.
    auth.connection_status(oauth.actor, client_id=CLAUDE_CODE_CLIENT_ID, revoke=True)
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(issued[CLAUDE_CODE_CLIENT_ID]["access_token"])
    assert auth.authenticate_access(chatgpt["access_token"])[0] is oauth.actor
    assert auth.authenticate_access(issued[CLAUDE_CLIENT_ID]["access_token"])[0] is oauth.actor
    assert auth.authenticate_access(issued[PI_CLIENT_ID]["access_token"])[0] is oauth.actor


def test_site_policy_blocks_existing_oauth_grants_and_public_users(oauth, monkeypatch):
    tokens = auth.exchange_token(_code(oauth))
    for flag in ("AI_ENABLED", "EXTERNAL_AI_ENABLED"):
        with monkeypatch.context() as policy:
            policy.setattr(auth.CONFIG, flag, False)
            with pytest.raises(auth.OAuthError):
                auth.authenticate_access(tokens["access_token"])
            with pytest.raises(auth.OAuthError):
                auth.begin_authorization(oauth.request)
    assert auth.authenticate_access(tokens["access_token"])[0] is oauth.actor
    oauth.actor.email = "new-user@example.test"
    assert auth.eligible_user(oauth.actor)
    oauth.actor.is_public = True
    assert not auth.eligible_user(oauth.actor)
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(tokens["access_token"])
    with pytest.raises(auth.OAuthError):
        auth.exchange_token(_refresh(oauth, tokens["refresh_token"]))
    pending = auth.begin_authorization(oauth.request)
    with pytest.raises(auth.OAuthError):
        auth.consent(pending, oauth.actor, allow=True)
    oauth.actor.is_public = False
    assert auth.authenticate_access(tokens["access_token"])[0] is oauth.actor
