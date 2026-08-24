# Infrastructure Deployment and Updates

Deployment joins generated configuration, the frontend production build,
Datastore indexes, App Engine handlers, and release metadata. A deployment must
use one reviewed source/build generation.

## Development deploy

`runner/deploy.py` performs:

1. deploy-surface validation for excluded local-package imports and runtime
   dependencies missing from `requirements.txt`;
2. production frontend build;
3. PWA manifest update;
4. Datastore index deployment when requested; and
5. `gcloud app deploy` with the generated descriptor.

When `SENTRY_AUTH_TOKEN` is set, production source maps are generated, uploaded,
and removed from static output. Without it, no source maps or upload plugins are
enabled.

Installer deployment calls the same helper in publish-only mode. It uses the
generated assets already present in the checkout and does not run npm or change
the application version.

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

Hosted E2E exports that exact commit for both its App Engine version and Cloud
Run runner image and never rebuilds it. See
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

## Configuration update

`./setup.sh update` keeps tracked source in place and:

1. verifies the saved gcloud credential can mint a fresh token;
2. rebuilds generated configuration, indexes, and manifest defaults;
3. validates required settings and the runtime dependency/upload surface;
4. reconciles runtime IAM and managed buckets;
5. restores app-saved deployment settings, AI settings, and site images; and
6. optionally deploys.

The runtime deploy-surface preflight runs before provider reconciliation, so a
missing runtime requirement or excluded local import stops an update before it
changes remote resources.

Use it for maintained forks and local source changes.

## Source upgrade

`./setup.sh upgrade [--branch BRANCH]` records tracked local changes in a
report, fetches the remote, replaces tracked files with `origin/main` or the
selected remote branch, reconciles setup dependencies, reloads installer
modules from the new source, and runs the same configuration/update flow.

The command names its exact replacement target and requires confirmation.
Ignored installation configuration and untracked files remain. Maintained forks
should merge the desired release themselves and run `update`.

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
