# Lagniappe MCP

`lagniappe-mcp` is Lagniappe's optional user-local MCP adapter. It runs over
standard input/output and delegates every workspace operation to the configured
Lagniappe site's authenticated `/api/v1` REST API.

The package is intentionally independent of the Lagniappe application source.
Run `lagniappe-mcp --help` after installing the content-addressed wheel
advertised by your Lagniappe site.

The first evaluation release supports Linux x86_64 with glibc 2.17 or newer
and CPython 3.14. Follow the install command shown by the site rather than
installing an unadvertised wheel.

`lagniappe-mcp configure codex --url URL --profile NAME` securely prompts for
the existing API key and saves the URL, key, and actor metadata in an owner-only
local profile. `--profile NAME` later selects that profile; it is not a place to
pass the URL or key. The generated Codex entry contains only the absolute
executable and `serve --profile NAME` arguments.

Owner-only storage does not sandbox the client from the credential. Codex, the
adapter, and other processes running as the same OS user may have permission to
read the profile; a client with unrestricted shell or file access can therefore
obtain the key. Profile mode keeps the bearer out of MCP configuration,
arguments, results, and model-authored HTTP, but it does not isolate the bearer
from the local user account. Environment mode has the same host boundary: the
client or another same-user process may be able to inspect forwarded values.

Credential-profile changes hold a per-profile process lock, recheck the full
reviewed file snapshot immediately before commit, and atomically replace an
owner-only, fsynced stage. Adapter processes that honor that lock cannot commit
from stale bytes. The old credential is not retained under a temporary,
recovery, or backup name; an abandoned pre-commit stage is removed on the next
locked profile access. A same-user process that edits these files without
honoring the lock is outside that compare-and-commit guarantee, though a newer
revision detected after replacement is preserved rather than rolled back.
Codex client configuration remains a separate noncredential transaction with
its documented fixed backup.

The server command itself is client-neutral. A standards-compatible local stdio
MCP harness can launch it directly:

```text
lagniappe-mcp serve --profile NAME
```

Automatic configuration and the current interoperability evidence are specific
to the pinned Codex trial client. Other CLI, IDE, desktop, or GUI clients must be
able to launch a local stdio child process and satisfy this server's negotiated
protocol; until their own interoperability smokes pass, treat them as unvalidated
integrations rather than advertised supported clients.

Standard output is reserved for MCP frames. Standard error emits bounded JSONL
evaluation records that join each startup or tool call to its API and storage
request counts, status, byte totals, elapsed time, and outcome. Correlation IDs
are generated locally; records never contain MCP request IDs, arguments, Plan
IDs, local paths, URLs, response values, credentials, or exception text.

Live catalog and proposal schemas are treated as untrusted input. The adapter
accepts only the bounded JSON Schema subset used by the current API, rejects
regular-expression, dynamic-reference, and unbounded-collection keywords, caps
applicator/reference expansion, and permits `uniqueItems` only for a small
explicitly bounded array. An incompatible future schema therefore stops startup
or the current Plan call instead of silently expanding the local validation
surface.

Local upload paths name files available to the adapter process. A relative path
is interpreted from the adapter's working directory, and symbolic links follow
the operating system's normal path resolution. The adapter may upload any
explicit, readable, nonempty regular file available to the current OS account;
it rejects directories, special files, missing files, empty files, and duplicate
objects. Each accepted file is opened once, verified and byte-snapshotted through
that descriptor, and streamed from the same descriptor so a later path change
cannot silently change the uploaded bytes. Existing size, upload-session,
storage-origin, redirect, and bearer-separation controls still apply.

For a nonpersistent test harness or CI process, set `LAGNIAPPE_URL` and
`LAGNIAPPE_API_KEY` in the parent process and launch:

```text
lagniappe-mcp serve --from-env
```

Run `lagniappe-mcp check --profile NAME` before enabling a saved registration.
Create and Organize submissions remain browser-reviewable proposals and are
never executed by this adapter.

The controlled paired evaluation may rerun `configure codex` with
`--trial-required` to generate an owned `required = true` entry. This flag is
only for the isolated candidate environment; ordinary user configuration
remains optional (`required = false`). Never hand-edit that TOML field because
it is included in the entry's ownership fingerprint.
