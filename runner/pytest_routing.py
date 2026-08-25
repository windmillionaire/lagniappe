"""Authoritative pytest argument routing for the repository test runner."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import re
import sys


PYTEST_CONFIG = "testing/pytest.ini"
TRACEABILITY_RESULTS_PLUGIN = "testing.utility.traceability_results"
PYTEST_ROUTING_PLUGIN = "runner.pytest_routing"

SETUP_TEST_GROUPS = {
    "ordinary": (
        "testing/tests_tooling/test_001a_setup_validation_config.py",
        "testing/tests_tooling/test_001b_setup_providers.py",
        "testing/tests_tooling/test_001c_setup_runtime_resources.py",
        "testing/tests_tooling/test_001e_setup_orchestration.py",
        "testing/tests_tooling/test_001f_setup_portability.py",
        "testing/tests_tooling/test_001g_setup_release_readiness.py",
        "testing/tests_tooling/test_001h_setup_ai_email.py",
    ),
    "setup_drift": ("testing/tests_tooling/test_001d_setup_drift.py",),
    "setup_provider": (
        "testing/tests_e2e/001_site/test_001g_setup_provider_contracts.py",
    ),
}
TEST_SUITE_ALIASES = {
    "unit": ("testing/tests_unit/",),
    "e2e": ("testing/tests_e2e/",),
    "js": ("testing/tests_js/",),
    "tooling": ("testing/tests_tooling/",),
    "setup": SETUP_TEST_GROUPS["ordinary"],
}
SETUP_OPT_IN_TESTS = {
    marker: targets
    for marker, targets in SETUP_TEST_GROUPS.items()
    if marker != "ordinary"
}

_MARKER_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PROVIDER_MARKER_PATTERN = re.compile(r"\bprovider\b")


class PytestRoutingError(ValueError):
    """Raised when the runner cannot construct an unambiguous test selection."""


# @testable infrastructure
class _IndexedArgument(str):
    """A command-line token that retains its source position through argparse."""

    argument_index: int

    # @testable false
    # @covered-by runner/pytest_routing.py::normalize_pytest_invocation
    def __new__(cls, value: str, argument_index: int):
        instance = super().__new__(cls, value)
        instance.argument_index = argument_index
        return instance


@dataclass(frozen=True)
class PytestInvocation:
    """Normalized pytest arguments and the preflight decisions they imply."""

    pytest_args: tuple[str, ...]
    collection_targets: tuple[str, ...]
    strict_relations: bool
    includes_e2e: bool


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_normalize_pytest_invocation_routes_registered_option_values
# @pair testing:pytest-options
def pytest_addoption(parser) -> None:
    """Register options that must be known before suite conftests are imported."""
    group = parser.getgroup("lagniappe")
    group.addoption(
        "--browser-failure-diagnostics",
        action="store_true",
        help="Record browser failures without making them teardown failures.",
    )


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_pytest_routing_plugin_normalizes_provider_marker_tokens
# @matrix setup testing : pytest-markers
def normalize_marker_expression(expression: str) -> str:
    """Expand the documented provider marker alias without substring matches."""
    return _PROVIDER_MARKER_PATTERN.sub(
        "(setup_drift or setup_provider)", expression
    )


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_pytest_routing_plugin_normalizes_provider_marker_tokens
# @matrix setup testing : pytest-markers
def pytest_configure(config) -> None:
    """Apply runner-owned marker aliases before pytest evaluates collection."""
    expression = str(getattr(config.option, "markexpr", "") or "")
    config.option.markexpr = normalize_marker_expression(expression)


# @testable false
# @covered-by runner/pytest_routing.py::normalize_pytest_invocation
def _consume_runner_separator(arguments: list[str]) -> list[str]:
    routed = list(arguments)
    try:
        routed.remove("--")
    except ValueError:
        pass
    return routed


# @testable false
# @covered-by runner/pytest_routing.py::normalize_pytest_invocation
def _expand_targets(
    targets: list[str], marker_expression: str
) -> tuple[str, ...]:
    aliases = [target for target in targets if target in TEST_SUITE_ALIASES]
    explicit = [target for target in targets if target not in TEST_SUITE_ALIASES]
    if aliases and explicit:
        raise PytestRoutingError(
            "suite aliases cannot be combined with explicit pytest paths or "
            "nodeids; choose aliases only or paths only"
        )

    selected_markers = set(_MARKER_TOKEN_PATTERN.findall(marker_expression))
    normalized = []
    for target in targets:
        if target not in TEST_SUITE_ALIASES:
            if target.startswith("@"):
                raise PytestRoutingError(
                    "pytest argument files cannot select test targets through "
                    "run.py; pass real paths or nodeids directly"
                )
            normalized.append(target)
            continue

        normalized.extend(TEST_SUITE_ALIASES[target])
        if target == "setup":
            for marker, opt_in_targets in SETUP_OPT_IN_TESTS.items():
                if marker in selected_markers:
                    normalized.extend(opt_in_targets)

    return tuple(normalized)


# @testable false
# @covered-by runner/pytest_routing.py::targets_include_e2e
def _target_path(target: str, repository_root: Path) -> Path:
    path_text = target.replace("\\", "/").split("::", 1)[0]
    path = Path(path_text)
    if not path.is_absolute():
        path = repository_root / path
    return path.resolve(strict=False)


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_normalize_pytest_invocation_routes_registered_option_values
# @tests tests_tooling/test_007_run_py_test_command.py::test_normalized_targets_control_actual_pytest_collection
# @matrix testing : cli-routing target-selection
def targets_include_e2e(
    targets: tuple[str, ...], repository_root: Path
) -> bool:
    """Return whether targets collect from or above the repository E2E root."""
    e2e_root = (repository_root / "testing/tests_e2e").resolve()
    for target in targets:
        target_path = _target_path(target, repository_root)
        if target_path == e2e_root:
            return True
        if target_path.is_relative_to(e2e_root):
            return True
        if e2e_root.is_relative_to(target_path):
            return True
    return False


# @testable true
# @tests tests_tooling/test_007_run_py_test_command.py::test_normalize_pytest_invocation_routes_registered_option_values
# @tests tests_tooling/test_007_run_py_test_command.py::test_normalize_pytest_invocation_rejects_ambiguous_or_indirect_targets
# @tests tests_tooling/test_007_run_py_test_command.py::test_normalize_pytest_invocation_adds_setup_opt_in_targets_without_filenames
# @matrix setup : cli-routing opt-in pytest-markers
# @matrix testing : cli-routing opt-in pytest-markers pytest-options target-selection
def normalize_pytest_invocation(
    test_args: list[str], repository_root: Path
) -> PytestInvocation:
    """Parse and normalize a runner request with pytest's configured parser."""
    from _pytest.config import _prepareconfig
    from _pytest.config.exceptions import UsageError

    routed_args = _consume_runner_separator(test_args)
    indexed_args = [
        _IndexedArgument(argument, index)
        for index, argument in enumerate(routed_args)
    ]
    parser_args = [
        "-c",
        PYTEST_CONFIG,
        "--noconftest",
        *indexed_args,
    ]
    traceability_plugin = importlib.import_module(TRACEABILITY_RESULTS_PLUGIN)

    previous_cwd = Path.cwd()
    config = None
    try:
        os.chdir(repository_root)
        try:
            config = _prepareconfig(
                parser_args,
                plugins=[sys.modules[__name__], traceability_plugin],
                prog="run.py test",
            )
        except UsageError as error:
            raise PytestRoutingError(str(error)) from error

        namespace = config.known_args_namespace
        disabled_plugins = {
            str(plugin).removeprefix("no:")
            for plugin in getattr(config.option, "plugins", ())
            if str(plugin).startswith("no:")
        }
        reserved_plugins = {
            PYTEST_ROUTING_PLUGIN,
            TRACEABILITY_RESULTS_PLUGIN,
        }
        if disabled_plugins.intersection(reserved_plugins):
            raise PytestRoutingError(
                "run.py's routing and traceability pytest plugins cannot be "
                "disabled"
            )
        if bool(getattr(namespace, "pyargs", False)):
            raise PytestRoutingError(
                "--pyargs selection is not supported by run.py; pass real pytest "
                "paths or nodeids"
            )

        parsed_targets = list(getattr(namespace, "file_or_dir", ()))
        hidden_targets = [
            str(target)
            for target in parsed_targets
            if not isinstance(target, _IndexedArgument)
        ]
        if hidden_targets:
            raise PytestRoutingError(
                "pytest configuration or PYTEST_ADDOPTS cannot provide collection "
                "targets; pass them directly to run.py test"
            )

        target_indexes = {
            target.argument_index
            for target in parsed_targets
            if isinstance(target, _IndexedArgument)
        }
        requested_targets = [
            str(indexed_args[index]) for index in sorted(target_indexes)
        ]
        marker_expression = normalize_marker_expression(
            str(getattr(config.option, "markexpr", "") or "")
        )
        normalized_targets = _expand_targets(
            requested_targets, marker_expression
        )

        passthrough = [
            str(argument)
            for index, argument in enumerate(indexed_args)
            if index not in target_indexes and argument != "--strict"
        ]
        pytest_args = (*passthrough, *normalized_targets)
        collection_targets = (
            normalized_targets
            if requested_targets
            else tuple(str(target) for target in config.args)
        )
        strict_relations = bool(
            getattr(config.option, "strict", False)
        )
        return PytestInvocation(
            pytest_args=pytest_args,
            collection_targets=collection_targets,
            strict_relations=strict_relations,
            includes_e2e=targets_include_e2e(
                collection_targets, repository_root
            ),
        )
    finally:
        if config is not None:
            config._ensure_unconfigure()
        os.chdir(previous_cwd)
