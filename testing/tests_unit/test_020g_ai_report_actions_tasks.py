"""Focused AI-report characterization coverage."""

from testing.utility.ai_report_fakes import *  # noqa: F403




# @pairs ai-report:deterministic-run ai-report:task-attachment ai-report:created-task
# @pairs ai-report:submission-completion ai-report:persistence
# @pairs tasks:task-attachment files:task-attachment
@pytest.mark.unit
def test_run_report_attach_file_to_task_targets_created_task(monkeypatch, get_schema):
    _patch_fake_keys(monkeypatch)
    user = _test_user("runner-task-file-owner")
    page = TestEntities.get("PAGE", {"name": "Medical", "hash": "medical-page"})
    form = TestEntities.get(
        "FORM",
        {"name": "Review", "hash": "review-task-form"},
    )
    form.form_type = "task"
    form.schema = get_schema("text_input_only")
    file = _test_file("sports-physical.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Task attachment report",
            "hash": "runner-task-attachment-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file],
            "proposal": {
                "summary": "Create a follow-up task.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "review_physical",
                        "type": "create_task",
                        "data": {
                            "name": "Review sports physical",
                            "description": "Review the uploaded sports physical.",
                            "page": page.urlsafe_key,
                            "form": form.urlsafe_key,
                            "submission": {
                                "input-textab12": "Physical reviewed.",
                                "unknown-field": "must not persist",
                            },
                        },
                    },
                    {
                        "id": "attach_physical",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "review_physical",
                            "file": file.urlsafe_key,
                        },
                    },
                ],
            },
        },
    )
    saved = []

    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({
            page.urlsafe_key: page,
            form.urlsafe_key: form,
        }),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete", result
    assert result["actions"][0]["type"] == "create_task"
    assert "attachments" not in result["actions"][0]
    attach_action = result["actions"][1]
    assert attach_action["type"] == "attach_file_to_task"
    assert attach_action["entity"]["id"] == file.urlsafe_key
    assert attach_action["target"]["kind"] == "task"
    tasks = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task"
    ]
    assert tasks[0].files == [file]
    assert tasks[0].submission == {"input-textab12": "Physical reviewed."}




# @features ai-report task-scheduling
# @dimensions structured-output recurring scheduled periodic validation normalization
@pytest.mark.unit
def test_report_task_schedule_contract_validates_supported_patterns():
    schema = report_proposal_response_schema(("create_task",))
    create_task_data = schema["properties"]["actions"]["items"]["anyOf"][0][
        "properties"
    ]["data"]
    assert create_task_data["properties"]["schedule"] == (
        report_schedules.task_schedule_response_schema()
    )
    assert create_task_data["properties"]["schedule"]["properties"]["days"][
        "items"
    ] == {"type": "integer"}
    assert report_schedules.validate_task_schedule(
        {"kind": "recurring", "interval": 2, "unit": "week"}
    ) == {"kind": "recurring", "interval": 2, "unit": "week"}
    assert report_schedules.validate_task_schedule(
        {
            "kind": "scheduled",
            "mode": "monthly",
            "pattern_type": "ordinal_weekday",
            "ordinal": -1,
            "weekday": 4,
            "description": "last Friday of the month",
        }
    ) == {
        "kind": "scheduled",
        "mode": "monthly",
        "pattern_type": "ordinal_weekday",
        "ordinal": -1,
        "weekday": 4,
        "description": "last Friday of the month",
        "user_prompt": "last Friday of the month",
    }
    with pytest.raises(exceptions.AIException, match="weekday"):
        report_schedules.validate_task_schedule(
            {"kind": "scheduled", "mode": "weekly", "days": [7]}
        )




# @features ai-report task-scheduling
# @dimensions persistence recurring
@pytest.mark.unit
def test_run_report_creates_task_with_reviewed_schedule(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("runner-scheduled-task-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "Household", "hash": "scheduled-task-page"},
    )
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Recurring filter reminder",
            "hash": "runner-scheduled-task-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Create a recurring reminder.",
                "confidence": 0.95,
                "actions": [
                    {
                        "id": "replace_filter",
                        "type": "create_task",
                        "data": {
                            "name": "Replace HVAC filter",
                            "page": page.urlsafe_key,
                            "schedule": {
                                "kind": "recurring",
                                "interval": 3,
                                "unit": "month",
                            },
                        },
                    }
                ],
            },
        },
    )
    saved = []
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({page.urlsafe_key: page}),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )

    result = report_runner.run_report(report, user)

    task = next(
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task"
    )
    assert task.processes["schedule"]["recurring"] == {
        "interval": 3,
        "unit": "month",
        "complete": True,
    }
    assert result["actions"][0]["schedule"] == {
        "kind": "recurring",
        "interval": 3,
        "unit": "month",
        "complete": True,
    }




# @features ai-report tasks task-completion
# @dimensions completed-task older-event name description attachments submission
@pytest.mark.unit
def test_run_report_records_older_completed_event_without_mutating_live_task(
    monkeypatch,
    get_schema,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("history-runner-owner")
    page = TestEntities.get("PAGE", {"name": "Jeep", "hash": "jeep-page"})
    form = TestEntities.get(
        "FORM",
        {"name": "Vehicle Service Form", "hash": "vehicle-service-form"},
    )
    form.schema = get_schema("text_input_only")
    task = TestEntities.get(
        "TASK",
        {
            "name": "Registration",
            "hash": "registration-task",
        },
        page=page,
    )
    task.form = form
    live_attachment = _test_file("current-task-note.pdf", "application/pdf")
    task.files = [live_attachment]
    task.completed = True
    task.completed_on = datetime(2024, 1, 1, tzinfo=timezone.utc)
    task.due_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    task.description = "Current registration details."
    page._completed = [task]
    file_one = _test_file("2023-06-24 jeep registration.pdf", "application/pdf")
    file_two = _test_file("dmv receipt.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Task history run report",
            "hash": "history-runner-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file_one, file_two],
            "proposal": {
                "summary": "Record Jeep registration history.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "registration_history",
                        "type": "create_task",
                        "display_label": "Record Jeep registration",
                        "data": {
                            "name": "Registration",
                            "description": "Archived registration renewal.",
                            "page": "jeep-page",
                            "task": "registration-task",
                            "completed_on": "2023-06-24",
                            "submission": {
                                "input-textab12": "Registration renewed at DMV."
                            },
                        },
                    },
                    {
                        "id": "attach_registration_scan",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "registration_history",
                            "file": "2023-06-24 jeep registration.pdf",
                        },
                    },
                    {
                        "id": "attach_dmv_receipt",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "registration_history",
                            "file": "dmv receipt.pdf",
                        },
                    },
                ],
            },
        },
    )
    saved = []

    def save_entities(*entities):
        saved.append(entities)

    monkeypatch.setattr(report_runner.Entities, "save", save_entities)
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({"jeep-page": page, "registration-task": task}),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    histories = list({
        entity.key: entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    }.values())
    assert result["status"] == "complete"
    assert len(histories) == 1
    history = histories[0]
    assert history.task is task
    assert history.page is page
    assert history.completed_on == datetime(2023, 6, 24, tzinfo=timezone.utc)
    assert history.db["completed_on"] == datetime(2023, 6, 24, tzinfo=timezone.utc)
    assert "completed" not in history.db
    assert history.name == "Registration"
    assert history.description == "Archived registration renewal."
    assert set(history.files) == {file_one, file_two}
    assert live_attachment not in history.files
    assert set(file_one.db["tasks"]) == {history.key}
    assert set(file_two.db["tasks"]) == {history.key}
    assert file_one.linked_tasks == [task]
    assert file_two.linked_tasks == [task]
    assert history.form is form
    assert history.submission == {
        "input-textab12": "Registration renewed at DMV."
    }
    assert task.completed is True
    assert task.completed_on == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert task.due_date == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert task.name == "Registration"
    assert task.description == "Current registration details."
    assert task.files == [live_attachment]
    assert task.db["history"] is True
    assert any(
        intent.intent is MutationIntentType.STANDARD and intent.entity is history
        for intent in task.mutation_intents
    )
    assert {
        intent.entity
        for intent in history.mutation_intents
        if intent.intent is MutationIntentType.PATCH
    } == {file_one, file_two}
    action = result["actions"][0]
    assert action["type"] == "create_task"
    assert action["entity"]["kind"] == "task_history"
    assert action["target"]["name"] == "Registration"
    assert action["submission"] == {"created": True, "field_count": 1}
    attachment_actions = result["actions"][1:3]
    assert [a["type"] for a in attachment_actions] == [
        "attach_file_to_task",
        "attach_file_to_task",
    ]
    assert [a["target"]["kind"] for a in attachment_actions] == [
        "task_history",
        "task_history",
    ]
    assert [a["entity"]["name"] for a in attachment_actions] == [
        "2023-06-24 jeep registration",
        "dmv receipt",
    ]
    assert [a["file_summary"]["present"] for a in attachment_actions] == [
        False,
        False,
    ]
    grouped = report.properties.result.grouped_actions
    assert grouped[0]["type"] == "page_group"
    assert grouped[0]["entity"]["name"] == "Jeep"
    grouped_task = grouped[0]["tasks"][0]
    assert grouped_task["created"] is False
    assert grouped_task["entity"]["name"] == "Registration"
    grouped_history_attachments = grouped_task["histories"][0]["attachments"]
    assert [a["entity"]["name"] for a in grouped_history_attachments] == [
        "2023-06-24 jeep registration",
        "dmv receipt",
    ]




# @features ai-report
# @dimensions completed-task attachments
@pytest.mark.unit
def test_run_report_records_dateless_historical_task_completion(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("dateless-completion-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "Community Service", "hash": "community-service-page"},
    )
    file = _test_file("volunteer certificate.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Dateless historical task report",
            "hash": "dateless-historical-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file],
            "proposal": {
                "summary": "Record the completed volunteer service.",
                "confidence": 0.9,
                "issues": [],
                "actions": [
                    {
                        "id": "volunteer_service",
                        "type": "create_task",
                        "data": {
                            "name": "Volunteer Service",
                            "description": "Historical volunteer service event.",
                            "page": "community-service-page",
                            "completed": True,
                        },
                    },
                    {
                        "id": "attach_certificate",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "volunteer_service",
                            "file": "volunteer certificate.pdf",
                        },
                    },
                ],
            },
        },
    )
    saved = []
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({"community-service-page": page}),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    tasks = {
        entity.key: entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task"
    }
    assert result["status"] == "complete"
    assert len(tasks) == 1
    task = next(iter(tasks.values()))
    assert task.completed is True
    assert task.completed_on is None
    assert task.files == [file]
    assert file.db["tasks"] == [task.key]
    assert result["actions"][0]["note"] == (
        "Recorded as the task's current completion."
    )
    assert result["actions"][1]["target"]["id"] == task.urlsafe_key




# @features ai-report tasks task-completion
# @dimensions completed-task newest-completion history-name live-task
@pytest.mark.unit
def test_run_report_promotes_newer_completed_event_to_live_task(
    monkeypatch,
    get_schema,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("history-newest-owner")
    page = TestEntities.get("PAGE", {"name": "Jeep", "hash": "jeep-newest-page"})
    form = TestEntities.get(
        "FORM",
        {"name": "Vehicle Registration Form", "hash": "registration-newest-form"},
    )
    form.schema = get_schema("text_input_only")
    task = TestEntities.get(
        "TASK",
        {"name": "Registration", "hash": "registration-newest-task"},
        page=page,
    )
    task.form = form
    old_file = _test_file("2020-06-24 jeep registration.pdf", "application/pdf")
    task.files = [old_file]
    task.completed = True
    task.completed_on = datetime(2020, 6, 24, tzinfo=timezone.utc)
    task.description = "Previous registration details."
    task.ai_submission({"input-textab12": "Previous registration."})
    page._completed = [task]
    new_file = _test_file("2023-06-24 jeep registration.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Newer task history report",
            "hash": "history-newest-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [new_file],
            "proposal": {
                "summary": "Record newer registration history.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "registration_history",
                        "type": "create_task",
                        "display_label": "Record newer Jeep registration",
                        "data": {
                            "name": "Registration",
                            "page": "jeep-newest-page",
                            "task": "registration-newest-task",
                            "completed_on": "2023-06-24",
                            "submission": {
                                "input-textab12": "Registration renewed again."
                            },
                        },
                    },
                    {
                        "id": "attach_registration_scan",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "registration_history",
                            "file": "2023-06-24 jeep registration.pdf",
                        },
                    },
                ],
            },
        },
    )
    saved = []

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(
            {
                "jeep-newest-page": page,
                "registration-newest-task": task,
            }
        ),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    histories = list({
        entity.key: entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    }.values())
    assert result["status"] == "complete"
    assert len(histories) == 1
    history = histories[0]
    assert history.task is task
    assert history.completed_on == datetime(2020, 6, 24, tzinfo=timezone.utc)
    assert history.name == "Registration"
    assert history.description == "Previous registration details."
    assert history.files == [old_file]
    assert history.submission == {"input-textab12": "Previous registration."}
    assert set(old_file.db["tasks"]) == {history.key}
    assert task.completed is True
    assert task.completed_on == datetime(2023, 6, 24, tzinfo=timezone.utc)
    assert task.due_date is None
    assert task.files == [new_file]
    assert task.submission == {"input-textab12": "Registration renewed again."}
    assert set(new_file.db["tasks"]) == {task.key}
    action = result["actions"][0]
    assert action["entity"]["kind"] == "task"
    assert action["created"] is False
    assert action["target"]["id"] == task.urlsafe_key
    assert action["submission"] == {"created": True, "field_count": 1}
    assert action["note"] == "Moved the previous completion to history."
    attach_action = result["actions"][1]
    assert attach_action["type"] == "attach_file_to_task"
    assert attach_action["entity"]["id"] == new_file.urlsafe_key
    assert attach_action["target"]["id"] == task.urlsafe_key
    assert attach_action["file_summary"]["present"] is False




# @features ai-report tasks task-completion
# @dimensions completed-task explicit-task-identity duplicate-task-prevention
@pytest.mark.unit
def test_run_report_reuses_one_created_task_for_multiple_completed_events(
    monkeypatch,
    get_schema,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("history-cache-owner")
    file_one = _test_file("2023-06-24 jeep registration.pdf", "application/pdf")
    file_two = _test_file("2018_06_07 jeep registration.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Duplicate task history report",
            "hash": "history-cache-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file_one, file_two],
            "proposal": {
                "summary": "Record registration history without duplicate tasks.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "jeep",
                        "type": "create_page",
                        "data": {"name": "Jeep"},
                    },
                    {
                        "id": "maintenance",
                        "type": "create_project",
                        "data": {"name": "Maintenance"},
                    },
                    {
                        "id": "registration_form",
                        "type": "create_form",
                        "data": {
                            "name": "Registration Form",
                            "form_type": "task",
                            "schema": get_schema("text_input_only"),
                        },
                    },
                    {
                        "id": "registration_model",
                        "type": "create_model_task",
                        "data": {
                            "name": "Vehicle Registration",
                            "project_action": "maintenance",
                            "form_action": "registration_form",
                        },
                    },
                    {
                        "id": "registration_2023",
                        "type": "create_task",
                        "data": {
                            "name": "Registration",
                            "page_action": "jeep",
                            "project_action": "maintenance",
                            "model_action": "registration_model",
                            "description": "Vehicle registration renewal payment.",
                            "completed_on": "2023-06-24",
                            "submission": {"input-textab12": "2023 event"},
                        },
                    },
                    {
                        "id": "attach_registration_2023",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "registration_2023",
                            "file": "2023-06-24 jeep registration.pdf",
                        },
                    },
                    {
                        "id": "registration_2018",
                        "type": "create_task",
                        "data": {
                            "name": "Registration",
                            "page_action": "jeep",
                            "task_action": "registration_2023",
                            "project_action": "maintenance",
                            "model_action": "registration_model",
                            "description": "Vehicle registration renewal payment.",
                            "completed_on": "2018-06-07",
                            "submission": {"input-textab12": "2018 event"},
                        },
                    },
                    {
                        "id": "attach_registration_2018",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "registration_2018",
                            "file": "2018_06_07 jeep registration.pdf",
                        },
                    },
                ],
            },
        },
    )
    saved = []

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    monkeypatch.setattr(
        report_runner.Entities, "fetch_one", lambda key, request: None
    )
    monkeypatch.setattr(
        report_runner.Entities.CATEGORY,
        "get_uncategorized_pages",
        lambda: TestEntities.get(
            "CATEGORY", {"name": "Uncategorized Pages", "hash": "uncategorized"}
        ),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    histories = list({
        entity.key: entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    }.values())
    forms = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "form"
    ]
    assert result["status"] == "complete"
    assert len(histories) == 1
    tracker_task = histories[0].task
    assert tracker_task.name == "Registration"
    assert tracker_task.description == "Vehicle registration renewal payment."
    assert tracker_task.form is forms[0]
    assert histories[0].form is forms[0]
    assert tracker_task.completed is True
    assert tracker_task.completed_on == datetime(2023, 6, 24, tzinfo=timezone.utc)
    assert tracker_task.due_date is None
    assert tracker_task.files == [file_one]
    assert tracker_task.submission == {"input-textab12": "2023 event"}
    assert histories[0].completed_on == datetime(2018, 6, 7, tzinfo=timezone.utc)
    assert histories[0].name == "Registration"
    assert histories[0].description == "Vehicle registration renewal payment."
    assert histories[0].submission == {"input-textab12": "2018 event"}

    first_task_action = result["actions"][4]
    first_attach_action = result["actions"][5]
    second_task_action = result["actions"][6]
    second_attach_action = result["actions"][7]
    assert first_task_action["type"] == "create_task"
    assert first_task_action["created"] is True
    assert first_task_action["entity"]["name"] == "Registration"
    assert first_attach_action["type"] == "attach_file_to_task"
    assert first_attach_action["target"]["id"] == first_task_action["entity"]["id"]
    assert second_task_action["type"] == "create_task"
    assert second_task_action["created"] is True
    assert second_task_action["target"]["id"] == first_task_action["entity"]["id"]
    assert second_task_action["target"]["name"] == "Registration"
    assert second_task_action["entity"]["kind"] == "task_history"
    assert second_task_action["entity"]["id"].startswith("task_history-")
    assert second_task_action["submission"] == {"created": True, "field_count": 1}
    assert second_attach_action["type"] == "attach_file_to_task"
    assert second_attach_action["target"]["id"] == second_task_action["entity"]["id"]




# @features ai-report tasks task-completion
# @dimensions completed-task explicit-task-identity distinct-task same-model
@pytest.mark.unit
def test_run_report_keeps_untargeted_same_model_tasks_distinct(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("distinct-prescriptions-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "Prescriptions", "hash": "distinct-prescriptions-page"},
    )
    project = TestEntities.get(
        "PROJECT",
        {"name": "Health", "hash": "distinct-health-project"},
    )
    model = TestEntities.get(
        "MODEL_TASK",
        {"name": "Prescription", "hash": "distinct-prescription-model"},
        project=project,
    )
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Distinct prescriptions report",
            "hash": "distinct-prescriptions-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Record two distinct prescriptions.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "lisinopril",
                        "type": "create_task",
                        "data": {
                            "name": "Lisinopril Prescription",
                            "page": page.urlsafe_key,
                            "project": project.urlsafe_key,
                            "model": model.urlsafe_key,
                            "completed_on": "2025-03-01",
                        },
                    },
                    {
                        "id": "atorvastatin",
                        "type": "create_task",
                        "data": {
                            "name": "Atorvastatin Prescription",
                            "page": page.urlsafe_key,
                            "project": project.urlsafe_key,
                            "model": model.urlsafe_key,
                            "completed_on": "2025-03-02",
                        },
                    },
                ],
            },
        },
    )
    saved = []
    entities = {
        page.urlsafe_key: page,
        project.urlsafe_key: project,
        model.urlsafe_key: model,
    }
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )

    result = report_runner.run_report(report, user)

    tasks = {
        entity.key: entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task"
    }
    histories = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    ]
    assert result["status"] == "complete"
    assert len(tasks) == 2
    assert histories == []
    assert {task.name for task in tasks.values()} == {
        "Lisinopril Prescription",
        "Atorvastatin Prescription",
    }
    assert (
        result["actions"][0]["target"]["id"]
        != result["actions"][1]["target"]["id"]
    )




# @features ai-report tasks task-completion
# @dimensions completed-task model-form lazy-load submission
@pytest.mark.unit
def test_run_report_loads_model_task_form_from_stored_key_for_history(
    monkeypatch,
    get_schema,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("history-model-form-owner")
    page = TestEntities.get("PAGE", {"name": "Pool", "hash": "pool-page"})
    project = TestEntities.get(
        "PROJECT", {"name": "Maintenance", "hash": "model-form-project"}
    )
    form = TestEntities.get(
        "FORM", {"name": "Invoice Form", "hash": "model-form-invoice-form"}
    )
    form.schema = get_schema("text_input_only")
    model = TestEntities.get(
        "MODEL_TASK",
        {"name": "Invoices", "hash": "model-form-invoices-model"},
        project=project,
    )
    model.db["form"] = form.key
    file_new = _test_file("2024-03-01 pool invoice.pdf", "application/pdf")
    file_old = _test_file("2023-03-01 pool invoice.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Lazy model form report",
            "hash": "history-model-form-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file_new, file_old],
            "proposal": {
                "summary": "Record pool invoice history.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "invoice_2024",
                        "type": "create_task",
                        "data": {
                            "name": "Invoice",
                            "page": page.urlsafe_key,
                            "project": project.urlsafe_key,
                            "model": model.urlsafe_key,
                            "completed_on": "2024-03-01",
                            "submission": {"input-textab12": "2024 invoice"},
                        },
                    },
                    {
                        "id": "attach_invoice_2024",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "invoice_2024",
                            "file": file_new.urlsafe_key,
                        },
                    },
                    {
                        "id": "invoice_2023",
                        "type": "create_task",
                        "data": {
                            "name": "Invoice",
                            "page": page.urlsafe_key,
                            "task_action": "invoice_2024",
                            "project": project.urlsafe_key,
                            "model": model.urlsafe_key,
                            "completed_on": "2023-03-01",
                            "submission": {"input-textab12": "2023 invoice"},
                        },
                    },
                    {
                        "id": "attach_invoice_2023",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "invoice_2023",
                            "file": file_old.urlsafe_key,
                        },
                    },
                ],
            },
        },
    )
    saved = []
    entities = {
        page.urlsafe_key: page,
        project.urlsafe_key: project,
        model.urlsafe_key: model,
        form.urlsafe_key: form,
    }

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    histories = list({
        entity.key: entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    }.values())
    assert result["status"] == "complete"
    assert len(histories) == 1
    task = histories[0].task
    assert task.name == "Invoice"
    assert task.form is form
    assert task.submission == {"input-textab12": "2024 invoice"}
    assert histories[0].form is form
    assert histories[0].name == "Invoice"
    assert histories[0].submission == {"input-textab12": "2023 invoice"}
    assert result["actions"][0]["project"]["name"] == "Maintenance"
    assert result["actions"][0]["model"]["name"] == "Invoices"
    assert result["actions"][0]["model"]["parent"]["name"] == "Maintenance"
    assert result["actions"][0]["form"]["name"] == "Invoice Form"
    assert result["actions"][0]["page"]["name"] == "Pool"
    assert result["actions"][1]["type"] == "attach_file_to_task"
    assert result["actions"][2]["project"]["name"] == "Maintenance"
    assert result["actions"][2]["model"]["name"] == "Invoices"
    assert result["actions"][2]["model"]["parent"]["name"] == "Maintenance"
    assert result["actions"][2]["form"]["name"] == "Invoice Form"
    assert result["actions"][2]["page"]["name"] == "Pool"
    assert result["actions"][2]["submission"] == {"created": True, "field_count": 1}
    assert result["actions"][3]["type"] == "attach_file_to_task"




# @features ai-report tasks task-completion
# @dimensions completed-task explicit-task-identity existing-task
@pytest.mark.unit
def test_run_report_reuses_existing_task_for_completed_event(
    monkeypatch,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("history-existing-owner")
    page = TestEntities.get("PAGE", {"name": "Jeep", "hash": "jeep-page"})
    task = TestEntities.get(
        "TASK",
        {"name": "Registration", "hash": "registration-task"},
        page=page,
    )
    page._tasks = [task]
    page._completed = []
    file = _test_file("2023-06-24 jeep registration.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Existing task history report",
            "hash": "history-existing-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file],
            "proposal": {
                "summary": "Record registration history on the existing task.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "registration_2023",
                        "type": "create_task",
                        "data": {
                            "name": "Jeep Registration - Jun 2023",
                            "page": "jeep-page",
                            "task": "registration-task",
                            "description": "Event-specific receipt text.",
                            "completed_on": "2023-06-24",
                            "submission": {"input-textab12": "event"},
                        },
                    },
                    {
                        "id": "attach_registration_2023",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "registration_2023",
                            "file": "2023-06-24 jeep registration.pdf",
                        },
                    },
                ],
            },
        },
    )
    saved = []

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({"jeep-page": page, "registration-task": task}),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    histories = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    ]
    assert result["status"] == "complete"
    assert result["actions"][0]["created"] is False
    assert result["actions"][0]["entity"]["id"] == "registration-task"
    assert result["actions"][0]["target"]["id"] == "registration-task"
    assert result["actions"][1]["type"] == "attach_file_to_task"
    assert result["actions"][1]["target"]["id"] == "registration-task"
    assert len(histories) == 0
    assert task.completed is True
    assert task.completed_on == datetime(2023, 6, 24, tzinfo=timezone.utc)
    assert task.files == [file]
    assert set(file.db["tasks"]) == {task.key}
    assert file.linked_tasks == [task]
    assert task.name == "Registration"
    assert task.description == "Event-specific receipt text."
    assert task.due_date is None
    assert task.submission == {}




# @features ai-report tasks task-completion
# @dimensions completed-task automatic-task-family period-name same-report
@pytest.mark.unit
def test_run_report_automatically_reuses_dated_completed_task_family(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("property-tax-history-owner")
    page = TestEntities.get(
        "PAGE", {"name": "Property Tax", "hash": "property-tax-page"}
    )
    project = TestEntities.get(
        "PROJECT", {"name": "Finances", "hash": "finances-project"}
    )
    model = TestEntities.get(
        "MODEL_TASK",
        {"name": "Payments", "hash": "payments-model"},
        project=project,
    )
    task = TestEntities.get(
        "TASK", {"name": "Pay Property Tax", "hash": "property-tax-task"},
        page=page,
    )
    task.model = model
    task.project = project
    page._tasks = [task]
    page._completed = []
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Property tax installments",
            "hash": "property-tax-history-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Record property-tax payments.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "property_tax_2026",
                        "type": "create_task",
                        "data": {
                            "name": "Pay Property Tax - April 2026 Installment",
                            "page": page.urlsafe_key,
                            "project": project.urlsafe_key,
                            "model": model.urlsafe_key,
                            "completed_on": "2026-04-01",
                        },
                    },
                    {
                        "id": "property_tax_2024",
                        "type": "create_task",
                        "data": {
                            "name": "Pay Property Tax - July 2024 installment",
                            "page": page.urlsafe_key,
                            "project": project.urlsafe_key,
                            "model": model.urlsafe_key,
                            "completed_on": "2024-07-01",
                        },
                    },
                ],
            },
        },
    )
    saved = []
    entities = {
        page.urlsafe_key: page,
        project.urlsafe_key: project,
        model.urlsafe_key: model,
    }
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )

    result = report_runner.run_report(report, user)

    histories = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    ]
    assert result["status"] == "complete"
    assert result["actions"][0]["created"] is False
    assert result["actions"][0]["target"]["id"] == task.urlsafe_key
    assert result["actions"][1]["target"]["id"] == task.urlsafe_key
    assert task.name == "Pay Property Tax"
    assert task.completed_on == datetime(2026, 4, 1, tzinfo=timezone.utc)
    assert len(histories) == 1
    assert histories[0].task is task
    assert histories[0].name == "Pay Property Tax"
    assert histories[0].completed_on == datetime(2024, 7, 1, tzinfo=timezone.utc)




# @features ai-report tasks task-completion
# @dimensions completed-task automatic-task-family ambiguity
@pytest.mark.unit
def test_run_report_keeps_ambiguous_completed_task_families_distinct(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("ambiguous-property-tax-owner")
    page = TestEntities.get(
        "PAGE", {"name": "Property Tax", "hash": "ambiguous-property-tax-page"}
    )
    project = TestEntities.get(
        "PROJECT", {"name": "Finances", "hash": "ambiguous-finances-project"}
    )
    model = TestEntities.get(
        "MODEL_TASK",
        {"name": "Payments", "hash": "ambiguous-payments-model"},
        project=project,
    )
    first = TestEntities.get(
        "TASK", {"name": "Pay Property Tax", "hash": "property-tax-first"},
        page=page,
    )
    second = TestEntities.get(
        "TASK", {"name": "Pay Property Tax", "hash": "property-tax-second"},
        page=page,
    )
    first.model = model
    second.model = model
    page._tasks = [first, second]
    page._completed = []
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Ambiguous property tax payment",
            "hash": "ambiguous-property-tax-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Record a payment without selecting a duplicate.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "property_tax_2026",
                        "type": "create_task",
                        "data": {
                            "name": "Pay Property Tax - April 2026 Installment",
                            "page": page.urlsafe_key,
                            "model": model.urlsafe_key,
                            "completed_on": "2026-04-01",
                        },
                    }
                ],
            },
        },
    )
    saved = []
    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from({page.urlsafe_key: page, model.urlsafe_key: model}),
    )

    result = report_runner.run_report(report, user)

    created_tasks = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task"
        and entity.key not in {first.key, second.key}
    ]
    assert result["status"] == "complete"
    assert result["actions"][0]["created"] is True
    assert result["actions"][0]["target"]["id"] not in {
        first.urlsafe_key,
        second.urlsafe_key,
    }
    assert len(created_tasks) == 1
    assert first.completed is False
    assert second.completed is False




# @features ai-report tasks task-completion
# @dimensions completed-task explicit-task-identity page-validation
@pytest.mark.unit
def test_run_report_rejects_completed_task_target_from_another_page(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("history-page-mismatch-owner")
    prescriptions = TestEntities.get(
        "PAGE",
        {"name": "Prescriptions", "hash": "prescriptions-target-page"},
    )
    appointments = TestEntities.get(
        "PAGE",
        {"name": "Appointments", "hash": "appointments-action-page"},
    )
    task = TestEntities.get(
        "TASK",
        {"name": "Lisinopril Prescription", "hash": "lisinopril-target-task"},
        page=prescriptions,
    )
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Mismatched task target report",
            "hash": "mismatched-task-target-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Invalid cross-page completion.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "lisinopril_completion",
                        "type": "create_task",
                        "data": {
                            "name": "Lisinopril Prescription",
                            "page": appointments.urlsafe_key,
                            "task": task.urlsafe_key,
                            "completed": True,
                        },
                    }
                ],
            },
        },
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(
            {
                appointments.urlsafe_key: appointments,
                task.urlsafe_key: task,
            }
        ),
    )
    monkeypatch.setattr(report_runner.Entities, "save", lambda *entities: None)

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert result["actions"][0]["status"] == "skipped"
    assert "does not belong to the referenced page" in (
        result["actions"][0]["error"]
    )
    assert task.completed is False




# @features ai-report tasks task-completion
# @dimensions completed-task task-form missing-submission continue
@pytest.mark.unit
def test_run_report_warns_but_continues_when_task_form_submission_missing(
    monkeypatch,
    get_schema,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("missing-task-submission-owner")
    page = TestEntities.get("PAGE", {"name": "Paul Mitrani, M.D.", "hash": "doctor"})
    project = TestEntities.get("PROJECT", {"name": "Medical", "hash": "medical"})
    form = TestEntities.get(
        "FORM",
        {"name": "Specialist Consultations", "hash": "specialist-form"},
    )
    form.form_type = "task"
    form.schema = get_schema("text_input_only")
    model = TestEntities.get(
        "MODEL_TASK",
        {"name": "Specialist Consultations", "hash": "specialist-model"},
        project=project,
    )
    model.form = form
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Missing completed task submission report",
            "hash": "missing-completed-task-submission-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Record a completed screening without confident fields.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "create_completed_cdi2",
                        "type": "create_task",
                        "display_label": "Record CDI-2 Depression Screen",
                        "data": {
                            "name": "CDI-2 Depression Screen",
                            "page": page.urlsafe_key,
                            "page_name": page.name,
                            "project": project.urlsafe_key,
                            "project_name": project.name,
                            "model": model.urlsafe_key,
                            "model_name": model.name,
                            "completed_on": "2021-10-23",
                        },
                    }
                ],
            },
        },
    )
    saved = []
    captured = []
    entities = {
        page.urlsafe_key: page,
        project.urlsafe_key: project,
        model.urlsafe_key: model,
        form.urlsafe_key: form,
    }

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )
    monkeypatch.setattr(
        exceptions,
        "capture",
        lambda error, context=None, level="error": captured.append(
            {"error": error, "context": context, "level": level}
        ),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert result["actions"][0]["status"] == "complete"
    assert result["actions"][0]["submission"] == {
        "created": False,
        "field_count": 0,
    }
    assert report.status == "complete"
    assert captured == [
        {
            "error": "AI report create_task used a task form but omitted submission data.",
            "level": "warning",
            "context": {
                "ai_report_runner": {
                    "operation": "create_task_missing_submission",
                    "report": report_results._diagnostic_entity(report),
                    "action": {
                        "id": "create_completed_cdi2",
                        "type": "create_task",
                        "display_label": "Record CDI-2 Depression Screen",
                        "data_keys": [
                            "completed_on",
                            "model",
                            "model_name",
                            "name",
                            "page",
                            "page_name",
                            "project",
                            "project_name",
                        ],
                        "completed_on": "2021-10-23",
                        "submission_key_present": False,
                    },
                    "page": report_results._diagnostic_entity(page),
                    "project": report_results._diagnostic_entity(project),
                    "model": report_results._diagnostic_entity(model),
                    "form": report_results._diagnostic_entity(form),
                    "form_schema": report_results._diagnostic_schema(form),
                    "files": [],
                }
            },
        }
    ]




# @features ai-report tasks forms
# @dimensions deterministic-run mismatched-form recoverable continue
@pytest.mark.unit
def test_run_report_skips_task_that_references_page_form_and_continues(monkeypatch):
    _patch_fake_keys(monkeypatch)
    user = _test_user("task-page-form-owner")
    page = TestEntities.get("PAGE", {"name": "Client", "hash": "client-page"})
    page_form = TestEntities.get(
        "FORM",
        {"name": "Client Intake", "hash": "client-page-form"},
    )
    page_form.form_type = "page"
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Task page form mismatch report",
            "hash": "task-page-form-mismatch-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "proposal": {
                "summary": "Skip the bad task and still create the page.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "bad_task",
                        "type": "create_task",
                        "display_label": "Create task with page form",
                        "data": {
                            "name": "Client follow-up",
                            "page": page.urlsafe_key,
                            "form": page_form.urlsafe_key,
                            "submission": {"input-notes": "Follow-up"},
                        },
                    },
                    {
                        "id": "good_page",
                        "type": "create_page",
                        "data": {"name": "Still Built"},
                    },
                ],
            },
        },
    )
    saved = []
    entities = {
        page.urlsafe_key: page,
        page_form.urlsafe_key: page_form,
    }

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities_to_save: saved.append(entities_to_save),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(entities),
    )

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert result["actions"][0]["status"] == "skipped"
    assert result["actions"][0]["error"] == report_common.TASK_FORM_TYPE_ERROR
    assert result["actions"][0]["note"] == (
        "Skipped because the action referenced a page form instead of a task form."
    )
    assert result["actions"][1]["status"] == "complete"
    assert result["actions"][1]["entity"]["name"] == "Still Built"
    assert report.status == "complete"




# @features ai-report tasks task-completion
# @dimensions task-history page-reference repair
@pytest.mark.unit
def test_run_report_resolves_task_page_by_exact_page_name_when_reference_is_wrong_kind(
    monkeypatch,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("history-page-repair-owner")
    page = TestEntities.get("PAGE", {"name": "Jeep", "hash": "jeep-page"})
    file = _test_file("2023-06-24 jeep registration.pdf", "application/pdf")
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Wrong page reference report",
            "hash": "history-page-repair-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file],
            "proposal": {
                "summary": "Record registration history on Jeep.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "registration_2023",
                        "type": "create_task",
                        "data": {
                            "name": "Jeep Registration - Jun 2023",
                            "page": file.urlsafe_key,
                            "page_name": "Jeep",
                            "completed_on": "2023-06-24",
                        },
                    },
                    {
                        "id": "attach_registration_2023",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "registration_2023",
                            "file": "2023-06-24 jeep registration.pdf",
                        },
                    },
                ],
            },
        },
    )
    saved = []

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(
            {
                file.urlsafe_key: file,
                page.urlsafe_key: page,
            }
        ),
    )
    monkeypatch.setattr(
        report_references.cache,
        "search",
        lambda *args, **kwargs: (
            [{"id": page.urlsafe_key, "kind": "page", "name": "Jeep"}],
            1,
        ),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    created_tasks = {
        entity.key: entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task"
    }
    histories = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task_history"
    ]
    assert result["status"] == "complete"
    assert len(created_tasks) == 1
    created_task = next(iter(created_tasks.values()))
    assert created_task.page is page
    assert created_task.name == "Registration"
    assert created_task.completed is True
    assert created_task.completed_on == datetime(2023, 6, 24, tzinfo=timezone.utc)
    assert created_task.files == [file]
    assert set(file.db["tasks"]) == {created_task.key}
    assert len(histories) == 0
    assert result["actions"][0]["entity"]["name"] == "Registration"
    assert result["actions"][0]["target"]["id"] == result["actions"][0]["entity"]["id"]
    assert result["actions"][1]["type"] == "attach_file_to_task"
    assert result["actions"][1]["target"]["id"] == result["actions"][0]["entity"]["id"]




# @features ai-report files
# @dimensions attachment page-reference repair prior-task-page
@pytest.mark.unit
def test_run_report_resolves_attachment_page_from_single_prior_task_when_reference_is_file(
    monkeypatch,
):
    _patch_fake_keys(monkeypatch)
    user = _test_user("attachment-page-repair-owner")
    page = TestEntities.get(
        "PAGE",
        {"name": "368 Pettis Ave Residence", "hash": "pettis-insurance-page"},
    )
    file_2022 = _test_file("2022-01-17 pettis insurance.pdf", "application/pdf")
    file_2023 = _test_file("2023-01-17 Pettis Insurance.pdf", "application/pdf")
    file_2025 = _test_file(
        "2025 homeowners insurance declaration.pdf",
        "application/pdf",
    )
    report = TestEntities.get(
        "REPORT",
        {
            "name": "Insurance renewal report",
            "hash": "insurance-renewal-report",
            "parent": user,
            "user": user,
            "status": "ready",
            "pending": False,
            "input_files": [file_2022, file_2023, file_2025],
            "proposal": {
                "summary": "Track homeowners insurance renewals.",
                "confidence": 0.9,
                "actions": [
                    {
                        "id": "task_2022_renewal",
                        "type": "create_task",
                        "display_label": "2022 Homeowners Insurance Renewal",
                        "data": {
                            "name": "2022 Homeowners Insurance Renewal",
                            "page": page.urlsafe_key,
                            "completed_on": "2022-01-17",
                        },
                    },
                    {
                        "id": "attach_2022_renewal",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "task_2022_renewal",
                            "file": file_2022.urlsafe_key,
                        },
                    },
                    {
                        "id": "task_2023_renewal",
                        "type": "create_task",
                        "display_label": "2023 Homeowners Insurance Renewal",
                        "data": {
                            "name": "2023 Homeowners Insurance Renewal",
                            "page": page.urlsafe_key,
                            "completed_on": "2023-01-17",
                        },
                    },
                    {
                        "id": "attach_2023_renewal",
                        "type": "attach_file_to_task",
                        "data": {
                            "task_action": "task_2023_renewal",
                            "file": file_2023.urlsafe_key,
                        },
                    },
                    {
                        "id": "attach_2025_file",
                        "type": "attach_file_to_page",
                        "display_label": "Attach 2025 Homeowners Insurance Document",
                        "data": {
                            "page": file_2025.urlsafe_key,
                            "file": file_2025.urlsafe_key,
                        },
                    },
                ],
            },
        },
    )
    saved = []

    monkeypatch.setattr(
        report_runner.Entities,
        "save",
        lambda *entities: saved.append(entities),
    )
    monkeypatch.setattr(
        report_runner.Entities,
        "fetch_one",
        _fetch_one_from(
            {
                page.urlsafe_key: page,
                file_2022.urlsafe_key: file_2022,
                file_2023.urlsafe_key: file_2023,
                file_2025.urlsafe_key: file_2025,
            }
        ),
    )
    _patch_task_file_add(monkeypatch)

    result = report_runner.run_report(report, user)

    assert result["status"] == "complete"
    assert [action["status"] for action in result["actions"]] == [
        "complete",
        "complete",
        "complete",
        "complete",
        "complete",
    ]
    assert result["actions"][4]["type"] == "attach_file_to_page"
    assert result["actions"][4]["target"]["id"] == page.urlsafe_key
    assert result["actions"][4]["entity"]["id"] == file_2025.urlsafe_key
    assert file_2025.db["pages"] == [page.key]
    created_tasks = [
        entity
        for batch in saved
        for entity in batch
        if getattr(entity, "entity_kind", None) == "task"
    ]
    assert len({task.key for task in created_tasks}) == 2




# @features ai-report
# @dimensions completed-task validation recoverable continue
@pytest.mark.unit
def test_run_report_skips_invalid_completed_task_events_and_continues(monkeypatch):
    _patch_fake_keys(monkeypatch)
    cases = [
        (
            {
                "name": "Registration",
                "page": "jeep-page",
                "completed_on": "not-a-date",
            },
            "page",
            "completion date is invalid",
        ),
        (
            {
                "name": "Registration",
                "page": "missing-page",
                "completed_on": "2023-06-24",
            },
            None,
            "Referenced entity not found",
        ),
    ]

    for index, (data, entity, expected_error) in enumerate(cases):
        user = _test_user(f"history-invalid-owner-{index}")
        page = TestEntities.get(
            "PAGE",
            {"name": "Jeep", "hash": f"jeep-invalid-page-{index}"},
        )
        file = _test_file("registration.pdf", "application/pdf")
        report = TestEntities.get(
            "REPORT",
            {
                "name": "Invalid task history report",
                "hash": f"invalid-history-{index}",
                "parent": user,
                "user": user,
                "status": "ready",
                "pending": False,
                "input_files": [file],
                "proposal": {
                    "summary": "Invalid completed task.",
                    "confidence": 0.5,
                    "actions": [
                        {
                            "id": "completed_task",
                            "type": "create_task",
                            "data": data,
                        },
                        {
                            "id": "continued_project",
                            "type": "create_project",
                            "data": {"name": "Still Runs"},
                        },
                    ],
                },
            },
        )

        monkeypatch.setattr(report_runner.Entities, "save", lambda *entities: None)
        monkeypatch.setattr(
            report_runner.Entities,
            "fetch_one",
            _fetch_one_from({"jeep-page": page} if entity else {}),
        )

        result = report_runner.run_report(report, user)

        assert result["status"] == "complete"
        assert "failed_at" not in result
        assert report.status == "complete"
        assert result["actions"][0]["status"] == "skipped"
        assert expected_error in result["actions"][0]["error"]
        assert result["actions"][0]["note"] == (
            "Skipped because this action could not be completed."
        )
        assert result["actions"][1]["status"] == "complete"
        assert result["actions"][1]["entity"]["name"] == "Still Runs"
