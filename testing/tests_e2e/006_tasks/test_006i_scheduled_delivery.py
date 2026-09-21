"""Scheduled-delivery HTTP contracts with token verification and storage isolated."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lagniappe.web import app
from lagniappe.web.routes.process import main as process_routes


pytestmark = pytest.mark.e2e


# @pairs task-completion:uncomplete task-scheduling:schedule-queue
# @pair task-scheduling:delivery-auth
@pytest.mark.parametrize("delivery", [
    "token", "legacy", "stale-token", "legacy-stale-date", "inactive",
    "already-open", "no-schedule", "missing", "unauthenticated",
    "wrong-caller", "wrong-issuer", "invalid-payload",
])
def test_scheduled_uncompletion_delivery_guards_and_preserves_due_date(monkeypatch, delivery):
    due_date = datetime(2026, 9, 20, tzinfo=timezone.utc)
    stored = {
        "completed": delivery != "already-open",
        "active": delivery != "inactive",
        "due_date": due_date,
        "scheduled_uncomplete_token": "current-token",
    }
    before = deepcopy(stored)
    writes = []

    def fetch(key, *, request):
        assert key == "task-key"
        if delivery == "missing":
            return None
        task = SimpleNamespace(**deepcopy(stored))
        task.properties = SimpleNamespace(schedule=SimpleNamespace(
            active=None if delivery == "no-schedule" else {"interval": 1, "unit": "day"}
        ))

        def uncomplete():
            # Core reopening is covered separately; it clears the old due date.
            task.completed = False
            task.due_date = None
            task.scheduled_uncomplete_token = None

        def save():
            stored.update({key: getattr(task, key) for key in before})
            writes.append(deepcopy(stored))

        task.uncomplete = uncomplete
        task.save = save
        return task

    loader = Mock(side_effect=fetch)
    monkeypatch.setattr(process_routes, "Entities", SimpleNamespace(fetch_one=loader))
    monkeypatch.setattr(process_routes, "CONFIG", SimpleNamespace(
        INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL="tasks@example.test"
    ))
    verifier = Mock(return_value={
        "iss": "wrong-issuer" if delivery == "wrong-issuer" else "https://accounts.google.com",
        "email": "other@example.test" if delivery == "wrong-caller" else "tasks@example.test",
    })
    monkeypatch.setattr(process_routes.id_token, "verify_oauth2_token", verifier)
    payload = {"key": "task-key", "token": "current-token"}
    if delivery.startswith("legacy"):
        payload = {"key": "task-key", "next_due_date": "2026-09-20"}
        if delivery == "legacy-stale-date":
            payload["next_due_date"] = "2026-09-19"
    elif delivery == "stale-token":
        payload["token"] = "old-token"
    elif delivery == "invalid-payload":
        payload["unexpected"] = True
    headers = {} if delivery == "unauthenticated" else {"Authorization": "Bearer test-token"}

    with app.test_client() as client:
        response = client.post("/process/uncomplete-task", json=payload, headers=headers)
        if delivery in {"unauthenticated", "wrong-caller", "wrong-issuer"}:
            assert response.status_code == 401
            loader.assert_not_called()
        elif delivery == "invalid-payload":
            assert response.status_code == 400
            loader.assert_not_called()
        else:
            assert response.status_code == 200, response.get_data(as_text=True)

        if delivery in {"token", "legacy"}:
            assert stored == {**before, "completed": False, "scheduled_uncomplete_token": None}
            assert len(writes) == 1
            duplicate = client.post("/process/uncomplete-task", json=payload, headers=headers)
            assert duplicate.status_code == 200
            assert len(writes) == 1
            assert stored["due_date"] == due_date
        else:
            assert stored == before
            assert writes == []

    if delivery == "unauthenticated":
        verifier.assert_not_called()
    else:
        assert verifier.call_args.args[0] == "test-token"
        assert verifier.call_args.kwargs["audience"].endswith("/process/uncomplete-task")
