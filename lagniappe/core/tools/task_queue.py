"""Google Cloud Tasks queue integration."""

import datetime
import json
import random

from google.cloud import tasks_v2
from google.api_core import exceptions as google_exceptions
from google.protobuf import duration_pb2, timestamp_pb2

from lagniappe import CONFIG

from .. import exceptions

AI_TASK_MIN_DELAY_SECONDS = 5
AI_TASK_MAX_DELAY_SECONDS = 30


# @testable true
# @tests tests_unit/test_015_ai_tools.py::test_ai_task_start_delay_is_bounded
# @features ai
# @dimensions queue-jitter
def ai_task_start_delay():
    """Return a small bounded delay for expensive background AI starts."""
    return random.randint(AI_TASK_MIN_DELAY_SECONDS, AI_TASK_MAX_DELAY_SECONDS)


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_cloud_task_dispatch_uses_key_payload_stable_id_and_deadline
# @tests tests_unit/test_023_deferred_jobs.py::test_cancel_deletes_tasks_and_persists_a_tombstone
# @features deferred-jobs
# @dimensions deterministic-task-id cancellation
def task_name(task_id):
    """Return the fully qualified Cloud Task name for a deterministic id."""
    project = CONFIG.GOOGLE_CLOUD_PROJECT
    location = CONFIG.RESOURCE_REGION or "us-central1"
    return (
        f"projects/{project}/locations/{location}/queues/"
        f"{CONFIG.TASK_QUEUE_NAME}/tasks/{task_id}"
    )


# @testable true
# @tests tests_unit/test_023_deferred_jobs.py::test_cloud_task_dispatch_uses_key_payload_stable_id_and_deadline
# @features deferred-jobs
# @dimensions task-payload deterministic-task-id dispatch-deadline
def create_task(
    endpoint,
    payload=None,
    delay_seconds=0,
    *,
    task_id=None,
    dispatch_deadline_seconds=None,
):
    """Create a Cloud Tasks HTTP POST task with optional delay when enabled."""
    if not getattr(CONFIG, "TASK_QUEUE_ENABLED", CONFIG.production):
        return None

    client = tasks_v2.CloudTasksClient(credentials=CONFIG.google_credentials)

    project = CONFIG.GOOGLE_CLOUD_PROJECT
    location = CONFIG.RESOURCE_REGION or "us-central1"

    # Construct the fully qualified queue name.
    parent = client.queue_path(project, location, CONFIG.TASK_QUEUE_NAME)

    service_account_email = CONFIG.INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL

    # Construct the task body with OIDC authentication.
    task = {
        "http_request": {  # Specify the type of request.
            "http_method": tasks_v2.HttpMethod.POST,
            "url": endpoint,
            "headers": {"Content-type": "application/json"},
            "oidc_token": {"service_account_email": service_account_email},
        }
    }

    if task_id:
        task["name"] = task_name(task_id)

    if payload:
        converted_payload = json.dumps(payload).encode()
        task["http_request"]["body"] = converted_payload
    else:
        task["http_request"]["body"] = json.dumps({}).encode()

    if delay_seconds > 0:
        d = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            seconds=delay_seconds
        )
        timestamp = timestamp_pb2.Timestamp()
        timestamp.FromDatetime(d)
        task["schedule_time"] = timestamp

    if dispatch_deadline_seconds:
        deadline = duration_pb2.Duration()
        deadline.FromSeconds(int(dispatch_deadline_seconds))
        task["dispatch_deadline"] = deadline

    try:
        response = client.create_task(request={"parent": parent, "task": task})
        return response.name
    except google_exceptions.AlreadyExists:
        return task.get("name")


# @testable false
# @reason Cloud Tasks deletion is provider-owned and covered through process/E2E workflows
def delete_task(task_name: str):
    """Delete a scheduled task by its name."""
    if not getattr(CONFIG, "TASK_QUEUE_ENABLED", CONFIG.production):
        return True

    if not task_name:
        return True

    try:
        client = tasks_v2.CloudTasksClient(credentials=CONFIG.google_credentials)
        client.delete_task(request={"name": task_name})
        return True
    except google_exceptions.NotFound:
        return True
    except Exception as e:
        # Task might not exist or already executed
        exceptions.capture(
            e, {"task_queue": {"operation": "delete_task", "task_name": task_name}}
        )
        return False
