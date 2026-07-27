from pathlib import Path
import re
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
# @features setup
# @dimensions redis-connection redis-tls
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


# @testable false
# @covered-by installer/redis.py::setup_redis
# @reason console-only Redis Cloud configuration instructions
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
                "This can be set in your Redis Cloud dashboard under "
                "Configuration → Durability → Data eviction policy"
            )
        )
    )
    print(f.info("You will need to click 'Edit', make the change, and click 'Save'"))
    print(
        f.info(
            wrap_text(
                "This policy helps manage memory by evicting keys with TTL when "
                "the memory limit is reached."
            )
        )
    )
    input(
        f"\n{f.warning('Press Enter after configuring the eviction policy to continue...')}"
    )


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_redis_cloud_instructions_open_console_and_locate_credentials
# @features setup
# @dimensions redis browser operator-guidance
def redis_cloud_instructions():
    """Open Redis Cloud and explain where to find connection credentials."""
    f = FORMATTER.initialize()

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

    print(
        wrap_text(
            "\n1. In Redis Cloud, open Databases and create a database or "
            "select an existing one."
        )
    )
    print(
        wrap_text(
            "2. Keep the Public endpoint and Default user enabled. Lagniappe's "
            "guided setup currently uses both."
        )
    )
    print(
        wrap_text(
            "3. Copy the Public endpoint from Access (Essentials) or General "
            "(Pro). It normally includes both the host and port."
        )
    )
    print(
        wrap_text(
            "4. Copy the Default user password from Security. For Essentials, "
            "select Default user, then Configure, to reveal it."
        )
    )


# @testable true
# @tests tests_tooling/test_001a_setup_validation_config.py::test_setup_validators_cover_expected_inputs
# @features setup
# @dimensions validation
def _is_redis_cloud_host(value):
    host = value.strip().lower()
    if ":" in host:
        host = host.rsplit(":", 1)[0]
    return bool(
        host.startswith("redis-cloud")
        or re.match(r"^redis-[0-9]+\.", host)
        or host.endswith(".redislabs.com")
    )


# @testable false
# @covered-by installer/redis.py::setup_redis
# @reason interactive input wrapper owned by the Redis setup flow
@validate_input(
    "Enter Redis Public Endpoint",
    validation_fn=_is_redis_cloud_host,
    error_msg="Invalid Redis host format. Expected a Redis Cloud endpoint (e.g. redis-12345.c123.us-east-1-2.ec2.redislabs.com).",
)
def _get_redis_host(value):
    return value


# @testable false
# @covered-by installer/redis.py::setup_redis
# @reason interactive input wrapper owned by the Redis setup flow
@validate_input(
    "Enter Redis Port",
    validation_fn=lambda x: x.isdigit(),
    error_msg="Redis Port must be a number",
)
def _get_redis_port(value):
    return int(value)


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_redis_password_uses_visible_standard_input
# @features setup
# @dimensions redis interactive-input cancellation
@validate_input("Enter Redis Default User Password")
def _get_redis_password(value):
    """Return the visibly entered Redis default-user password."""
    return value


# @testable false
# @covered-by installer/redis.py::_enable_redis_tls
# @reason deterministic project-relative destination wrapper
def _managed_redis_ca_path():
    from config import APP_DIR, constants

    return Path(APP_DIR) / constants.REDIS_CA_CERT_RELATIVE_PATH


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_redis_tls_enablement_uses_managed_ca
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_redis_tls_enablement_requires_managed_ca
# @features setup
# @dimensions redis-tls settings-save certificate-validation failure-isolation missing-file operator-guidance
def _enable_redis_tls():
    """Guide the operator through verified server-side Redis TLS enablement."""
    from config import SETTINGS, constants
    from config.redis import RedisTLSConfigurationError, validate_redis_ca_cert

    f = FORMATTER.initialize()

    print(f"\n{f.info('Redis Cloud TLS')}")
    print(
        wrap_text(
            "Redis database TLS is available on paid Redis Cloud "
            "Essentials/Flex and Pro plans. It is not available on Free "
            "Essentials plans."
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
# @features setup
# @dimensions redis-tls rollback settings-save failure-isolation
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
# @features setup
# @dimensions redis-tls optional settings-save
def _offer_redis_tls_for_fresh_install():
    """Offer Redis TLS while the initial Redis connection is being configured."""
    f = FORMATTER.initialize()

    print(f"\n{f.info('Optional Redis Transport Security')}")
    print(
        wrap_text(
            "Paid Redis Cloud plans can encrypt application-to-database traffic "
            "with TLS; Free Essentials plans cannot enable this database "
            "setting."
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
# @features setup
# @dimensions redis settings-save retry rollback failure-isolation
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
        if "REDIS_HOST" not in SETTINGS.APP:
            host = _get_redis_host()
            parts = host.rsplit(":", 1)
            if len(parts) == 2:
                SETTINGS.APP["REDIS_HOST"] = parts[0]
                SETTINGS.APP["REDIS_PORT"] = int(parts[-1])
            else:
                SETTINGS.APP["REDIS_HOST"] = host

        if "REDIS_PORT" not in SETTINGS.APP:
            port = _get_redis_port()
            SETTINGS.APP["REDIS_PORT"] = int(port)

        if "REDIS_PASSWORD" not in SETTINGS.APP:
            password = _get_redis_password()
            SETTINGS.APP["REDIS_PASSWORD"] = password

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
