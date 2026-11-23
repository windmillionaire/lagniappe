"""Snapshot, merge, and review contracts for concurrently editable autofill."""
import json
from collections.abc import Collection, Mapping, Sequence
from copy import deepcopy
from typing import TYPE_CHECKING, TypedDict, cast

from ...definitions import Action, Fetch
from ...entities import Entities
from ...properties.schema import SchemaFields
from ..ai import autofill
from ..database.utility import ExactEntityState, PageSubmissionState
from .contracts import check_size, json_value

if TYPE_CHECKING:
    from google.cloud.datastore import Key

    from ...entities.deferred_job import DeferredJob
    from ...entities.page import Page
    from ...entities.task import Task
    from ...entities.user import User
    from ...properties.base_schema import FieldDefinition


REVIEWS = "autofill_reviews"
RECEIPT = "autofill_receipt"


class Proposal(TypedDict):
    answers: dict[str, object]
    values: dict[str, object]


def merge_proposal(
    baseline: Mapping[str, object],
    current: dict[str, object],
    proposed: Mapping[str, object],
    *,
    review_only: bool = False,
) -> tuple[dict[str, object], dict[str, object], list[str]]:
    """Merge whole-field updates; never infer identities for rows or checklist items."""
    merged, conflicts, applied = deepcopy(current), {}, []
    for field_id, value in proposed.items():
        before, latest = baseline.get(field_id), current.get(field_id)
        if value in (before, latest):
            continue
        if review_only or latest != before:
            conflicts[field_id] = deepcopy(value)
        else:
            if value is None:
                merged.pop(field_id, None)
            else:
                merged[field_id] = deepcopy(value)
            applied.append(field_id)
    return merged, conflicts, applied


def launch_snapshot(
    target: Page | Task,
    actor: User,
    *,
    instructions: str | None = None,
    submission: dict[str, object] | None = None,
    prompt_submission: dict[str, object] | None = None,
    target_context: dict[str, object] | None = None,
    review_context: dict[str, object] | None = None,
) -> dict[str, object]:
    """Seal the form and the initial AI input before the worker can reload them."""
    prompt = autofill.autofill_prompt_data(target, actor, user_context=instructions)
    prompt.pop("user", None)
    prompt.pop("file", None)
    if prompt_submission is not None:
        prompt["submission"] = deepcopy(prompt_submission)
    elif submission is not None:
        prompt["submission"] = deepcopy(submission)
    if target_context:
        prompt.setdefault("target", {}).update(deepcopy(target_context))
    if review_context:
        prompt["review_context"] = deepcopy(review_context)
    snapshot = {
        "version": 1,
        "form": getattr(target.form, "urlsafe_key", None),
        "generation": target.generation,
        "revision": target.autofill_revision,
        "answers": deepcopy(target.properties.submission.value or {}),
        "saved_values": deepcopy(target.properties.submission.form_value or {}),
        "values": deepcopy(submission if submission is not None else target.properties.submission.form_value or {}),
        "prompt": prompt,
    }
    # References in snapshots are strings, not live Datastore keys/entities.
    return json.loads(json.dumps(snapshot, default=str))


def snapshot_matches_form(snapshot: Mapping[str, object], target: Page | Task) -> bool:
    """Answer drift can be reviewed; a different form definition needs a fresh run."""
    return bool(snapshot) and (
        snapshot.get("form") == getattr(target.form, "urlsafe_key", None)
        and snapshot.get("generation") == target.generation
        and cast(Mapping[str, object], snapshot.get("prompt", {})).get("schema") == target.submission_schema
    )


def prepare_proposal(
    schema: Sequence[FieldDefinition],
    submission: Mapping[str, object],
    target: Page | Task,
    actor: User,
) -> Proposal:
    """Validate against the launch schema and retain both stored and browser values."""
    submission = autofill.validate_submission(submission, entity=target, user=actor, schema=schema)
    fields = {field["id"]: field for field in schema}
    answers, values = {}, {}
    for field_id, value in submission.items():
        candidate = SchemaFields.prepare_ai_field(fields[field_id], value, target, user=actor)
        answers[field_id] = candidate.db_value if candidate.is_set else None
        values[field_id] = candidate.form_value if candidate.is_set else None
    return {"answers": answers, "values": values}


def stage_submission_guard(
    target: Page | Task, submitted: Mapping[str, object]
) -> bool:
    """Check a browser baseline and fence the eventual write, not just the read."""
    expected = submitted.get("form-revision")
    if expected != target.autofill_revision:
        return False
    guards: list[tuple[Key, ExactEntityState]] = list(getattr(target, "_form_additional_guards", ()))
    if target.key is None:
        return False
    expectation = PageSubmissionState if getattr(target, "entity_kind", None) == "page" else ExactEntityState
    guards.append((target.key, expectation(deepcopy(dict(target.db)))))
    target._form_additional_guards = guards
    return True


def review_slot(actor: User | None = None) -> str | None:
    return actor.urlsafe_key if actor is not None else "shared"


def review_references(target: Page | Task) -> dict[str | None, str | None]:
    return cast(dict[str | None, str | None], json_value(target.db, REVIEWS))


def remember_review(
    target: Page | Task, job: DeferredJob, *, private: bool = False
) -> None:
    refs = review_references(target)
    refs[review_slot(job.actor if private else None)] = job.urlsafe_key
    target.db[REVIEWS] = json.dumps(refs)
    check_size(target.db)


def review_projection(target: Page | Task, actor: User) -> list[dict[str, object]]:
    """Project only saved shared proposals and this editor's private refinement."""
    if not target.allowed(Action.EDIT, user=actor):
        return []
    refs = review_references(target)
    keys = list(dict.fromkeys(filter(None, (refs.get("shared"), refs.get(review_slot(actor))))))
    result = []
    for job in Entities.fetch(*keys, request=Fetch.direct()) if keys else ():
        if not isinstance(job, Entities.DEFERRED_JOB) or job.job_type != "autofill":
            continue
        if ((job.inputs or {}).get("target") or {}).get("id") != target.urlsafe_key:
            continue
        private = (job.parameters or {}).get("mode") == "revise"
        if private and (job.actor is None or job.actor.key != actor.key):
            continue
        snapshot = (job.parameters or {}).get("snapshot") or {}
        checkpoint = job.checkpoint or {}
        proposal = checkpoint.get("proposal")
        if not job.db.get(RECEIPT) or not isinstance(snapshot, dict) or not isinstance(proposal, dict):
            continue
        if not snapshot_matches_form(snapshot, target):
            continue
        result.append({
            "operation": job.urlsafe_key,
            "private": private,
            "fields": list(proposal["values"]),
            "schema": snapshot["prompt"]["schema"],
            "baseline": snapshot.get("values", {}),
            "saved_baseline": snapshot.get("saved_values", {}),
            "submission": {**snapshot.get("values", {}), **proposal["values"]},
        })
    return result


def acknowledge_reviews(
    target: Page | Task, actor: User, operations: Collection[str]
) -> None:
    """Only a successful ordinary save consumes explicitly reviewed references."""
    refs = review_references(target)
    for slot in ("shared", review_slot(actor)):
        if refs.get(slot) in operations:
            refs.pop(slot, None)
    if refs:
        target.db[REVIEWS] = json.dumps(refs)
    else:
        target.db.pop(REVIEWS, None)
