"""Final full-E2E structural baseline for durable efficiency evidence."""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import tracemalloc
from urllib.parse import urlsplit

from flask import g
from google.cloud.datastore import Entity as DatastoreEntity
from playwright.sync_api import expect
import pytest

from lagniappe import CONFIG
from lagniappe.core.definitions import DeferredJobSpec, DeferredJobType, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools import ai, database, deferred_job_adapters
from lagniappe.core.tools.cache import filter_cache
from lagniappe.core.tools.database import assets as storage_assets
from lagniappe.core.tools.database.core import KINDS
from lagniappe.core.tools.database.filter import Query
from lagniappe.core.tools.filters.cache import FilterCache
from lagniappe.core.tools.deferred_jobs import DeferredJobs
from lagniappe.web import app as web_app
from lagniappe.web.routes.process import main as process_main
from testing.definitions import Pages, SitePages, Tasks, Users
from testing.utility.structural_evidence import (
    COMPONENT_REFRESH_INSTRUMENTATION,
    canonical_json_bytes,
    dataset_inventory,
    entity_load_summary,
    prompt_evidence,
    stable_key,
    write_evidence,
)


pytestmark = [pytest.mark.e2e, pytest.mark.structural_evidence]
FIELD_ID = "input-textab12"


def _result_size(value):
    if value is None:
        return 0
    if hasattr(value, "results"):
        return len(value.results)
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return 1


def _argument_count(args):
    count = 0
    for value in args:
        count += len(value) if isinstance(value, (list, tuple, set)) else 1
    return count


class WorkflowProbe:
    """Count local request structure while leaving application behavior intact."""

    def __init__(self, monkeypatch):
        self.active = None
        self.records = {}
        self._install(monkeypatch)

    def _bump(self, section, operation, amount=1):
        if not self.active:
            return
        bucket = self.records[self.active][section]
        bucket[operation] = bucket.get(operation, 0) + amount

    def _install(self, monkeypatch):
        def wrap_read(owner, name, operation, *, input_count=False):
            original = getattr(owner, name)

            @wraps(original)
            def wrapped(*args, **kwargs):
                result = original(*args, **kwargs)
                argument_count = _argument_count(args)
                if operation == "get_many" and not argument_count:
                    return result
                if operation == "get_one" and (
                    not args
                    or args[0] is None
                    or isinstance(args[0], DatastoreEntity)
                ):
                    return result
                self._bump("datastore_requests", operation)
                if input_count:
                    self._bump(
                        "datastore_input_keys",
                        operation,
                        argument_count,
                    )
                self._bump(
                    "datastore_returned_rows",
                    operation,
                    _result_size(result),
                )
                return result

            monkeypatch.setattr(owner, name, wrapped)

        wrap_read(database.get, "entity", "get_one", input_count=True)
        wrap_read(database.get, "entities", "get_many", input_count=True)
        for method in ("fetch", "fetch_all", "fetch_one"):
            wrap_read(Query, method, f"query_{method}")

        original_save = database.save

        @wraps(original_save)
        def save(*entities, **kwargs):
            result = original_save(*entities, **kwargs)
            self._bump("datastore_writes", "save_calls")
            self._bump("datastore_writes", "saved_entities", len(entities))
            return result

        monkeypatch.setattr(database, "save", save)

        for method in ("create", "get", "delete", "exists", "set"):
            original = getattr(filter_cache, method)

            def cache_call(*args, _method=method, _original=original, **kwargs):
                result = _original(*args, **kwargs)
                self._bump("redis_json_requests", _method)
                return result

            monkeypatch.setattr(filter_cache, method, cache_call)

        for method in (
            "direct_upload_file",
            "delete_direct_upload",
            "download_file",
            "file_size",
        ):
            if not hasattr(storage_assets, method):
                continue
            original = getattr(storage_assets, method)

            def storage_call(*args, _method=method, _original=original, **kwargs):
                result = _original(*args, **kwargs)
                self._bump("storage_requests", _method)
                return result

            monkeypatch.setattr(storage_assets, method, storage_call)

    @contextmanager
    def measure(self, name):
        self.active = name
        self.records[name] = {
            "datastore_requests": {},
            "datastore_input_keys": {},
            "datastore_returned_rows": {},
            "datastore_writes": {},
            "redis_json_requests": {},
            "storage_requests": {},
        }
        already_tracing = tracemalloc.is_tracing()
        if not already_tracing:
            tracemalloc.start()
        before_bytes = tracemalloc.get_traced_memory()[0]
        tracemalloc.reset_peak()
        g.entity_loads = []
        try:
            yield self.records[name]
        finally:
            _, peak_bytes = tracemalloc.get_traced_memory()
            self.records[name]["peak_python_allocated_bytes"] = max(
                0, peak_bytes - before_bytes
            )
            self.records[name]["entity_loads"] = entity_load_summary(
                getattr(g, "entity_loads", ())
            )
            self.records[name]["datastore_request_count"] = sum(
                self.records[name]["datastore_requests"].values()
            )
            self.records[name]["datastore_write_count"] = self.records[name][
                "datastore_writes"
            ].get(
                "save_calls",
                0,
            )
            self.records[name]["redis_json_request_count"] = sum(
                self.records[name]["redis_json_requests"].values()
            )
            self.records[name]["storage_request_count"] = sum(
                self.records[name]["storage_requests"].values()
            )
            if not already_tracing:
                tracemalloc.stop()
            self.active = None

    def run(self, name, function):
        with web_app.test_request_context(f"/evidence/{name}"):
            with self.measure(name):
                return function()


def _all_datastore_rows():
    return {
        kind.value: Query(kind).fetch_all()
        for kind in KINDS
    }


def _notification(owner, target, body):
    notification = Entities.NOTIFICATION.create(
        {
            "parent": owner,
            "target": target,
            "body": body,
            "pending": True,
        }
    )
    Entities.save(notification, owner)
    return notification


def _run_job(job_type, owner, inputs, parameters=None):
    job, _notification = DeferredJobs.start(
        DeferredJobSpec(
            job_type=job_type,
            actor=owner,
            inputs=inputs,
            parameters=parameters or {},
        )
    )
    return DeferredJobs.run(job.urlsafe_key)


def _report(owner, name):
    report = Entities.REPORT.create(
        {
            "parent": owner,
            "user": owner,
            "name": name,
            "tool": "organize",
            "instructions": (
                "Review the accumulated test workspace and propose a minimal "
                "organization plan without deleting records."
            ),
            "input_files": [],
            "status": "pending",
            "pending": True,
        }
    )
    Entities.save(report, owner)
    return report


def _prior_failures(request):
    failures = []
    for item in request.session.items:
        if item is request.node:
            break
        if any(
            getattr(getattr(item, f"rep_{phase}", None), "failed", False)
            for phase in ("setup", "call", "teardown")
        ):
            failures.append(item.nodeid)
    return failures


def _network_record(responses, failed_requests):
    rows = Counter()
    response_bytes = Counter()
    request_bytes = Counter()
    for response in responses:
        request = response.request
        parsed = urlsplit(response.url)
        updated = response.headers.get("x-lagniappe-updated", "missing")
        key = (request.method, parsed.path, response.status, updated)
        rows[key] += 1
        post_data = request.post_data or ""
        request_bytes[key] += len(post_data.encode("utf-8"))
        try:
            response_bytes[key] += len(response.body())
        except Exception:
            pass

    routes = [
        {
            "method": key[0],
            "path": key[1],
            "status": key[2],
            "updated_header": key[3],
            "requests": count,
            "request_body_bytes": request_bytes[key],
            "response_body_bytes": response_bytes[key],
        }
        for key, count in sorted(rows.items())
    ]
    failures = [
        {
            "method": request.method,
            "path": urlsplit(request.url).path,
        }
        for request in failed_requests
    ]
    return {
        "requests": sum(rows.values()) + len(failures),
        "responses": sum(rows.values()),
        "failed_requests": failures,
        "request_body_bytes": sum(request_bytes.values()),
        "response_body_bytes": sum(response_bytes.values()),
        "updated_headers": dict(
            Counter(
                row["updated_header"]
                for row in routes
                for _ in range(row["requests"])
            )
        ),
        "routes": routes,
    }


def _reconnect_evidence(get_user):
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)
    home.task_list
    home.page_list
    home.project_list
    home.category_list
    home.activity_list
    home.starred_list
    home._open_loaded_list(home.TOOL_REPORT_LIST, home.TOOL_REPORT_LIST_TOGGLE)

    search = user.page.locator("[lp-search] input")
    search.focus()
    user.offline = True
    expect(user.locate("[data-role='offline']")).to_be_visible()

    instrumentation = """
        () => {
            const view = document.querySelector("[lp-view]")?._lp_view;
            if (!view) throw new Error("The active view was not initialized");
            const identity = (elt) => elt ? {
                tag: elt.tagName.toLowerCase(),
                id: elt.id || null,
                name: elt.getAttribute("name"),
                role: elt.getAttribute("role"),
                widget: elt.closest("[data-widget]")?.dataset.widget || null,
            } : null;
            const activeWidgets = () => Object.fromEntries(
                Object.entries(view.components).map(([name, component]) => [
                    name,
                    component.active?.name || null,
                ]),
            );
            const stats = {
                complete: false,
                view_refreshes: 0,
                component_refreshes: {},
                widget_reconciliations: {},
                mutation_records: 0,
                added_nodes: 0,
                removed_nodes: 0,
                attribute_changes: 0,
                text_changes: 0,
                before: {
                    dom_nodes: document.querySelectorAll("*").length,
                    focus: identity(document.activeElement),
                    active_widgets: activeWidgets(),
                    components: Object.keys(view.components).length,
                    loaded_widgets: Object.values(view.components).reduce(
                        (count, component) => count + Object.keys(component.widgets).length,
                        0,
                    ),
                },
            };
            window.__structuralEvidence = stats;

            const instrumentComponentRefreshes =
                __COMPONENT_REFRESH_INSTRUMENTATION__;
            instrumentComponentRefreshes(view.components, stats);

            const viewRefresh = view.refresh.bind(view);
            view.refresh = async (...args) => {
                stats.view_refreshes += 1;
                return await viewRefresh(...args);
            };
            const viewSync = view.sync.bind(view);
            view.sync = async (...args) => {
                const observer = new MutationObserver((records) => {
                    stats.mutation_records += records.length;
                    for (const record of records) {
                        stats.added_nodes += record.addedNodes?.length || 0;
                        stats.removed_nodes += record.removedNodes?.length || 0;
                        if (record.type === "attributes") stats.attribute_changes += 1;
                        if (record.type === "characterData") stats.text_changes += 1;
                    }
                });
                observer.observe(document.documentElement, {
                    subtree: true,
                    childList: true,
                    attributes: true,
                    characterData: true,
                });
                try {
                    return await viewSync(...args);
                } finally {
                    observer.disconnect();
                    stats.after = {
                        dom_nodes: document.querySelectorAll("*").length,
                        focus: identity(document.activeElement),
                        active_widgets: activeWidgets(),
                    };
                    stats.complete = true;
                }
            };
        }
        """
    instrumentation = instrumentation.replace(
        "__COMPONENT_REFRESH_INSTRUMENTATION__",
        COMPONENT_REFRESH_INSTRUMENTATION,
    )
    user.page.evaluate(instrumentation)

    responses = []
    failed_requests = []
    origin = urlsplit(user.page.url).netloc

    def capture_response(response):
        if urlsplit(response.url).netloc == origin:
            responses.append(response)

    def capture_failure(request):
        if urlsplit(request.url).netloc == origin:
            failed_requests.append(request)

    user.page.on("response", capture_response)
    user.page.on("requestfailed", capture_failure)
    try:
        user.offline = False
        user.page.wait_for_function(
            "() => window.__structuralEvidence?.complete === true",
            timeout=30000,
        )
        browser = user.page.evaluate("window.__structuralEvidence")
    finally:
        user.page.remove_listener("response", capture_response)
        user.page.remove_listener("requestfailed", capture_failure)

    browser["focus_preserved"] = (
        browser["before"]["focus"] == browser["after"]["focus"]
    )
    browser["active_widgets_preserved"] = (
        browser["before"]["active_widgets"] == browser["after"]["active_widgets"]
    )
    browser["network"] = _network_record(responses, failed_requests)
    failures = browser["network"]["failed_requests"]
    intentional_failures = [
        failure
        for failure in failures
        if failure == {"method": "HEAD", "path": "/ping"}
    ]
    unexpected_failures = [
        failure for failure in failures if failure not in intentional_failures
    ]
    browser["network"]["intentional_failed_requests"] = intentional_failures
    browser["network"]["unexpected_failed_requests"] = unexpected_failures
    assert browser["view_refreshes"] == 1
    assert intentional_failures
    assert not unexpected_failures
    return browser


def test_structural_evidence_after_full_e2e_suite(
    get_user,
    monkeypatch,
    request,
):
    """Regenerate the no-timing baseline immediately before E2E teardown."""
    rows_by_kind = _all_datastore_rows()
    dataset = dataset_inventory(rows_by_kind)
    prior_failures = _prior_failures(request)
    record = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "collector_complete": False,
        "suite_clean": not prior_failures,
        "prior_failures": prior_failures,
        "collection": request.config._structural_evidence_collection,
        "measurement_policy": {
            "excluded": ["wall-clock time", "request speed", "provider speed"],
            "reason": (
                "The managed server and providers are local or environment-dependent; "
                "speed values would not be comparable or actionable."
            ),
        },
        "dataset": dataset,
        "workflows": {},
    }
    probe = WorkflowProbe(monkeypatch)
    prompts = {}

    monkeypatch.setattr(CONFIG, "DEBUG_TRACING", True)

    def fake_autofill(prompt):
        prompts[probe.active] = prompt_evidence(prompt)
        return {FIELD_ID: "Full-suite structural evidence"}

    def fake_organize(prompt):
        prompts[probe.active] = prompt_evidence(prompt)
        return {
            "summary": "No structural changes are required by this baseline.",
            "confidence": 1,
            "issues": [],
            "actions": [],
        }

    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "generate_autofilled_submission",
        fake_autofill,
    )
    monkeypatch.setattr(
        deferred_job_adapters.ai,
        "generate_organize_plan",
        fake_organize,
    )
    try:
        owner_browser = get_user(Users.OWNER)
        owner = Entities.USER.load(owner_browser.email)
        assert owner is not None

        top_projects = dataset["project_task_distribution"]["top_projects"]
        assert top_projects, "The accumulated E2E dataset has no project tasks"
        project_row = top_projects[0]
        project = Entities.fetch_one(project_row["key"], request=Fetch.direct())
        assert isinstance(project, Entities.PROJECT)
        project_cache = FilterCache(project, owner)
        filter_cache.delete(project_cache.cache_key)

        probe.run("project_filter_cache", project_cache.cache)
        stored_cache = filter_cache.get(project_cache.cache_key)
        assert stored_cache == project_cache._to_cache
        probe.records["project_filter_cache"].update(
            {
                "representative_data": {
                    "project_key": stable_key(project),
                    "task_count": project_row["task_count"],
                },
                "cache_entries": len(project_cache._to_cache) - int(
                    "access" in project_cache._to_cache
                ),
                "serialized_bytes": len(canonical_json_bytes(project_cache._to_cache)),
                "published_cache_matches_build": True,
            }
        )

        page = Entities.fetch_one(
            Pages.test_page_autofill.get(owner_browser).key,
            request=Fetch.direct(),
        )
        task = Entities.fetch_one(
            Tasks.test_task_autofill.get(owner_browser).key,
            request=Fetch.direct(),
        )
        assert page and task

        page_result = probe.run(
            "ai_page_autofill",
            lambda: _run_job(
                DeferredJobType.AUTOFILL,
                owner,
                {"target": page},
                {
                    "user_context": (
                        "Use the accumulated page evidence to fill this form."
                    )
                },
            ),
        )
        probe.records["ai_page_autofill"]["prompt"] = prompts["ai_page_autofill"]
        assert page_result.success is True

        task_result = probe.run(
            "ai_task_autofill",
            lambda: _run_job(
                DeferredJobType.AUTOFILL,
                owner,
                {"target": task},
                {
                    "user_context": (
                        "Use the accumulated task and parent-page evidence."
                    )
                },
            ),
        )
        probe.records["ai_task_autofill"]["prompt"] = prompts["ai_task_autofill"]
        assert task_result.success is True

        report = _report(owner, "Structural organize generation evidence")
        generation_result = probe.run(
            "ai_organize_generation",
            lambda: _run_job(
                DeferredJobType.REPORT_ORGANIZE,
                owner,
                {"report": report},
            ),
        )
        probe.records["ai_organize_generation"]["prompt"] = prompts[
            "ai_organize_generation"
        ]
        assert generation_result.success is True

        report = Entities.fetch_one(report.urlsafe_key, request=Fetch.direct())
        report.properties.process.revise()
        Entities.save(report, owner)
        revision_result = probe.run(
            "ai_organize_revision",
            lambda: _run_job(
                DeferredJobType.REPORT_ORGANIZE,
                owner,
                {"report": report},
                {
                    "mode": "revise",
                    "feedback": "Keep the result read-only and make no changes.",
                },
            ),
        )
        probe.records["ai_organize_revision"]["prompt"] = prompts[
            "ai_organize_revision"
        ]
        assert revision_result.success is True

        category = Entities.CATEGORY.create(
            {"name": "Structural report execution evidence"}
        )
        Entities.save(category)
        execution_report = _report(owner, "Structural report execution evidence")
        execution_report.properties.process.set_proposal(
            {
                "summary": "Add one category to exercise deterministic execution.",
                "confidence": 1,
                "issues": [],
                "actions": [
                    {
                        "id": "structural-evidence-add-category",
                        "type": "add_category",
                        "display_label": "Add evidence category",
                        "data": {
                            "page": page.urlsafe_key,
                            "page_name": page.name,
                            "category": category.urlsafe_key,
                            "category_name": category.name,
                        },
                    }
                ],
            }
        )
        Entities.save(execution_report, owner)
        execution_result = probe.run(
            "ai_report_execution",
            lambda: ai.run_report(execution_report, owner),
        )
        probe.records["ai_report_execution"]["actions"] = len(
            execution_result["actions"]
        )
        assert execution_result["status"] == "complete"

        record["workflows"].update(probe.records)
        record["workflows"]["client_reconnect"] = _reconnect_evidence(get_user)
        record["collector_complete"] = True
    finally:
        record["workflows"].update(probe.records)
        write_evidence(record)

    assert record["collector_complete"] is True
