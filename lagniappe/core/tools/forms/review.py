"""Snapshot, merge, and review contracts for concurrently editable autofill."""

from copy import deepcopy
import json

from ...definitions import Action, Fetch
from ...entities import Entities
from ...properties.schema import SchemaFields
from ..ai import autofill
from ..database.utility import ExactEntityState
from .contracts import check_size, json_value


REVIEWS = "autofill_reviews"
RECEIPT = "autofill_receipt"


# @testable true
# @pair ai:autofill
def merge_proposal(baseline, current, proposed, *, review_only=False):
    """Merge whole-field updates; never infer identities for rows or checklist items."""
    merged, conflicts, applied = deepcopy(current), {}, []
    for field_id, value in proposed.items():
        before, latest = baseline.get(field_id), current.get(field_id)
        if value == before or value == latest:
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


# @testable true
# @pair ai:autofill
def launch_snapshot(target, actor, *, instructions=None, submission=None, review_context=None):
    """Seal the form and the initial AI input before the worker can reload them."""
    prompt = autofill.autofill_prompt_data(target, actor, user_context=instructions)
    prompt.pop("user", None)
    prompt.pop("file", None)
    if submission is not None:
        prompt["submission"] = deepcopy(submission)
    if review_context:
        prompt["review_context"] = deepcopy(review_context)
    snapshot = {
        "version": 1,
        "form": getattr(target.form, "urlsafe_key", None),
        "generation": target.generation,
        "revision": target.autofill_revision,
        "answers": deepcopy(target.properties.submission.value or {}),
        "values": deepcopy(submission if submission is not None else target.properties.submission.form_value or {}),
        "prompt": prompt,
    }
    # References in snapshots are strings, not live Datastore keys/entities.
    return json.loads(json.dumps(snapshot, default=str))


# @testable true
# @pair ai:autofill
def prepare_proposal(schema, submission, target, actor):
    """Validate against the launch schema and retain both stored and browser values."""
    submission = autofill.validate_submission(submission, entity=target, user=actor, schema=schema)
    fields = {field["id"]: field for field in schema}
    answers, values = {}, {}
    for field_id, value in submission.items():
        candidate = SchemaFields.prepare_ai_field(fields[field_id], value, target, user=actor)
        answers[field_id] = candidate.db_value if candidate.is_set else None
        values[field_id] = candidate.form_value if candidate.is_set else None
    return {"answers": answers, "values": values}


# @testable true
# @pair ai:autofill
def stage_submission_guard(target, submitted):
    """Check a browser baseline and fence the eventual write, not just the read."""
    expected = submitted.get("form-revision")
    if expected != target.autofill_revision:
        return False
    guards = list(getattr(target, "_form_additional_guards", ()))
    guards.append((target.key, ExactEntityState(deepcopy(dict(target.db)))))
    target._form_additional_guards = guards
    return True


# @testable infrastructure
def review_slot(actor=None):
    return actor.urlsafe_key if actor is not None else "shared"


# @testable infrastructure
def review_references(target):
    return json_value(target.db, REVIEWS)


# @testable infrastructure
def remember_review(target, job, *, private=False):
    refs = review_references(target)
    refs[review_slot(job.actor if private else None)] = job.urlsafe_key
    target.db[REVIEWS] = json.dumps(refs)
    check_size(target.db)


# @testable true
# @pair ai:autofill
def review_projection(target, actor):
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
        if private and job.actor.key != actor.key:
            continue
        snapshot = (job.parameters or {}).get("snapshot") or {}
        checkpoint = job.checkpoint or {}
        if not job.db.get(RECEIPT) or not snapshot or "proposal" not in checkpoint:
            continue
        result.append({
            "operation": job.urlsafe_key,
            "private": private,
            "fields": list(checkpoint["proposal"]["values"]),
            "schema": snapshot["prompt"]["schema"],
            "baseline": snapshot.get("values", {}),
            "submission": {**snapshot.get("values", {}), **checkpoint["proposal"]["values"]},
        })
    return result


# @testable true
# @pair ai:autofill
def acknowledge_reviews(target, actor, operations):
    """Only a successful ordinary save consumes explicitly reviewed references."""
    refs = review_references(target)
    for slot in ("shared", review_slot(actor)):
        if refs.get(slot) in operations:
            refs.pop(slot, None)
    if refs:
        target.db[REVIEWS] = json.dumps(refs)
    else:
        target.db.pop(REVIEWS, None)


# @testable infrastructure
def migration_review(target):
    """Typed before-values for the same review UI, without discarding old types."""
    before = json_value(target.db, "pre_migration")
    schema, values = [], {}
    for field_id, original in before.items():
        definition = original["schema"]
        field = SchemaFields.create_field(definition, target)
        if field is None:
            continue
        field.db_value = original.get("value")
        schema.append(deepcopy(definition))
        values[field_id] = field.form_value
    return {"schema": schema, "submission": values} if schema else None
