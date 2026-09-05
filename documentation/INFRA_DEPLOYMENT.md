# Infrastructure Deployment and Updates

Deployment joins generated configuration, the frontend production build,
Datastore indexes, App Engine handlers, and release metadata. A deployment must
use one reviewed source/build generation.

## Development deploy

`runner/deploy.py` performs:

1. deploy-surface validation for excluded local-package imports and runtime
   dependencies missing from `requirements.txt`;
2. production frontend validation using the same source/artifact freshness
   checks as the test server, running `npm run build` only when the bundle is
   missing, incomplete, corrupt, non-production, or stale;
3. source and artifact manifest validation for one complete production build;
4. PWA manifest update;
5. Datastore index deployment when requested; and
6. `gcloud app deploy` with the generated descriptor.

When `SENTRY_AUTH_TOKEN` is set, production source maps are generated, uploaded,
and removed from static output. Without it, no source maps or upload plugins are
enabled.

Installer deployment calls the same helper in publish-only mode. It uses the
generated assets already present in the checkout and does not run npm or change
the application version. The same manifest validation runs before any gcloud
operation, so a missing, partial, corrupt, or stale prebuilt frontend is
rejected. Every App Engine deploy command also names the saved target project
explicitly. Interactive setup replaces gcloud's verbose successful-deployment
transcript with one long-running progress line, retains the provider output on
failure, and finishes with Lagniappe's exact saved application URL.

## Release preparation

Freeze the release tree, then create one canonical build:

```bash
npm ci
npm run build
git add -A
git commit -m "Release Candidate X.Y.Z"
venv/bin/python run.py release-check --base origin/main
```

Review and commit the complete source and generated release output.
`release-check`
requires a `next/*` or `hotfix/*` candidate, rejects installation-local files,
and checks that package metadata, lockfile, production build metadata,
`BUILD_ID`, settings version, and release note agree on one `X.Y.Z` version.
It computes source and artifact digests from the exact Git index, preventing an
unstaged working-tree build from validating a different committed candidate.

Hosted E2E exports that exact commit for both its App Engine version and Cloud
Run runner image and never rebuilds it. `hosted-e2e create` runs source-quality,
tooling tests, full and changed traceability, and release checks before gcloud
activation or provider mutation. The GitHub workflow then requires the prepared
Cloud Run job to identify the exact release candidate. Manual diagnostic runs
cannot publish release attestation. See
[TESTING_HOSTED_E2E.md](TESTING_HOSTED_E2E.md).

## App Engine upload boundary

`.gcloudignore` root-anchors local directories such as `/testing/`,
`/installer/`, `/runner/`, `/testing_ai_workflows/`, and the MCP `/mcp/` source tree. Keep
those patterns root-anchored so nested runtime packages are not excluded.
`config/files/` is
excluded, then only `lagniappe_settings.yaml` and optional `redis_ca.pem` are
included.

Cloud Build images use their own explicit ignore files. The hosted-E2E image
includes the shared adapter source and installs its locked environment; its final
stage does not contain uv or pipx. The remote MCP image uses a smaller allowlist
containing only the adapter libraries, package inputs, and container definition.
Neither build context includes private workflow artifacts or application secrets.

`config/constants.py` is the template source for App Engine handlers. Keep
specific static handlers before broad ones:

- versioned `/chunks/*.js` before general JavaScript;
- CSS with the correct UTF-8 content type;
- PDF.js auxiliary assets before general JavaScript; and
- registered dynamic blueprint/root prefixes before the terminal static 404.

The final unknown-path handler serves the authored no-store/no-index 404 page
without starting Gunicorn. Because App Engine static handlers cannot set 404
status, Flask routes requiring exact status must remain in the dynamic
allowlist. Tooling checks keep route prefix constants aligned with blueprint
registration.

## Remote MCP pilot

The hosted MCP adapter is a separate manual Cloud Run deployment. Its
source is `mcp/src/lagniappe_mcp/`; its Dockerfile, Cloud Build
definition, and upload allowlist live in `mcp/`.
The image installs the complete service using its pinned Python, uv, and lock
file, then removes its test/build dependencies. It runs as a non-root user.
The dedicated build context includes only `mcp/src`, locked package inputs,
and the container definition. Tests live under `testing/` and are not uploaded. It excludes application
configuration, user profiles, and private workflow fixtures. The application
continues to receive OAuth/authentication code through the ordinary App Engine
deployment boundary.

The local stdio client, public wheels, immutable release ledger and package
release checks have been retired. Python package metadata remains an internal
container installation detail. Its API adapter and remote protocol/attachment tests run
through `run.py test`; application deploys no longer assemble or check MCP wheels.
Runtime configuration is documented in
[Infrastructure Configuration](INFRA_CONFIG.md#remote-mcp-pilot).

Activation has a deliberate bootstrap order: create the service disabled, read
its canonical `status.url`, configure that exact URL plus `/mcp` in the main
app, then enable the service with the same issuer/resource pair. Network
invocation is public; application OAuth protects `/mcp`. The dedicated runtime
service account needs no direct Datastore or Storage role because the main API
owns token and permission checks and existing upload sessions grant access to
individual uploads. Scale-to-zero, a small instance cap, low concurrency, and
memory sized for ephemeral upload spools are pilot choices to verify in the
deployed service. No custom domain or normal installer lifecycle is added.

Before inviting a user, verify public discovery and unauthenticated challenges,
the live Google identity envelope, and login/consent on the configured issuer.
The container's public health path is `/health`; avoid `/healthz`, which Cloud
Run reserves before the request reaches the application. The canonical OAuth
resource comes from the service's `status.url`, even if the deploy command also
prints a different working Cloud Run hostname.
Also configure platform log handling for `/oauth/authorize`: application
redaction cannot remove the state and PKCE challenge in App Engine's initial
request URL. Native TTL on the `mcp_oauth` kind's Datetime `expires_at` field
supplies asynchronous record cleanup. Per-request expiry checks enforce
authentication expiry before physical cleanup.
The living [pilot implementation record](../todo/REMOTE_MCP_PILOT_IMPLEMENTATION.md)
tracks actual resource names, deployment commands/results, retention/log
configuration, and the manual ChatGPT web, Android, and desktop trials. An
unfilled deployment entry is pending, not evidence of a working cloud service.

Revocation in `/oauth/connection` stops the selected client grant for the
current user. Turning off
the main app's `REMOTE_MCP.enabled` flag stops all remote authorization and
envelope authentication; turning off `LAGNIAPPE_MCP_ENABLED` stops the Cloud Run
endpoint. Retire the exact pilot service and resources explicitly after
disconnecting pilot clients. Existing local API credentials remain independent.

For the Codex extension, enable `REMOTE_MCP.codex_enabled` in private application
settings and deploy the main app normally. Rebuild/redeploy Cloud Run to add
the terminal upload tools; no new cloud resources or service-account roles are
needed. Then configure the terminal client:

```bash
codex mcp add lagniappe-remote --url https://YOUR-CLOUD-RUN-ORIGIN/mcp --oauth-client-id lagniappe-codex
codex mcp login lagniappe-remote
```

Use a `tool_timeout_sec` of 300 and `startup_timeout_sec` of 60 for the pilot.
Set `required = true` under `[mcp_servers.lagniappe-remote]` while trialing it.
Codex's initial catalog can omit an optional server that takes longer than its
startup grace period, even if `/mcp` later shows the server connected. Making
the pilot server required waits for its tools and reports a startup failure if
it cannot initialize; it does not force the model to choose those tools.
Remove any retired local MCP entry and restart the client session to refresh
its tool catalog.
Current Codex registration and callback behavior is documented in the
[official MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

### Current installation and update lifecycle

Remote MCP remains an opt-in manual deployment; removing the local transport
does not add Cloud Run provisioning to the installer. The pilot is disabled by
default, accepts an explicit list of up to ten invited account emails, and has
a separate Codex enable flag. Setup does not collect these values interactively.

1. `setup.sh` installs/configures the main application. `setup.sh update`
   regenerates the App Engine descriptor, indexes and other configuration outputs
   from saved settings and the current templates, then publishes the prebuilt
   application. Both use the ordinary App Engine deployment helper.
2. Separately enable the needed Cloud Run / Cloud Build / Artifact Registry
   services, create an image repository and dedicated MCP runtime service
   account, and submit `mcp/cloudbuild.yaml` with an
   explicit `_IMAGE` destination and its `gcloudignore` allowlist. Cloud Build
   builds and pushes an image; this YAML does not deploy a service.
3. Deploy that image to Cloud Run with MCP disabled. Read its canonical
   `status.url`. Configure the main application's `REMOTE_MCP` issuer, exact
   resource URL, runtime identity and allowed clients; regenerate configuration
   and deploy the app. Then enable Cloud Run with the matching issuer/resource.
4. Configure expiry cleanup and authorization-request log handling as described
   above. Users add the remote URL in their MCP client and authorize through
   their invited Lagniappe account. They do not install a Python package.

The container contains the MCP libraries and their dependencies, not the Flask
application, its saved settings, or its database. OAuth grants, permissions,
Plans and persistent files remain owned by the main application. The Cloud Run
service obtains its Google identity from its runtime account; it has no saved
user API key. Each MCP request carries both the user's OAuth token and a Google
identity envelope to the main API, where both are checked. File-upload sessions
grant only the individual transfers; the adapter needs no direct database or
Storage IAM role.

| Change | Deployment needed today |
| --- | --- |
| Website, API, OAuth implementation or application configuration | App Engine; use `setup.sh update` when generated configuration changes. |
| Shared adapter, remote tools, pinned dependencies or container | Build a new image and deploy a Cloud Run revision separately. |
| A contract change spanning the API and adapter | Deploy both, in a compatible order, then verify discovery and a workflow. |
| User groups, permissions or connection revocation | No code deployment; subsequent authenticated requests use the current permissions/grant. |

`run.py deploy` neither builds nor updates Cloud Run. A successful application
update can therefore leave the adapter at its previous revision. Cloud Run
image tags/digests and App Engine versions must currently be recorded and rolled
back separately. Automated provisioning, paired updates, recovery and teardown
remain follow-up work; none is implied by the normal setup command. The service
lives in the installation owner's Google Cloud project and is billed there.

## Scaling and runtime settings

`config/deployment.py` normalizes values shared by setup-generated YAML and the
Administrator deployment-settings form. Automatic scaling includes the
constants-owned warmup service; basic scaling removes only that managed entry.
The generated Gunicorn timeout is one hour; deferred Cloud Tasks retain their
shorter delivery deadline.

Gunicorn workers multiply application memory because each worker is a separate
process. Lagniappe therefore defaults to three workers and enforces a
three-worker ceiling for the 768 MB F2 and B2 classes. Other instance classes
retain the configurable 1-20 range; review App Engine memory after increasing
their worker count. Installation prints this memory warning, but updates do not
rewrite an existing saved worker count; the ceiling is enforced when an
operator submits new Site Settings deployment values.

`config/ai_settings.py` and `ai_models.py` similarly normalize live model
settings used by setup and Site Settings. Provider discovery is cached and
falls back to the curated catalog on failure.

## Outbound network boundary

The generated App Engine descriptor does not create a VPC connector, NAT,
egress firewall, or all-traffic routing. Application-level outbound URL policy
is therefore the default SSRF boundary for user-directed metadata and image
fetches. App Engine also intentionally exposes its metadata service to each
runtime instance, including service-account credential endpoints; see Google's
[Python runtime metadata contract](https://docs.cloud.google.com/appengine/docs/standard/python3/runtime#metadata_server).

Operators who need defense in depth can separately provision VPC connectivity,
route `all-traffic`, and apply DNS, routing, and firewall controls. That setup
is not generated or reconciled by Lagniappe and has separate capacity and cost
implications. In particular, Serverless VPC connectors can incur charges even
while disconnected. Review Google's
[Serverless VPC egress guidance](https://docs.cloud.google.com/appengine/docs/standard/connecting-vpc#manage_your_connector)
before opting in, and preserve runtime access required by Google credential
libraries.

## Configuration update

`./setup.sh update` keeps tracked source in place and:

1. verifies the saved gcloud credential can mint a fresh token;
2. rebuilds generated configuration, indexes, and manifest defaults;
3. validates required settings and the runtime dependency/upload surface;
4. reconciles runtime IAM and managed buckets;
5. restores app-saved deployment settings, AI settings, public-page discovery,
   and site images; and
6. optionally deploys.

Site-image restoration is best-effort. Setup ignores Datastore metadata fields,
restores each available object independently, and keeps existing local images
when an object is missing or malformed. A site-image warning does not abort an
otherwise valid update or upgrade.

The runtime deploy-surface preflight runs before provider reconciliation, so a
missing runtime requirement or excluded local import stops an update before it
changes remote resources.

Use it for maintained forks and local source changes.

## Source upgrade

`./setup.sh upgrade [--branch BRANCH]` records tracked local changes in a
report, fetches the remote, replaces tracked files with `origin/main` or the
selected remote branch, reconciles setup dependencies, reloads installer
modules from the new source, and runs the same configuration/update flow.

The command resolves one exact fetched commit and reads its committed
`package.json` version; release tags are not required, including during branch
rehearsal. It names that exact replacement target and requires confirmation.
Ignored installation configuration and untracked files remain. Maintained
forks should merge the desired release themselves and run `update`.

When the target crosses a major-version boundary, the deployment prompt states
that setup does not run application migrations and lists the required
Maintenance workflow. Declining that default-no prompt leaves the deployed
application unchanged. A compatibility check at the deployment boundary gives
installations upgrading directly from a pre-1.0 orchestrator the same final
stop before App Engine deployment.

## Data migrations and jobs

Setup does not transform application data. After deploying a release with
pending migrations, use **Admin → Site Settings → Maintenance → Apply Updates**,
resolve any reported rows, then **Refresh Cache**. See
[DATA_MIGRATIONS.md](DATA_MIGRATIONS.md).

Setup-managed deployments reconcile deferred-job Scheduler infrastructure after
the route exists. For a manual deployment, run:

```bash
./setup.sh jobs
./setup.sh monitoring
```

The monitoring command reconciles the managed per-instance App Engine memory
warning. Installer-managed deployments run it automatically; a monitoring
failure is reported with this retry command but does not invalidate a
successful application deployment.

## Change checklist

- Keep one source version, build ID, service worker, and build metadata set.
- Validate runtime imports against `.gcloudignore` and `requirements.txt`.
- Preserve handler ordering and dynamic route allowlists.
- Do not rebuild inside hosted test creation.
- Keep setup update and source replacement as distinct commands.
- Document any command, generated-file, handler, or release workflow change.
