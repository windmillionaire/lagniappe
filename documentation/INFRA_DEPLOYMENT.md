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

## Remote MCP service

MCP is an optional component of the installation, managed by `installer/mcp.py`
through the ordinary `runner.deploy.deploy` path. Select it in the AI section
of setup, or later with `./setup.sh ai`. Selecting external AI enables both
MCP and the direct API/skill; disabling external AI closes both. Disabling AI
closes built-in generation and external access together.

### Installation and update order

1. Validate the normal app build and generated configuration. If MCP is selected,
   check the deployer's provisioning permissions and reconcile the dedicated
   service/build accounts, Artifact Registry repository, private build-source
   bucket, OAuth TTL and App Engine authorization-request log exclusion.
2. Compute the MCP source fingerprint. Reuse a matching image or build it with
   Cloud Build. On first installation, create a **disabled** Cloud Run service
   and read its canonical `status.url`; this does not require a running app.
3. Save that URL plus `/mcp`, the app's canonical issuer, runtime service account,
   and desired `MCP_VERSION` in application settings. Publish App Engine normally.
4. Only after App Engine succeeds, enable/update the Cloud Run revision and
   verify its readiness, traffic, runtime identity, image version and environment.
   An unchanged service skips both the build and revision deployment.

This ordering is shared by normal installation, `setup.sh update`, source
upgrade, recovery/repair, handoff, and `run.py deploy`. The main app is deployed
once. Cloud Build builds an image; the installer then deploys that image. A
failed app deployment leaves the prepared MCP service disabled, or the previous
service revision in place. A failed MCP activation returns an error even though
the app may already be available. Retry with `./setup.sh mcp`; completed resources
and images are reused. That focused command also publishes the matching app
configuration using the normal prebuilt-app path. If initial setup defers app
deployment, its final instructions include this command after manual app setup.

`MCP_VERSION` is a SHA-256 fingerprint (first 32 hexadecimal characters) of the
service source, container/locked build inputs and managed runtime arguments. It is desired state,
not a claim that deployment succeeded. Cloud Run's `lagniappe-mcp-version` label
and current ready revision provide deployed state. App-only changes do not
change this fingerprint. `setup.sh doctor` checks the selected endpoint and
version without changing cloud resources. There is no wheel release or manual
version bump.

### Resources, identity and build boundary

The component runs in the owner's existing Google Cloud project and resource
region. Standard resource names are:

| Resource | Name / purpose |
| --- | --- |
| Cloud Run service | `lagniappe-mcp` |
| Artifact Registry Docker repository | `lagniappe-mcp` |
| Runtime account | `lagniappe-mcp@PROJECT.iam.gserviceaccount.com`; a saved exact account is preserved |
| Build account | `lagniappe-mcp-build@PROJECT.iam.gserviceaccount.com` |
| Private build-source bucket | `PROJECT-mcp-builds` |
| Firestore TTL | `mcp_oauth.expires_at` |
| `_Default` log-sink exclusion | `remote-mcp-oauth-query`; excludes App Engine OAuth request URLs |

The installer uses the existing project Owner/delegated-installer convention.
It checks the additional Cloud Run, Cloud Build, Artifact Registry, service
account, bucket, logging and TTL provisioning permissions before creating
resources. Scope `serviceAccountUser` to the two accounts, repository management
to the image repository, bucket management to the build bucket, and Run
management to the service. Owner handoff grants those exact resources to the
permanent Owner and removes the installer's direct bindings before removing
the installer's project role. No service-account keys are generated.

The build account gets Artifact Registry writer and staging-bucket object viewer
on those resources, plus project log writer. Cloud Build uses
`CLOUD_LOGGING_ONLY`, as required for this
[user-managed build identity](https://docs.cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts).
The runtime account needs no direct Datastore or Storage role: every request
carries the user's OAuth token and the runtime Google identity to the main API,
which checks both. Upload sessions authorize individual transfers.

`mcp/gcloudignore` allows only the service source and build inputs into the
build bucket; application settings, keys, tests, local environments and workflow
fixtures are excluded. The container uses its locked Python/uv dependencies,
runs as non-root, and strips test/build dependencies. It does not contain the
Flask app or its configuration. The Cloud Run service scales to zero, with a
maximum of two instances, concurrency four, and 1 GiB for temporary upload spools.
It is publicly invokable at the network layer; application OAuth protects tools.
Its health path is `/health`. Use the canonical `status.url` for OAuth even if
another Cloud Run hostname also works.

### Disabling and clients

After the app is deployed with `AI_ENABLED: false` or
`EXTERNAL_AI_ENABLED: false`, its API, API-key issuance, OAuth metadata and
OAuth requests reject access, including previously issued credentials. The
normal deploy then disables an existing Cloud Run endpoint. Resources and
credentials are retained, so re-enabling can reuse them; use account-level
revocation when credentials must remain revoked. Saved reports and ordinary
workspace editing remain available within normal permissions.

Users add the MCP URL shown in the signed-in AI manual, then authorize with an
eligible Lagniappe account. The account's workspace permissions still apply;
its email need not match the agent account. New installations permit eligible
non-public users; an explicit older `actors` restriction is preserved. No local
MCP package or upload helper is installed.

For Codex, configure the server URL and fixed public client:

```bash
codex mcp add lagniappe-remote --url https://YOUR-CLOUD-RUN-ORIGIN/mcp --oauth-client-id lagniappe-codex
codex mcp login lagniappe-remote
```

A `tool_timeout_sec` of 300 and `startup_timeout_sec` of 60 accommodate uploads
and startup. `required = true` makes missing initialization visible; it does not
force the model to choose MCP tools. Restart a client after changing its tool
catalog. See the [official MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

Historical trial outcomes remain in the
[pilot implementation record](../todo/REMOTE_MCP_PILOT_IMPLEMENTATION.md).

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
