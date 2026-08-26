from pathlib import Path
import shlex
from urllib.parse import unquote, urlsplit
import webbrowser

from runner.context import setup_command
from installer import FORMATTER, wrap_text
from installer.errors import ProviderError
from .package_install import install_if_missing
from .utils import validate_input


REDIS_TLS_DOCUMENTATION_URL = (
    "https://redis.io/docs/latest/operate/rc/security/database-security/tls-ssl/"
)
REDIS_CLOUD_CONSOLE_URL = "https://cloud.redis.io/"


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_redis_connection_uses_shared_tls_settings_and_exits_on_failure
# @matrix setup : redis-connection redis-tls
def test_redis_connection(settings=None, *, exit_on_failure=True):
    """Test Redis connection."""
    from config import SETTINGS
    from config.redis import redis_client_kwargs, redis_tls_enabled

    f = FORMATTER.initialize()
    settings = settings or SETTINGS.APP
    client = None

    with f.yaspin(text=f.success("Test Redis connection")) as sp:
        install_if_missing(
            "redis",
            "Python client library used to test the same TLS and authenticated "
            "connection as Lagniappe; this does not install a Redis server",
        )
        import redis

        try:
            client = redis.Redis(
                **redis_client_kwargs(settings, socket_timeout=5)
            )
            client.ping()
            sp.ok(f.ok_glyph)
            return True
        except Exception as e:
            sp.write(f.error(f"Failed to connect to Redis.\n{e}"))
            if redis_tls_enabled(settings):
                sp.write(
                    f.warning(
                        "Confirm TLS is enabled in Redis Cloud, Mutual TLS is "
                        "unchecked, and config/files/redis_ca.pem is current."
                    )
                )
            else:
                sp.write(
                    f.warning(
                        "Confirm TLS is disabled in Redis Cloud for this "
                        "plaintext connection."
                    )
                )
            sp.fail(f.fail_glyph)
            if exit_on_failure:
                raise ProviderError("Redis connection validation failed.") from e
            return False
        finally:
            if client is not None:
                close = getattr(client, "close", None)
                if callable(close):
                    close()


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_redis_eviction_policy_instructions_require_confirmation
# @matrix setup : interactive-input operator-guidance redis
def eviction_policy_instructions():
    """Print eviction policy instructions."""
    from installer import FORMATTER

    f = FORMATTER.initialize()
    print(f"\n{f.warning('IMPORTANT REDIS CONFIGURATION:')}")
    print(
        f.info(
            wrap_text(
                "Please ensure your Redis Cloud database is configured with "
                "the following eviction policy:"
            )
        )
    )
    print(f"  • Data eviction policy: {f.success('volatile-ttl')}")
    print(
        f.info(
            wrap_text(
                "On the same Redis Cloud database details page, find "
                "Performance & Availability → Data eviction policy and "
                "select volatile-ttl."
            )
        )
    )
    print(
        f.info(
            wrap_text(
                "The selection is only pending until you click 'Review "
                "changes', review the confirmation modal, and click 'Confirm' "
                "or 'Confirm & pay' to save it."
            )
        )
    )
    print(
        f.info(
            wrap_text(
                "Wait for the pending-change indicator to clear, then verify "
                "the displayed Data eviction policy is still volatile-ttl."
            )
        )
    )
    print(
        f.info(
            wrap_text(
                "This policy helps manage memory by evicting keys with TTL when "
                "the memory limit is reached."
            )
        )
    )
    input(
        f"\n{f.warning('Press Enter only after Redis Cloud confirms the eviction policy...')}"
    )


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_redis_cloud_instructions_open_console_and_locate_credentials
# @matrix setup : browser operator-guidance plan-selection provider-region redis redis-tls
def redis_cloud_instructions():
    """Open Redis Cloud and guide database placement and credential copying."""
    from config import SETTINGS, constants

    f = FORMATTER.initialize()
    resource_region = str(
        SETTINGS.APP.get("RESOURCE_REGION") or constants.DEFAULT_RESOURCE_REGION
    ).strip()

    print(f"\n{f.info('Configure Redis Cloud')}")
    print(
        wrap_text(
            "Lagniappe uses a Redis Cloud database for search, cache, and "
            "synchronization state."
        )
    )
    print(f"Opening Redis Cloud:\n  {REDIS_CLOUD_CONSOLE_URL}")
    try:
        webbrowser.open_new_tab(REDIS_CLOUD_CONSOLE_URL)
    except webbrowser.Error:
        pass

    print(wrap_text("\n1. Sign in to Redis Cloud or create an account."))
    print(
        wrap_text(
            "2. Open Databases and create a database. For a disposable "
            "trial/test installation, select 'Try 30 MB for free'; it is "
            "sufficient for the rehearsal, but Lagniappe's configurable "
            "database TLS option is unavailable on the free plan."
        )
    )
    print(
        wrap_text(
            "3. For production, or to configure Redis TLS during setup, "
            "select a paid Essentials or Pro plan instead."
        )
    )
    print(
        wrap_text(
            "4. Under 'Select cloud provider & region', choose Cloud vendor "
            f"'Google Cloud' and Region '{resource_region}' to match "
            "Lagniappe's regional Google Cloud resources. An existing "
            "database is suitable only when it has that same placement."
        )
    )
    print(
        wrap_text(
            "5. Create the database, then find Access on that same database "
            "details page and click the blue Connect button."
        )
    )
    print(
        wrap_text(
            "6. In the connection panel, expand Redis CLI and keep Internet "
            "(public endpoint) as the connection method."
        )
    )
    print(
        wrap_text(
            "7. Click the blue Copy button beneath the redis-cli command."
        )
    )
    print(
        wrap_text(
            "8. Return to setup and paste the complete copied command when "
            "prompted; you do not need to run it. Keep the database details "
            "page open because setup will next guide the required eviction "
            "policy there."
        )
    )


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_redis_cli_command_parser_extracts_connection_details
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_redis_cli_command_parser_rejects_invalid_commands
# @matrix setup : credential-parsing redis validation
def _parse_redis_cli_command(value):
    """Extract host, port, and password from pasted Redis connection input."""
    try:
        arguments = shlex.split(value)
    except ValueError as error:
        raise ValueError("The pasted Redis value has invalid quoting.") from error

    if not arguments:
        raise ValueError("The pasted Redis value is empty.")

    uri = None
    for argument in arguments:
        lowered = argument.lower()
        starts = [
            index
            for index in (lowered.find("redis:"), lowered.find("rediss:"))
            if index >= 0
        ]
        if starts:
            uri = argument[min(starts) :]
            break

    if uri is not None:
        try:
            parsed = urlsplit(uri)
            port = parsed.port
        except ValueError as error:
            raise ValueError("The Redis URI has an invalid endpoint.") from error

        password = unquote(parsed.password or "")
        host = parsed.hostname or ""
        if parsed.scheme.lower() not in {"redis", "rediss"}:
            raise ValueError("The pasted value must contain a Redis URI.")
    else:
        executable = arguments[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        if executable not in {"redis-cli", "redis-cli.exe"}:
            raise ValueError("Input should begin with redis: or redis-cli.")

        options = {}
        option_names = {
            "-h": "host",
            "--host": "host",
            "-p": "port",
            "--port": "port",
            "-a": "password",
            "--pass": "password",
        }
        for index, argument in enumerate(arguments[1:], start=1):
            option, separator, inline_value = argument.partition("=")
            name = option_names.get(option)
            if name is None:
                continue
            if separator:
                options[name] = inline_value
            elif index + 1 < len(arguments):
                options[name] = arguments[index + 1]

        host = options.get("host", "")
        password = options.get("password", "")
        try:
            port = int(options["port"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("The Redis command must include a valid port.") from error

    if not password or set(password) == {"*"}:
        raise ValueError("The Redis input must include the copied password.")
    if not host:
        raise ValueError("The Redis input must include the endpoint host.")
    if port is None:
        raise ValueError("The Redis input must include the endpoint port.")

    return {"host": host, "port": port, "password": password}


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_redis_cli_command_parser_rejects_invalid_commands
# @matrix setup : credential-parsing redis validation
def _is_redis_cli_command(value):
    try:
        _parse_redis_cli_command(value)
    except ValueError:
        return False
    return True


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_redis_cli_command_uses_visible_standard_input
# @matrix setup : cancellation credential-parsing interactive-input redis
@validate_input(
    "Paste copied Redis CLI command",
    validation_fn=_is_redis_cli_command,
    error_msg=(
        "Invalid command. In Redis Cloud, find Access, click Connect, expand "
        "Redis CLI, click Copy, then paste the complete command here. It should "
        "begin with 'redis-cli' or 'redis:'."
    ),
)
def _get_redis_connection_details(value):
    """Parse the visibly pasted Redis Cloud CLI command."""
    return _parse_redis_cli_command(value)


# @testable false
# @covered-by installer/redis.py::_enable_redis_tls
# @reason deterministic project-relative destination wrapper
def _managed_redis_ca_path():
    from config import APP_DIR, constants

    return Path(APP_DIR) / constants.REDIS_CA_CERT_RELATIVE_PATH


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_redis_tls_enablement_uses_managed_ca
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_redis_tls_enablement_requires_managed_ca
# @matrix setup : certificate-validation failure-isolation missing-file operator-guidance redis-tls settings-save
def _enable_redis_tls():
    """Guide the operator through verified server-side Redis TLS enablement."""
    from config import SETTINGS, constants
    from config.redis import RedisTLSConfigurationError, validate_redis_ca_cert

    f = FORMATTER.initialize()

    print(f"\n{f.info('Redis Cloud TLS')}")
    print(
        wrap_text(
            "Redis database TLS is available on paid Redis Cloud "
            "Essentials/Flex and Pro plans. It is not available on the free "
            "30 MB Essentials plan."
        )
    )
    print(
        wrap_text(
            "Think of Redis TLS as HTTPS for the server-to-server connection "
            "between Lagniappe and Redis Cloud."
        )
    )
    print(
        wrap_text(
            "The Redis password is still required for authentication; TLS "
            "wraps that password-authenticated connection in encryption and "
            "verifies the Redis Cloud server."
        )
    )
    print(f"Documentation: {REDIS_TLS_DOCUMENTATION_URL}")

    paid_plan = input(
        f.info("Is this database on a paid Redis Cloud plan? [y/N]: ")
    )
    if paid_plan.lower() != "y":
        print(
            f.warning(
                "Redis TLS was not changed. Upgrade the Redis Cloud plan, then "
                f"run {setup_command('security')}."
            )
        )
        return None

    print("\n1. Open Redis Cloud → Databases and select this database")
    print("2. Open Configuration, select Edit, and find the Security section")
    print("3. Enable Transport layer security (TLS)")
    print("4. Download the server certificate ZIP archive")
    print("5. Unzip the downloaded archive")
    print(
        "6. Place the extracted redis_ca.pem file in "
        f"{constants.REDIS_CA_CERT_RELATIVE_PATH}"
    )
    print("7. Leave Mutual TLS (require client authentication) unchecked")
    print("8. Save the database configuration")
    print(
        f.warning(
            "After TLS is saved, Redis Cloud rejects new unencrypted connections."
        )
    )

    configured = input(
        f.info(
            "Has TLS been enabled and the extracted redis_ca.pem placed in "
            f"{constants.REDIS_CA_CERT_RELATIVE_PATH}? [y/N]: "
        )
    )
    if configured.lower() != "y":
        print(f.warning("Redis TLS configuration was not changed."))
        return None

    try:
        managed_ca_path = validate_redis_ca_cert(_managed_redis_ca_path())
    except RedisTLSConfigurationError as error:
        print(f.error(f"Redis TLS settings were not saved.\n{error}"))
        print(
            f.warning(
                "Unzip the Redis Cloud certificate download and place the "
                "extracted redis_ca.pem file at "
                f"{constants.REDIS_CA_CERT_RELATIVE_PATH}, then retry."
            )
        )
        return False

    candidate = dict(SETTINGS.APP)
    candidate["REDIS_TLS"] = True
    candidate["REDIS_CA_CERT"] = str(managed_ca_path)

    if not test_redis_connection(candidate, exit_on_failure=False):
        print(
            f.error(
                "Redis TLS settings were not saved; the previous settings "
                "remain unchanged."
            )
        )
        print(
            f.warning(
                "Fix the certificate/connection and retry promptly, or disable "
                "TLS again in Redis Cloud to restore the previous transport mode."
            )
        )
        return False

    SETTINGS.APP["REDIS_TLS"] = True
    SETTINGS.APP["REDIS_CA_CERT"] = constants.REDIS_CA_CERT_RELATIVE_PATH
    SETTINGS.save()
    print(f.success("Redis TLS enabled with server certificate verification."))
    return True


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_redis_tls_disablement_is_transactional
# @matrix setup : failure-isolation redis-tls rollback settings-save
def _disable_redis_tls():
    """Guide the operator through a tested Redis TLS rollback."""
    from config import SETTINGS
    from config.redis import redis_tls_enabled

    f = FORMATTER.initialize()

    if not redis_tls_enabled(SETTINGS.APP):
        print(f.info("Redis TLS is already disabled."))
        return None

    print(f"\n{f.warning('Disable Redis Cloud TLS')}")
    print("1. Open the database Configuration screen in Redis Cloud")
    print("2. Edit the Security section and disable TLS")
    print("3. Save the database configuration")
    print(
        f.warning(
            wrap_text(
                "Do this before continuing so setup can verify a new plaintext "
                "connection."
            )
        )
    )
    configured = input(f.info("Has TLS been disabled in Redis Cloud? [y/N]: "))
    if configured.lower() != "y":
        print(f.warning("Redis TLS configuration was not changed."))
        return None

    candidate = dict(SETTINGS.APP)
    candidate["REDIS_TLS"] = False
    candidate.pop("REDIS_CA_CERT", None)
    if not test_redis_connection(candidate, exit_on_failure=False):
        print(
            f.error(
                "Redis TLS settings were not changed; the previous verified "
                "configuration remains saved."
            )
        )
        print(
            f.warning(
                "Re-enable TLS in Redis Cloud or fix the plaintext connection "
                "and rerun this command promptly."
            )
        )
        return False

    SETTINGS.APP["REDIS_TLS"] = False
    SETTINGS.APP.pop("REDIS_CA_CERT", None)
    SETTINGS.save()
    print(
        f.success(
            wrap_text(
                "Redis TLS disabled. The unused CA bundle remains available "
                "for rollback."
            )
        )
    )
    return True


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_settings_mutation_flows
# @matrix setup : optional redis-tls settings-save
def _offer_redis_tls_for_fresh_install():
    """Offer Redis TLS while the initial Redis connection is being configured."""
    f = FORMATTER.initialize()

    print(f"\n{f.info('Optional Redis Transport Security')}")
    print(
        wrap_text(
            "Paid Redis Cloud plans can encrypt application-to-database traffic "
            "with TLS; the free 30 MB Essentials plan cannot enable this "
            "database setting."
        )
    )
    consent = input(f.info("Configure Redis TLS now? [y/N]: "))
    if consent.lower() == "y":
        return _enable_redis_tls()

    print(
        f.info(
            f"Redis TLS left disabled. Run {setup_command('security')} "
            "after upgrading to a paid Redis Cloud plan."
        )
    )
    return None


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_settings_mutation_flows
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_redis_clears_failed_credentials_and_retries
# @matrix setup : failure-isolation redis retry rollback settings-save
def setup_redis():
    """Configure Redis connection details."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    if all(
        key in SETTINGS.APP for key in ["REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD"]
    ):
        test_redis_connection()
        return True

    redis_cloud_instructions()
    redis_provider_prepared = False

    while True:
        if not all(
            key in SETTINGS.APP
            for key in ("REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD")
        ):
            connection = _get_redis_connection_details()
            SETTINGS.APP["REDIS_HOST"] = connection["host"]
            SETTINGS.APP["REDIS_PORT"] = connection["port"]
            SETTINGS.APP["REDIS_PASSWORD"] = connection["password"]

        if not redis_provider_prepared:
            eviction_policy_instructions()
            tls_result = _offer_redis_tls_for_fresh_install()
            if tls_result is False:
                raise ProviderError("Redis TLS validation failed.")
            if tls_result is True:
                return True
            redis_provider_prepared = True

        SETTINGS.APP["REDIS_TLS"] = False
        SETTINGS.APP.pop("REDIS_CA_CERT", None)
        try:
            test_redis_connection()
        except ProviderError as error:
            for key in (
                "REDIS_HOST",
                "REDIS_PORT",
                "REDIS_PASSWORD",
                "REDIS_TLS",
                "REDIS_CA_CERT",
            ):
                SETTINGS.APP.pop(key, None)
            SETTINGS.save()
            print(
                f.warning(
                    wrap_text(
                        "The failed Redis connection details were cleared and "
                        "were not saved."
                    )
                )
            )
            retry = input(
                f.info("Enter the Redis connection details again? [Y/n]: ")
            )
            if retry.strip().lower() == "n":
                raise error
            continue

        SETTINGS.save()
        return True
