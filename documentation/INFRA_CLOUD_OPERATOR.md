# Running an experiments installation from Codex Cloud

A private operator environment can restore one experiments installation, run its ordinary development commands, and recover a hosted test run after a task ends. Ordinary installations continue using the installer, local YAML, and the existing Owner recovery snapshot. The deployed experiments site owns the notebook and its history.

## What the bundle protects

Secret Manager stores a single versioned envelope containing the installer-authored runtime YAML, developer YAML and optional Redis CA. It fits within the service's 64 KiB payload limit. A checkout receipt in `config/files/lagniappe_cloud.json` records the numeric secret version and source commit. Settings, receipts and restore journals are private local files.

For one owner, the additional protection is chiefly at rest between tasks. Central access control, version history, and an auditable identity reduce the need to distribute a laptop's files or Google login. During an operator task the process can read the materialized files and use the permissions of its service account. A compromised dependency or untrusted branch running there could use those credentials. Use a credential-free environment for untrusted code and ordinary code review. Keep the operator environment private, review the source revision before running it, and materialize settings after an individual task starts. Republish the reusable image from a clean checkout.

## Seed an existing installation

Use the experiments installation's saved project, gcloud configuration and account. Run the following from the checkout containing the Cloud commands. Replace `PROJECT`, `CONFIG`, `ACCOUNT`, `REGION` and `INSTALLATION` with that installation's values.

```sh
gcloud secrets create lagniappe-cloud-settings --replication-policy=automatic --configuration=CONFIG --account=ACCOUNT --project=PROJECT
venv/bin/python run.py cloud-settings publish --project PROJECT --from-checkout INSTALLATION --configuration CONFIG --account ACCOUNT
gcloud storage buckets create gs://PROJECT-lagniappe-operator --location=REGION --uniform-bucket-level-access --public-access-prevention --configuration=CONFIG --account=ACCOUNT --project=PROJECT
venv/bin/python run.py hosted-e2e checkpoint-init --project PROJECT --from-checkout INSTALLATION
```

The initial checkpoint imports a completed hosted setup and torn-down state from the same installation. Its generation-zero write prevents replacing an existing checkpoint. The command leaves historical reports on the source machine. Inspect active work against the on-site notebook and copy individual missing artifacts only when needed.

`cloud-settings publish` reads back the uploaded version, then moves the `current` alias using the secret's etag. A stale publisher must reconcile its edits with a fresh restore. If a race leaves an extra numbered version, tasks selecting `current` continue to use the winning version. To roll back, restore an earlier numeric version in a fresh task. Publishers use the existing installer and Admin editing flows. For Admin edits saved on the running site, first synchronize the authoritative settings using the existing update/recovery workflow.

## Configure the environment

1. Add the repository to a private environment. Select Python 3.14, the Node release in `.nvmrc`, Git, GitHub CLI and the Google Cloud CLI. Run `bash runner/cloud_setup.sh` from a clean checkout of the revision containing this guide. It installs the Python, Node, browser and managed MCP dependencies. Publish that setup for future tasks.
2. Create a dedicated service account `lagniappe-codex@PROJECT.iam.gserviceaccount.com` and a dedicated Workload Identity Federation pool and provider. In Codex choose **Google Cloud**, enter the full numeric-project provider resource and service account email, then expand **Subject and token claims**. Configure Google's OIDC provider with the displayed issuer and audience, map `google.subject=assertion.sub`, and restrict its attribute condition to that exact subject. Grant `roles/iam.workloadIdentityUser` on the dedicated service account to the pool's exact subject principal.
3. As the installation operator, preview the grants with `venv/bin/python -m runner.cloud_operator_iam --project PROJECT --from-checkout INSTALLATION`. Repeat with `--apply` to reconcile them. Deployment and build roles apply to the experiments project. Signing and acting as a runtime identity, publishing settings, changing test bucket CORS, reading results, and managing the designated MCP service have resource-specific grants. Hosted infrastructure setup and MCP infrastructure repair remain installer operations.
4. Allow the Google API, GitHub, package registry, browser download, app and MCP destinations needed by the selected commands. For hosted tests, the Google Cloud runner connects to Redis. A task running its own Redis-backed app or test server also needs a direct TCP route to the configured Redis endpoint.
5. Give ordinary tasks their own environment without the operator connection. Keep the release publisher's private key in its protected GitHub environment.

The task launcher uses the selected connection's native external-account file, an isolated temporary gcloud configuration, and short-lived credentials. Its account comes from the verified federation target. Select a nondefault connection with `LAGNIAPPE_OIDC_ALIAS`. The Google project can be passed as `--project` or set as `LAGNIAPPE_CLOUD_PROJECT` in the private environment.

App Engine can build a version with its app-level default account even when the version runs as the dedicated E2E runtime. Operator setup looks up both the default Cloud Build account and the App Engine account and grants Service Account User on each. Preview reports direct project Editor or Owner grants on those accounts. Applying the operator grants stops until those broad roles have been replaced. Check the installation’s current workloads and successful builds before changing a default account. For the experiments installation, each builder writes its own Artifact Registry repository, accesses its own staging and log buckets, and has project-level Logs Writer and Service Usage Consumer. [Google Cloud build service account permissions](https://docs.cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts)

The hosted job's IAM policy is set on the job resource. If creation stops while assigning invoker roles, the installer can run the following once the job exists. Then resume `hosted-e2e create` from the same commit and numeric settings version. Include this grant in installation-side provisioning each time the job is recreated. [Cloud Run resource access](https://docs.cloud.google.com/run/docs/securing/managing-access)

```sh
gcloud run jobs add-iam-policy-binding lagniappe-e2e --region=REGION --project=PROJECT --configuration=CONFIG --account=ACCOUNT --member=serviceAccount:lagniappe-codex@PROJECT.iam.gserviceaccount.com --role=projects/PROJECT/roles/lagniappeHostedJobPolicy
```

Before publishing the setup image, run this check on the branch that fresh tasks will use. It verifies that the selected service account can obtain a short-lived token through Google IAM or the environment's configured HTTPS relay. It keeps the token out of the output and exits before reading installation settings.

```sh
venv/bin/python -m runner.cloud_task --project PROJECT --check-connection
```

The provider guides cover connection claims and version aliases. [Codex Cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environments) · [Google Secret Manager version aliases](https://docs.cloud.google.com/secret-manager/docs/assign-alias-to-secret-version)

## Use a fresh task

```sh
venv/bin/python -m runner.cloud_task --project PROJECT
venv/bin/python -m runner.cloud_task --project PROJECT -- venv/bin/python run.py test unit
venv/bin/python -m runner.cloud_task --project PROJECT -- venv/bin/python run.py hosted-e2e status
```

The first command restores the bundle, verifies CLI and ADC identities, and reads the hosted checkpoint. Add `--check-redis` for a task that needs to connect directly to Redis. The first restore resolves `current` once. Subsequent commands reuse the recorded number. Pass `--version NUMBER` to reproduce a previous task. The task projects its own operator into the developer YAML and the checkout's release version into runtime YAML. The settings publisher preserves the installation's authoring identity. The saved application Owner, deployer and designated agent are distinct.

A restore validates before writing, regenerates deployment YAML, indexes and the PWA manifest with the installer builders, then commits the generation marker and receipt. A failed restore rolls back. After a hard interruption the next settings command recovers its journal under the setup lock. Existing unrecorded edits require review before using `cloud-settings restore --replace`. A different installation requires a separate checkout.

Pass individual commands directly to the launcher as shown above. For an interactive shell, use `-- bash --noprofile --norc` to keep the launcher's Google configuration. Within that shell, use ordinary `venv/bin/python run.py ...` commands. After an intentional settings change use `cloud-settings publish --project PROJECT`, then `cloud-settings check --project PROJECT`. Keep the reported numeric version with the experiment. A deliberate deployment uses `run.py deploy` in the selected experiments project. Publish changed settings after a successful deployment. The managed services keep running after the task and laptop stop.

If the connection reports `identity_unsupported_request` on a test-bucket CORS update, the installation owner can authorize the App Engine test service once on its three test buckets. The hosted runner then checks the existing policy at candidate creation. [Hosted E2E browser origins](TESTING_HOSTED_E2E.md#architecture)

Sign in to the verified app origin at `/users/agent-login` using the designated application agent. Authorize its saved MCP resource through the normal OAuth flow. Verify the browser actor, MCP actor and an existing notebook Page by reading them before recording a new experiment. The app guide covers the notebook workflow. [Experiments guide](INFRA_EXPERIMENTS.md#agent-notebook)

## Rehearse before moving the release gate

1. Start a fresh operator task on the reviewed candidate. Check the restored settings version, source SHA, gcloud and ADC accounts, browser and MCP actors, and an existing notebook Page. Prepare a coherent committed production build following the release runbook.
2. From the operator shell, run `venv/bin/python run.py hosted-e2e create --base origin/main`. To verify Redis from the hosted runner, run `venv/bin/python run.py hosted-e2e execute --no-import-results --target testing/tests_e2e/001_site/test_001a_environment.py::test_cache_setup`. Then run `venv/bin/python run.py hosted-e2e execute --no-import-results` for the complete release suite on the same candidate. Keep the source SHA, numeric settings version, version URL, execution names and full suite result.
3. Close the task. Start a second fresh operator task at the identical source and restore the numeric settings version. Use `hosted-e2e status`, `hosted-e2e results --execution EXECUTION --download-only` for the full run, then `hosted-e2e teardown`. Run `hosted-e2e status` again and verify the checkpoint is idle, the candidate version and job are absent, and the notebook remains readable. Include a run with the laptop offline.
4. A live writer owns a GCS generation. Read-only status shows its operation and generation. If a task dies, first confirm its process has stopped and inspect live builds/executions. Use `hosted-e2e --recover-generation GENERATION teardown` or resume the interrupted create at the same source. An outdated generation fails before provider mutations.
5. After both tasks pass, update all four GitHub `hosted-e2e` environment variables together from the experiments setup receipt. Run the normal protected release PR gate against the new target and verify the GitHub job, project and result. Only after that green gate, switch the local upgrade installation to current `main` and follow the ordinary upgrade runbook. Keep the previous target identifiers available until that cutover is verified.

The GitHub release procedure and operator recovery are documented separately. [Release runbook](RELEASE_RUNBOOK.md) · [Hosted E2E](TESTING_HOSTED_E2E.md)
