"""Schema guidance selected by trusted invocation context."""

_SCHEMA_EVOLUTION_COMMON = """
### Schema Evolution Guidelines

Use update_form_schema for a bounded set of changes to one Form. The user reviews
the plan before execution. Explain removals, type changes, lost choices/columns,
clearing of unconvertible values, and the absence of submission-migration Undo.
Do not apply unrelated schema changes just to accommodate one document.
For a new Form, put the final schema in create_form instead of planning conversions.

First read get_schema for exact field/option/column IDs. Call
preview_form_schema_update with the proposed operations to validate the complete
schema and discover all affected live Pages/Tasks, including completed Tasks.
Follow every next_cursor with identical operations. Preserve baseline and
scope_fingerprint in the action. Restricted affected Pages/Tasks block the whole
AI-proposed migration; do not substitute a filtered query or omit hidden targets.
Link affected entities in the plan; the server also supplies paginated review links.

Operations use exact IDs:
- add_field: a complete field with a new stable id, type and title; input fields
  specify input, selections specify options, tables specify exact column IDs.
- add_select_option: schema_id and option {value, label}.
- update_field: schema_id and patch containing only changed settings. IDs are
  immutable. Omitted settings survive; null removes an optional setting. Type
  changes discard obsolete type-specific settings, so include destination options
  or columns where needed. Metadata, required flags and conditions may be edited.
- remove_field: schema_id. Reserved Page name/description fields cannot be removed.
- reorder_fields: ids containing every final field ID exactly once.
Repair any dependent visibility/status conditions explicitly in the operations.
Static/signature conversions and entity lookup or asset conversions are unsupported.

The preview classifies conversion rules deterministically. AI is used only for
textarea to table/todo, table to todo, and todo to table. Todo is Task-only.
Table/todo to textarea is deterministic. Destination tables require supported
scalar/checkbox/external-link columns; preserve zero, false, row order and explicit
completion states. Empty or absent values do not need AI. Unresolvable populated
values will clear with their originals retained in View changes.

Place the single schema action before every action that depends on its Form or
submissions. Dependents wait for schema publication and skip if the user skips
that schema action. Existing completed submission envelopes and TaskHistory stay
unchanged. Describe the proposed result; the user will review the plan before any
schema or saved values change.
"""

SCHEMA_EVOLUTION_GUIDELINES = _SCHEMA_EVOLUTION_COMMON + """
### Conversion instructions

Include optional conversion_instructions keyed by AI-converted field ID (maximum
4000 characters each). Describe how to interpret the values and destination
columns. Saved-value conversion happens after the user approves the plan; your
proposal contains the schema changes and instructions, not generated conversions.
Use the preview's affected entities and conversion rules to explain the impact.
"""

EXTERNAL_SCHEMA_EVOLUTION_GUIDELINES = _SCHEMA_EVOLUTION_COMMON + """
### Prepared conversions

Call preview_form_schema_update with include_values=true and follow ALL pages.
Only affected AI field values are returned, preserving rows and types. Supply
data.conversions with exactly one {entity, schema_id, source_fingerprint, value}
or {entity, schema_id, source_fingerprint, unresolved_reason} per populated AI
field. Copy each entity and source_fingerprint from the preview. Value must match
the exact destination shape: {rows: [{column_id: value}]} or
{items: [{text: "item", checked: false}]}. Preserve zero, false, order and explicit
completion states. Do not infer entity links. An unresolved value requires a
nonempty unresolved_reason and no value; empty collections cannot clear a
populated source implicitly. No duplicate, missing or extra conversion targets.

The user will review these exact candidates before they are applied. Author the
complete conversions now; execution does not generate or repair candidates.
Candidate cells use exact destination JSON types: text/email/tel are strings,
numbers are finite JSON numbers, and checkboxes are booleans (not strings).
Dates are ISO 8601 timestamps with a timezone; times use HH:MM. External links
use {title, url}. Omit missing cells rather than inventing a value. Numeric-string
coercion accepted by ordinary submission entry does not apply to candidates.
Keep candidates inside the proposal size limit. For a storage-size rejection,
reduce the change's scope; never truncate source values. Changed values,
membership, permissions or schema require a fresh preview and review.
"""
