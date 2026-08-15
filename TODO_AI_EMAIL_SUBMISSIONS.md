# Deferred: AI Email Submissions

Status: In progress — production handoff implemented; managed E2E and live smoke tests remain
Prepared: 2026-08-14  
Target project: `/home/swifty/lagniappe`

## Purpose

Add email as a secure, durable entry point to the three saved AI report tools on the homepage:

- `ask@<inbound-domain>` creates an Ask report.
- `create@<inbound-domain>` creates a Create report.
- `organize@<inbound-domain>` creates an Organize report.

The email subject and normalized plain-text body become the user's instructions. Eligible ordinary attachments become normal Lagniappe `File` entities and report input files. After ingestion, the existing report adapters, review UI, deterministic proposal runner, permissions, and deletion/cleanup behavior remain authoritative. Email must not create a second AI implementation.

This document records the agreed product contract and an implementation sequence for a later agent. Revalidate the external Resend contracts listed near the end before coding because provider APIs and retention behavior can change.

## Locked Product Decisions

| Area | Decision |
| --- | --- |
| Provider | Resend-first, behind a provider-neutral inbound-email service boundary. |
| Mail stack | Resend for receiving and feedback sending. Keep a Full access receiving key separate from a Sending access key. |
| Installation scope | Optional and only for custom-domain installations with a configured email provider. |
| Receiving domain | Operator-selected dedicated inbound subdomain; suggest `inbound.<custom-domain>`. Never claim the application's root mail domain. |
| Addresses | Ask, Create, and Organize aliases on that subdomain. |
| Identity | Parse exactly one `From` mailbox and require an exact match to a stored registered-user email after domain-only IDNA/case normalization. Preserve local-part spelling; no aliases, plus stripping, provider-specific normalization, shared mailboxes, or user-schema migration. |
| AI entitlement | Ask requires `AI.ASK`; Create and Organize require `AI.CREATE`. Normal workspace permissions still apply. |
| Sender authentication | Provider-reported aligned DMARC is optional defense-in-depth telemetry, not the authorization boundary. A spoofed exact `From` can at worst start a rate-limited report under that user; report access and proposal execution still require login and normal permissions. |
| Prompt context | Subject plus normalized plain-text body only. Sender and routing headers are not model context. |
| Ask files | Save ordinary attachments as files and expose them as read-only Ask context. Ask must never propose attachment actions for those files. |
| Create files | Reject a Create submission containing ordinary attachments and direct the sender to Organize. |
| Organize files | Require at least one ordinary attachment. Text is optional. |
| Inline/CID content | Ignore inline/CID resources; do not save them as ordinary files. |
| Attachment envelope | At most 20 ordinary files, 30 MiB per file, and 50 MiB total. Enforce metadata and actual streamed byte counts. |
| Text envelope | Subject plus normalized body must be at most 64 KiB in UTF-8. |
| Raw mail | Do not retain raw `.eml`, raw webhook payloads, signed attachment URLs, or unneeded routing headers. |
| Forwarding | Automatic forwarding is unsupported. Human-composed messages and manual forwards are supported. |
| Replies | Feedback uses the selected tool address as `Reply-To`. Text above the Lagniappe reply marker creates a fresh report; there are no report threads. |
| Feedback | Send one acceptance receipt and one terminal result email containing a report link. Revisions and proposal execution do not send another email-origin feedback cycle. |
| Rejections | Send rejection mail only after the sender is a known user. Unknown or malformed senders are silent. Automated/list/DSN mail is silent even for known users. |
| Rate limits | Shared across all aliases: 30 accepted attempts per user per hour and 200 per user per day. |
| Discovery | Show eligible addresses on the homepage AI Tools panel and in the Manual, with copy controls. |
| Report UI | Show an Email submission badge, normalized subject/body, and attachment list. Use a compact stored report name for page titles. |
| Setup | Add an idempotent `./setup.sh ai-email` workflow. Reruns reconcile existing resources; disabling turns off the provider webhook before clearing/deploying config. |

## Tool Contract

| Recipient | Required access | Text | Ordinary attachments | Existing pipeline |
| --- | --- | --- | --- | --- |
| Ask | `AI.ASK` | Required after normalization; subject counts | Optional, saved as read-only input files | `DeferredJobType.REPORT_ASK` |
| Create | `AI.CREATE` | Required after normalization; subject counts | Must be absent | `DeferredJobType.REPORT_CREATE` |
| Organize | `AI.CREATE` | Optional | At least one required | `DeferredJobType.REPORT_ORGANIZE` |

“Required text” means the assembled instruction text is nonblank. Use one shared helper for browser-independent email prompt assembly:

```text
Subject: <normalized subject or "(no subject)">

<normalized plain-text body>
```

Do not insert `From`, `To`, `Delivered-To`, provider event IDs, authentication headers, or other transport metadata into the AI prompt. Preserve subject and body separately in the report's inbound display metadata.

## User-Visible Behavior

1. A registered user sends a human-composed email to an address their AI tier permits.
2. Lagniappe validates the provider signature, replay identity, exact stored sender identity, message shape, rate limits, and tool contract. Sender-authentication results may be observed as defense-in-depth evidence but do not authorize a report.
3. Valid mail receives an acceptance email after the durable ingest job and deterministic report exist. The receipt says which tool was selected and links to the pending report.
4. The standard AI report workflow runs under the matched user and their current AI entitlement and workspace permissions.
5. On terminal success or failure, Lagniappe sends one result email with a report link. A successful Create/Organize result still requires normal review and manual execution in Lagniappe.
6. Replying above the marker to either feedback email submits a new message to the same tool alias and therefore creates a new report.

Rejection messages for a known sender must be specific enough to correct the request, including:

- insufficient AI access;
- rate limit exceeded and when to retry;
- body too large;
- too many, oversized, or excessive-total attachments;
- Create received attachments;
- Organize had no ordinary attachments;
- Ask/Create had no text;
- automated/list/DSN mail or unsupported automatic forwarding.

Do not reveal whether an address belongs to a registered user. Unknown senders, ambiguous sender identities, and malformed sender addresses receive HTTP acknowledgement but no email response.

## Architecture

Keep four distinct layers:

1. **Webhook boundary** — raw-body signature verification, event-shape parsing, and replay claim.
2. **Provider adapter** — Resend HTTP calls and provider payload normalization.
3. **Inbound submission service** — sender/tool policy, rate limits, durable ingest orchestration, attachment streaming, and report creation.
4. **Existing report pipeline** — Ask/Create/Organize generation, review, execution, notifications, and cleanup.

Do not put provider payload parsing in the report adapters or report behavior in the webhook route.

Recommended flow:

```text
Resend email.received
  -> POST /webhooks/resend/ai-email
  -> verify raw Svix signature and timestamp
  -> HMAC event ID and claim durable replay ledger
  -> retrieve Received Email metadata/body/headers and attachment metadata
  -> resolve one exact stored user email; optionally inspect authentication results
  -> validate alias, AI tier, automation rules, envelopes, and rate limits
  -> create/get deterministic pending AIReport
  -> start/get deterministic EMAIL_INGEST DeferredJob
  -> send idempotent acceptance receipt
  -> acknowledge webhook

EMAIL_INGEST worker
  -> stream/checkpoint ordinary attachments into report-owned File entities
  -> start/get the existing deterministic REPORT_ASK/CREATE/ORGANIZE job
  -> scrub transient provider identifiers from the completed ingest job

Existing report job
  -> existing adapter stages and report publication
  -> normal in-app notification
  -> checkpointed Resend terminal email
```

The webhook must do only bounded provider metadata calls and durable writes. Attachment bytes belong in the background ingest adapter, not the request thread.

## Configuration Contract

Add optional `AI_EMAIL_CONFIG` schema version 1. Absence and `enabled: false` both mean the public webhook is unavailable and no addresses are advertised.

Use a canonical shape equivalent to:

```json
{
  "version": 1,
  "provider": "resend",
  "enabled": true,
  "domain": "inbound.example.com",
  "aliases": {
    "ask": "ask",
    "create": "create",
    "organize": "organize"
  },
  "resend": {
    "domainId": "...",
    "webhookId": "...",
    "webhookSecret": "whsec_...",
    "inboundApiKey": "re_...",
    "sendingApiKey": "re_...",
    "senderEmail": "noreply@example.com",
    "senderName": "Lagniappe"
  },
  "limits": {
    "maxBodyBytes": 65536,
    "maxFiles": 20,
    "maxFileBytes": 31457280,
    "maxTotalFileBytes": 52428800,
    "hourlyPerUser": 30,
    "dailyPerUser": 200
  }
}
```

Implementation requirements:

- Put normalization and validation in a runtime-safe `config/ai_email.py` so installer/tooling tests do not import `lagniappe.core` or `lagniappe.web`.
- Reject unknown keys where doing so protects against misspelled security settings; preserve forward compatibility only deliberately.
- Normalize the domain to lower-case IDNA ASCII without a trailing dot.
- Local aliases must be nonempty conservative ASCII mailbox atoms, unique after casefolding, and may not contain `+`.
- Require exactly the locked limits for schema version 1 unless a later product decision intentionally makes limits configurable. Do not let a malformed saved value weaken the envelope.
- Require distinct nonblank receiving and sending API keys. The receiving key must be Full access. The sending key should be Sending access and restricted to the verified sending domain when Resend supports that restriction.
- Treat `webhookSecret`, both API keys, and any future provider token as secrets in recovery display/redaction.
- `AI_EMAIL_CONFIG` is optional, not a member of `REQUIRED_APPLICATION_SETTINGS`.
- Recovery export must preserve and redact it; recovery validation must either accept a complete disabled/enabled version-1 object or omit it.
- Expose only a derived public projection to templates: enabled flag and the three completed addresses. Never pass provider IDs or secrets to Jinja.

## Sender Identity

Inbound identity deliberately reuses the existing exact user-email lookup and does not add a canonical-email property or migration:

1. Parse exactly one mailbox. Reject groups, multiple addresses, missing local/domain parts, control characters, or display-name-only values.
2. Unicode-normalize the mailbox, normalize Unicode domain labels with IDNA, and casefold only the domain.
3. Preserve local-part spelling for lookup and for the final equality check against the stored user email after the same domain normalization.
4. Do **not** remove dots, strip `+tag`, apply Gmail rules, infer aliases, casefold the local part, or rewrite provider-specific local parts.

This keeps email ingestion aligned with the account identity already stored by Lagniappe and avoids unrelated user-schema churn. A malformed legacy stored email cannot match and is treated as unknown mail.

## Webhook Security Boundary

Create a dedicated blueprint and register only the endpoint:

```text
POST /webhooks/resend/ai-email
```

CSRF-exempt this blueprint only. Do not reuse the OIDC-authenticated `/process` blueprint and do not exempt a broader route collection.

### Signature verification

- Read `request.get_data(cache=True)` before JSON parsing.
- Verify `svix-id`, `svix-timestamp`, and `svix-signature` against the configured webhook secret using the documented Svix signing format.
- Support multiple `v1` signatures for secret rotation.
- Use constant-time signature comparison.
- Reject timestamps outside a tight documented tolerance (normally five minutes), while durable event IDs remain the replay authority.
- Return a non-2xx response for invalid signatures. Do not log the payload or signature material.
- Accept only `email.received`; safely acknowledge irrelevant valid event types.

Using the official Svix library is acceptable if its transitive cost and Python support are reviewed. A small local verifier is also acceptable and easier to audit; test it against official fixtures either way.

### Authentication-Results telemetry

`Authentication-Results` cannot be the authorization boundary because a retrieved message may contain sender-injected header values unless the receiving provider supplies a separately authenticated provenance signal. The transport proof showed useful aligned DMARC evidence but not a durable provenance contract that setup should hard-code.

Lagniappe may parse provider-visible aligned DMARC results as defense-in-depth telemetry. It must not reject otherwise valid mail, reveal account existence, or enable reports based on that header. Exact stored-email matching, AI entitlement, rate limits, report ownership, login, and normal proposal review/execution remain the operative boundaries.

### Automated and forwarded mail

Silently discard before rate counting when headers identify auto-generated/list/DSN traffic, including non-`no` `Auto-Submitted`, list headers, bulk/list/junk precedence, delivery-status/report content, and auto-response suppression headers. Detect provider-visible automatic-forwarding markers conservatively and reject them as unsupported. A manual forward is ordinary authored body text and remains supported.

## Replay Ledger and Idempotency

Add an internal `InboundAIEmail` persistence service backed by a dedicated Datastore kind or tightly scoped `site` records. It is not a user-facing Entity and must not enter search/cache projections.

Derive the storage key as:

```text
HMAC-SHA256(application secret, "resend:" + provider_event_id)
```

Never persist the raw webhook event ID as the permanent key or in the compacted record. During active processing the record may contain only what recovery requires:

- schema version;
- state (`processing`, `retry`, `accepted`, `rejected`, `ignored`);
- lease token and expiry;
- created/modified timestamps;
- no raw provider ID, address, subject, body, header, or attachment metadata.

Claim with a transaction and a bounded lease. Duplicate active or terminal events acknowledge without repeating lookups, rate counts, files, reports, or mail. A transient failure releases or expires the claim so the provider retry can resume. Accepted/rejected/ignored webhook handoffs compact immediately to the digest key, schema, state, and timestamps only. Acceptance and report-result email have their own deterministic Resend idempotency keys.

Use deterministic identities derived from the event digest:

- report Datastore key;
- ingest job idempotency key;
- standard report job idempotency key;
- acceptance-email idempotency key;
- terminal-email idempotency key;
- attachment file key from event digest plus provider attachment ID or stable ordinal.

The deterministic child report job is essential: a worker retry after starting the normal report pipeline must get the existing job, not supersede it or create a second report.

## Message Retrieval and Normalization

The Resend adapter should expose provider-neutral values, for example:

```python
InboundMessage(
    provider_message_id,
    sender,
    recipients,
    subject,
    text_body,
    headers,
    received_at,
    attachments,
)
```

Normalization rules:

- Decode provider JSON as UTF-8 and reject unexpected object shapes.
- Accept exactly one sender mailbox using the stored-email identity rules above.
- Route using envelope recipients from the provider object, not a user-supplied body/header string.
- Require exactly one recognized Lagniappe alias for a submission. Reject ambiguous multi-alias routing.
- Normalize CRLF/CR to LF, remove NUL/control characters except tab/newline, trim trailing horizontal whitespace, collapse excessive terminal blank lines, and preserve meaningful paragraph breaks.
- Prefer the provider's plain-text body. If it is absent, use a small deterministic HTML-to-text converter that removes scripts/styles and preserves block separation; do not pass HTML to the model.
- Strip everything from the exact Lagniappe reply marker downward. The marker must be unique, stable, and included in every feedback message, for example `--- Reply above this line to start a new report ---`.
- If normalization leaves no body, the subject can still satisfy Ask/Create text requirements.
- Count UTF-8 bytes of the normalized subject plus body and separators; reject above 64 KiB.

Do not attempt broad reply/quote heuristics such as deleting every line beginning with `>`; only the Lagniappe marker is authoritative.

## Attachment Ingestion

Retrieve attachment metadata before accepting the message. Classify as ordinary versus inline/CID from provider disposition/content-ID fields. Inline resources are skipped and neither saved nor counted as ordinary attachments.

Preflight ordinary attachments:

- maximum count 20;
- every declared size must be known, nonnegative, nonzero, and no more than 30 MiB;
- sum of declared sizes no more than 50 MiB;
- Create must have zero;
- Organize must have at least one.

The ingest worker must then process one ordinary attachment at a time:

1. Request a fresh signed attachment URL from Resend; never persist it.
2. Stream into `tempfile.SpooledTemporaryFile` with a small memory threshold.
3. Enforce 30 MiB per file and 50 MiB cumulative limits while bytes arrive, independent of provider metadata and `Content-Length`.
4. Stop immediately if actual bytes exceed either limit.
5. Rewind and save through the normal `File` asset path with sanitized filename and normalized MIME metadata.
6. Use a deterministic file key so a crash between save and checkpoint cannot duplicate the file.
7. Append the file to `report.input_files`, save, and checkpoint its completion before moving to the next attachment.
8. Close the spool in all cases and clean up a partially saved unreferenced file on permanent rejection/failure.

Add an explicit bounded file consumer for email attachments rather than borrowing an unbounded copy capability. Signed URLs and response bodies must never appear in logs, exception contexts, job parameters, or report metadata.

While an email file is only a report input, grant temporary view/download access to the report's submitting user and the owner. Do not grant edit/placement rights. When Organize later attaches it to a Page or Task, normal file relationships/permissions become authoritative and the temporary marker can be removed. Report deletion must retain the existing behavior: delete report-only unreferenced files, preserve referenced files.

## Report and Pipeline Changes

### AIReport shape

Extend `AIReport` with bounded fields, preferably:

- `origin`: `"web"` or `"email"` (legacy absence reads as web);
- `inbound_manifest`: JSON containing normalized subject, body, selected alias/tool, received timestamp, and safe attachment display metadata.

Exclude `inbound_manifest` from search indexing and generic cache serialization. Do not store raw headers, provider IDs, authentication results, signed URLs, or raw webhook data in the report.

Allow report/file creation with deterministic keys through narrow internal factory parameters. Do not make arbitrary request-provided keys available to browser routes.

Use compact names:

- `Ask: <subject or first compact body text>`;
- `Create: <subject or first compact body text>`;
- one file: `Organize: <filename>`;
- multiple files: `Organize: <N> files`.

Limit names with the existing compact title convention. The report template `<title>` and visible title must use `report.name`, not concatenate all instructions.

### Ingest deferred job

Add `DeferredJobType.EMAIL_INGEST` and an adapter whose only responsibilities are durable attachment finalization and starting the standard report job. Its dynamic authorization requires `AI.ASK` for Ask or `AI.CREATE` for Create/Organize and rechecks entitlement before provider work and before handing off.

Suggested checkpoint stages:

```text
report_ready
attachment_<stable-id>_ready (one durable entry per file)
attachments_ready
report_job_started
acceptance_sent (or keep this in the replay/outbound ledger)
ready_to_apply
```

Do not place body text or provider headers in `DeferredJob.checkpoint`; the report already owns normalized display/prompt data. A transient provider message ID may remain in active ingest parameters only until attachments are complete, then cleanup must scrub it before terminal retention.

### Ask attachments

Refactor `AskReportAdapter` into resumable stages similar to Organize:

```text
inputs_ready -> summaries_ready -> answer_ready -> ready_to_apply
```

- Summarize missing email-origin input files using the existing bounded summary path with search indexing disabled for temporary report-only files.
- Add a bounded `submitted_files` prompt context containing file references, safe names, MIME types, sizes, and summaries.
- Ensure `get_file` can read those report-owned files under the submitting user's temporary view permission.
- Retain Ask's existing read-only workspace/search tools and explicit prohibition on file attachment actions.
- Do not add Organize's file-placement actions or mutate the workspace automatically.

Create continues to use its current pipeline and never receives a file manifest. Organize continues to use direct-upload finalization/summarization/retrieval/planning/completion after email ingestion has produced ordinary `File` entities.

## Feedback Email and Terminal Delivery

Add provider-neutral delivery methods and a Resend implementation. Use Resend's send API rather than SMTP so feedback requests can carry provider idempotency keys.

Every feedback message must include:

- normal `From` using the configured verified sending identity;
- `To` set to the matched user's registered display email;
- `Reply-To` set to the selected Ask/Create/Organize receiving address;
- concise subject identifying acceptance, readiness, or failure;
- plain text and escaped HTML bodies;
- the stable reply marker;
- `Auto-Submitted: auto-generated`;
- `X-Auto-Response-Suppress: All`;
- conservative precedence/list-loop suppression headers where supported.

Acceptance is sent only after the report and ingest job are durable. It links to the pending report and states that Create/Organize results are proposals requiring review.

Extend the shared deferred-job terminal delivery sequence with an independent `delivery.external_email` checkpoint:

1. domain cleanup;
2. in-app notification;
3. external email for eligible email-origin initial report jobs.

The exact order may place external email before the in-app notification, but each must have its own persisted checkpoint and retries must resume only missing steps. Use the deterministic Resend idempotency key. Provider success followed by a local checkpoint failure must retry with the same key. Deferred report retries fit inside Resend's current 24-hour idempotency window; revalidate this assumption.

Only the initial Ask/Create/Organize job for an email-origin report sends terminal email. Skip external delivery for:

- browser-origin reports;
- report revisions (`mode == "revise"`);
- manual proposal execution or undo;
- internal ingest jobs.

On success, say “answer ready” for Ask and “proposal ready for review” for Create/Organize. On failure, provide a safe public error and report link without provider internals. Email-delivery failure must not change a successfully generated report into a failed report; it leaves terminal delivery pending for reconciliation and records/captures the delivery problem separately.

## Rate Limiting

Use the existing Redis fixed-window helper with the matched user's stable key, never their raw email address:

```text
ai-email:user:<digest>:hour  limit 30 / 3600 seconds
ai-email:user:<digest>:day   limit 200 / 86400 seconds
```

Both windows are shared across aliases. Apply them after signature, replay, sender lookup, and tool/envelope validation, but before report creation or attachment downloads. A replay does not increment. Increment only submissions otherwise eligible for acceptance, so a user correcting one malformed email is not needlessly penalized.

Redis failure is fail closed for new email submissions. Return a transient webhook failure so Resend retries; do not bypass the limit.

## Setup Workflow: `./setup.sh ai-email`

Add the command in `installer/__main__.py` and focused tooling tests. The command is interactive, idempotent, and safe to rerun.

Prerequisites:

- current installation preparation succeeds;
- `CUSTOM_DOMAIN` exists;
- AI and deferred-job infrastructure are configured;
- authentication email is working;
- operator has a Resend Full access API key for receiving administration;
- Resend-backed authentication email already has a separate Sending access key and verified sending identity;
- chosen inbound subdomain is dedicated and does not already carry unrelated MX records.

Recommended sequence:

1. Show current local/provider state and offer configure, reconcile, or disable.
2. Suggest `inbound.<CUSTOM_DOMAIN>` but allow another dedicated subdomain.
3. Validate the Full access key with a bounded Resend API request.
4. Find or create the Resend receiving domain, recording its provider ID.
5. For Cloudflare-managed installations, use the existing assisted DNS path where feasible; otherwise print exact provider MX/DNS records and wait for operator confirmation.
6. Poll with bounded retries until Resend reports the inbound domain verified. Never infer verification solely from DNS lookup.
7. Reuse the Resend sender identity and Sending-access key already established by `./setup.sh email`; require it to differ from the Full access receiving key.
8. Find or create the webhook for `https://<custom-domain>/webhooks/resend/ai-email` and `email.received`, retrieve its signing secret, and leave it disabled before deployment.
9. Save the complete enabled application configuration locally.
10. Explain exactly what deployment will do and offer to deploy now, matching the other primary setup flows. If declined, retain the local config and disabled webhook for a later rerun.
11. After deployment succeeds, enable the Resend webhook and verify its provider state. Do not run a synthetic health request, setup-probe email, or duplicate sending-key test.
12. Print all three addresses and the exact manual smoke-test steps.

Reruns must compare endpoint, subscribed event, domain ID/status, webhook state, secret availability, aliases, and sending identity. Reuse matching resources. Do not create duplicate domains/webhooks or rotate secrets unnecessarily.

Disable sequence:

1. Disable the provider webhook and verify its state.
2. Save/deploy `enabled: false` (retain a recoverable disabled config unless the operator explicitly requests removal).
3. Stop advertising addresses immediately.
4. Do not delete the receiving domain, DNS records, webhook, or keys without a separate explicit destructive action.

If setup fails after creating a provider resource, report exactly what remains and how the next rerun will reconcile it.

## Homepage, Manual, and Report UI

### Homepage

In `lagniappe/web/templates/home/tools.html`, show a small Email submissions block only when receiving is enabled and the current user has access to the selected tool. Display the selected tool's completed address and a Copy button. Put each address in a server-rendered data attribute; update the visible address when `CreateToolReport.setTool()` changes tools.

Extend `src/script/widgets/tools.mjs` with clipboard support and the same safe fallback pattern used by `src/script/views/manual.mjs`. Announce “Copied” briefly and restore the button label. Do not expose Create/Organize addresses to an Ask-only user in rendered markup.

### Manual/reference help

Update the AI Manual content and AI Tools reference modal with:

- what each address does;
- entitlement requirements;
- subject/body behavior;
- Ask/Create/Organize attachment rules and limits;
- acceptance/result emails and reply-as-new-report behavior;
- exact known-sender requirement and the bounded spoofing/cost tradeoff;
- automatic-forwarding/automated-mail limitation;
- privacy note that Resend temporarily handles received content and signed attachment downloads.

Public Manual pages must use only the safe public address projection and never render secrets/provider IDs.

### Report detail

For `origin == "email"`, add a clearly labeled, escaped panel near the top:

- Email submission badge;
- Subject;
- normalized message body in whitespace-preserving text, never `safe` HTML;
- ordinary attachment names/sizes, linked only when the current user can view the file.

The existing Files section may remain the authoritative file list; avoid duplicating it if the inbound panel already contains equivalent linked rows. Preserve current report action/revision/execution controls.

## Repository Change Map

Names may be adjusted to match local conventions, but keep responsibilities in these areas:

- `config/ai_email.py` — schema normalization, public projection, constants shared safely with installer.
- `config/recovery.py` — optional validation and secret redaction coverage.
- `installer/__main__.py` — `ai-email` CLI route.
- `installer/ai_email.py` — idempotent Resend/domain/webhook/deploy workflow.
- `lagniappe/core/tools/ai_email.py` — provider-neutral service, Resend adapter, normalization/authentication policy, feedback builder.
- `lagniappe/core/tools/database/` — replay-claim transactions.
- `lagniappe/core/definitions/deferred_jobs.py` — ingest job type.
- `lagniappe/core/tools/deferred_job_adapters.py` — ingest adapter, staged Ask inputs, report external-delivery hook.
- `lagniappe/core/tools/deferred_jobs.py` — independent terminal external-email checkpoint.
- `lagniappe/core/entities/ai_report.py` and `lagniappe/core/properties/ai_report.py` — origin/inbound manifest.
- `lagniappe/core/entities/file.py` / file properties — temporary report-user view ownership and deterministic internal creation.
- `lagniappe/core/tools/ai/ask.py` — bounded submitted-file prompt context.
- `lagniappe/web/routes/webhooks/` plus route registration — narrow Resend webhook.
- `lagniappe/web/start/blueprints.py` — register and CSRF-exempt only that blueprint.
- `lagniappe/web/templates/home/tools.html`, `lagniappe/web/templates/tools/report.html`, `src/script/widgets/tools.mjs` — discovery/copy/report UI.
- `lagniappe/web/templates/manual/content/ai.html` and `lagniappe/web/templates/reference/ai_tools.html` — user documentation.
- `documentation/AI_PIPELINE.md`, `documentation/BACKEND_TOOLS.md`, `documentation/BACKEND_ENTITIES.md`, `documentation/INFRA_SETUP.md`, `documentation/INFRA_CONFIG.md`, `documentation/AUTHENTICATION.md`, and relevant privacy/security docs — developer/operator contracts.

Do not inspect or hand-edit `lagniappe/web/static/`; rebuild through the normal frontend workflow.

## Error and Logging Policy

Create stable internal error codes for observability without logging private mail content, for example:

```text
signature_invalid
event_duplicate
message_unavailable
sender_unknown
automated_mail
route_invalid
ai_access_denied
body_too_large
attachment_contract
rate_limited
attachment_download_failed
report_start_failed
feedback_delivery_failed
```

Exception/Sentry contexts may include digest prefix, provider, tool, counts, byte totals, user key, report key, and error code. They must not include subject/body, raw addresses, headers, API keys, webhook secrets, signed URLs, or attachment bytes/filenames unless an existing privacy-reviewed policy explicitly permits the safe filename.

Public errors sent to known users must not include stack traces, provider response bodies, secret/config state, or internal IDs.

## Tests

Read `documentation/TESTING_WRITING_TESTS.md` before adding tests and annotate new durable symbols per `documentation/TESTING_TRACEABILITY_TOOL.md`.

### Unit tests (`testing/tests_unit/`)

- exact stored-email parsing: domain case/IDNA, local-part preservation, one-mailbox enforcement, plus preservation, and malformed behavior;
- AI email config normalization and public projection;
- Svix valid/invalid/multiple signatures, constant-time path, timestamp tolerance, and raw-body sensitivity;
- Resend event/message/attachment payload normalization and provider error classification;
- optional Authentication-Results telemetry fixtures, folding, comments, and alignment;
- automatic/list/DSN/forwarding rejection;
- reply-marker and text/HTML normalization, control removal, UTF-8 byte boundary;
- alias routing and AI tier matrix;
- attachment count/per-file/total metadata and actual-stream limits, inline skipping, spool cleanup, and signed-URL non-persistence;
- replay transactions, expired leases, duplicate delivery, permanent compaction, and deterministic keys;
- rate-limit ordering and shared-alias windows;
- ingest adapter checkpoint resume after every file and after child-job start;
- Ask staged summaries/input context and continued prohibition on attachment actions;
- report terminal external-email checkpoint resume, Resend idempotency key reuse, revision/execution suppression, and email failure isolation;
- report/file deletion and temporary file visibility.

### Tooling tests (`testing/tests_tooling/`)

- CLI parser/dispatcher includes `ai-email` and returns honest status;
- prerequisites/custom-domain failures;
- provider fake for find/create/reconcile domain and webhook;
- rerun idempotence and disabled-webhook-first rollback;
- distinct-key validation and sender-identity reuse;
- config save/deploy sequencing and partial-failure recovery messages;
- recovery export/validation/redaction;
- no tooling test imports `lagniappe.core` or `lagniappe.web`.

### JavaScript tests (`testing/tests_js/`)

- tool selection updates only the eligible address;
- clipboard API success and fallback;
- copy status reset;
- no behavior when config/address markup is absent.

### E2E tests (`testing/tests_e2e/`)

- valid signed Ask/Create/Organize webhook stories using a fake provider boundary;
- unknown and malformed-sender submissions are silent;
- acceptance and terminal delivery are exactly-once under replay;
- tool/envelope rejection messages for known users;
- report is owned by the matched user and uses that user's permissions/tier;
- Ask attachments are visible/readable but never attached by proposed actions;
- Create rejects files; Organize requires and processes files;
- email report badge/subject/body/files render escaped;
- homepage addresses follow current tool and entitlement;
- Manual documentation renders for authenticated/public modes without secrets;
- report deletion cancels work and removes only report-only files.

Keep managed E2E sessions sequential. Use provider fakes at the service boundary; do not make ordinary tests depend on live Resend.

### Live release gate

Before enabling production receiving, run a documented manual smoke test against a real Resend domain:

- each alias with a valid registered sender;
- Ask with/without attachment, Create without attachment, Organize with attachment;
- reply above marker creates one fresh report;
- duplicate webhook replay creates nothing new;
- unknown sender is silent;
- forged or missing Authentication-Results does not authorize or block a report;
- inline-only Organize, oversized, too-many, and automated mail are rejected/ignored as specified;
- acceptance and terminal links resolve to the correct owner-only report;
- disabling the webhook stops new ingestion.

Record provider payload *shapes* with values redacted as contract fixtures; never commit real messages, addresses, IDs, signatures, or signed URLs.

### Focused verification commands

Run small probes first, one E2E invocation at a time:

```bash
venv/bin/python run.py test testing/tests_unit/<ai_email_tests>.py
venv/bin/python run.py test testing/tests_unit/test_023_deferred_jobs.py
venv/bin/python run.py test testing/tests_tooling/<ai_email_setup_tests>.py
venv/bin/python run.py test js
venv/bin/python run.py test testing/tests_e2e/<ai_email_story>.py
venv/bin/python run.py template-contracts --changed --check
venv/bin/python run.py traceability --changed --check
```

Expand to the relevant unit/tooling suites after focused probes pass. Do not run E2E, `test-server`, or `browser-review` concurrently against the managed server.

## Implementation Order

1. Revalidate the current Resend receiving, attachment, webhook, and idempotency contracts.
2. Add config normalization/public projection and focused tests.
3. Add the Resend adapter, raw signature verifier, exact sender/message normalization, replay ledger, policy, and rate limits.
4. Add deterministic report/file factories and the staged ingest adapter that hands off to the existing report jobs.
5. Extend Ask for read-only email input files and add checkpointed acceptance/result delivery.
6. Add homepage, report, Manual, and reference UI.
7. Simplify `./setup.sh ai-email` to explicit provider guidance, reconciliation, one deploy offer, and post-deploy webhook activation.
8. Update focused architecture/setup/security/privacy docs and automated tests.
9. Run focused verification, then the real-provider release gate.

## Rollout

1. Deploy code with `AI_EMAIL_CONFIG` absent/disabled. The webhook returns unavailable and no addresses render.
2. Run `./setup.sh ai-email`; complete the explicit Full-key, receiving-domain, DNS, webhook, and deployment flow.
3. Let setup deploy the saved config, then enable and verify the webhook.
4. Run all alias/security/error live smoke cases.
5. Monitor replay outcomes, ingest failures, rate limits, feedback failures, queue recovery, Resend webhook delivery, and provider retention during the first release window.

## Rollback

1. Disable the Resend webhook first.
2. Deploy `AI_EMAIL_CONFIG.enabled: false` and confirm addresses disappear.
3. Allow already-started ingest/report jobs to finish and send their pending idempotent feedback; they remain valid Lagniappe reports. Disabling prevents new webhook handoffs, not completion of work already accepted.
4. Preserve replay tombstones; they are harmless and needed for safe re-enable/retry behavior.
5. Do not delete provider domains/DNS/keys as part of routine rollback.

## Acceptance Checklist

- [ ] Receiving cannot enable without a verified custom inbound subdomain.
- [ ] Full access receiving and Sending access keys are distinct and redacted.
- [ ] Unknown/malformed mail gets no response and creates no user/report/file/job data beyond a minimal replay tombstone.
- [ ] Sender parsing preserves the local part and matches exactly one stored user email without a schema migration.
- [ ] Ask/Create/Organize enforce the locked text, file, tier, and rate contracts.
- [ ] Attachment metadata and actual streams enforce 20 / 30 MiB / 50 MiB limits.
- [ ] No raw `.eml`, raw webhook payload, signed URL, or secret is retained/logged.
- [ ] Webhook replay, worker retry, child report start, and feedback are idempotent.
- [ ] Ask attachments are saved/readable context but cannot become attachment actions.
- [ ] Existing Create and Organize review/execution semantics remain unchanged.
- [ ] Acceptance and terminal email each send once and reply to the selected alias.
- [ ] Replies create fresh reports from content above the marker.
- [ ] Homepage and Manual expose only eligible safe addresses.
- [ ] Email-origin reports render escaped subject/body and ordinary files.
- [ ] Setup reruns reconcile and disable turns off the provider webhook first.
- [ ] Documentation, focused tests, template contracts, and traceability are current.
- [ ] Real-provider security and smoke gates pass before production enablement.

## Explicit Non-Goals

- IMAP/POP polling or support for providers other than the Resend adapter in the first release.
- Catch-all inbox behavior or secret per-user aliases.
- Guest/unregistered sender submissions.
- Plus-address identity aliases or provider-specific mailbox equivalence.
- Email threads, conversation state, reply-to-existing-report mutation, or automatic proposal execution.
- Automatic forwarding support.
- Saving inline/CID signature images.
- Raw email archival.
- Create attachments.
- Organize without an ordinary attachment.
- Bypassing the normal AI entitlement or workspace permission system.
- Folding this into the separate deferred messaging proposal in `~/Desktop/release/TODO_MESSAGING.md`.

## Provider Assumptions to Revalidate

The later implementer must re-open official documentation and confirm:

- current webhook event/data shapes and raw signing algorithm;
- retry duration and duplicate/out-of-order guarantees;
- Received Email and attachment endpoints, authorization scope, pagination, size fields, dispositions, signed URL lifetime, and retention;
- webhook create/list/get/update API and signing-secret retrieval/rotation behavior;
- domain receiving/DNS verification APIs and Cloudflare compatibility;
- send API headers, `Reply-To`, custom headers, idempotency syntax/window, and Sending-key restrictions;
- the current shape and provenance limitations of any `Authentication-Results` values used as optional telemetry.

Primary references as of 2026-08-14:

- [Resend Receiving overview](https://resend.com/docs/dashboard/receiving/introduction)
- [Receive emails with webhooks](https://resend.com/docs/dashboard/receiving/receive-emails-with-webhooks)
- [email.received event](https://resend.com/docs/dashboard/webhooks/event-types/email-received)
- [Verify webhook requests](https://resend.com/docs/dashboard/webhooks/verify-webhooks-requests)
- [Retrieve a received email](https://resend.com/docs/api-reference/emails/retrieve-received-email)
- [List received email attachments](https://resend.com/docs/api-reference/emails/list-received-email-attachments)
- [Create a webhook](https://resend.com/docs/api-reference/webhooks/create-webhook)
- [Send email](https://resend.com/docs/api-reference/emails/send-email)
- [Idempotency keys](https://resend.com/docs/dashboard/emails/idempotency-keys)
- [RFC 8601: Authentication-Results](https://www.rfc-editor.org/rfc/rfc8601)

If any provider contract conflicts with this design, keep the feature disabled, document the evidence, and return to product/security review. Do not silently change the locked behavior.
