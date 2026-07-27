"""Seed packs for the managed browser test server.

The seed loader intentionally reuses the E2E definition/resource layer instead
of maintaining a parallel fixture format. Keep this module light at import time:
``run.py test-server --help`` imports it, and the app/entity modules must only
be imported after ``FLASK_ENV=testing`` is set.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import importlib
import json
import os
import sys
from typing import Iterable

from .artifacts import REPORTS_ROOT


LOAD_REPORT = REPORTS_ROOT / "test-server-load.json"


@dataclass(frozen=True)
class SeedItem:
    """One top-level definition enum member to load."""

    ref: str
    complete: bool = False
    note: str = ""


@dataclass(frozen=True)
class SeedPack:
    """Named collection of definition resources for browser review."""

    description: str
    resources: tuple[SeedItem, ...]
    landing_ref: str | None = None
    post_load: str | None = None


PROJECT_REVIEW = SeedPack(
    description="Project page review data with model tasks and filterable tasks.",
    landing_ref="Projects.test_filter_project",
    resources=(
        SeedItem(
            "Projects.test_filter_project",
            note="Project filter review landing page",
        ),
        SeedItem("Categories.test_create_page_task"),
        SeedItem("Pages.test_create_page_task"),
        SeedItem("Forms.test_project_filter_task_form"),
        SeedItem(
            "Users.create_user",
            note="Assignee used by the assigned-user filter",
        ),
        SeedItem("ModelTasks.test_filter_by_model_task"),
        SeedItem("ModelTasks.test_status_filter_model_task"),
        SeedItem("ModelTasks.test_filter_by_attached_form"),
        SeedItem("Tasks.test_filter_by_task_name"),
        SeedItem("Tasks.test_filter_by_due_date"),
        SeedItem("Tasks.test_filter_by_model_task"),
        SeedItem("Tasks.test_status_filter_completed", complete=True),
        SeedItem("Tasks.test_status_filter_in_progress"),
        SeedItem("Tasks.test_filter_by_assigned_user"),
        SeedItem("Tasks.test_filter_by_attached_form_match"),
        SeedItem("Tasks.test_filter_by_attached_form_nonmatch"),
    ),
)


CATEGORY_REVIEW = SeedPack(
    description="Category index review data with page filters and saved-filter fodder.",
    landing_ref="Categories.test_category_filter_pages",
    post_load="category-review",
    resources=(
        SeedItem(
            "Categories.test_category_filter_pages",
            note="Category filter review landing page",
        ),
        SeedItem("Forms.test_category_filter_page_form"),
        SeedItem(
            "Categories.test_category_filter_extra",
            note="Extra category assigned to the urgent filter page",
        ),
        SeedItem(
            "Pages.test_category_filter_match_page",
            note="Matches name, description, extra category, and form filters",
        ),
        SeedItem(
            "Pages.test_category_filter_nonmatch_page",
            note="Nonmatching page for filter contrast",
        ),
        SeedItem(
            "Pages.test_category_filter_public_document_page",
            note="Public page with a document asset for boolean filters",
        ),
    ),
)


PAGE_REVIEW = SeedPack(
    description="Page view review data with form submission and varied page tasks.",
    landing_ref="Pages.test_page_review",
    resources=(
        SeedItem(
            "Categories.test_basic_inputs_submission",
            note="Category with the default Basic Inputs page form",
        ),
        SeedItem(
            "Pages.test_page_review",
            note=(
                "Page review landing page; document starts empty for live "
                "editor review"
            ),
        ),
        SeedItem(
            "Users.create_user",
            note="Assignee used by the page review assigned task",
        ),
        SeedItem(
            "Projects.test_create_project_manual_mode",
            note="Project linked from one page review task",
        ),
        SeedItem("Tasks.test_page_review_active"),
        SeedItem("Tasks.test_page_review_due"),
        SeedItem("Tasks.test_page_review_assigned"),
        SeedItem("Tasks.test_page_review_project"),
        SeedItem("Tasks.test_page_review_form"),
        SeedItem("Tasks.test_page_review_completed", complete=True),
    ),
)


FORM_INDEX_REVIEW = SeedPack(
    description="Form index review data with page/task forms and related usage.",
    landing_ref="SitePages.FORM_INDEX",
    resources=(
        SeedItem(
            "Forms.test_create_page_form",
            note="Simple page form for create/open-builder review",
        ),
        SeedItem(
            "Forms.test_create_category_with_form",
            note="Basic page form linked from a category",
        ),
        SeedItem(
            "Forms.test_basic_inputs_form",
            note="Page form with representative input fields",
        ),
        SeedItem(
            "Forms.test_selection_types_form",
            note="Page form with checkbox/radio/select fields",
        ),
        SeedItem(
            "Forms.test_link_external_form",
            note="Page form with an external link field",
        ),
        SeedItem(
            "Forms.test_create_task_form",
            note="Task form linked from a project model task",
        ),
        SeedItem(
            "Forms.test_preview_panel",
            note="Page form with broad saved schema for preview review",
        ),
        SeedItem(
            "Forms.test_task_history_form",
            note="Task form with basic input fields",
        ),
        SeedItem(
            "Forms.test_project_filter_task_form",
            note="Task form with filter-oriented fields",
        ),
        SeedItem(
            "Categories.test_create_category_with_form",
            note="Category using Basic Page Form",
        ),
        SeedItem(
            "Categories.test_basic_inputs_submission",
            note="Category using Basic Inputs Form",
        ),
        SeedItem(
            "Categories.test_selection_types_submission",
            note="Category using Selection Types Form",
        ),
        SeedItem(
            "Categories.test_link_external_submission",
            note="Category using External Link Form",
        ),
        SeedItem(
            "Projects.test_create_project_manual_mode",
            note="Project for a model task that uses Basic Task Form",
        ),
        SeedItem("ModelTasks.test_create_model_task_with_form"),
        SeedItem(
            "Projects.test_filter_project",
            note="Project for a model task that uses Project Filter Task Form",
        ),
        SeedItem("ModelTasks.test_filter_by_attached_form"),
    ),
)


TASK_INDEX_REVIEW = SeedPack(
    description="Task index review data with varied active task rows.",
    landing_ref="SitePages.TASK_INDEX",
    resources=(
        SeedItem(
            "Categories.test_create_page_task",
            note="Category for the page-backed task index rows",
        ),
        SeedItem(
            "Pages.test_create_page_task",
            note="Shared page for page-backed task index rows",
        ),
        SeedItem(
            "Users.create_user",
            note="Assignee used by the assigned task row",
        ),
        SeedItem(
            "Projects.test_create_project_manual_mode",
            note="Project linked from one task index row",
        ),
        SeedItem(
            "Projects.test_page_tasks_multi_model",
            note="Project backing the model/form task row",
        ),
        SeedItem("ModelTasks.test_multi_model_beta_with_form"),
        SeedItem("Forms.test_task_history_form"),
        SeedItem(
            "Tasks.test_task_index_personal_today",
            note="Personal task due today; should appear in the active index",
        ),
        SeedItem(
            "Tasks.test_task_index_page_active",
            note="Undated page task; should appear after dated tasks",
        ),
        SeedItem(
            "Tasks.test_task_index_due_future",
            note="Future dated task for due-date ordering",
        ),
        SeedItem(
            "Tasks.test_task_index_assigned",
            note="Task with an assignee for hidden/visible column review",
        ),
        SeedItem(
            "Tasks.test_task_index_project_linked",
            note="Task linked to a project for row navigation review",
        ),
        SeedItem(
            "Tasks.test_task_index_model_form",
            note="Task linked to a model task with an attached form",
        ),
        SeedItem(
            "Tasks.test_task_index_form_submission",
            note="Task with saved attached-form submission",
        ),
        SeedItem(
            "Tasks.test_task_index_completed",
            complete=True,
            note=(
                "Completed contrast row; active task index should exclude it, "
                "but it remains visible from its page/project contexts"
            ),
        ),
    ),
)


USER_INDEX_REVIEW = SeedPack(
    description="User index review data with users, groups, and permission profiles.",
    landing_ref="SitePages.USER_INDEX",
    resources=(
        SeedItem(
            "Users.create_user",
            note="Plain user row for table and user-settings navigation review",
        ),
        SeedItem(
            "Users.create_user_from_index",
            note="Second plain user row for create-form/table contrast",
        ),
        SeedItem(
            "Groups.test_set_general_permissions",
            note="Manual group for general permission form review",
        ),
        SeedItem(
            "Groups.test_set_entity_specific_permissions",
            note="Manual group for entity-specific permission sections",
        ),
        SeedItem(
            "Groups.delete_group_refreshes_navigation",
            note="Extra group for group navigation/delete affordance review",
        ),
        SeedItem(
            "Groups.all_create",
            note="Group with broad create permissions",
        ),
        SeedItem("Users.admin"),
        SeedItem(
            "Groups.admin_cannot_create_users",
            note="Group with users assign but no users create permission",
        ),
        SeedItem("Users.admin_cannot_create_users"),
        SeedItem("Groups.general_models_view_only"),
        SeedItem("Users.general_models_view_only"),
        SeedItem("Groups.general_forms_view_only"),
        SeedItem("Users.general_forms_view_only"),
        SeedItem("Groups.general_users_view_only"),
        SeedItem("Users.general_users_view_only"),
        SeedItem(
            "Groups.models_create_forms_none",
            note="Group with model create and no form access",
        ),
        SeedItem("Users.models_create_forms_none"),
        SeedItem(
            "Groups.test_user_one_category",
            note="Entity-scoped category permission group",
        ),
        SeedItem("Users.user_one_category"),
        SeedItem("Groups.two_categories_edit_and_delete"),
        SeedItem("Users.two_categories_edit_and_delete"),
        SeedItem("Groups.page_acl_one_visible"),
        SeedItem("Users.page_acl_one_visible"),
        SeedItem("Groups.single_category_create"),
        SeedItem("Users.single_category_create"),
    ),
)


SEARCH_REVIEW = SeedPack(
    description="Search page review data with cross-facet filter results.",
    landing_ref="SitePages.SEARCH_PAGE",
    post_load="category-review",
    resources=(
        SeedItem(
            "Categories.test_category_filter_pages",
            note="Category result and parent for filter-oriented page results",
        ),
        SeedItem("Forms.test_category_filter_page_form"),
        SeedItem(
            "Categories.test_category_filter_extra",
            note="Second category result for facet contrast",
        ),
        SeedItem(
            "Pages.test_category_filter_match_page",
            note="Page result with matching name, description, categories, and form data",
        ),
        SeedItem(
            "Pages.test_category_filter_nonmatch_page",
            note="Page result that contrasts with the urgent page filters",
        ),
        SeedItem(
            "Pages.test_category_filter_public_document_page",
            note="Page result with a public document asset after post-load prep",
        ),
        SeedItem(
            "Projects.test_filter_project",
            note="Project result with several indexed task children",
        ),
        SeedItem("Forms.test_project_filter_task_form"),
        SeedItem(
            "Users.create_user",
            note="User result for secondary searches and assignee context",
        ),
        SeedItem("ModelTasks.test_filter_by_model_task"),
        SeedItem("ModelTasks.test_status_filter_model_task"),
        SeedItem("ModelTasks.test_filter_by_attached_form"),
        SeedItem("Tasks.test_filter_by_task_name"),
        SeedItem("Tasks.test_filter_by_due_date"),
        SeedItem("Tasks.test_filter_by_model_task"),
        SeedItem("Tasks.test_status_filter_in_progress"),
        SeedItem("Tasks.test_filter_by_assigned_user"),
        SeedItem("Tasks.test_filter_by_attached_form_match"),
        SeedItem("Tasks.test_filter_by_attached_form_nonmatch"),
        SeedItem(
            "Tasks.test_status_filter_completed",
            complete=True,
            note="Completed contrast task for completed/uncompleted search icon review",
        ),
    ),
)


PACKS = {
    "category-review": CATEGORY_REVIEW,
    "form-index-review": FORM_INDEX_REVIEW,
    "page-review": PAGE_REVIEW,
    "project-review": PROJECT_REVIEW,
    "search-review": SEARCH_REVIEW,
    "task-index-review": TASK_INDEX_REVIEW,
    "user-index-review": USER_INDEX_REVIEW,
}


def available_pack_names() -> tuple[str, ...]:
    """Return seed pack names safe to show in CLI help."""

    return tuple(sorted(PACKS))


def _ensure_testing_environment() -> None:
    os.environ["FLASK_ENV"] = "testing"

    if "lagniappe" not in sys.modules:
        return

    from lagniappe import CONFIG

    if not CONFIG.testing:
        raise RuntimeError(
            "test-server seed loading must run before importing app modules "
            "outside FLASK_ENV=testing."
        )


def _resolve_definition_ref(ref: str):
    definitions = importlib.import_module("testing.definitions")
    value = definitions
    for part in ref.split("."):
        value = getattr(value, part)
    return value


def _merged_items(pack_names: Iterable[str]) -> list[SeedItem]:
    merged: dict[str, SeedItem] = {}
    for pack_name in pack_names:
        try:
            pack = PACKS[pack_name]
        except KeyError as exc:
            available = ", ".join(available_pack_names())
            raise ValueError(
                f"Unknown test-server load pack {pack_name!r}. Available: {available}"
            ) from exc

        for item in pack.resources:
            existing = merged.get(item.ref)
            if existing:
                merged[item.ref] = SeedItem(
                    item.ref,
                    complete=existing.complete or item.complete,
                    note=existing.note or item.note,
                )
            else:
                merged[item.ref] = item

    return list(merged.values())


def _resource_url(resource) -> str | None:
    try:
        suffix = resource.url_suffix
    except Exception:
        return None

    if not suffix:
        return None
    if isinstance(suffix, str) and suffix.startswith("/"):
        return f"{resource._url_prefix.rstrip('/')}{suffix}"
    return resource.url


def _resource_name(resource, enum_member=None) -> str | None:
    try:
        name = resource.name
    except Exception:
        name = getattr(resource, "title", None)
    if name:
        return name
    if enum_member is not None:
        return enum_member.name.replace("_", " ").title()
    return None


def _resource_summary(ref: str, resource, item: SeedItem) -> dict[str, object]:
    entity = getattr(resource, "entity", None)
    summary = {
        "ref": ref,
        "name": _resource_name(resource),
        "resource": resource.__class__.__name__,
        "entity_kind": getattr(entity, "entity_kind", None),
        "key": getattr(resource, "key", None),
        "url": _resource_url(resource),
        "actions": [],
    }
    if item.complete:
        summary["actions"].append("complete")
    if item.note:
        summary["note"] = item.note
    return summary


def _write_report(summary: dict[str, object]) -> None:
    LOAD_REPORT.parent.mkdir(parents=True, exist_ok=True)
    LOAD_REPORT.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _prepare_category_review(owner) -> list[dict[str, str]]:
    from testing.definitions import Categories, Pages

    matching_page = Pages.test_category_filter_match_page.get(owner)
    public_document_page = Pages.test_category_filter_public_document_page.get(owner)
    extra_category = Categories.test_category_filter_extra.get(owner)

    matching_page.entity.properties.categories.add(extra_category.entity)
    matching_page.entity.save()

    public_document_page.entity.is_public = True
    public_document_page.entity.properties.document.save(
        html="<p>Category filter document marker.</p>"
    )
    public_document_page.entity.save()

    return [
        {
            "action": "add-extra-category",
            "page": matching_page.definition.name,
            "category": extra_category.definition.name,
        },
        {
            "action": "make-public-with-document",
            "page": public_document_page.definition.name,
        },
    ]


POST_LOAD_ACTIONS = {
    "category-review": _prepare_category_review,
}


def _run_post_load_actions(
    pack_names: Iterable[str],
    owner,
) -> list[dict[str, str]]:
    actions = []
    seen: set[str] = set()
    for pack_name in pack_names:
        post_load = PACKS[pack_name].post_load
        if not post_load or post_load in seen:
            continue
        seen.add(post_load)
        actions.extend(POST_LOAD_ACTIONS[post_load](owner))
    return actions


def load_packs(pack_names: Iterable[str]) -> dict[str, object]:
    """Load one or more seed packs into the testing datastore/cache."""

    pack_names = list(pack_names)
    if not pack_names:
        raise ValueError("At least one load pack is required.")

    _ensure_testing_environment()

    from lagniappe.core.entities import Entities
    from testing.definitions import Users

    Entities.initialize()
    owner = Users.OWNER.get(None)

    resources = []
    for item in _merged_items(pack_names):
        enum_member = _resolve_definition_ref(item.ref)
        resource = enum_member.get(owner)
        if item.complete:
            resource.mark_completed()
        resources.append(_resource_summary(item.ref, resource, item))

    post_load_actions = _run_post_load_actions(pack_names, owner)

    landings = []
    for pack_name in pack_names:
        landing_ref = PACKS[pack_name].landing_ref
        if not landing_ref:
            continue
        landing_enum = _resolve_definition_ref(landing_ref)
        landing = landing_enum.get(owner)
        landing_url = _resource_url(landing)
        if landing_url:
            landings.append(
                {
                    "pack": pack_name,
                    "ref": landing_ref,
                    "name": _resource_name(landing, landing_enum),
                    "url": landing_url,
                }
            )

    summary = {
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "packs": pack_names,
        "owner": {
            "name": owner.name,
            "email": owner.email,
            "key": owner.key,
        },
        "resources": resources,
        "post_load_actions": post_load_actions,
        "landings": landings,
    }
    _write_report(summary)
    return summary
