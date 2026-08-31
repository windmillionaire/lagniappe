# Infrastructure Deployment and Updates

Deployment joins generated configuration, the frontend production build,
Datastore indexes, App Engine handlers, and release metadata. A deployment must
use one reviewed source/build generation.

## Development deploy

`runner/deploy.py` performs:

1. deploy-surface validation for excluded local-package imports and runtime
   dependencies missing from `requirements.txt`;
2. production frontend build;
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
venv/bin/python run.py release-check --base origin/main
```

Commit the complete source and generated release output. `release-check`
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
`/installer/`, and `/runner/`. Keep those patterns root-anchored so nested
runtime packages are not excluded. `config/files/` is excluded, then only
`lagniappe_settings.yaml` and optional `redis_ca.pem` are included.

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

## Scaling and runtime settings

`config/deployment.py` normalizes values shared by setup-generated YAML and the
Administrator deployment-settings form. Automatic scaling includes the
constants-owned warmup service; basic scaling removes only that managed entry.
The generated Gunicorn timeout is one hour; deferred Cloud Tasks retain their
shorter delivery deadline.

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
```

## Change checklist

- Keep one source version, build ID, service worker, and build metadata set.
- Validate runtime imports against `.gcloudignore` and `requirements.txt`.
- Preserve handler ordering and dynamic route allowlists.
- Do not rebuild inside hosted test creation.
- Keep setup update and source replacement as distinct commands.
- Document any command, generated-file, handler, or release workflow change.
