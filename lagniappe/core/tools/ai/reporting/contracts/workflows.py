"""Shared Organize profiles; transport origin is assigned by trusted intake."""

REMOTE_UPDATE_ACTIONS = frozenset(
    {
        "complete_task",
        "append_page_document",
        "update_form_values",
        "extend_form_schema",
        "rename_entity",
        "move_page",
        "move_task",
        "move_file",
        "add_page_category",
        "add_form_to_page",
        "needs_review",
    }
)

ORGANIZE_UPDATE_GUIDELINES = """
Propose updates to existing workspace records for authenticated browser review;
do not execute changes or say they have been performed. No upload is required
for this remote Organize profile. Creation requests belong in Create instead.

Discover the intended records with permission-bounded reads. Compare approximate
names, descriptions and parent context rather than assuming the user's wording
is an exact name. Read the exact target and relevant Form schema before proposing
changes. Use needs_review if the target or requested change is ambiguous. Freeze
exact tool-returned references in the proposal; execution does not search again.

Use only the allowed actions. Fetch get_guidelines(task="report_actions",
actions=[...]) for the selected operations when details are needed, and the
schema_evolution bundle before additive Form changes. Fetch only relevant field
types for form_autofill guidance. Do not load file-organization or task-creation
guidance for a simple existing-record update.

Use update_form_values for named field patches, preserving other values;
read existing values before replacing them and clear a value only when requested.
Apply submission updates before complete_task and make completion depend on them.
complete_task checks off one exact existing Task using normal completion rules,
including required fields and recurrence; it is not create_task's historical
occurrence import. Preserve unrelated descriptions, assignments and attachments.
Use append_page_document to add the requested text to an existing Page's document
(or start its missing document). Supply only the addition in document_markdown,
not a rewritten copy of the document. The server prefixes source/time attribution.
Replacement/deletion of existing document text is not supported.

Return a complete proposal, not a conversational answer or an intermediate plan.
Every mutation still requires the user's browser approval and live permissions.
If files are uploaded, use the file Organize profile instead: inspect, summarize
and place every supplied file; update requests do not waive those obligations.
"""


# @testable true
# @tests tests_unit/test_032_agent_api.py::test_remote_organize_update_contract_and_submission
# @matrix agent-api ai-report : remote-update transport-boundary
def is_remote_organize_update(report):
    """Allow fileless edits only on API/email reports, never on UI reports."""
    return (
        getattr(report, "tool", None) == "organize"
        and getattr(report, "origin", None) in {"api", "email"}
        and not getattr(report, "input_files", None)
        and not getattr(report, "upload_manifest", None)
    )
