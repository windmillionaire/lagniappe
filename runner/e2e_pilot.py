"""Opt-in coordinated protocol checks and automatically grouped browser stories."""

from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from runner.context import REPOSITORY_ROOT
from runner.e2e_parallel import Batch, merge_results, schedule
from runner.e2e_inventory import story_batches


PILOT_FILE = "testing/tests_e2e/001_site/test_001h_parallel_pilot.py"
CASES = ("independent-a", "independent-b", "shared-a", "shared-b", "exclusive")
PROTOCOL_TARGETS = tuple(f"{PILOT_FILE}::test_worker_page_and_task[{case}]" for case in CASES)
STORY_TARGETS = (
    'testing/tests_e2e/001_site/test_001a_environment.py::test_authenticated_home_response_headers_include_etag',
    'testing/tests_e2e/002_home/test_002b_home_projects.py::test_create_project_ai_mode',
    'testing/tests_e2e/002_home/test_002c_home_categories.py::test_create_category_ai_mode[quota-fallback]',
    'testing/tests_e2e/002_home/test_002e_home_starred.py::test_star_category',
    'testing/tests_e2e/002_home/test_002e_home_starred.py::test_star_project',
    'testing/tests_e2e/002_home/test_002e_home_starred.py::test_star_page',
    'testing/tests_e2e/003_forms/test_003b_form_builder.py::test_preview_panel',
    'testing/tests_e2e/003_forms/test_003b_form_builder.py::test_change_select_options',
    'testing/tests_e2e/003_forms/test_003a_forms.py::test_generate_form_schema_live_saved_state[quota-fallback]',
    'testing/tests_e2e/004_projects/test_004c_model_tasks.py::test_click_model_opens_info',
    'testing/tests_e2e/004_projects/test_004c_model_tasks.py::test_edit_model_task_name',
    'testing/tests_e2e/004_projects/test_004c_model_tasks.py::test_change_model_task_form',
    'testing/tests_e2e/004_projects/test_004c_model_tasks.py::test_delete_model_task_form',
    'testing/tests_e2e/004_projects/test_004d_document.py::test_editor_loads_and_saves_text',
    'testing/tests_e2e/004_projects/test_004j_editor_menus.py::test_compact_editor_menus',
    'testing/tests_e2e/004_projects/test_004j_editor_menus.py::test_list_menu_formats_selection',
    'testing/tests_e2e/004_projects/test_004j_editor_menus.py::test_table_menu_creates_edits_and_saves',
    'testing/tests_e2e/005_pages/test_005c_page_mobile_ui.py::test_page_mobile_nav_replaces_desktop_tabs',
    'testing/tests_e2e/005_pages/test_005c_page_mobile_ui.py::test_page_mobile_section_switching_updates_visible_panel_and_title',
    'testing/tests_e2e/005_pages/test_005c_page_mobile_ui.py::test_page_mobile_create_task_opens_from_tasks_section',
    'testing/tests_e2e/005_pages/test_005g_page_document_ai.py::test_generate_text_live_page_context_with_tasks_and_files[quota-fallback]',
    'testing/tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_basic_page_task',
    'testing/tests_e2e/006_tasks/test_006b_page_tasks.py::test_empty_page_task_list_shows_marker_only_after_create_closes',
    'testing/tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_form',
    'testing/tests_e2e/006_tasks/test_006b_page_tasks.py::test_complete_page_task',
    'testing/tests_e2e/006_tasks/test_006b_page_tasks.py::test_submit_attached_task_form',
    'testing/tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_visibility_persists_after_reload',
    'testing/tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_expands_table_submission_cell',
    'testing/tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_hiding_column_updates_visible_headers_and_cells',
    'testing/tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_name_column_sort_ascending_reorders_rows',
    'testing/tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_name_column_sort_descending_reorders_rows',
    'testing/tests_e2e/009_search/test_009a_search_page.py::test_search_from_navbar',
    'testing/tests_e2e/009_search/test_009a_search_page.py::test_search_returns_results',
    'testing/tests_e2e/009_search/test_009a_search_page.py::test_search_no_results',
    'testing/tests_e2e/009_search/test_009a_search_page.py::test_click_result_navigates',
    'testing/tests_e2e/011_files/test_011a_file_tabs.py::test_file_text_tab_renders_uploaded_text_content',
    'testing/tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_image_shows_desktop_preview',
    'testing/tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_pdf_renders_pdf_preview_widget',
    'testing/tests_e2e/011_files/test_011a_file_tabs.py::test_file_info_update_persists_name_and_summary',
    'testing/tests_e2e/012_messaging/test_012a_direct_messages.py::test_messages_page_uses_mobile_peer_selector_with_inline_reply',
    'testing/tests_e2e/008_users/test_008e_public_users.py::test_public_user_own_page_hides_photo_and_file_surfaces',
    'testing/tests_e2e/008_users/test_008e_public_users.py::test_public_user_edits_document_without_ai_or_image_tools',
    'testing/tests_e2e/008_users/test_008e_public_users.py::test_public_user_creates_task_with_reduced_schedule_options',
    'testing/tests_e2e/008_users/test_008g_site_settings.py::test_site_settings_sections_expand_help_and_configuration',
    'testing/tests_e2e/008_users/test_008g_site_settings.py::test_site_settings_public_page_indexing_saves_live_setting',
)
TARGETS = (*PROTOCOL_TARGETS, *STORY_TARGETS)


# @testable true
# @tests tests_tooling/test_015_e2e_parallel.py::test_pilot_arguments_are_bounded_and_keep_normal_runs_unchanged
# @matrix testing : parallel-e2e
def pilot_arguments(arguments):
    flags = [arg for arg in arguments if arg == "--experiments" or arg.startswith("--experiments=")]
    if not flags:
        return False, arguments
    if len(flags) != 1 or flags[0] not in {"--experiments", "--experiments=pilot", "--experiments=all"}:
        raise ValueError("Use --experiments or --experiments=all")
    scope = "all" if flags[0] == "--experiments=all" else "pilot"
    rest = [arg for arg in arguments if arg not in flags]
    if any(not arg.startswith("--junitxml=") for arg in rest):
        raise ValueError("test --experiments selects coordinated E2E tests; only --junitxml= is additional")
    return scope, [*rest, *(TARGETS if scope == "pilot" else ("e2e",))]


# @testable infrastructure
@contextmanager
def pilot_authority(local_authority):
    if local_authority is not None:
        yield local_authority
        return
    from lagniappe.core.tools.hosted_e2e.lease import E2ELease
    from runner.testing import cleanup_test_data, initialize_test_data, prepare_test_artifacts
    from testing.utility.e2e_runtime import validate_hosted_e2e_health

    validate_hosted_e2e_health()
    with E2ELease() as authority:
        try:
            cleanup_test_data(authority)
            initialize_test_data(authority)
            prepare_test_artifacts(authority)
            yield authority
        finally:
            authority.assert_active()
            cleanup_test_data(authority)


# @testable true
# @tests tests_e2e/001_site/test_001h_parallel_pilot.py::test_worker_page_and_task
# @matrix testing : parallel-e2e
def run_pilot(authority, command, pytest_args, *, scope="pilot"):
    from lagniappe import CONFIG
    from lagniappe.core.entities import Entities
    from runner.test_session import capture_process_identity, load_session_state
    from testing.utility.traceability_common import behavior_snapshot
    from testing.utility.traceability_results import _write_manifest

    authority.assert_active()
    Entities.initialize()
    attempt = uuid4().hex
    snapshot, _ = behavior_snapshot(REPOSITORY_ROOT)
    root = REPOSITORY_ROOT / "reports" / "e2e-pilot" / attempt
    root.mkdir(parents=True)
    shared = Entities.PAGE.create({"name": f"Pilot shared {attempt[:8]}"})
    shared.save()
    shared.remember_empty_notes()
    fixtures = {"shared_page": shared.urlsafe_key}
    owner = capture_process_identity(os.getpid())
    if owner is None:
        raise RuntimeError("Cannot identify E2E pilot coordinator")
    run_id = getattr(authority, "run_id", None) or authority.nonce
    cookies = ()
    if CONFIG.hosted_e2e_runner:
        from testing.utility.e2e_runtime import hosted_e2e_browser_cookie
        # Google may return the same single-use bootstrap token to concurrent
        # callers. Exchange once for the run, then share only its scoped cookie.
        cookies = (hosted_e2e_browser_cookie(run_id),)
    local = load_session_state() if not CONFIG.hosted_e2e_runner else None
    batches = [Batch(case, target, frozenset({"shared-page"}) if case.startswith("shared")
                     else frozenset(), exclusive=case == "exclusive")
               for case, target in zip(CASES, PROTOCOL_TARGETS)]
    collection = root / "collection.json"
    story_targets = STORY_TARGETS if scope == "pilot" else ("testing/tests_e2e", f"--ignore={PILOT_FILE}", "-m", "not unfinished")
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", "testing/pytest.ini", "--collect-only", "-q",
         "-p", "runner.e2e_inventory", *story_targets], cwd=REPOSITORY_ROOT,
        env={**os.environ, "LAGNIAPPE_E2E_COLLECTION": str(collection)},
        capture_output=True, text=True, timeout=120,
    )
    (root / "collection.log").write_text(collected.stdout + collected.stderr, encoding="utf-8")
    if collected.returncode:
        raise RuntimeError(f"Pilot collection failed; see {root / 'collection.log'}")
    stories, inventory = story_batches(REPOSITORY_ROOT, json.loads(collection.read_text(encoding="utf-8")))
    batches = ([batch for batch in stories if batch.name == "stories-before"] + batches
               + [batch for batch in stories if batch.name != "stories-before"])
    (root / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    for batch in stories:
        print(f"{batch.name}: {len(batch.nodeids)} cases, {len(batch.resources)} resources, "
              f"exclusive={batch.exclusive}", flush=True)
    destination = next((arg.split("=", 1)[1] for arg in pytest_args if arg.startswith("--junitxml=")),
                       str(root / "junit.xml"))
    statuses, events, scheduler_error = {}, [], None
    previous = {}
    launched = []
    next_progress = time.monotonic() + 30

    def check_authority():
        nonlocal next_progress
        authority.assert_active()
        now = time.monotonic()
        if now < next_progress:
            return
        next_progress = now + 30
        for name in launched:
            progress = root / name / "progress.json"
            if progress.is_file():
                counts = json.loads(progress.read_text(encoding="utf-8"))
                state = f"exit={statuses[name]}" if name in statuses else "running"
                print(f"{name}: {counts['completed']}/{counts['total']} complete, "
                      f"{counts['failed']} failed ({state}); {counts['last_nodeid']}", flush=True)

    def cancel(signum, frame):
        raise KeyboardInterrupt(f"E2E pilot cancelled by signal {signum}")

    with ExitStack() as stack:
        contexts = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="lagniappe-e2e-workers-")))

        def launch(batch):
            artifacts = root / batch.name
            artifacts.mkdir()
            record = {"attempt": attempt, "snapshot": snapshot, "batch": batch.name,
                      "nodeid": batch.nodeid, "nodeids": batch.nodeids, "run_id": run_id, "owner": owner,
                      "base_url": CONFIG.BASE_URL, "fixtures": fixtures,
                      "browser_cookies": cookies,
                      "resource_registry": str(contexts),
                      "server_pid": local["server"]["pid"] if local else None,
                      "artifacts": str(artifacts)}
            path = contexts / f"{batch.name}.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            path.chmod(0o600)
            output = stack.enter_context((artifacts / "pytest.log").open("w", encoding="utf-8"))
            child_command = [sys.executable, "-m", "pytest", "-c", "testing/pytest.ini",
                             "-p", "testing.utility.traceability_results", "-p", "runner.pytest_routing",
                             "-o", f"cache_dir={artifacts / 'pytest-cache'}",
                             f"--junitxml={artifacts / 'junit.xml'}", "-m", "not unfinished", *batch.nodeids]
            print(f"Pilot starting {batch.name}", flush=True)
            launched.append(batch.name)
            return subprocess.Popen(child_command, cwd=REPOSITORY_ROOT, start_new_session=True,
                                    stdout=output, stderr=subprocess.STDOUT,
                                    env={**os.environ, "LAGNIAPPE_E2E_WORKER_CONTEXT": str(path),
                                         "LAGNIAPPE_TEST_ARTIFACTS": str(artifacts)})

        try:
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous[signum] = signal.signal(signum, cancel)
            schedule(batches, launch, check_authority, workers=3, timeout=7200 if scope == "all" else 1800,
                     finished=statuses, events=events)
        except (OSError, RuntimeError, KeyboardInterrupt) as error:
            scheduler_error = str(error)
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)

    outcomes, errors = merge_results(batches, root, statuses, attempt=attempt,
                                     snapshot=snapshot, destination=destination)
    if scheduler_error:
        errors.append(scheduler_error)
    if behavior_snapshot(REPOSITORY_ROOT)[0] != snapshot:
        errors.append("Source changed during E2E pilot; results are not importable")
    status = int(bool(errors) or any(row["outcome"] == "failed" for row in outcomes.values()))
    summary = {"attempt": attempt, "source_snapshot": snapshot,
               "hosted": CONFIG.hosted_e2e_runner, "workers": 3, "scope": scope,
               "selected": [nodeid for batch in batches for nodeid in batch.nodeids],
               "batches": [{"name": b.name, "selected": b.nodeids, "resources": sorted(b.resources),
                            "exclusive": b.exclusive} for b in batches], "events": events,
               "exit_status": status, "errors": errors}
    (root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if not any("Source changed" in error for error in errors):
        _write_manifest(REPOSITORY_ROOT, command, outcomes, status)
    print(f"Pilot: {sum(row['outcome'] == 'passed' for row in outcomes.values())}/{len(outcomes)} passed; {root}", flush=True)
    for error in errors:
        print(error, flush=True)
    return status
