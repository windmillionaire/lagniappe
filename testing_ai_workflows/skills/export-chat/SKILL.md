---
name: export-chat
description: Export the active local Codex chat when the user says "export this chat", asks to archive or save the current session, or invokes $export-chat. Save a native JSONL transcript and a readable session-statistics summary in the requested directory; do not use for remote chats without a local transcript.
---

# Export Chat

Export the active local Codex transcript with the deterministic helper in this skill.

## Workflow

1. Treat the user's current working directory as the destination unless they explicitly name another directory.
2. Run `scripts/export_chat.py` directly from this skill directory while leaving the command working directory set to the export destination. Do not `cd` into the skill directory.
3. With no arguments, the helper atomically replaces each of these files:
   - `./CODEX_ARCHIVE.jsonl`: a snapshot of complete native Codex JSONL records.
   - `./CODEX_SESSION.txt`: a Pi-style summary with session metadata, message and tool counts, and cumulative token usage.
4. For a different destination, pass `--output-dir PATH`. Use `--source PATH` only when the active transcript path is already established and automatic identification is unavailable.
5. Report both absolute output paths and the tool-call and token totals printed by the helper.

The helper intentionally refuses to guess when it cannot identify one active local transcript. Surface its error instead of silently exporting the newest session. A raw transcript can contain prompts, tool inputs and outputs, code, credentials, or other sensitive data; remind the user to review it before sharing when sharing is relevant.

The export is a point-in-time snapshot. It includes only complete records present when the helper begins reading, so it will not contain the helper's later tool result or the assistant's final confirmation.
