"""Provider report references preserve all evidence and the public tool contract."""

import json
from types import SimpleNamespace

import pytest

from lagniappe.core.tools.ai import functions
from lagniappe.core.tools.ai.report_payloads import ReportToolPayloads


@pytest.mark.unit
def test_report_reuses_an_identical_record_across_tool_responses(monkeypatch):
    task = {"hash": "hash:000000000001", "task_name": "First trial", "url": "/tasks/one",
            "Completed": False, "description": "Recorded evidence. " * 40}
    history = {"task": task, "history": [], "has_more": False}
    monkeypatch.setitem(functions.HANDLERS, "query_workspace_filter", lambda args, user: {"a/b~rows": [task]})
    monkeypatch.setitem(functions.HANDLERS, "get_task_history", lambda args, user: history)
    calls = [SimpleNamespace(name=name, args={}) for name in ("query_workspace_filter", "get_task_history")]
    user = SimpleNamespace()
    trace = []
    parts, files = functions.execute_function_calls(calls, user, trace=trace, report_payloads=ReportToolPayloads())
    first, second = [json.loads(part.function_response.response["result"]) for part in parts]
    assert first == {"a/b~rows": [task]}
    assert second == {**history, "task": {
        "hash": task["hash"], "url": task["url"], "task_name": task["task_name"], "Completed": False,
        "same_as_tool_result": {"tool": "query_workspace_filter", "occurrence": 1, "json_pointer": "/a~1b~0rows/0"},
    }}
    assert [part.function_response.name for part in parts] == [call.name for call in calls]
    assert trace[1]["result_chars"] == len(parts[1].function_response.response["result"]) < len(json.dumps(history))
    assert files == []
    external, _ = functions.execute_registered_tool("get_task_history", {}, user, external=True)
    assert external == {"task": task, "history": [], "has_more": False}
    full_parts, _ = functions.execute_function_calls([calls[1], calls[1]], user)
    assert all(json.loads(part.function_response.response["result"]) == history for part in full_parts)


@pytest.mark.unit
def test_only_matching_visible_form_snapshots_share_schema_and_edit_reads_stay_full():
    view = ReportToolPayloads()
    form = {"hash": "hash:000000000001", "form_name": "Review", "url": "/forms/one",
            "permissions": {"can_view": True}, "schema": [{"name": "Notes", "description": "Detail " * 80}]}
    def details(page_form):
        return {"category": {"Form": form}, "page": {"Form": page_form}}

    matching = json.loads(view.encode("get_page_details", details(form)))
    assert matching["category"]["Form"] == form
    assert matching["page"]["Form"]["same_as_tool_result"] == {
        "tool": "get_page_details", "occurrence": 1, "json_pointer": "/category/Form"}
    for difference in ({"hash": "hash:000000000002"}, {"schema": [{"name": "Changed"}]},
                       {"permissions": {"can_view": True, "can_edit": False}}):
        distinct = {**form, **difference}
        assert json.loads(view.encode("get_page_details", details(distinct)))["page"]["Form"] == distinct
    assert json.loads(view.encode("get_page_details", details(form), edit=True)) == details(form)
    assert json.loads(view.encode("get_schema", form)) == form
    assert json.loads(ReportToolPayloads().encode("get_entity", form)) == form
