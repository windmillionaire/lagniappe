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

Nested reads require a registered `FetchReason`. Request authentication loads
the session User, user Page, and requested entity as roots with
`Fetch.direct()`. A handler that genuinely needs another level re-fetches the
typed entity at the point of use. Attached relations are reused, so only
missing second-level keys need another batch.

`DEBUG_TRACING` records the declared depth, reason, stage, key counts, and
database read counts. Strict relation checks make an unplanned relation access
visible rather than allowing an implicit N+1 read.

## Fingerprints and cache effects

`modified` represents dependency invalidation, not only direct content edits.
Changing a Page can touch its Category owners because their rendered Page lists
changed. Those owners receive new fingerprints and ETags even though their own
form fields did not change.

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

## File ownership (1.3.0)

Files have either `page` or `task`, each a single key. Unattached upload/report
Files may have neither. A TaskHistory's `files` are non-owning references; the
live Task remains the permission owner after a completion is archived. Removing
a current attachment does not erase that ownership. `File.move_to()` updates
current Task attachment lists and both owners' refresh intents.

Deleting a Page or Task deletes its owned Files, including history-only Task
attachments, and removes surviving history references. Combining Tasks transfers
all owned Files before deleting the old Task. Moving a Task updates its owned
Files' `requires` through masked writes, without persisting a derived Page key.

Migration `FIL-001` converts unambiguous legacy lists and normalizes history links
to live Tasks. Multiple owners or missing owners are reported for repair; those
rows remain untouched and the migration ledger stays incomplete. `RST-001`
materializes local Form/Page group hashes while preserving owner-only settings.
Both migrations are introduced in 1.3.0 and precede the existing cache rebuild.

File ownership updates use explicit empty `MutationIntent.depends_on` tuples
for reverse links and owner touches. Those key-list writes do not depend on the
File's computed fields; the File's `requires` calculation depends on its owner.
Other patch/touch intents retain their default dependency on the emitting entity.
