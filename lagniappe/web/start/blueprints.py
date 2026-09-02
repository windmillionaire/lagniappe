"""Register route blueprints and apply the explicit CSRF exemption policy."""

from dataclasses import dataclass


# @testable infrastructure
@dataclass(frozen=True)
class BlueprintRegistration:
    """One logical blueprint binding and its application URL prefix."""

    binding: str
    url_prefix: str | None = None
    enable_if_any: tuple[str, ...] = ()


# @testable infrastructure
@dataclass(frozen=True)
class CSRFExemption:
    """One CSRF exception and the replacement authentication boundary."""

    target_kind: str
    target: str
    rationale: str


BLUEPRINT_REGISTRATIONS = (
    BlueprintRegistration("home"),
    BlueprintRegistration("internal", "/l"),
    BlueprintRegistration("projects", "/projects"),
    BlueprintRegistration("files", "/files"),
    BlueprintRegistration("categories", "/categories"),
    BlueprintRegistration("forms", "/forms"),
    BlueprintRegistration("users", "/users"),
    BlueprintRegistration("pages", "/pages"),
    BlueprintRegistration("tasks", "/tasks"),
    BlueprintRegistration("tools", "/tools"),
    BlueprintRegistration("process", "/process"),
    BlueprintRegistration("manual", "/manual"),
    BlueprintRegistration("reference", "/reference"),
    BlueprintRegistration("filters", "/filters"),
    BlueprintRegistration("assets", "/assets"),
    BlueprintRegistration("testing", "/testing"),
    BlueprintRegistration("messages", "/messages"),
    BlueprintRegistration("message_internal", "/l/messages"),
    BlueprintRegistration("webhooks", "/webhooks"),
    BlueprintRegistration("api_family", "/api"),
    BlueprintRegistration("api", "/api/v1"),
    BlueprintRegistration(
        "analytics",
        "/analytics",
        ("ANALYTICS", "AI_OBSERVABILITY"),
    ),
)


CSRF_EXEMPTIONS = (
    CSRFExemption(
        "blueprint",
        "process",
        "Google OIDC service-account validation",
    ),
    CSRFExemption(
        "blueprint",
        "testing",
        "Hosted-E2E OIDC and run-bound session gate",
    ),
    CSRFExemption(
        "blueprint",
        "webhooks",
        "Provider signature verification",
    ),
    CSRFExemption(
        "blueprint",
        "api_family",
        "Bearer-only external API authentication",
    ),
    CSRFExemption(
        "blueprint",
        "api",
        "Bearer-only external API authentication",
    ),
    CSRFExemption(
        "view",
        "users.login_google",
        "Google double-submit cookie/body token",
    ),
)


# @testable false
# @covered-by lagniappe/web/start/blueprints.py::initialize
# @reason production-only lazy import plumbing is exercised through application boot
def _resolve_bindings(runtime_config):
    from lagniappe.web.routes import assets, categories, files, filters, forms
    from lagniappe.web.routes import home, internal, manual, message_internal
    from lagniappe.web.routes import messages, pages, process, projects, reference
    from lagniappe.web.routes import tasks, testing, tools, users
    from lagniappe.web.routes.api import api, api_family
    from lagniappe.web.routes.users.login import login_google
    from lagniappe.web.routes.webhooks import webhooks

    bindings = {
        "home": home,
        "internal": internal,
        "projects": projects,
        "files": files,
        "categories": categories,
        "forms": forms,
        "users": users,
        "pages": pages,
        "tasks": tasks,
        "tools": tools,
        "process": process,
        "manual": manual,
        "reference": reference,
        "filters": filters,
        "assets": assets,
        "testing": testing,
        "messages": messages,
        "message_internal": message_internal,
        "webhooks": webhooks,
        "api_family": api_family,
        "api": api,
        "users.login_google": login_google,
    }
    if any(
        getattr(runtime_config, setting, False)
        for setting in ("ANALYTICS", "AI_OBSERVABILITY")
    ):
        from lagniappe.web.routes import analytics

        bindings["analytics"] = analytics
    return bindings


# @testable false
# @covered-by lagniappe/web/start/blueprints.py::apply_blueprint_policy
# @reason small predicate keeps conditional registration data-driven
def _registration_enabled(registration, runtime_config):
    return not registration.enable_if_any or any(
        getattr(runtime_config, setting, False)
        for setting in registration.enable_if_any
    )


# @testable false
# @covered-by lagniappe/web/start/blueprints.py::apply_blueprint_policy
# @reason validation helper is exercised through the policy application boundary
def _validate_policy(registrations, exemptions):
    registration_targets = set()
    for registration in registrations:
        if not registration.binding:
            raise ValueError("Blueprint registration requires a binding name.")
        if registration.binding in registration_targets:
            raise ValueError(
                f"Duplicate blueprint registration target: {registration.binding}"
            )
        if (
            registration.url_prefix is not None
            and not registration.url_prefix.startswith("/")
        ):
            raise ValueError(
                f"Blueprint URL prefix must start with '/': {registration.binding}"
            )
        registration_targets.add(registration.binding)

    exemption_targets = set()
    for exemption in exemptions:
        identity = (exemption.target_kind, exemption.target)
        if exemption.target_kind not in {"blueprint", "view"}:
            raise ValueError(
                f"Unknown CSRF exemption target kind: {exemption.target_kind}"
            )
        if not exemption.target:
            raise ValueError("CSRF exemption requires a logical target.")
        if not exemption.rationale.strip():
            raise ValueError(f"CSRF exemption requires a rationale: {exemption.target}")
        if identity in exemption_targets:
            raise ValueError(
                "Duplicate CSRF exemption target: "
                f"{exemption.target_kind}:{exemption.target}"
            )
        if (
            exemption.target_kind == "blueprint"
            and exemption.target not in registration_targets
        ):
            raise ValueError(
                f"CSRF blueprint exemption is not registered: {exemption.target}"
            )
        exemption_targets.add(identity)


# @testable true
# @tests tests_e2e/001_site/test_001c_web_security_wiring.py::test_blueprint_registration_and_csrf_exemption_policy
# @tests tests_e2e/001_site/test_001c_web_security_wiring.py::test_blueprint_policy_rejects_invalid_bindings_and_exemptions
# @tests tests_e2e/001_site/test_001c_web_security_wiring.py::test_csrf_exempt_surfaces_reach_replacement_authentication_gates
# @matrix csrf web-startup : blueprint-registration exemption-policy validation
# @pair csrf:route-gate
def apply_blueprint_policy(
    app,
    csrf,
    bindings,
    runtime_config,
    *,
    registrations=BLUEPRINT_REGISTRATIONS,
    exemptions=CSRF_EXEMPTIONS,
):
    """Register enabled blueprints and apply only declared CSRF exemptions."""
    registrations = tuple(registrations)
    exemptions = tuple(exemptions)
    _validate_policy(registrations, exemptions)

    enabled_registrations = tuple(
        registration
        for registration in registrations
        if _registration_enabled(registration, runtime_config)
    )
    for registration in enabled_registrations:
        if registration.binding not in bindings:
            raise RuntimeError(f"Missing blueprint binding: {registration.binding}")

    for exemption in exemptions:
        if exemption.target not in bindings:
            raise RuntimeError(f"Missing CSRF exemption binding: {exemption.target}")

    for registration in enabled_registrations:
        options = {}
        if registration.url_prefix is not None:
            options["url_prefix"] = registration.url_prefix
        app.register_blueprint(bindings[registration.binding], **options)

    resolved_exemptions = []
    for exemption in exemptions:
        target = bindings[exemption.target]
        if exemption.target_kind == "view":
            endpoint_view = app.view_functions.get(exemption.target)
            if endpoint_view is None:
                raise RuntimeError(
                    f"CSRF-exempt view endpoint is unavailable: {exemption.target}"
                )
            if endpoint_view is not target:
                raise RuntimeError(
                    "CSRF-exempt view binding does not match its registered endpoint: "
                    f"{exemption.target}"
                )
        resolved_exemptions.append(target)

    for target in resolved_exemptions:
        csrf.exempt(target)


# @testable true
# @tests tests_e2e/001_site/test_001c_web_security_wiring.py::test_blueprint_registration_and_csrf_exemption_policy
# @matrix web-startup : blueprint-registration
def initialize(app, csrf, *, binding_factory=_resolve_bindings, runtime_config=None):
    """Resolve production bindings and apply registration/security policy."""
    if runtime_config is None:
        from lagniappe import CONFIG

        runtime_config = CONFIG
    bindings = binding_factory(runtime_config)
    apply_blueprint_policy(app, csrf, bindings, runtime_config)
