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
4. Allow the Google API, GitHub, package registry, browser download, app and MCP destinations needed by the selected commands. Verify the authenticated Redis TLS connection from a real task. A TLS Redis endpoint on a non-HTTPS port may require a private network route. Record which operation is blocked if the environment cannot route it, and evaluate moving that operation to Google Cloud.
5. Give ordinary tasks their own environment without the operator connection. Keep the release publisher's private key in its protected GitHub environment.

The task launcher uses the selected connection's native external-account file, an isolated temporary gcloud configuration, and short-lived credentials. Its account comes from the verified federation target. Select a nondefault connection with `LAGNIAPPE_OIDC_ALIAS`. The Google project can be passed as `--project` or set as `LAGNIAPPE_CLOUD_PROJECT` in the private environment.

The provider guides cover connection claims and version aliases. [Codex Cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environments) · [Google Secret Manager version aliases](https://docs.cloud.google.com/secret-manager/docs/assign-alias-to-secret-version)

## Use a fresh task

```sh
venv/bin/python -m runner.cloud_task --project PROJECT
venv/bin/python -m runner.cloud_task --project PROJECT -- venv/bin/python run.py test unit
venv/bin/python -m runner.cloud_task --project PROJECT -- venv/bin/python run.py hosted-e2e status
```

The first command restores the bundle, verifies CLI and ADC identities, pings Redis using the application's verified TLS settings, and reads the hosted checkpoint. The first restore resolves `current` once. Subsequent commands reuse the recorded number. Pass `--version NUMBER` to reproduce a previous task. The task projects its own operator into the developer YAML and the checkout's release version into runtime YAML. The settings publisher preserves the installation's authoring identity. The saved application Owner, deployer and designated agent are distinct.

A restore validates before writing, regenerates deployment YAML, indexes and the PWA manifest with the installer builders, then commits the generation marker and receipt. A failed restore rolls back. After a hard interruption the next settings command recovers its journal under the setup lock. Existing unrecorded edits require review before using `cloud-settings restore --replace`. A different installation requires a separate checkout.

To work interactively, pass `-- bash` to the launcher. Within that shell, use ordinary `venv/bin/python run.py ...` commands. After an intentional settings change use `cloud-settings publish --project PROJECT`, then `cloud-settings check --project PROJECT`. Keep the reported numeric version with the experiment. A deliberate deployment uses `run.py deploy` in the selected experiments project. Publish changed settings after a successful deployment. The managed services keep running after the task and laptop stop.

Sign in to the verified app origin at `/users/agent-login` using the designated application agent. Authorize its saved MCP resource through the normal OAuth flow. Verify the browser actor, MCP actor and an existing notebook Page by reading them before recording a new experiment. The app guide covers the notebook workflow. [Experiments guide](INFRA_EXPERIMENTS.md#agent-notebook)

## Rehearse before moving the release gate

1. Start a fresh operator task on the reviewed candidate. Check the restored settings version, source SHA, gcloud and ADC accounts, Redis PING, browser and MCP actors, and an existing notebook Page. Prepare a coherent committed production build following the release runbook.
2. Run `venv/bin/python run.py hosted-e2e create --base origin/main`, then `venv/bin/python run.py hosted-e2e execute` from the operator shell. Keep the source SHA, numeric settings version, version URL, execution name and full suite result. A focused target is useful while debugging. The release gate requires the full suite.
3. Close the task. Start a second fresh operator task at the identical source and restore the numeric settings version. Use `hosted-e2e status`, `hosted-e2e results --execution EXECUTION`, then `hosted-e2e teardown`. Verify that the job and candidate version have gone and that the notebook remains readable. Include a run with the laptop offline.
4. A live writer owns a GCS generation. Read-only status shows its operation and generation. If a task dies, first confirm its process has stopped and inspect live builds/executions. Use `hosted-e2e --recover-generation GENERATION teardown` or resume the interrupted create at the same source. An outdated generation fails before provider mutations.
5. After both tasks pass, update all four GitHub `hosted-e2e` environment variables together from the experiments setup receipt. Run the normal protected release PR gate against the new target and verify the GitHub job, project and result. Only after that green gate, switch the local upgrade installation to current `main` and follow the ordinary upgrade runbook. Keep the previous target identifiers available until that cutover is verified.

The GitHub release procedure and operator recovery are documented separately. [Release runbook](RELEASE_RUNBOOK.md) · [Hosted E2E](TESTING_HOSTED_E2E.md)
