"""Opt-in, project-bound experiments installation settings."""

import re


# @testable true
# @tests tests_tooling/test_001l_setup_experiments.py::test_experiments_settings_are_opt_in_and_project_bound
# @matrix experiments : configuration
def normalize_experiments_config(settings):
    """Validate execution and diagnostics without creating application authority."""
    enabled = settings.get("EXPERIMENTS_ENABLED", False)
    execution = settings.get("EXPERIMENTS_EXECUTION_ENABLED", False)
    for name, value in (
        ("EXPERIMENTS_ENABLED", enabled),
        ("EXPERIMENTS_EXECUTION_ENABLED", execution),
    ):
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")
    mode = settings.get("EXPERIMENTS_DIAGNOSTICS", "off")
    if not isinstance(mode, str) or mode not in {"off", "summary", "trace"}:
        raise ValueError("EXPERIMENTS_DIAGNOSTICS must be off, summary, or trace")
    project = str(settings.get("EXPERIMENTS_PROJECT") or "").strip()
    source = str(settings.get("EXPERIMENTS_SOURCE_ID") or "").strip()
    if source and not re.fullmatch(r"[a-f0-9]{64}", source):
        raise ValueError("EXPERIMENTS_SOURCE_ID must be a SHA-256 digest")
    if not enabled and (execution or mode != "off"):
        raise ValueError(
            "Experiments execution and diagnostics require EXPERIMENTS_ENABLED"
        )
    if enabled:
        if not project or project != settings.get("GOOGLE_CLOUD_PROJECT"):
            raise ValueError("EXPERIMENTS_PROJECT must match GOOGLE_CLOUD_PROJECT")
        owner = str(settings.get("ADMIN_EMAIL") or "").strip().casefold()
        agent = str(settings.get("AGENT_ACCESS_EMAIL") or "").strip().casefold()
        if not owner or not agent or owner == agent or "@" not in agent:
            raise ValueError(
                "Experiments require distinct Owner and agent email identities"
            )
    return {
        "EXPERIMENTS_ENABLED": enabled,
        "EXPERIMENTS_EXECUTION_ENABLED": execution,
        "EXPERIMENTS_DIAGNOSTICS": mode,
        "EXPERIMENTS_PROJECT": project,
        "EXPERIMENTS_SOURCE_ID": source,
    }
