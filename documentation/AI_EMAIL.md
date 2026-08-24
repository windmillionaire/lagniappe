# AI Email

AI email lets a registered User create an Ask, Create, or Organize report by
email. It is a signed transport into the existing report pipeline, not a login,
permission bypass, or separate proposal engine.

## Prerequisites and setup

`./setup.sh ai-email` requires:

- a custom application domain;
- Resend-backed authentication email;
- configured AI models and runtime credentials; and
- deployed deferred-job recovery infrastructure.

The installer creates or reconciles a dedicated receiving subdomain, verifies
its DNS through Resend, and configures one `email.received` webhook for
`https://<CUSTOM_DOMAIN>/webhooks/resend/ai-email`. The receiving-administration
key has Full access because runtime retrieval of the complete received message
and attachment download URLs requires it. Outbound receipts and results use
the existing domain-scoped Sending key from authentication email. The keys must
be distinct.

Setup keeps the webhook disabled until the application deployment succeeds,
then enables and verifies it. Disabling the feature disables the webhook before
saving local configuration; it does not delete provider domains, DNS records,
webhooks, or API keys.

`AI_EMAIL_CONFIG` is normalized by `config/ai_email.py`. It fixes the security
and size limits, rejects unknown security fields, requires four unique aliases
(`ai`, `ask`, `create`, `organize`), and exposes only a public enabled/address
projection to templates.

## Inbound boundary

The webhook verifies the untouched request body, signature, and five-minute
timestamp window before processing the event. The runtime then retrieves and
normalizes the message through Resend, matches one exact stored User email, and
claims a deterministic replay record. It does not store raw webhook payloads,
raw provider headers, full mail, signed attachment URLs, or authentication
headers.

Inbound sender matching identifies the report owner but does not create a
browser session. Report creation remains owner-scoped and rate-limited, AI tier
and workspace reads are checked normally, and Create/Organize mutations require
sign-in, review, and explicit execution.

## Routing

Explicit aliases select their workflow directly. The shared `ai@` alias uses:

- Organize for attachment-only messages when that workflow is available; or
- the utility model to choose among the sender's eligible Ask, Create, and
  Organize workflows from normalized subject/body and safe attachment metadata.

The classifier has no Search or workspace tools. The chosen workflow and short
diagnostic are stored in the report's `inbound_manifest` before attachment
download so retries cannot make a different choice.

## Durable handoff

The webhook starts `EMAIL_INGEST`. Its adapter downloads ordinary attachments
and intentional inline content outside the webhook request, creates
deterministically keyed report-owned Files, and then starts the normal
`REPORT_ASK`, `REPORT_CREATE`, or `REPORT_ORGANIZE` job.

`AIReport.inbound_manifest` contains only normalized message content, selected
address, requested/resolved workflow, received time, and safe attachment display
metadata. Provider IDs and signed URLs remain outside the report. Temporary
`report_user` relationships let the submitting User read evidence attached only
to the report without granting edit or placement authority.

Acceptance and handoff are independently idempotent. Ingestion failure before
a report job starts creates a linked error Notification. Once the report job
owns the workflow, it uses the normal report Notification and browser status.

## Outbound feedback

The AI-email path sends acceptance and pre-handoff failure receipts through its
dedicated reply contract. After handoff, terminal success or failure follows
the User's ordinary notification-email preference; the email transport does
not send a duplicate result.

All outbound mail uses the verified authentication-email sender identity and
Sending key. Provider idempotency keys keep retries from sending the same
receipt twice.

## Ownership

| Module | Responsibility |
| --- | --- |
| `installer/ai_email.py` | Provider domain, DNS, webhook, keys, deployment order, and disable flow. |
| `config/ai_email.py` | Runtime-safe schema and public projection. |
| `tools/email/ai.py` | Webhook verification, provider retrieval, normalization, identity matching, limits, and feedback. |
| `tools/ai/email_router.py` | Shared-alias workflow classification. |
| Deferred email adapter | Attachment ingestion and report-job handoff. |
| `properties/ai_report_*` | Durable inbound manifest and report state. |

Provider APIs and receiving requirements change outside this repository.
Recheck Resend's official receiving, received-message, domain, webhook, and
idempotency documentation before changing setup or runtime calls.
