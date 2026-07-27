"""Guidelines for bounded AI-proposed form schema edits."""

SCHEMA_EVOLUTION_GUIDELINES = """
### Schema Evolution Guidelines

Use schema update actions only for additive, non-destructive changes that make
existing or proposed submission updates visible in the current form.

Allowed schema changes:
- Add one optional field when the existing form lacks a clear place for useful
  structured data.
- Add one missing option to an existing select or radio field when the field is
  otherwise the right place for the value.

Do not delete, rename, reorder, or change the type of existing fields. Do not
make a new or existing field required. Do not change visibility rules. Do not
rewrite an entire schema when a small additive operation is enough.

When proposing submission updates that would benefit from a schema update, keep
the schema update in a separate update_form_schema action. The user can skip
schema updates independently; submission updates should still be exact,
reviewable patches against page/task ids and schema ids.

Every `add_field` operation must contain a complete executable field object.
It must include a unique, stable `id`, a supported `type`, and a human-readable
`title`; a label or placeholder by itself is not a field definition. An
`input` field must also include its input subtype, such as `text`, `date`, or
`number`. Selection fields must include explicit value/label option objects.
Do not claim that a schema was corrected unless the returned operation contains
the corrected field definition.
"""
