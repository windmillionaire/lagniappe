from runner import presentation as ui
from runner.presentation import output as print, read_input as input
from config import constants
from runner.console import format_prompt
from installer import FORMATTER, wrap_text


# @testable false
# @covered-by installer/optional.py::setup_error_monitoring
# @covered-by installer/optional.py::configure_development_error_monitoring
# @reason shared DSN prompt validation is exercised through the two monitoring setup flows
def _operator_sentry_dsn(prompt):
    from urllib.parse import urlparse

    while True:
        dsn = input(format_prompt(prompt)).strip()
        if not dsn:
            return None

        parsed = urlparse(dsn)
        if parsed.scheme == "https" and parsed.username and parsed.netloc and parsed.path:
            return dsn
        print(
            ui.error(wrap_text(
                "Enter an HTTPS Sentry DSN such as "
                "'https://public-key@sentry.example.com/project-id', "
                "or leave blank to disable monitoring."
            ))
        )


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_settings_mutation_flows
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_error_monitoring_supports_maintainer_or_operator_sentry
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_disabled_error_monitoring_offers_to_enable
# @matrix setup : default-disabled optional privacy-consent rerun sentry-destination settings-save
def setup_error_monitoring():
    """
    Ask user for consent to enable error monitoring and crash reporting.
    Returns True if user consents, False otherwise.
    """
    from config import SETTINGS

    f = FORMATTER.initialize()
    if "CAPTURE_ERRORS" in SETTINGS.APP:
        enabled = str(SETTINGS.APP.get("CAPTURE_ERRORS")).casefold() == "true"
        destination = str(SETTINGS.APP.get("SENTRY_DSN") or "").strip()
        if enabled and destination:
            print(wrap_text("\nExisting error-monitoring choice: enabled."))
            preserve = input(
                format_prompt(
                    "Keep the existing monitoring choice and destination? [Y/n]: "
                )
            )
            if preserve.casefold() != "n":
                if not str(SETTINGS.APP.get("SENTRY_JS_DSN") or "").strip():
                    SETTINGS.APP["SENTRY_JS_DSN"] = (
                        constants.SENTRY_JS_DSN
                        if destination == constants.SENTRY_DSN
                        else destination
                    )
                    SETTINGS.save()
                print(ui.status(wrap_text("Existing error-monitoring settings preserved.")))
                return True
        else:
            print(wrap_text("\nError monitoring is currently disabled."))
            enable = input(
                format_prompt("Would you like to enable error monitoring? [y/N]: ")
            )
            if enable.casefold() != "y":
                print(ui.status(wrap_text("Error monitoring remains disabled.")))
                return True

    print(wrap_text(f"\n{ui.heading('Error monitoring and crash reporting')}"))
    print(
        wrap_text(
            "Lagniappe can optionally report errors and crashes to help improve "
            "the software."
        )
    )
    print(
        wrap_text(
            "Privacy notice: https://lagniappe.site/reporting_privacy "
            "(repository copy: ERROR_REPORTING_PRIVACY.md)"
        )
    )

    print(
        wrap_text(f"\n{ui.heading('What can be reported when monitoring is enabled:')}")
    )
    print(wrap_text("- Error messages and stack traces when something breaks"))
    print(
        wrap_text(
            "- Route template, endpoint, method, and bounded request-size metadata"
        )
    )
    print(
        wrap_text(
            "- Query field names/counts and a short allowlist of diagnostic headers"
        )
    )
    print(wrap_text("- Browser context and performance data when available"))

    print(wrap_text(f"\n{ui.heading('What Lagniappe removes before sending:')}"))
    print(
        wrap_text(
            "- Form and JSON values, request/response bodies, and query values"
        )
    )
    print(
        wrap_text(
            "- Uploaded filenames, file contents, full URLs, and referrers"
        )
    )
    print(
        wrap_text(
            "- Authorization, cookies, arbitrary X-* headers, and user identity "
            "context"
        )
    )
    print(
        wrap_text(
            "- Recognized password, token, API-key, and private-key values at "
            "any depth"
        )
    )
    print(
        wrap_text(
            "- Oversized strings, collections, and deeply nested diagnostic "
            "context"
        )
    )

    print(wrap_text(f"\n{ui.heading('Important limits:')}"))
    print(wrap_text("- Sentry default PII collection is disabled"))
    print(
        wrap_text(
            "- Unstructured error messages and stack traces are still "
            "diagnostic text"
        )
    )
    print(
        wrap_text(
            "- Third-party integrations can add metadata before the final "
            "scrubber runs"
        )
    )
    print(
        wrap_text(
            "- Reports are privacy-reduced, not guaranteed to be anonymous"
        )
    )
    print(wrap_text("- Error reports are sent over HTTPS"))

    print(wrap_text(f"\n{ui.heading('Where reports go:')}"))
    print(
        wrap_text(
            "- The default DSN sends opted-in reports to the Lagniappe maintainer"
        )
    )
    print(wrap_text("- You may instead enter your own Sentry DSN"))
    print(
        wrap_text(
            "- With your own DSN, reports go to your Sentry project, not the "
            "maintainer"
        )
    )
    print(
        wrap_text(
            "- Development installations must use their own DSN or disable "
            "monitoring"
        )
    )

    print(wrap_text(f"\n{ui.heading('How this helps:')}"))
    print(wrap_text("- Developers can fix bugs you encounter automatically"))
    print(wrap_text("- Performance issues get identified and resolved faster"))
    print(wrap_text("- Your Lagniappe instance becomes more stable over time"))

    print(wrap_text(ui.heading("\nExamples of what gets reported:")))
    print(
        wrap_text('- "Image upload failed: file too large" (no image content)')
    )
    print(
        wrap_text(
            '- "Form validation error on date field" (no submitted field values)'
        )
    )
    print(
        wrap_text(
            '- "Database connection timeout after 30s" (no query details)'
        )
    )

    print(
        f"\n{f.info(wrap_text('You can disable this at any time by changing '
                             'CAPTURE_ERRORS to False in your settings file.'))}"
    )

    consent = input(
        format_prompt(
            f"\n{'Send privacy-reduced error reports to the Lagniappe maintainer? [y/N]: '}"
        )
    )
    if consent.casefold() == "y":
        dsn = constants.SENTRY_DSN
    else:
        own_sentry = input(
            format_prompt(
                "Would you like to use your own Sentry project instead? [y/N]: "
            )
        )
        dsn = (
            _operator_sentry_dsn(
                "Enter your Sentry DSN, or leave blank to disable monitoring: "
            )
            if own_sentry.casefold() == "y"
            else None
        )

    if dsn:
        SETTINGS.APP["SENTRY_DSN"] = dsn
        SETTINGS.APP["SENTRY_JS_DSN"] = (
            constants.SENTRY_JS_DSN
            if dsn == constants.SENTRY_DSN
            else dsn
        )
        SETTINGS.APP["CAPTURE_ERRORS"] = "True"
        destination = (
            "the maintainer Sentry project"
            if dsn == constants.SENTRY_DSN
            else "your Sentry project"
        )
        print(ui.info(f"Error monitoring enabled with {destination}."))
    else:
        SETTINGS.APP["CAPTURE_ERRORS"] = "False"
        SETTINGS.APP.pop("SENTRY_DSN", None)
        SETTINGS.APP.pop("SENTRY_JS_DSN", None)
        print(ui.info("Error monitoring disabled."))

    SETTINGS.save()
    print(f.success("Error monitoring settings saved"))
    return True


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_development_monitoring_rejects_maintainer_sentry
# @matrix setup : development privacy sentry-destination
def configure_development_error_monitoring():
    """Ensure development errors never use the maintainer Sentry project."""
    from config import SETTINGS

    current_dsn = str(SETTINGS.APP.get("SENTRY_DSN") or "").strip()
    current_js_dsn = str(SETTINGS.APP.get("SENTRY_JS_DSN") or "").strip()
    maintainer_dsns = {constants.SENTRY_DSN, constants.SENTRY_JS_DSN}
    if (
        current_dsn not in maintainer_dsns
        and current_js_dsn not in maintainer_dsns
    ):
        return True

    print(
        wrap_text(
            "\nDevelopment installations cannot report to the maintainer "
            "Sentry project. Use your own Sentry DSN or disable monitoring."
        )
    )
    while True:
        dsn = _operator_sentry_dsn(
            "Enter your Sentry DSN, or leave blank to disable monitoring: "
        )
        if dsn not in maintainer_dsns:
            break
        print(
            ui.error(wrap_text(
                "That is the maintainer DSN. Development installations must "
                "use a different Sentry project or disable monitoring."
            ))
        )
    if dsn:
        SETTINGS.APP["SENTRY_DSN"] = dsn
        SETTINGS.APP["SENTRY_JS_DSN"] = dsn
        SETTINGS.APP["CAPTURE_ERRORS"] = "True"
        print(wrap_text("Development error monitoring will use your Sentry project."))
    else:
        SETTINGS.APP.pop("SENTRY_DSN", None)
        SETTINGS.APP.pop("SENTRY_JS_DSN", None)
        SETTINGS.APP["CAPTURE_ERRORS"] = "False"
        print(wrap_text("Development error monitoring disabled."))
    SETTINGS.save()
    return True


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_ai_observability_is_an_explicit_preserved_setup_choice
# @matrix ai-observability setup : privacy-consent rerun settings-save
def configure_ai_observability():
    """Set the optional owner-only AI generation summary flag."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    existing = SETTINGS.APP.get("AI_OBSERVABILITY")
    if existing is not None:
        existing_enabled = (
            existing
            if isinstance(existing, bool)
            else str(existing).casefold() == "true"
        )
        state = "enabled" if existing_enabled else "disabled"
        print(
            wrap_text(
                f"\n{f.info(f'AI generation observability is currently {state}.')}"
            )
        )
        preserve = input(
            format_prompt("Keep this AI observability choice? [Y/n]: ")
        )
        if preserve.casefold() != "n":
            print(ui.status(wrap_text("Existing AI observability choice preserved.")))
            return existing_enabled

    print(wrap_text(f"\n{ui.heading('Optional AI generation observability')}"))
    for paragraph in (
        "When enabled, Lagniappe stores owner-only operational summaries for "
        "text generations, including model, token totals, duration, retry and "
        "error categories, and tool names.",
        "The summaries exclude prompts, generated text, messages, tool "
        "arguments/results, file contents, and application identifiers.",
    ):
        print(wrap_text(paragraph))
    enabled = (
        input(
            format_prompt(f"\n{'Enable AI generation observability? [y/N]: '}")
        ).casefold()
        == "y"
    )
    SETTINGS.APP["AI_OBSERVABILITY"] = enabled
    state = "enabled" if enabled else "disabled"
    print(ui.info(f"AI generation observability {state}."))
    return enabled


# @testable true
# @tests tests_tooling/test_001j_setup_ai_mcp.py::test_mcp_connection_name_prompt
# @matrix setup : interactive-input settings-save validation
def configure_mcp_name():
    """Choose the saved connection name used by the installation's manual."""
    from config import SETTINGS
    from config.remote_mcp import mcp_connection_name

    default = SETTINGS.APP.get("MCP_NAME")
    if not default:
        default = f"{SETTINGS.APP.get('GCLOUD_CONFIG') or 'lagniappe'}-mcp"
    try:
        mcp_connection_name(default)
    except ValueError:
        default = "lagniappe-mcp"
    print(wrap_text("The manual uses this name in connection instructions and copyable commands."))
    while True:
        answer = input(format_prompt("MCP connection name", default=default)).strip()
        try:
            name = mcp_connection_name(answer or default)
        except ValueError as error:
            print(ui.error(str(error)))
            continue
        SETTINGS.APP["MCP_NAME"] = name
        return name


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_settings_mutation_flows
# @matrix setup : ai-model ai-observability optional settings-save site-policy
def configure_ai_features():
    """Choose the installation's built-in and external AI access policy."""
    from config import SETTINGS

    f = FORMATTER.initialize()
    print(wrap_text(f"\n{ui.heading('AI features')}"))
    previous = SETTINGS.APP.get("AI_ENABLED", True)
    answer = (
        input(
            format_prompt(
                f"Enable AI features? {'[Y/n]' if previous else '[y/N]'}: "
            )
        )
        .strip()
        .casefold()
    )
    enabled = answer in {"y", "yes"} if answer else previous
    SETTINGS.APP["AI_ENABLED"] = enabled
    if not enabled:
        SETTINGS.APP["EXTERNAL_AI_ENABLED"] = False
        SETTINGS.APP["AI_OBSERVABILITY"] = False
        print(ui.info("AI features and external AI access are disabled."))
    else:
        print(wrap_text(
            f"AI models: {SETTINGS.APP.get('AI_MODEL', constants.DEFAULT_AI_MODEL)} "
            f"(primary), {SETTINGS.APP.get('AI_UTILITY_MODEL', constants.DEFAULT_UTILITY_AI_MODEL)} "
            f"(utility), {SETTINGS.APP.get('AI_IMAGE_MODEL', constants.DEFAULT_AI_IMAGE_MODEL)} "
            "(images). You can change these in Admin → Site Settings → AI Models."
        ))
        print(wrap_text(
            "External AI access lets users connect their own agents through MCP "
            "or the API/skill. Those agents use their own model providers. "
            "Leave this disabled to keep AI access within the site's configured provider."
        ))
        previous = SETTINGS.APP.get("EXTERNAL_AI_ENABLED", bool(SETTINGS.APP.get("MCP_RESOURCE")))
        answer = (
            input(
                format_prompt(
                    f"Enable external AI access and the MCP server? {'[Y/n]' if previous else '[y/N]'}: "
                )
            )
            .strip()
            .casefold()
        )
        SETTINGS.APP["EXTERNAL_AI_ENABLED"] = answer in {"y", "yes"} if answer else previous
        if SETTINGS.APP["EXTERNAL_AI_ENABLED"]:
            configure_mcp_name()
        configure_ai_observability()
    SETTINGS.save()
    print(f.success("AI settings saved"))
    return enabled
