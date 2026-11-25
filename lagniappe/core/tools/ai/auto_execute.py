"""App-wide opt-in automatic plan execution policy and safety-review guards."""

from collections.abc import Mapping
import re

from lagniappe import CONFIG
from lagniappe.core.definitions import AI

from .settings import runtime_ai_settings


OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
PROPOSAL_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
DELETE_ACTION_TYPES = frozenset(
    {
        "delete_page",
        "delete_task",
        "delete_category",
        "delete_project",
        "delete_model_task",
        "delete_file",
    }
)


def site_auto_execute_enabled(config: object = CONFIG) -> bool:
    """Return True only when AI is enabled and the live site setting allows auto-execution."""
    if not getattr(config, "AI_ENABLED", False):
        return False
    return bool(runtime_ai_settings(config=config).get("AI_AUTO_EXECUTE", False))


def experiments_execution_allowed(
    user: object,
    *,
    remote_mcp: bool = False,
    config: object = CONFIG,
) -> bool:
    """Designated Administrator agent execution preset for experiments installations."""
    return bool(
        remote_mcp
        and getattr(config, "EXPERIMENTS_ENABLED", False)
        and getattr(config, "EXPERIMENTS_EXECUTION_ENABLED", False)
        and getattr(config, "EXPERIMENTS_PROJECT", None)
        == getattr(config, "GOOGLE_CLOUD_PROJECT", None)
        and getattr(config, "AI_ENABLED", False)
        and getattr(config, "EXTERNAL_AI_ENABLED", False)
        and getattr(config, "AGENT_ACCESS_ENABLED", False)
        and user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_admin", False)
        and not getattr(user, "is_public", False)
        and str(getattr(user, "email", "") or "").strip().casefold()
        == str(getattr(config, "AGENT_ACCESS_EMAIL", "") or "").strip().casefold()
    )


def user_auto_execute_enabled(user: object, *, config: object = CONFIG) -> bool:
    """Return True when both site policy and this non-public user allow auto-execution."""
    return bool(
        site_auto_execute_enabled(config=config)
        and user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", True)
        and not getattr(user, "is_public", False)
        and getattr(user, "allow_auto_execute", False)
    )


def can_execute_external_plan(
    user: object,
    *,
    remote_mcp: bool = False,
    config: object = CONFIG,
) -> bool:
    """Return True when an authenticated API or remote-MCP caller may trigger plan execution."""
    if not getattr(config, "AI_ENABLED", False) or not getattr(
        config, "EXTERNAL_AI_ENABLED", False
    ):
        return False
    if experiments_execution_allowed(user, remote_mcp=remote_mcp, config=config):
        return True
    return user_auto_execute_enabled(user, config=config)


def can_auto_execute_onsite_plan(user: object, *, config: object = CONFIG) -> bool:
    """Return True when an on-site Create a Plan request may auto-run safe proposals.

    The user's saved ``allow_auto_execute`` sets the checkbox default on Home and
    gates unattended external API/MCP execution; an explicit on-site checkbox
    selection is honored whenever site auto-execution and ``AI.CREATE`` are active.
    """
    if not (
        site_auto_execute_enabled(config=config)
        and user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", True)
        and not getattr(user, "is_public", False)
    ):
        return False
    access = getattr(user, "access", None)
    return bool(callable(access) and access(AI.CREATE))


def review_required_reason(proposal: Mapping[str, object] | None) -> str | None:
    """Return a human-readable pause reason if the proposal must stop for browser review."""
    if not isinstance(proposal, Mapping):
        return None
    actions = proposal.get("actions")
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, Mapping):
                continue
            action_type = action.get("type")
            if action_type == "update_form_schema":
                return (
                    "Paused for browser review because this plan changes a form schema."
                )
        for action in actions:
            if not isinstance(action, Mapping):
                continue
            if action.get("type") in DELETE_ACTION_TYPES:
                return (
                    "Paused for browser review because this plan deletes workspace records."
                )
        for action in actions:
            if not isinstance(action, Mapping):
                continue
            if action.get("type") == "needs_review":
                return (
                    "Paused for browser review because this plan includes items that need manual review."
                )
    issues = proposal.get("issues")
    if isinstance(issues, list) and any(str(item or "").strip() for item in issues):
        return (
            "Paused for browser review because the planner flagged issues to check."
        )
    return None


def plan_requires_review(report: object, *, enforce_safety_pause: bool = True) -> str | None:
    """Return why a Plan cannot execute automatically, or None if eligible."""
    manifest = getattr(report, "agent_manifest", None)
    if isinstance(manifest, Mapping) and manifest.get("require_review") is True:
        return "This plan was marked for browser review before running."
    if enforce_safety_pause:
        return review_required_reason(getattr(report, "proposal", None))
    return None
