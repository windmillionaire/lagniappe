# Infrastructure Setup

`installer/` is the interactive operator CLI for installation, repair, focused
provider configuration, and source/configuration updates. Platform launchers
create and invoke this checkout's `venv`; the installer process must run from
that interpreter.

```bash
./setup.sh
```

Use `setup.cmd` in Windows PowerShell. Direct POSIX invocation after the
environment exists is `venv/bin/python -m installer ...`.

## Commands

| Command | Purpose |
| --- | --- |
| no arguments | Install or recover a complete instance. |
| `auth` | Refresh the saved gcloud account and align human ADC. |
| `doctor` | Read-only local/provider audit. |
| `repair` | Explicit full reconciliation, followed by validation. |
| `development` | Add test buckets and the local Python/Node/Playwright toolchain. |
| `url` | Configure an App Engine custom domain and DNS. |
| `email` | Configure custom-domain authentication email. |
| `oauth` | Configure the Google Sign-In Web client. |
| `ai` | Configure AI models and observability choice. |
| `ai-email` | Configure Resend receiving and the AI email webhook. |
| `security` | Configure verified Redis TLS. |
| `jobs` | Reconcile deferred-job Cloud Scheduler infrastructure. |
| `handoff` | Transfer a delegated installation to the permanent Owner/deployer. |
| `update` | Regenerate configuration and restore app-saved settings without replacing source. |
| `upgrade [--branch BRANCH]` | Replace tracked source from the selected remote branch, then run update. |

Only one mode may be selected. Cancellation, validation failure, provider
failure, and incomplete required work return nonzero. Helpers raise typed
`SetupError` values; the CLI boundary maps them to exit codes.

## Authority boundaries

The installer separates inspection from mutation:

- `validate_installation()` and `verify_installation()` read local/provider
  state;
- `activate_installation()` selects the checkout's saved gcloud target;
- `initialize_installation()` owns first-time project/settings work;
- `prepare_existing_installation()` composes activation and validation for
  focused mutating commands; and
- `repair_installation()` is the explicitly authorized reconciliation path.

`doctor` activates the saved target at the CLI boundary and remains read-only.
It does not acquire the mutation journal or call repair. `update` and `upgrade`
activate the target without requiring the current generated-file set to be
valid because rebuilding it is their purpose.

Setup holds `config/files/.lagniappe_setup.lock` and writes an owner-only,
secret-free operation journal. An interrupted operation reports its last
completed step and safe resume command. Concurrent setup operations stop before
provider mutation.

## Installation flow

The default flow is deliberately ordered:

1. verify Python, project virtualenv, pip, gcloud, exact installer pins, and
   `pip check`;
2. display the account marked active by gcloud CLI authentication and require
   default-no confirmation instead of silently trusting an ambient
   configuration; verify that account can mint a token, then choose the
   installation mode; delegated setup lists only active projects with a direct,
   unconditional Owner binding for the installer and derives the application
   name from the selection, while ordinary setup asks whether the project
   already exists, offers a visible-project picker when it does, and asks for a
   name/project ID only when creating a project; for an existing project,
   verify the CLI account's permissions before ADC, then collect the permanent
   Owner and Google sign-in intent and align ADC;
3. save a non-secret resume draft and show a default-no mutation summary;
4. create or verify the project, link billing, and enable required APIs;
5. create App Engine, the runtime service account/IAM, Storage buckets, Cloud
   Tasks queue, and Document AI processor;
6. configure domain/DNS and authentication email;
7. initialize Identity Platform and optionally configure Google Sign-In;
8. configure Redis and optional TLS;
9. choose error reporting, AI models, and AI observability;
10. write generated settings, indexes, and PWA metadata;
11. optionally configure AI email when its prerequisites are present;
12. deploy the prepared artifacts; and
13. create the deferred-job Scheduler contract after a successful deployment.

Setup re-reads provider state after create/update calls and accepts success only
when the resulting resource matches the saved target. Ambiguous timeouts stop
with rerun guidance; rerunning discovers and reuses completed resources.

Backup, archive, and restore operate through provider APIs using the checkout's
validated ADC and target project. They do not run application data migrations;
those remain an explicit Owner action under **Admin → Site Settings →
Maintenance**. Installer commands must not cross into application migrations,
Flask, request authorization, or broad package export façades.

## Focused architecture guides

| Guide | Read before changing |
| --- | --- |
| [INFRA_SETUP_CLOUD.md](INFRA_SETUP_CLOUD.md) | Projects, billing, APIs, App Engine, IAM, buckets, Scheduler, domain/DNS. |
| [INFRA_SETUP_RECOVERY.md](INFRA_SETUP_RECOVERY.md) | Recovery snapshots, doctor/repair, delegated handoff. |
| [INFRA_DATA_LIFECYCLE.md](INFRA_DATA_LIFECYCLE.md) | Backup, archive, restore, safety clone, queue handling. |
| [INFRA_SETUP_DEVELOPMENT.md](INFRA_SETUP_DEVELOPMENT.md) | Launchers, supported platforms, dependencies, and developer setup. |
| [INFRA_DEPLOYMENT.md](INFRA_DEPLOYMENT.md) | Deploy, release preparation, update, and source upgrade. |
| [AUTHENTICATION.md](AUTHENTICATION.md) | Identity Platform, Google Sign-In, authentication email, and login trust boundary. |
| [AI_EMAIL.md](AI_EMAIL.md) | Resend receiving, webhook, durable report handoff, and feedback. |

## Module map

| Module/package | Responsibility |
| --- | --- |
| `installer/install.py` | Ordered installation orchestration. |
| `create_config.py` | Generated settings/deployment/index files and generation marker. |
| `gcloud.py` | Project, billing, APIs, App Engine, runtime IAM, buckets, Tasks, OCR. |
| `identity.py`, `admin.py`, `auth_email.py` | Identity Platform, Owner/OAuth, authentication email. |
| `domain/` | App Engine mapping and Cloudflare/manual DNS. |
| `ai.py`, `ai_email.py` | AI settings and AI email provider setup. |
| `redis.py`, `security.py` | Redis discovery, connection test, and TLS. |
| `development.py` | Additive developer toolchain and test buckets. |
| `upgrade.py` | Configuration update and source replacement workflow. |
| `handoff.py` | Delegated identity and IAM transfer. |
| `data_lifecycle/` | Backup, archive, restore, and operator journals. |
| `verify.py`, `doctor.py` | Focused validation and broader read-only audit. |
| `package_install.py` | Bootstrap dependency transaction. |

## Generated configuration

Setup writes `lagniappe.yaml`, `index.yaml`, the PWA manifest, and the ignored
files under `config/files/`. Writes are atomic and generated-file completeness
is committed through `lagniappe_generation.json`. Only
`lagniappe_settings.yaml` and optional `redis_ca.pem` enter the App Engine
upload. See [INFRA_CONFIG.md](INFRA_CONFIG.md).

## Development installation

Developer onboarding is two-stage:

```bash
./setup.sh
./setup.sh development
```

The second command is additive and idempotent. See
[INFRA_SETUP_DEVELOPMENT.md](INFRA_SETUP_DEVELOPMENT.md).

## Operator output

Pass prose through `installer.wrap_text()` so prompts remain readable at the
current terminal width. Keep resource identifiers, URLs, commands, and other
copy-sensitive values verbatim. Successful summaries use a safe-field allowlist
and never dump the application settings mapping.
