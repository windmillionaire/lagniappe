"""Small end-user command surface for the standalone adapter."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from datetime import datetime, timezone
import getpass
import os
from pathlib import Path
import stat
import sys
from typing import Any
import warnings

from . import __version__
from .catalog import ACTOR_SCHEMA
from .codex_config import (
    console_executable,
    inspect_entry,
    install_entry,
    manual_entry,
    remove_entry,
    render_entry,
    server_name,
)
from .configuration import ConnectionConfig, from_environment
from .errors import AdapterError, ConfigurationError
from .limits import MAX_STDERR_BYTES
from .profiles import (
    PROFILE_SCHEMA_VERSION,
    connection_from_profile,
    delete_profile,
    load_profile_snapshot,
    save_profile,
    validate_profile_name,
)
from .rest import RESTClient
from .schema import validate_value
from .server import check, serve
from .url_security import normalize_site_url


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/cli.py::_parser
class _BoundedArgumentParser(argparse.ArgumentParser):
    """Route parser failures through the same bounded redacted diagnostic."""

    def error(self, _message: str) -> None:
        # argparse normally repeats unknown argument values verbatim.  That is
        # inappropriate for a credential-handling command because an accidental
        # ``--api-key SECRET`` must not copy SECRET into stderr.
        raise ConfigurationError(
            "invalid_arguments",
            "Command arguments are invalid; run lagniappe-mcp --help.",
        )


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_cli_source_modes_and_lowercase_profile_names_are_exact
def _parser() -> argparse.ArgumentParser:
    parser = _BoundedArgumentParser(prog="lagniappe-mcp")
    parser.add_argument(
        "--version", action="version", version=f"lagniappe-mcp {__version__}"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name in ("serve", "check"):
        command = commands.add_parser(name)
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument("--profile", type=validate_profile_name)
        source.add_argument("--from-env", action="store_true")
        command.add_argument("--allowed-root", action="append", default=[])

    configure = commands.add_parser("configure")
    configure_clients = configure.add_subparsers(dest="client", required=True)
    codex = configure_clients.add_parser("codex")
    codex.add_argument("--url")
    codex.add_argument("--profile", required=True, type=validate_profile_name)
    codex.add_argument("--allowed-root", action="append", default=[])
    codex.add_argument("--remove", action="store_true")
    codex.add_argument(
        "--trial-required",
        action="store_true",
        help="make the server mandatory only in an isolated controlled trial",
    )

    credentials = commands.add_parser("credentials")
    credential_action = credentials.add_subparsers(
        dest="credential_action", required=True
    )
    for action in ("set", "remove"):
        subcommand = credential_action.add_parser(action)
        subcommand.add_argument("--profile", required=True, type=validate_profile_name)

    profile = commands.add_parser("profile")
    profile_action = profile.add_subparsers(dest="profile_action", required=True)
    remove = profile_action.add_parser("remove")
    remove.add_argument("--profile", required=True, type=validate_profile_name)
    return parser


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_cli_source_modes_and_lowercase_profile_names_are_exact
def _connection(args: argparse.Namespace) -> ConnectionConfig:
    if args.profile:
        if args.allowed_root:
            raise ConfigurationError(
                "invalid_arguments",
                "--allowed-root is accepted only with --from-env.",
            )
        return connection_from_profile(args.profile)
    roots = [_safe_root(value) for value in args.allowed_root]
    if len(set(roots)) != len(roots):
        raise ConfigurationError(
            "duplicate_root", "Each allowed root may be configured only once."
        )
    return from_environment(roots)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/cli.py::_configure_codex
def _safe_root(raw: str) -> str:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if any(part == ".." for part in candidate.parts):
        raise ConfigurationError(
            "unsafe_root", "Allowed roots cannot contain parent traversal."
        )
    candidate = Path(os.path.normpath(candidate))
    current = Path(candidate.anchor)
    try:
        for part in candidate.parts[1:]:
            current = current / part
            details = current.lstat()
            if stat.S_ISLNK(details.st_mode):
                raise ConfigurationError(
                    "unsafe_root", "Allowed roots cannot contain symbolic links."
                )
        details = candidate.stat(follow_symlinks=False)
    except FileNotFoundError as error:
        raise ConfigurationError(
            "invalid_root", "Every allowed root must already exist."
        ) from error
    except ConfigurationError:
        raise
    except OSError as error:
        raise ConfigurationError(
            "unsafe_root", "An allowed root could not be inspected safely."
        ) from error
    if not stat.S_ISDIR(details.st_mode):
        raise ConfigurationError(
            "invalid_root", "Every allowed root must be a directory."
        )
    return str(candidate)


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/cli.py::_configure_codex
def _eligible_actor(
    actor: Any, *, expected_hash: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_value(ACTOR_SCHEMA, actor, phase="actor")
    user = actor["user"]
    credential = actor["credential"]
    if credential.get("active") is not True:
        raise ConfigurationError(
            "invalid_credentials", "The API credential is not active."
        )
    expiry = credential.get("expires_at")
    if not isinstance(expiry, str):
        raise ConfigurationError(
            "invalid_credentials", "The API credential has no valid expiry."
        )
    try:
        expires_at = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except ValueError as error:
        raise ConfigurationError(
            "invalid_credentials", "The API credential expiry is malformed."
        ) from error
    if expires_at.tzinfo is None or expires_at <= datetime.now(timezone.utc):
        raise ConfigurationError(
            "invalid_credentials", "The API credential is expired."
        )
    if expected_hash is not None and user.get("hash") != expected_hash:
        raise ConfigurationError(
            "actor_mismatch", "The replacement credential belongs to a different actor."
        )
    return user, credential


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/cli.py::_configure_codex
async def _validate_key(
    site_url: str, key: str, *, expected_hash: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    config = ConnectionConfig(authority=normalize_site_url(site_url), api_key=key)
    async with RESTClient(config) as rest:
        actor, _request_id = await rest.request_json("GET", "me", max_bytes=128 * 1024)
    return _eligible_actor(actor, expected_hash=expected_hash)


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_api_key_prompt_fails_closed_when_no_echo_is_unavailable
def _prompt_key() -> str:
    try:
        # ``getpass`` normally warns and then reads from an echoed stream when
        # terminal echo cannot be disabled.  A credential prompt must fail
        # closed before that fallback can read any input.
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("Lagniappe API key: ").strip()
    except (getpass.GetPassWarning, EOFError, OSError) as error:
        raise ConfigurationError(
            "secure_prompt_unavailable",
            "A protected no-echo credential prompt is unavailable; re-run in an interactive terminal.",
        ) from error
    if not key:
        raise ConfigurationError("empty_credentials", "The API key cannot be empty.")
    return key


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/cli.py::_configure_codex
def _confirm(message: str) -> None:
    if not sys.stdin.isatty():
        raise ConfigurationError(
            "confirmation_required", f"{message} Re-run in an interactive terminal."
        )
    answer = input(f"{message} [y/N] ").strip().casefold()
    if answer not in {"y", "yes"}:
        raise ConfigurationError("cancelled", "No local configuration was changed.")


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_configure_rolls_back_new_codex_entry_when_profile_save_fails
# @tests tests_unit/test_033_mcp_adapter.py::test_configure_idempotently_preserves_existing_allowed_roots
# @tests tests_unit/test_033_mcp_adapter.py::test_configure_remove_falls_back_without_claiming_manual_removal
# @tests tests_unit/test_033_mcp_adapter.py::test_configure_trial_required_uses_owned_required_entry
# @tests tests_unit/test_033_mcp_adapter.py::test_configure_manual_fallback_preserves_a_changed_manual_identity
# @tests tests_unit/test_033_mcp_adapter.py::test_configure_save_failure_restores_prior_required_entry
# @tests tests_unit/test_033_mcp_adapter.py::test_configure_remove_rejects_configuration_arguments
async def _configure_codex(args: argparse.Namespace) -> int:
    name = args.profile
    trial_required = bool(getattr(args, "trial_required", False))
    if args.remove:
        if args.url or args.allowed_root or trial_required:
            raise ConfigurationError(
                "invalid_arguments",
                "--remove cannot be combined with --url, --allowed-root, or "
                "--trial-required.",
            )
        profile, profile_snapshot = load_profile_snapshot(name)
        client = (
            profile.get("client") if isinstance(profile.get("client"), dict) else {}
        )
        fingerprint = client.get("fingerprint")
        registered = client.get("registered") is True
        if not registered and client.get("mode") == "manual" and isinstance(
            fingerprint, str
        ):
            try:
                _text, _parsed, match, _snapshot = inspect_entry(
                    name, expected_fingerprint=fingerprint
                )
            except ConfigurationError as error:
                if error.code != "manual_configuration_required":
                    raise
                print(
                    manual_entry(
                        name,
                        client.get("executable") or "lagniappe-mcp",
                        remove=True,
                        required=client.get("required") is True,
                    )
                )
                return 0
            if match is None:
                profile["client"] = {
                    **client,
                    "registered": False,
                    "fingerprint": None,
                }
                save_profile(profile, expected_snapshot=profile_snapshot)
                return 0
            registered = True
        if not registered:
            return 0
        _confirm(
            f"Remove the owned {server_name(name)} entry from user Codex configuration?"
        )
        if not isinstance(fingerprint, str):
            raise ConfigurationError(
                "foreign_server",
                "The Codex entry ownership fingerprint is missing.",
            )
        try:
            remove_entry(name, expected_fingerprint=fingerprint)
        except ConfigurationError as error:
            if error.code != "manual_configuration_required":
                raise
            # Do not claim the entry was removed or unlock profile deletion.
            # A later rerun verifies the user's manual removal before updating
            # the profile's ownership state.
            print(
                manual_entry(
                    name,
                    client.get("executable") or "",
                    remove=True,
                    required=client.get("required") is True,
                )
            )
            return 0
        profile["client"] = {**client, "registered": False, "fingerprint": None}
        save_profile(profile, expected_snapshot=profile_snapshot)
        return 0

    if not args.url:
        raise ConfigurationError(
            "invalid_arguments",
            "configure codex requires --url unless --remove is used.",
        )
    authority = normalize_site_url(args.url)
    try:
        existing, profile_snapshot = load_profile_snapshot(name)
    except ConfigurationError as error:
        if error.code != "profile_not_found":
            raise
        existing = None
        profile_snapshot = None
    if existing is not None and existing["site_url"] != authority.origin:
        raise ConfigurationError(
            "profile_site_conflict",
            "This profile already belongs to a different Lagniappe site.",
        )
    if existing is not None:
        key = existing.get("api_key")
        if not isinstance(key, str) or not key:
            raise ConfigurationError(
                "missing_credentials",
                "Set this profile's credential before reconfiguring it.",
            )
    else:
        key = _prompt_key()
    expected_hash = None
    if existing and isinstance(existing.get("actor"), dict):
        expected_hash = existing["actor"].get("hash")
    user, credential = await _validate_key(
        authority.origin, key, expected_hash=expected_hash
    )
    root_arguments = args.allowed_root
    if existing is not None and not root_arguments:
        root_arguments = list(existing["allowed_roots"])
    roots = [_safe_root(value) for value in root_arguments]
    if len(set(roots)) != len(roots):
        raise ConfigurationError(
            "duplicate_root", "Each allowed root may be configured only once."
        )
    executable = console_executable()
    prior_client = (
        existing.get("client")
        if existing and isinstance(existing.get("client"), dict)
        else {}
    )
    prior_fingerprint = prior_client.get("fingerprint")
    expected_fingerprint = (
        prior_fingerprint if isinstance(prior_fingerprint, str) else None
    )
    block, proposed_fingerprint = render_entry(
        name,
        executable,
        required=trial_required,
    )
    print(
        f"Profile {name}: site={authority.origin}, allowed_roots={len(roots)}, "
        f"Codex server={server_name(name)}, credential_expires={credential['expires_at']}"
    )
    print("Allowed roots:")
    if roots:
        for root in roots:
            print(f"  - {root}")
    else:
        print("  (none)")
    print("Proposed user Codex entry:")
    print(block, end="")
    _confirm("Save the owner-only profile and update user Codex configuration?")
    client = {
        "name": server_name(name),
        "mode": "automatic",
        "registered": True,
        "fingerprint": proposed_fingerprint,
        "executable": executable,
        "required": trial_required,
    }
    profile = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "name": name,
        "site_url": authority.origin,
        "api_key": key,
        "allowed_roots": roots,
        "actor": {"name": user["name"], "hash": user["hash"]},
        "credential": {
            "expires_at": credential["expires_at"],
            "display_prefix": credential.get("display_prefix"),
            "generation": credential.get("generation"),
        },
        "client": client,
    }
    try:
        fingerprint = install_entry(
            name,
            executable,
            expected_fingerprint=expected_fingerprint,
            required=trial_required,
        )
        client["fingerprint"] = fingerprint
    except ConfigurationError as error:
        if error.code != "manual_configuration_required":
            raise
        prior_identity_may_remain = (
            existing is not None
            and expected_fingerprint is not None
            and (
                prior_client.get("registered") is True
                or expected_fingerprint != proposed_fingerprint
            )
        )
        if prior_identity_may_remain:
            # A failed safe edit can leave the prior automatic or manually
            # installed entry in place. Never replace its only ownership
            # fingerprint with a different manual identity, and never demote a
            # registered entry without proving its removal. Keep the reviewed
            # profile unchanged and make removal converge first.
            raise ConfigurationError(
                "managed_entry_update_requires_removal",
                "The prior Codex entry state could not be changed safely; "
                "no profile or ownership metadata was changed. Run configure "
                "codex --remove for this profile before configuring the new entry.",
            ) from error
        print(manual_entry(name, executable, required=trial_required))
        client.update(
            {
                "mode": "manual",
                "registered": False,
                "fingerprint": proposed_fingerprint,
            }
        )
    try:
        save_profile(profile, expected_snapshot=profile_snapshot)
    except BaseException as save_error:
        if client["mode"] == "automatic":
            try:
                if (
                    prior_client.get("mode") == "automatic"
                    and prior_client.get("registered") is True
                    and isinstance(prior_client.get("fingerprint"), str)
                    and isinstance(prior_client.get("executable"), str)
                ):
                    install_entry(
                        name,
                        prior_client["executable"],
                        expected_fingerprint=client["fingerprint"],
                        required=prior_client.get("required") is True,
                    )
                else:
                    remove_entry(
                        name,
                        expected_fingerprint=client["fingerprint"],
                    )
            except BaseException as rollback_error:
                raise ConfigurationError(
                    "configuration_rollback_failed",
                    "Profile saving failed and the Codex entry could not be restored safely.",
                ) from rollback_error
        raise save_error
    return 0


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_local_credential_and_profile_removal_are_distinct_state_transitions
# @tests tests_unit/test_033_mcp_adapter.py::test_rejected_credential_replacement_preserves_the_saved_profile
# @tests tests_unit/test_033_mcp_adapter.py::test_removed_local_credential_takes_effect_only_in_a_new_process
async def _credentials(args: argparse.Namespace) -> int:
    profile, profile_snapshot = load_profile_snapshot(args.profile)
    if args.credential_action == "remove":
        _confirm(f"Remove only the saved credential from profile {args.profile}?")
        profile["api_key"] = None
        profile["credential"] = {}
        save_profile(profile, expected_snapshot=profile_snapshot)
        return 0
    key = _prompt_key()
    actor = profile["actor"] if isinstance(profile.get("actor"), dict) else {}
    user, credential = await _validate_key(
        profile["site_url"],
        key,
        expected_hash=actor.get("hash"),
    )
    _confirm(f"Replace the saved credential for profile {args.profile}?")
    profile["api_key"] = key
    profile["actor"] = {"name": user["name"], "hash": user["hash"]}
    profile["credential"] = {
        "expires_at": credential["expires_at"],
        "display_prefix": credential.get("display_prefix"),
        "generation": credential.get("generation"),
    }
    save_profile(profile, expected_snapshot=profile_snapshot)
    return 0


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/cli.py::_run
def _remove_profile(name: str) -> int:
    profile, profile_snapshot = load_profile_snapshot(name)
    client = profile.get("client") if isinstance(profile.get("client"), dict) else {}
    if client.get("registered") is True or client.get("fingerprint") is not None:
        raise ConfigurationError(
            "client_still_registered",
            "Verify removal of the profile's Codex entry before removing the profile.",
        )
    _confirm(f"Permanently remove profile {name} and its saved credential?")
    delete_profile(name, expected_snapshot=profile_snapshot)
    return 0


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_cli_entrypoint_bounds_errors_and_routes_commands
async def _run(args: argparse.Namespace) -> int:
    if args.command in {"serve", "check"}:
        config = _connection(args)
        if args.command == "serve":
            await serve(config)
            return 0
        await check(config)
        print(
            f"Lagniappe MCP {__version__}: compatible; actor=verified; "
            f"roots={len(config.allowed_roots)}"
        )
        return 0
    if args.command == "configure":
        return await _configure_codex(args)
    if args.command == "credentials":
        return await _credentials(args)
    if args.command == "profile" and args.profile_action == "remove":
        return _remove_profile(args.profile)
    raise ConfigurationError("invalid_arguments", "Unknown command.")


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/cli.py::main
def _only_broken_pipes(error: BaseException) -> bool:
    """Recognize task-group wrappers without hiding unrelated failures."""
    if isinstance(error, BrokenPipeError):
        return True
    if isinstance(error, BaseExceptionGroup):
        return bool(error.exceptions) and all(
            _only_broken_pipes(item) for item in error.exceptions
        )
    return False


# @testable false
# @covered-by clients/lagniappe_mcp/src/lagniappe_mcp/cli.py::main
def _silence_broken_stdio() -> None:
    """Prevent finalization noise after a known-broken MCP output pipe."""
    replacement: int | None = None
    try:
        replacement = os.open(os.devnull, os.O_WRONLY)
        for stream in (sys.stdout, sys.stderr):
            os.dup2(replacement, stream.fileno())
    except (AttributeError, OSError, ValueError):
        pass
    finally:
        if replacement is not None:
            with suppress(OSError):
                os.close(replacement)


# @testable true
# @pair mcp-adapter:product-contract
# @tests tests_unit/test_033_mcp_adapter.py::test_cli_entrypoint_bounds_errors_and_routes_commands
# @tests tests_unit/test_033_mcp_adapter.py::test_real_stdio_subprocess_broken_output_pipe_exits_without_diagnostics
def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        _silence_broken_stdio()
        return 0
    except AdapterError as error:
        diagnostic = error.render()
        # AdapterError is already capped more tightly; retain an explicit
        # command-boundary guard so future parser or rendering changes cannot
        # exceed the frozen stderr allowance.
        encoded = diagnostic.encode("utf-8", errors="replace")
        if len(encoded) > MAX_STDERR_BYTES:
            diagnostic = encoded[:MAX_STDERR_BYTES].decode(
                "utf-8", errors="ignore"
            )
        print(diagnostic, file=sys.stderr)
        return 1
    except Exception as error:
        if _only_broken_pipes(error):
            _silence_broken_stdio()
            return 0
        error = AdapterError(
            "adapter_failure",
            "The Lagniappe MCP command could not complete safely.",
        )
        print(error.render(), file=sys.stderr)
        return 1
