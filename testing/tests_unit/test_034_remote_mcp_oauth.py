"""Opaque OAuth transitions, exact client binding, and service identity."""

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import threading
from types import SimpleNamespace

import pytest

from config.remote_mcp import (
    ACCESS_SECONDS,
    CODE_SECONDS,
    REFRESH_SECONDS,
    CLIENT_ID,
    REDIRECT_URI,
)
from lagniappe.core.tools.auth import remote_mcp as auth
from lagniappe.core.tools.database import remote_mcp as store


pytestmark = pytest.mark.unit
NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)
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


# @matrix mcp-oauth : cimd validation
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
        monkeypatch.setattr(auth, "fetch_user_content", lambda *args: response)
        with pytest.raises(auth.OAuthError):
            auth.client_metadata(oauth.config["client_id"])


# @matrix mcp-oauth : authorization validation
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


# @matrix mcp-oauth : authorization consent token refresh validation
# @source lagniappe/core/tools/auth/remote_mcp.py::begin_authorization
# @source lagniappe/core/tools/auth/remote_mcp.py::consent
# @source lagniappe/core/tools/auth/remote_mcp.py::exchange_token
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


# @matrix mcp-oauth : authentication existing-grants refresh
# @source lagniappe/core/tools/auth/remote_mcp.py::exchange_token
# @source lagniappe/core/tools/auth/remote_mcp.py::authenticate_access
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


# @matrix mcp-oauth : consent transaction
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


# @matrix mcp-oauth : consent token pkce refresh replay transaction
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
    second = auth.exchange_token(_refresh(oauth, first["refresh_token"]))
    assert first["refresh_token"] != second["refresh_token"]
    assert auth.authenticate_access(first["access_token"])[0] is oauth.actor
    assert auth.authenticate_access(second["access_token"])[0] is oauth.actor
    with pytest.raises(auth.OAuthError):
        auth.exchange_token(_refresh(oauth, first["refresh_token"]))
    for value in (first, second):
        with pytest.raises(auth.OAuthError):
            auth.authenticate_access(value["access_token"])
    persisted = repr(oauth.rows)
    for secret in (
        parameters["code"],
        parameters["code_verifier"],
        first["access_token"],
        first["refresh_token"],
        second["refresh_token"],
    ):
        assert secret not in persisted


# @matrix mcp-oauth : token pkce refresh replay transaction authentication expiry revocation user-binding
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
    with pytest.raises(auth.OAuthError):
        auth.exchange_token(
            _refresh(oauth, refreshed["refresh_token"]),
            now=NOW + timedelta(seconds=REFRESH_SECONDS),
        )
    oauth.actor.is_active = False
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(tokens["access_token"])
    oauth.actor.is_active = True
    monkeypatch.setattr(auth.CONFIG, "MCP_RESOURCE", "https://changed.run.app/mcp")
    with pytest.raises(auth.OAuthError):
        auth.authenticate_access(tokens["access_token"])


# @matrix mcp-oauth : user-binding oidc audience service-identity token-separation authentication expiry revocation
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


# @matrix mcp-oauth : oidc certificate-cache
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


# @matrix mcp-oauth : oidc certificate-cache audience service-identity token-separation authentication revocation
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
    timestamp = int(datetime.now(timezone.utc).timestamp())
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


# @matrix mcp-oauth : observability privacy service-identity
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


# @matrix mcp-oauth : revocation reconnect privacy user-binding
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


# @matrix mcp-oauth : persistence transaction
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


# @matrix error-reporting : payload-bounds privacy redaction
# @source lagniappe/core/exceptions/request.py::sanitize_error_context
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


# @matrix mcp-oauth : authorization consent loopback token refresh revocation client-isolation
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


# @matrix mcp-oauth : site-policy existing-grants user-binding
# @source lagniappe/core/tools/auth/remote_mcp.py::authenticate_access
# @source lagniappe/core/tools/auth/remote_mcp.py::eligible_user
@pytest.mark.unit
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
