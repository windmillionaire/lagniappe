# Hosted E2E Pilot and CI TODO

Use this checklist to prove the hosted E2E path from a trusted local checkout,
compare it with the existing local run, exercise the GitHub entry point, and
remove the ephemeral resources afterward.

The commands below start from the repository root. Replace `OWNER/REPOSITORY`
with the GitHub repository that contains this exact source. Use the intended
non-personal test installation for the first pilot.

## What success looks like

- [ ] `create` deploys one App Engine test version and one matching Cloud Run
  job from the exact committed production build.
- [ ] The four-test pilot passes remotely: Datastore, Redis, Storage, and login.
- [ ] The full hosted suite is materially faster than the existing local E2E
  run, excluding one-time setup and candidate creation.
- [ ] A local invocation and a GitHub invocation run the same Cloud Run job and
  report the same source commit, application version, and build ID.
- [ ] GitHub receives no application settings, Redis credentials, service
  account key, or repository write permission.
- [ ] Download-only result handling leaves `testing/evidence/latest.json`
  unchanged; the explicit import step updates it with hosted provenance.
- [ ] Normal teardown removes the ephemeral job and App Engine version without
  requiring `--force`.

## 1. Record a baseline and choose the target

- [ ] Record the existing local E2E wall time from a recent comparable run. If
  a fresh baseline is useful, run it before creating the hosted version and do
  not overlap it with any hosted/test-server/browser-review session:

  ```bash
  /usr/bin/time -p venv/bin/python run.py test e2e
  ```

- [ ] Confirm which configured Google Cloud project and installation will be
  used. For the initial experiment, use the demo/non-personal installation,
  not the personal-data installation.
- [ ] Confirm nobody else is running local E2E, hosted E2E, `test-server`, or
  `browser-review` against the same managed testing resources.
- [ ] Run the normal environment/identity checks:

  ```bash
  ./setup.sh doctor
  ./setup.sh development
  ```

  `development` is additive and idempotent. It supplies the test buckets,
  virtualenv dependencies, browser, Node dependencies, and ADC setup expected
  by the hosted runner.

## 2. Satisfy the first-use production prerequisite

The default App Engine service must already contain the hosted-E2E
soft-routing guard. This is a one-time bootstrap requirement for each Google
Cloud project, not something required before every future candidate test.

- [ ] If the default service already contains this implementation, continue to
  step 3.
- [ ] Otherwise, deploy a version containing the guard through the normal
  trusted setup/deployment flow and verify that the ordinary application is
  healthy before continuing.
- [ ] If using `venv/bin/python run.py deploy` for this bootstrap, do it before
  the candidate freeze below: that development helper intentionally performs
  another production frontend build.

`hosted-e2e setup` probes a nonexistent reserved test hostname and will stop if
the default service does not return the expected rejection marker. Do not
bypass that check.

## 3. Freeze and commit the exact candidate

- [ ] Review the working tree and finish all candidate source changes:

  ```bash
  git status --short
  ```

- [ ] Create the one canonical production bundle:

  ```bash
  npm ci
  npm run build
  ```

- [ ] Explicitly stage the build-owned output:

  ```bash
  git add -- \
    config/constants.py \
    lagniappe/web/static \
    lagniappe/web/start/styles/icons.py \
    lagniappe/web/start/styles/styles.py
  ```

- [ ] Stage the rest of the reviewed candidate source, including the hosted E2E
  implementation and workflow. Do not stage `config/files/`, `reports/`, or
  other installation-local material.
- [ ] Review and commit the complete candidate:

  ```bash
  git diff --cached --check
  git diff --cached --stat
  git commit
  git rev-parse HEAD
  ```

- [ ] Record the candidate SHA. Do not amend or replace this commit after
  `hosted-e2e create`.
- [ ] For a real release candidate, run the normal release check:

  ```bash
  venv/bin/python run.py release-check --base origin/main
  ```

`create` reads build metadata from the Git object, exports that exact commit,
and uses the export for both hosted artifacts. It never rebuilds the frontend.

## 4. Provision the stable hosted-E2E resources once

This step enables APIs and creates/reconciles service accounts, IAM bindings,
an Artifact Registry repository, a seven-day result bucket, two Secret Manager
targets, Workload Identity Federation, and the inert App Engine service anchor.
It is idempotent, but it is a real cloud mutation.

- [ ] Run setup from the trusted operator checkout:

  ```bash
  venv/bin/python run.py hosted-e2e setup \
    --github-repository OWNER/REPOSITORY
  ```

- [ ] Save the non-secret output for reference. It is also written to
  `reports/hosted-e2e/setup.json`.
- [ ] If setup stops partway through, fix the reported identity, permission, or
  production-guard problem and rerun the same command. Do not manually guess
  at missing IAM grants.

## 5. Create and inspect the candidate environment

- [ ] Create the ephemeral App Engine version and matching Cloud Run job:

  ```bash
  /usr/bin/time -p venv/bin/python run.py hosted-e2e create
  ```

- [ ] Record creation time separately from test execution time. Creation
  includes image build/upload and App Engine deployment and is not the expected
  per-suite speedup.
- [ ] Inspect the reconciled local and provider state:

  ```bash
  venv/bin/python run.py hosted-e2e status
  ```

- [ ] Confirm the reported source equals the recorded candidate SHA and note
  the version URL, App Engine version, Cloud Run job, and build ID.

Opening the version URL directly in a normal browser is not a useful smoke
test: application requests intentionally require the short-lived signed test
session created inside the job.

## 6. Run the small local pilot without changing evidence

The pilot runs the database, cache, storage, and successful-login checks. The
`--no-results` flag makes artifact retrieval and evidence import a separate,
explicit step during this evaluation.

- [ ] Run and time the pilot:

  ```bash
  /usr/bin/time -p venv/bin/python run.py hosted-e2e execute \
    --suite pilot \
    --no-results
  ```

- [ ] Record the execution name and exit status printed by the command.
- [ ] Download its artifacts without merging evidence:

  ```bash
  venv/bin/python run.py hosted-e2e results --latest --download-only
  ```

  A failing test can make this command exit nonzero even when the artifacts
  downloaded correctly.

- [ ] Inspect the corresponding directory beneath
  `reports/hosted-e2e/results/`:

  - `manifest.json` — commit, version, build ID, suite, and exit status;
  - `junit.xml` — individual test durations and failures;
  - `evidence.json` — normal traceability output from the hosted run; and
  - `reports.tar.gz` — browser screenshots/traces and other E2E reports.

- [ ] Confirm `testing/evidence/latest.json` did not change during the
  download-only trial.
- [ ] Resolve any pilot failure before starting the full suite. Login failure
  usually points to the hosted request/bootstrap boundary; database, cache, or
  storage failures usually point to runtime identity, provider access, or
  regional configuration.

## 7. Run and measure the full suite locally

- [ ] Run the full hosted suite, still keeping evidence import explicit:

  ```bash
  /usr/bin/time -p venv/bin/python run.py hosted-e2e execute \
    --suite full \
    --no-results
  ```

- [ ] Download the full result without merging it yet:

  ```bash
  venv/bin/python run.py hosted-e2e results --latest --download-only
  ```

- [ ] Compare these separately:

  - existing local full-suite wall time;
  - hosted `execute` wall time, including Cloud Run cold start;
  - pytest duration in hosted `junit.xml`;
  - one-time `create` duration; and
  - failure rate or flakiness, especially browser navigation and asynchronous
    task behavior.

- [ ] Note whether the Datastore/Redis-heavy tests show the expected gain. Do
  not count one-time `setup` or `create` against the normal run-time comparison.

## 8. Exercise the GitHub entry point

- [ ] In GitHub, create a protected environment named `hosted-e2e`.
- [ ] Copy these non-secret values from
  `reports/hosted-e2e/setup.json` into that environment:

  - `GCP_PROJECT_ID` from `project`;
  - `GCP_RESOURCE_REGION` from `region`;
  - `GCP_WORKLOAD_IDENTITY_PROVIDER` from `provider_resource`; and
  - `GCP_E2E_INVOKER_SERVICE_ACCOUNT` from `invoker_email`.

- [ ] Push the exact candidate commit used by `create` to GitHub.
- [ ] In Actions, manually dispatch `.github/workflows/hosted-e2e.yml` at that
  exact candidate ref with suite `pilot`.
- [ ] Confirm the workflow validates the job source as `github.sha`, obtains a
  federated identity, invokes the existing job, and receives no checkout or
  repository write permission.
- [ ] Repeat with suite `full` only if the GitHub pilot passes and another full
  run is useful.
- [ ] Do not commit imported evidence until all desired dispatches against this
  candidate are complete; the follow-up evidence commit has a different SHA.

## 9. Import the selected release evidence manually

Remain checked out at the exact candidate commit used by `create`. Import only
after choosing the execution that should represent the release result.

- [ ] Import the newest execution, or substitute its explicit execution name:

  ```bash
  venv/bin/python run.py hosted-e2e results --latest
  # Or:
  # venv/bin/python run.py hosted-e2e results --execution EXECUTION_NAME
  ```

- [ ] Review the downloaded manifest and the diff to normal evidence:

  ```bash
  git diff -- testing/evidence/latest.json
  ```

- [ ] Confirm the evidence provenance names the expected hosted execution,
  source SHA, version, build ID, job, service, and suite.
- [ ] Commit the reviewed evidence as ordinary follow-up release work on the
  existing `next/*` or `hotfix/*` branch. CI does not create an evidence branch
  or write to the repository.

If source or semantic-snapshot validation rejects the merge, do not override
it. Check out the exact candidate commit and retry, or retain the artifact with
`--download-only` for diagnosis.

## 10. Tear down the runnable resources

- [ ] Confirm no execution is still active:

  ```bash
  venv/bin/python run.py hosted-e2e status
  ```

- [ ] Remove the ephemeral Cloud Run job, App Engine version, temporary bucket
  CORS origin, and stranded test data:

  ```bash
  venv/bin/python run.py hosted-e2e teardown
  ```

- [ ] Run status again and confirm the lifecycle is torn down:

  ```bash
  venv/bin/python run.py hosted-e2e status
  ```

- [ ] Use `teardown --force` only when an execution is genuinely stuck and its
  cancellation is intended. Normal teardown deliberately refuses to race an
  active run.

Teardown leaves the reusable anchor, service accounts, IAM/WIF configuration,
Artifact Registry repository, Secret Manager targets, and lifecycle-managed
result bucket in place. Result objects expire after seven days.

## 11. Pilot notes

- Local full-suite baseline:
- Hosted create time:
- Hosted pilot wall time:
- Hosted full wall time:
- Hosted pytest/JUnit duration:
- Candidate SHA:
- Build ID:
- App Engine version:
- Cloud Run execution(s):
- Result/evidence behavior:
- Failures or flakes:
- Approximate provider cost observed:
- Keep, revise, or abandon:
- Follow-up changes:

