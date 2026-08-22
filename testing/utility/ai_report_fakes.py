"""Shared AI-report characterization imports and lightweight fakes."""

import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from google.genai import types as genai_types

from lagniappe.core import exceptions
from lagniappe.core.entities import Entities
from lagniappe.core.entities.ai_report import AIReport
from lagniappe.core.entities import entity as entity_module
from lagniappe.core.definitions import (
    Action,
    LARGE_ASSET_BYTES,
    MutationIntent,
    MutationIntentType,
)
from lagniappe.core.tools.ai import (
    ask,
    create,
    organize,
    organize_retrieval,
    references as ai_references,
    summarize,
)
from lagniappe.core.tools.ai.reporting import uploads as report_uploads
from lagniappe.core.tools.ai.reporting.completion import files as organize_completion
from lagniappe.core.tools.ai.reporting.contracts import actions as report_contracts
from lagniappe.core.tools.ai.reporting.contracts.schema import (
    report_proposal_response_schema,
)
from lagniappe.core.tools.ai.reporting.execution import ledger as report_ledger
from lagniappe.core.tools.ai.reporting.execution import runner as report_runner
from lagniappe.core.tools.ai.reporting.execution import undo as report_undo
from lagniappe.core.tools.ai.reporting.execution.actions import (
    base as report_action_lifecycle,
)
from lagniappe.core.tools.ai.reporting.execution.actions.registry import (
    REPORT_ACTION_ADAPTERS,
)
from lagniappe.core.tools.ai.reporting.execution.actions import common as report_common
from lagniappe.core.tools.ai.reporting.execution.actions import references as report_references
from lagniappe.core.tools.ai.reporting.execution.actions import results as report_results
from lagniappe.core.tools.ai.reporting import schedules as report_schedules
from testing.utility.mock_restrictions import MockRestrictions
from testing.utility.test_entities import TestEntities


def _attach_report_process(report):
    class Process:
        def begin_execution(self, result=None):
            report.status = "running"
            report.pending = True
            report.error = None
            if result is not None:
                report.result = result

        def complete_execution(self, result):
            report.status = "complete"
            report.pending = False
            report.error = None
            report.result = result

        def fail(self, message, result=None):
            report.status = "failed"
            report.pending = False
            report.error = message
            if result is not None:
                report.result = result

    report.properties = SimpleNamespace(process=Process())
    return report


def _with_validator(generate):
    def wrapped(prompt, *, validator=None):
        result = generate(prompt)
        return validator(result) if validator else result

    return wrapped


class FakeKey:
    def __init__(self, name):
        self.name = name

    def to_legacy_urlsafe(self):
        return self.name.encode("utf-8")

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return getattr(other, "name", other) == self.name


def _patch_fake_keys(monkeypatch):
    counter = {"value": 0}

    def create_key(kind, parent=None):
        counter["value"] += 1
        return FakeKey(f"{kind}-{counter['value']}")

    monkeypatch.setattr(entity_module.database, "create_key", create_key)
    monkeypatch.setattr(
        entity_module.database.get,
        "urlsafe_key",
        lambda key: getattr(key, "name", str(key)),
    )
    monkeypatch.setattr(
        "lagniappe.core.properties.common_entity.cache.check_hash",
        lambda value: False,
    )
    monkeypatch.setattr(
        "lagniappe.core.entities.page.database.get.page_tasks",
        lambda page: [],
    )
    monkeypatch.setattr(
        report_runner.Entities.CATEGORY,
        "get_uncategorized_pages",
        lambda: TestEntities.get(
            "CATEGORY",
            {"name": "Uncategorized Pages", "hash": "uncategorized"},
        ),
    )
def _test_file(name="scan.pdf", mimetype="application/pdf"):
    file = TestEntities.get(
        "FILE",
        {
            "name": name.rsplit(".", 1)[0],
            "filename": name,
            "mimetype": mimetype,
            "hash": name.replace(".", "-"),
            "assets": {"file": {"type": "file", "path": name}},
        },
    )
    file.filename = name
    file.mimetype = mimetype
    return file


def _patch_task_file_add(monkeypatch):
    def add_task_file(field, attached_file):
        current = list(getattr(field, "_value", []) or [])
        if attached_file not in current:
            current.insert(0, attached_file)
        field._value = current
        field.entity.db[field.id] = [item.key for item in current]

        linked = list(attached_file.db.get("tasks") or [])
        if field.entity.key not in linked:
            linked.insert(0, field.entity.key)
        attached_file.db["tasks"] = linked

        task_links = list(getattr(attached_file.properties.tasks, "_value", []) or [])
        if field.entity not in task_links:
            task_links.insert(0, field.entity)
        attached_file.properties.tasks._value = task_links
        field.entity.add_mutation_intents(
            MutationIntent.patch(
                attached_file,
                "tasks",
                "requires",
                property_updates=("requires", "modified"),
                reason="task-file-mirror",
            )
        )
        return True

    monkeypatch.setattr(
        "lagniappe.core.properties.task_related.TaskFiles.add",
        add_task_file,
    )


def _fetch_one_from(entities):
    def fetch_one(identifier, *, request):
        if hasattr(identifier, "db"):
            return identifier
        return entities.get(identifier)

    return fetch_one


def _test_user(hash_value):
    return TestEntities.get(
        "USER",
        {
            "name": "Owner",
            "hash": hash_value,
            "owner": True,
            "page": {"name": "Owner Page", "hash": f"{hash_value}-page"},
        },
    )


def _permissioned_user(hash_value, permissions):
    return TestEntities.get(
        "USER",
        {
            "name": "Permissioned User",
            "hash": hash_value,
            "permissions": permissions,
            "page": {"name": "Permissioned Page", "hash": f"{hash_value}-page"},
        },
    )


def _prompt_context(prompt, label):
    for block in prompt.context_blocks:
        if block["label"] == label:
            return block["value"]
    raise AssertionError(f"Missing prompt context block: {label}")


def _prompt_context_json(prompt, label):
    value = _prompt_context(prompt, label).strip()
    if value.startswith("```") and value.endswith("```"):
        value = value.split("\n", 1)[1].rsplit("\n", 1)[0]
    return json.loads(value)


def _response_action_schemas(prompt):
    variants = prompt.response_schema["properties"]["actions"]["items"]["anyOf"]
    return {
        variant["properties"]["type"]["enum"][0]: variant
        for variant in variants
    }


def _assert_repair_prompt_contract(prompt, *, invalid_proposal, allowed_actions):
    assert prompt.allowed_actions == tuple(allowed_actions)
    assert prompt.output_format["type"] == "JSON"
    assert _prompt_context(prompt, "Validation Error").strip()
    assert _prompt_context_json(prompt, "Allowed Actions") == list(allowed_actions)
    assert _prompt_context_json(prompt, "Invalid Proposal Json") == invalid_proposal
    assert prompt.response_schema["required"] == [
        "summary",
        "confidence",
        "issues",
        "actions",
    ]
    assert tuple(_response_action_schemas(prompt)) == tuple(allowed_actions)
    assert prompt.audit()["duplicate_headings"] == []



def _recovery_store(monkeypatch, *initial):
    stored = {entity.urlsafe_key: entity for entity in initial}
    saves = []

    def save(*entities):
        saves.append(tuple(entities))
        for entity in entities:
            if getattr(entity, "entity_kind", None) != "report":
                stored[entity.urlsafe_key] = entity

    def fetch_one(identifier, *, request):
        if hasattr(identifier, "db"):
            return identifier
        return stored.get(identifier)

    monkeypatch.setattr(report_runner.Entities, "save", save)
    monkeypatch.setattr(report_runner.Entities, "fetch_one", fetch_one)
    return stored, saves

__all__ = tuple(name for name in globals() if not name.startswith("__"))
