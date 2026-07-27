from config import constants
from installer import FORMATTER, wrap_text


# @testable false
# @covered-by installer/optional.py::setup_error_monitoring
# @covered-by installer/optional.py::configure_development_error_monitoring
# @reason shared DSN prompt validation is exercised through the two monitoring setup flows
def _operator_sentry_dsn(prompt):
    from urllib.parse import urlparse

    while True:
        dsn = input(prompt).strip()
        if not dsn:
            return None

        parsed = urlparse(dsn)
        if parsed.scheme == "https" and parsed.username and parsed.netloc and parsed.path:
            return dsn
        print(
            wrap_text(
                "Enter an HTTPS Sentry DSN such as "
                "'https://public-key@sentry.example.com/project-id', "
                "or leave blank to disable monitoring."
            )
        )


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_settings_mutation_flows
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_error_monitoring_supports_maintainer_or_operator_sentry
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_disabled_error_monitoring_offers_to_enable
# @features setup
# @dimensions optional settings-save privacy-consent sentry-destination rerun default-disabled
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
            print("\nExisting error-monitoring choice: enabled.")
            preserve = input(
                "Keep the existing monitoring choice and destination? [Y/n]: "
            )
            if preserve.casefold() != "n":
                print("Existing error-monitoring settings preserved.")
                return True
        else:
            print("\nError monitoring is currently disabled.")
            enable = input("Would you like to enable error monitoring? [y/N]: ")
            if enable.casefold() != "y":
                print("Error monitoring remains disabled.")
                return True

    print(f"\n{f.info('Error Monitoring & Crash Reporting')}")
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

    print(f"\n{f.success('What can be reported when monitoring is enabled:')}")
    print(wrap_text("• Error messages and stack traces when something breaks"))
    print(
        wrap_text(
            "• Route template, endpoint, method, and bounded request-size metadata"
        )
    )
    print(
        wrap_text(
            "• Query field names/counts and a short allowlist of diagnostic headers"
        )
    )
    print(wrap_text("• Browser context and performance data when available"))

    print(f"\n{f.warning('What Lagniappe removes before sending:')}")
    print(
        wrap_text(
            "• Form and JSON values, request/response bodies, and query values"
        )
    )
    print(
        wrap_text(
            "• Uploaded filenames, file contents, full URLs, and referrers"
        )
    )
    print(
        wrap_text(
            "• Authorization, cookies, arbitrary X-* headers, and user identity "
            "context"
        )
    )
    print(
        wrap_text(
            "• Recognized password, token, API-key, and private-key values at "
            "any depth"
        )
    )
    print(
        wrap_text(
            "• Oversized strings, collections, and deeply nested diagnostic "
            "context"
        )
    )

    print(f"\n{f.warning('Important limits:')}")
    print(wrap_text("• Sentry default PII collection is disabled"))
    print(
        wrap_text(
            "• Unstructured error messages and stack traces are still "
            "diagnostic text"
        )
    )
    print(
        wrap_text(
            "• Third-party integrations can add metadata before the final "
            "scrubber runs"
        )
    )
    print(
        wrap_text(
            "• Reports are privacy-reduced, not guaranteed to be anonymous"
        )
    )
    print(wrap_text("• Error reports are sent over HTTPS"))

    print(f"\n{f.info('Where reports go:')}")
    print(
        wrap_text(
            "• The default DSN sends opted-in reports to the Lagniappe maintainer"
        )
    )
    print(wrap_text("• You may instead enter your own Sentry DSN"))
    print(
        wrap_text(
            "• With your own DSN, reports go to your Sentry project, not the "
            "maintainer"
        )
    )
    print(
        wrap_text(
            "• Development installations must use their own DSN or disable "
            "monitoring"
        )
    )

    print(f"\n{f.info('How this helps:')}")
    print(wrap_text("• Developers can fix bugs you encounter automatically"))
    print(wrap_text("• Performance issues get identified and resolved faster"))
    print(wrap_text("• Your Lagniappe instance becomes more stable over time"))

    print("\nExamples of what gets reported:")
    print(
        wrap_text('• "Image upload failed: file too large" (no image content)')
    )
    print(
        wrap_text(
            '• "Form validation error on date field" (no submitted field values)'
        )
    )
    print(
        wrap_text(
            '• "Database connection timeout after 30s" (no query details)'
        )
    )

    print(
        f"\n{f.info(wrap_text('You can disable this at any time by changing '
                             'CAPTURE_ERRORS to False in your settings file.'))}"
    )

    consent = input(
        f"\n{f.warning('Send privacy-reduced error reports to the Lagniappe maintainer? [y/N]: ')}"
    )
    if consent.casefold() == "y":
        dsn = constants.SENTRY_DSN
    else:
        own_sentry = input(
            "Would you like to use your own Sentry project instead? [y/N]: "
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
        SETTINGS.APP["CAPTURE_ERRORS"] = "True"
        destination = (
            "the maintainer Sentry project"
            if dsn == constants.SENTRY_DSN
            else "your Sentry project"
        )
        print(f.success(f"Error monitoring enabled with {destination}."))
    else:
        SETTINGS.APP["CAPTURE_ERRORS"] = "False"
        SETTINGS.APP.pop("SENTRY_DSN", None)
        print(f.success("Error monitoring disabled."))

    SETTINGS.save()
    return True


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_development_monitoring_rejects_maintainer_sentry
# @features setup
# @dimensions development sentry-destination privacy
def configure_development_error_monitoring():
    """Ensure development errors never use the maintainer Sentry project."""
    from config import SETTINGS

    current_dsn = str(SETTINGS.APP.get("SENTRY_DSN") or "").strip()
    if current_dsn != constants.SENTRY_DSN:
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
        if dsn != constants.SENTRY_DSN:
            break
        print(
            wrap_text(
                "That is the maintainer DSN. Development installations must "
                "use a different Sentry project or disable monitoring."
            )
        )
    if dsn:
        SETTINGS.APP["SENTRY_DSN"] = dsn
        SETTINGS.APP["CAPTURE_ERRORS"] = "True"
        print("Development error monitoring will use your Sentry project.")
    else:
        SETTINGS.APP.pop("SENTRY_DSN", None)
        SETTINGS.APP["CAPTURE_ERRORS"] = "False"
        print("Development error monitoring disabled.")
    SETTINGS.save()
    return True


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_ai_observability_is_an_explicit_preserved_setup_choice
# @features setup ai-observability
# @dimensions privacy-consent settings-save rerun
def configure_ai_observability():
    """Set the optional owner-only AI generation summary flag."""
    from config import SETTINGS

    existing = SETTINGS.APP.get("AI_OBSERVABILITY")
    if existing is not None:
        existing_enabled = (
            existing
            if isinstance(existing, bool)
            else str(existing).casefold() == "true"
        )
        state = "enabled" if existing_enabled else "disabled"
        print(f"\nAI generation observability is currently {state}.")
        preserve = input("Keep this AI observability choice? [Y/n]: ")
        if preserve.casefold() != "n":
            print("Existing AI observability choice preserved.")
            return existing_enabled

    print("\nOptional AI Generation Observability")
    for paragraph in (
        "When enabled, Lagniappe stores owner-only operational summaries for "
        "text generations, including model, token totals, duration, retry and "
        "error categories, and tool names.",
        "The summaries exclude prompts, generated text, messages, tool "
        "arguments/results, file contents, and application identifiers.",
    ):
        print(wrap_text(paragraph))
    enabled = (
        input("Enable AI generation observability? [y/N]: ").casefold() == "y"
    )
    SETTINGS.APP["AI_OBSERVABILITY"] = enabled
    print(f"AI generation observability {'enabled' if enabled else 'disabled'}.")
    return enabled


# @testable true
# @tests tests_tooling/test_001c_setup_runtime_resources.py::test_setup_settings_mutation_flows
# @features setup
# @dimensions ai-model optional settings-save ai-observability
def change_ai_model():
    """
    Ask user for consent to change the AI model.
    Returns True if user consents, False otherwise.
    """
    from config import SETTINGS

    f = FORMATTER.initialize()

    print(f"\n{f.info('Change AI Model')}")
    print(f"Currently using {SETTINGS.APP['AI_MODEL']}")
    print(
        "Available models: https://cloud.google.com/vertex-ai/generative-ai/docs/models#generally_available_models"
    )

    consent = input(f"\n{f.warning('Change AI model to use? [y/N]: ')}")
    if consent.lower() == "y":
        model = input(f"\n{f.warning('Enter the model name: ')}")
        SETTINGS.APP["AI_MODEL"] = model
        SETTINGS.APP["AI_LOCATION"] = constants.DEFAULT_AI_LOCATION
        print(f.success(f"AI model changed to {model}."))
    else:
        print(f.success("AI model not changed."))

    print(f"\n{f.info('Change AI Utility Model')}")
    print(
        f"Currently using {SETTINGS.APP.get('AI_UTILITY_MODEL', constants.DEFAULT_UTILITY_AI_MODEL)}"
    )
    print(
        "Available models: https://cloud.google.com/vertex-ai/generative-ai/docs/models#generally_available_models"
    )

    consent = input(f"\n{f.warning('Change AI utility model to use? [y/N]: ')}")
    if consent.lower() == "y":
        model = input(f"\n{f.warning('Enter the model name: ')}")
        SETTINGS.APP["AI_UTILITY_MODEL"] = model
        SETTINGS.APP["AI_LOCATION"] = constants.DEFAULT_AI_LOCATION
        print(f.success(f"AI utility model changed to {model}."))
    else:
        SETTINGS.APP["AI_UTILITY_MODEL"] = SETTINGS.APP.get(
            "AI_UTILITY_MODEL",
            constants.DEFAULT_UTILITY_AI_MODEL,
        )

    print(f"\n{f.info('Change AI Image Model')}")
    print(f"Currently using {SETTINGS.APP['AI_IMAGE_MODEL']}")
    print(
        "Available models: https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/image-generation"
    )

    consent = input(f"\n{f.warning('Change AI image model to use? [y/N]: ')}")
    if consent.lower() == "y":
        model = input(f"\n{f.warning('Enter the model name: ')}")
        SETTINGS.APP["AI_IMAGE_MODEL"] = model
        print(f.success(f"AI image model changed to {model}."))

    configure_ai_observability()
    SETTINGS.save()
