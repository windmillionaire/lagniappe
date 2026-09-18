"""Working entities and atomic commits for deterministic report execution."""

from contextlib import ExitStack
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace as replace_intent
import json
from uuid import uuid4

from lagniappe.core.definitions import Fetch, MutationIntent, MutationIntentType
from lagniappe.core.entities import Entities
from lagniappe.core.exceptions import MutationConflict
from lagniappe.core.tools.cache import documents
from lagniappe.core.tools.document_crdt import document_state
from lagniappe.core.tools.document_updates import document_seed
from lagniappe.core.tools.deferred_jobs.errors import DeferredJobInfrastructureError

MAX_BATCH_ACTIONS = 50
MAX_BATCH_BYTES = 4 * 1024 * 1024


# @testable true
# @tests tests_unit/test_032h_report_batches.py::test_document_publication_retries_without_reapplying_changes
# @matrix ai-report : batching documents recovery
def publish_pending_documents(report, workspace=None):
    """Finish committed collaborative publications without replaying actions."""
    pending = report.db.get("execution_documents") or []
    if not pending:
        return
    try:
        for reference in pending:
            page = workspace.resolve(reference) if workspace is not None else Entities.fetch_one(reference, request=Fetch.direct())
            if page is None:
                continue
            sync_id = page.properties.document.sync_id
            with nullcontext() if workspace is not None else documents.document_write_lock(sync_id):
                documents.publish_document_checkpoint(sync_id, seed=document_seed(page))
        report.db["execution_documents"] = []
        report._form_additional_guards = [(report.key, {"execution_commit": report.db.get("execution_commit")})]
        Entities.save(report)
    except Exception as error:
        raise DeferredJobInfrastructureError("Changes were saved; document publication needs recovery.") from error
    finally:
        report._form_additional_guards = []


# @testable true
# @tests tests_unit/test_032h_report_batches.py::test_dependent_creations_share_one_commit
# @tests tests_unit/test_032h_report_batches.py::test_updates_reuse_loaded_entities_and_merge_final_state
# @matrix ai-report : batching identity dependencies
class WorkingEntities(dict):
    """Resolve saved references once and share staged outputs by key and alias."""

    def __init__(self):
        super().__init__()
        self.new_keys = set()
        self.references = {}

    def resolve(self, reference):
        if reference in self:
            return self[reference]
        if reference in self.references:
            return self[self.references[reference]]
        from .actions.references import _fetch_report_entity

        entity = _fetch_report_entity(reference)
        if entity is not None:
            entity = self.remember(entity, replace=False)
            self.references[reference] = entity.key
        return entity

    def remember(self, entity, *, replace=True):
        pending = [entity]
        seen = set()
        while pending:
            current = pending.pop()
            if current.key in seen:
                continue
            seen.add(current.key)
            previous = self.get(current.key)
            if previous is None or (current is entity and replace):
                for alias, value in list(self.items()):
                    if value.key == current.key:
                        self[alias] = current
                self[current.key] = self[current.urlsafe_key] = current
            pending.extend(current.related_entities.values())
        by_key = {value.key: value for value in self.values()}
        for value in by_key.values():
            rebound = False
            for relation in value.relations:
                attached = relation.attached_entities
                if any(key in by_key and by_key[key] is not linked for key, linked in attached.items()):
                    relation.attach({**attached, **by_key})
                    rebound = True
            if rebound:
                # Derived relationships (for example Page categories including
                # its model) can cache another relation's attached instance.
                for relation in value.relations:
                    relation._invalidate_projections()
            value._mutation_intents = [
                replace_intent(intent, entity=by_key[intent.entity.key])
                if intent.entity is not None and intent.entity.key in by_key and by_key[intent.entity.key] is not intent.entity
                else intent
                for intent in value.mutation_intents
            ]
        return self[entity.key]


# @testable true
# @tests tests_unit/test_032h_report_batches.py::test_dependent_creations_share_one_commit
# @tests tests_unit/test_032h_report_batches.py::test_batch_failure_and_ambiguous_commit_do_not_duplicate_creations
# @tests tests_unit/test_032h_report_batches.py::test_documents_upload_before_combined_commit_and_publish_after
# @tests tests_unit/test_032h_report_batches.py::test_batch_boundaries_resume_without_replaying_completed_work
# @matrix ai-report : batching atomicity documents dependencies recovery
class ExecutionBatch:
    """Stage final entity states; publish documents only after their receipt commits."""

    def __init__(self, report, result, workspace, ensure_active):
        self.report, self.result, self.workspace = report, result, workspace
        self.ensure_active = ensure_active
        self.roots = {}
        self.documents = {}
        self.indices = []
        self.before = deepcopy(result)
        self.previous_commit = report.db.get("execution_commit")
        self.previous_documents = deepcopy(report.db.get("execution_documents") or [])

    def stage(self, index, entity, writes):
        for item in writes:
            # Detached preparation can also patch a shared relationship owner.
            # Adopt its final state so the next action extends the same record.
            for intent in item.mutation_intents:
                if intent.intent is MutationIntentType.PATCH:
                    self.workspace.remember(intent.entity)
            self.workspace.remember(item)
            self.roots[item.key] = True
        if entity is not None:
            self.workspace.remember(entity)
        self.indices.append(index)

    @property
    def full(self):
        if len(self.indices) >= MAX_BATCH_ACTIONS:
            return True
        size = sum(len(json.dumps(dict(self.workspace[key].db), default=str).encode()) for key in self.roots)
        return size >= MAX_BATCH_BYTES

    def add_document(self, entity):
        if entity.key not in self.documents:
            self.documents[entity.key] = {
                "expected": deepcopy(entity.db.get("assets")),
                "seed": document_seed(entity),
                "sync_id": entity.properties.document.sync_id,
            }
            return True
        return False

    def discard(self):
        """Discard uncommitted results; no staged workspace writes were published."""
        self.report.db["execution_documents"] = self.previous_documents
        for index in self.indices:
            self.result["actions"][index] = deepcopy(self.before["actions"][index])

    def commit(self):
        self.ensure_active()
        report = self.report
        token = uuid4().hex
        previous_intents = list(report.mutation_intents)
        guards = [(report.key, {"execution_commit": self.previous_commit})]
        with ExitStack() as locks:
            document_intents = []
            for key, document in sorted(self.documents.items(), key=lambda item: item[1]["sync_id"]):
                locks.enter_context(documents.document_write_lock(document["sync_id"]))
                current = documents.current_document_state(document["sync_id"], seed=document["seed"], reconcile=False)
                if current.get("updates") or document_state(current.get("ydoc")) != document_state(document["seed"].get("ydoc")):
                    raise MutationConflict("Document changed during execution; retry the plan.")
                page = self.workspace[key]
                guards.append((key, None if key in self.workspace.new_keys else {"assets": document["expected"]}))
                if key not in self.roots:
                    document_intents.extend((
                        MutationIntent.patch(page, "assets", "document_history", reason="report-document"),
                        *page.mutation_intents,
                        *(MutationIntent.touch(owner, reason="report-document-owner") for owner in page.page_list_owners),
                    ))
            self.ensure_active()
            try:
                if document_intents:
                    report.add_mutation_intents(*document_intents)
                report.db["execution_commit"] = token
                report.db["execution_documents"] = [self.workspace[key].urlsafe_key for key in self.documents]
                report._form_additional_guards = guards
                report.result = self.result
                Entities.save(*(self.workspace[key] for key in self.roots), report)
            except Exception as error:
                # A timeout or a post-commit cache error is not evidence that the
                # write failed. Read just the batch receipt, never replay writes.
                try:
                    saved = Entities.fetch_one(report.key, request=Fetch.root())
                except Exception:
                    # Leave the durable ledger alone until recovery can read it.
                    raise DeferredJobInfrastructureError("Could not reconcile the batch commit; recovery must read its receipt.") from error
                if saved is None or saved.db.get("execution_commit") != token:
                    report.db["execution_commit"] = self.previous_commit
                    if saved is not None and saved.db.get("execution_commit") != self.previous_commit:
                        raise DeferredJobInfrastructureError("Another batch was committed; recovery must use its saved receipt.") from error
                    raise
                if self.result.get("status") != "complete":
                    # The server accepted the writes, but local save lifecycle
                    # cleanup may not have run. Continue from fresh objects on
                    # recovery instead of reusing uncertain in-memory intents.
                    raise DeferredJobInfrastructureError("The batch was saved; recovery will continue the remaining actions.") from error
            finally:
                report._form_additional_guards = []
                report._mutation_intents = previous_intents

            publish_pending_documents(report, self.workspace)
        self.previous_commit = token
        self.previous_documents = []
        self.before = deepcopy(self.result)
        self.roots.clear()
        self.documents.clear()
        self.indices.clear()
        self.workspace.new_keys.clear()
