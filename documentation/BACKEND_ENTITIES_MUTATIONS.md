# Backend Entity Mutations

Entity persistence is planned before it is executed. This boundary keeps
root writes, dependent repairs, cache work, and provider cleanup explicit and
makes partial failure observable.

## Save flow

`Entity.save()` delegates to `Entities.save()`. The registry selects the
entity-kind planner under `lagniappe/core/mutations/` and produces a
`MutationPlan` containing:

- complete root writes;
- property-masked dependent writes;
- durable deletes and survivor repairs;
- cache/search effects; and
- asset cleanup and other post-commit work.

Every entity passed directly to `Entities.save(*entities)` is a complete root
write. Lifecycle properties, requirements, process serialization, and the full
`exclude_from_indexes` set are prepared by the executor.
If a dependency touch carries a different instance of the same entity, the
complete root save supplies the authoritative instance for both the durable
write and cache refresh, regardless of planning order. A shallow dependency
copy must never replace the complete root's fields or permission requirements.
Dependency ordering tracks completed entity keys and removes each ready write
by object identity. Mutation-effect equality excludes its entity and dependencies,
so equal-looking effects for different roots must remain distinct.

An entity may declare `retired_fields` for obsolete stored keys. The executor
discards those keys while preparing any otherwise-requested complete save,
allowing old records to converge without a global data migration.

Domain code can register typed `MutationIntent` values while it changes an
entity. `standard` means another complete domain write; `patch` and `touch`
name narrow dependent changes; cache-state and search-delete intents are
post-commit effects. Intents are consumed only after all durable writes and
deletes succeed, so a failed commit can be retried from the same domain state.

## Property masks

Masked writes use Datastore `update`, not a partial upsert. A missing row is
not recreated from an incomplete document. Use a mask when the contract owns a
small dependent change, such as:

- touching a list owner's `modified` timestamp;
- updating an exact mirrored relationship;
- persisting one task default field; or
- advancing document assets/history independently from the parent lifecycle.

`save_root(entity, property_mask=...)` is a low-level root-only write. It keeps
the complete index-exclusion set but deliberately skips lifecycle values,
intent consumption, and cache work. `touch()` uses the same boundary with a
`modified` mask.

Collaborative documents have two masks. `save_document_checkpoint()` writes
only `assets` and `document_history` and refreshes the document cache without
changing the parent fingerprint. `advance_document_parent()` later touches the
Page/Project and list owner when the changed document leaves its active
lifecycle. See [SYNC_DOCUMENTS.md](SYNC_DOCUMENTS.md).

## Delete flow

`Entities.delete()` uses the same planner/executor boundary. It:

1. resolves cascade and survivor effects;
2. merges repeated survivor instances by key;
3. commits survivor unlinks and durable deletes;
4. runs cache, search, and blob cleanup; and
5. returns a `MutationOutcome` that separates durable commit from post-commit
   completion.

A post-commit Redis or Storage failure never rolls back or obscures the durable
result. Callers must inspect and report post-commit errors when their workflow
needs them.

Cascade ownership is domain-specific. Category deletion owns its Pages; Page
deletion owns its Tasks, TaskHistory, Files, and Filters; Project deletion owns
its ModelTasks and orphaned Forms. Non-owning references are not rewritten by
an unrelated delete unless the mutation contract declares that survivor
effect.

Category deletion preserves Pages that still belong to another Category and
deletes those with no remaining Category. Decide this before removing the
Category: ordinary Page category removal can assign the Uncategorized Pages
fallback. Surviving Page repairs persist both `categories` and `model` so a
deleted model Category cannot remain as a stale durable reference.

## Mutation contracts

`core/definitions/mutation_contracts.py` is the machine-readable inventory for
persisted entity kinds and DB-backed relations. Each relation declares:

- source and target types;
- cardinality and storage shape;
- durable authority and mutation gateway;
- save effects; and
- source/target delete policy.

Query-derived edges are included with `persisted=False`. Virtual Site/Home
objects and non-persisted Conditions are outside the registry. Unregistered
persisted kinds fail instead of receiving generic mutation behavior.

Inspect the inventory with:

```bash
venv/bin/python run.py mutation-contracts --kind task --json
venv/bin/python run.py mutation-contracts --check
```

Run the check whenever a persisted kind, relation, cascade, property mask, or
post-commit effect changes.

## Fetch depth and relation loading

Reads are explicit about the total graph promised to a consumer:

| Request | Available graph | Relation batches for a typed root |
| --- | --- | --- |
| `Fetch.root()` | Roots only. | 0 |
| `Fetch.direct()` | Roots and their direct relations. | At most 1. |
| `Fetch.nested(because=...)` | Roots, direct relations, and their relations. | At most 2. |

Starting from keys adds one root-loading batch. Nested fetching stops after two
relationship levels: at most three batches from keys, or two from loaded roots.

Nested reads require a registered `FetchReason`. Request authentication loads
the session User and user Page with `Fetch.direct()`. Task and File permission
boundaries use `Fetch.nested()` so effective restrictions have their Page and
Form dependencies loaded. History authorization resolves the live Task as a
nested root, because its current Page can differ from the historical Page.
Other handlers declare the graph needed at the point of use. Attached relations
are reused, so only missing second-level keys need another batch.

`DEBUG_TRACING` records the declared depth, reason, stage, key counts, and
database read counts. Strict relation checks make an unplanned relation access
visible rather than allowing an implicit N+1 read.

## Fingerprints and cache effects

`modified` represents dependency invalidation, not only direct content edits.
Changing a Page can touch its Category owners because their rendered Page lists
changed. Those owners receive new fingerprints and ETags even though their own
form fields did not change.

Page/Form restriction changes and Page/Task attached-Form changes mark a pending
permission-source invalidation. The source's full save advances the Tasks
collection fingerprint in its Datastore batch and queues permission
reconciliation after durable success. The pending marker survives commit
failure for retry; incidental masked touches do not consume it.
Page/Form save planners pass their already-resolved Category/Project owner keys
to reconciliation so completion can refresh those lists without another owner
query. Reconciliation supplements those hints with raw Category/Project keys
from its root Page/Task batches, preserving their deduplicated union across
continuations before the final touch. Finding these owners requires no relation
expansion and does not depend solely on the Category's Form registry.

Redis search/detail refresh, filter-index updates, cache invalidation, and blob
deletion happen after durable success. The browser receives entity revisions
from mutation responses and obtains collection changes through durable site
fingerprints. Do not move those authorities into Redis.

## Before changing a mutation

Trace the whole effect, not just the root method:

1. Find the kind and relation entries in `mutation_contracts.py`.
2. Read the kind planner and any property methods that register intents.
3. Identify every dependent fingerprint and survivor relation.
4. Separate durable changes from reconstructable/provider effects.
5. Add focused unit coverage for commit failure, retry, and delete behavior.
6. Run `mutation-contracts --check` and
   `venv/bin/python run.py traceability --changed --check`.

## File ownership

Direct Page attachments store `page`. Task attachments store `task` and the
unindexed `task_page` ancestry key, with no direct `page`. File saves recalculate
`task_page` from the Task and clear incompatible links; the primary link supplies
File permissions and restrictions. Unattached upload/report Files stay private
and unsearchable; `report_user` identifies the uploader allowed to view staged
content. Task form uploads retain their signed, actor-and-scope-bound attachment
claims until final attachment. A TaskHistory's `files` are non-owning references; the
live Task remains the permission owner after a completion is archived. Removing
a current attachment does not erase that ownership. `File.move_to()` updates
current Task attachment lists and both owners' refresh intents.

Report saves update the Report and its parent/user lists without touching input
Files. Upload, summary, and execution operations save the Files they change.

Deleting a Page or Task deletes its owned Files, including history-only Task
attachments, and removes surviving history references. Combining Tasks transfers
all owned Files before deleting the old Task. Moving a Task updates its owned
Files' `task_page` and `requires` through masked writes. A pending Task move survives a
failed durable commit for retry. Page Files tabs and the Page-only File delete
cascade query `page` to select only direct Page attachments.

Upgrade and repair steps are documented in
[Durable Data Migrations](DATA_MIGRATIONS.md).

File ownership updates use explicit empty `MutationIntent.depends_on` tuples
for reverse links and owner touches. Those key-list writes do not depend on the
File's computed fields; the File's `requires` calculation depends on its owner.
Other patch/touch intents retain their default dependency on the emitting entity.
