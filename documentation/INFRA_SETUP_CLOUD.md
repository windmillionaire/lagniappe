# Infrastructure Cloud Setup

`installer/gcloud.py` owns Google Cloud project and runtime resource
provisioning. It runs with the saved human installer/deployer credential;
application runtime clients use the attached service account.

## Identities

| Identity | Authority |
| --- | --- |
| Installer | Select/create the project, link billing, enable APIs, provision resources, and reconcile IAM. |
| Deployer | Deploy App Engine/indexes and run privileged data lifecycle commands. |
| Application Owner | Singleton Lagniappe authority; controls Administrators and recovery configuration. |
| Bootstrap Administrator | Exact temporary Google account allowed only before the Owner's first login. |
| Runtime service account | Application Datastore/Storage/provider access and signed URLs. |
| Internal caller | OIDC subject expected on Cloud Tasks and Scheduler routes; currently the runtime account. |

These identities are explicit settings. Application roles do not grant GCP
permissions, and GCP permissions do not grant a Lagniappe session.

## Project and billing

Setup re-reads the active gcloud configuration, account, project, ADC project,
and quota project before mutation. For an existing project, it first uses a
short-lived token from the already selected gcloud CLI login to run the
read-only installer/deployer permission preflight. Only after that account is
proven usable does setup inspect or open Application Default Credentials (ADC),
which are a separate credential used by the Python provider clients. A new
project is created only after default-no confirmation, then management APIs and
billing are established before general provider work.

Fresh setup asks whether the operator is installing for a different permanent
Owner. Delegated mode never creates a project or begins with an application-name
prompt. It lists the active projects visible to the selected gcloud account,
reads each project-level IAM policy through that CLI session, and offers only
projects where the installer has a direct, unconditional `roles/owner` binding.
The selected project's display name becomes the application name. If no project
qualifies, setup stops with instructions for the business Owner to create the
project, link billing, and grant the installer **Basic / Owner**. Ordinary setup
asks whether its project already exists. An existing-project answer opens a
picker of active projects visible to the selected gcloud account and also
derives the application name from the selection. Only the ordinary
new-project branch asks for an application name and allows project creation.

Fresh installation, settings recovery, repair, update, and upgrade all run the
same required-API reconciler before API-dependent resource work. Doctor audits
that exact required-service set read-only, so a disabled prerequisite is
reported as drift before repair or another deployment workflow reaches it.

During delegated setup, the permanent site Owner email must be the exact Google
account address, not a forwarding alias, and that account must already have a
direct Project Owner binding. Setup verifies that binding before offering the
selected installer temporary Lagniappe application Administrator access. That
bootstrap access affects application login only; it does not authenticate the
installer to gcloud or add Cloud IAM permissions. The binding check reads the
existing policy with the installer credential; it never asks the permanent
Owner to log in or configure ADC on the installer's computer.

Billing association is checked through Cloud Billing and Resource Manager
permissions. Setup may select the sole accessible open billing account; if none
is discoverable, the operator links one through the project billing page and
setup verifies the result.

The App Engine location is immutable. Setup shows it immediately before create
and requires explicit confirmation. Existing applications are discovered and
their provider-reported location and hostname are saved without synthesizing a
replacement.

## Runtime IAM

The runtime account receives only application consumer roles:

- Datastore user;
- Identity Platform account/OOB operations;
- Cloud Tasks enqueue and task delete;
- Document AI user;
- Vertex AI user; and
- Cloud Scheduler administration for the one setup-owned recovery job.

It does not receive deployment, Cloud Build, Service Usage administration,
project IAM, service-account key administration, Cloud Tasks administration,
or project-wide Storage roles.

`roles/iam.serviceAccountUser` and
`roles/iam.serviceAccountTokenCreator` are bound only on the exact runtime
service-account resource for the deployer and runtime self-use. This supports
App Engine attachment, internal OIDC, and IAM `signBlob` without a project-wide
impersonation grant.

All managed IAM reconciliation preserves unrelated members and conditional
bindings, uses policy version 3 and provider etags, and skips no-op writes.
Unexpected conditional broad grants are reported for manual review.

## Storage buckets

Production uses deterministic private, public, history, and operator-only
recovery buckets. Development adds test-prefixed private/public/history
buckets.

- Runtime buckets use uniform bucket-level access, browser CORS, bucket-scoped
  runtime object administration, and runtime bucket metadata read.
- Public buckets additionally grant public object viewing.
- The recovery bucket has no browser CORS and no runtime service-account
  access; only the saved human operator administers its objects.
- Existing retention, soft-delete, and lifecycle policy are preserved.
- Runtime application startup validates expected buckets and never creates or
  mutates them.

All new buckets use the configured location contract and standard storage
class. Setup reconciles supported metadata drift without changing an existing
bucket's location.

## Cloud Tasks and deferred recovery

Setup creates the shared Cloud Tasks queue used by background workflows.
Application process routes require an OIDC token for the exact internal caller
and audience. Missing/invalid identity returns 401; authenticated invalid input
returns 400; retryable processing failure returns 5xx.

`create_deferred_job_reconciler()` creates one regional Cloud Scheduler job
that POSTs `{"reconcile": true}` to `/process/jobs/reconcile` every five
minutes. The application enables the schedule while durable recovery-required
jobs exist and pauses it when empty. Google's Scheduler service agent keeps its
provider role; the runtime account is the OIDC caller and controls only the
setup-owned job's operational pause/enable lifecycle.

Run `./setup.sh jobs` after a manual application deployment. Setup-managed
deployments invoke this step automatically after the new route exists.

## Identity Platform and authentication email

`installer/identity.py` initializes standalone Identity Platform, enables
email/password, preserves authorized domains, and stores only public browser
configuration. `auth_email.py` verifies the selected SMTP sender before saving
it. Google Sign-In uses an operator-created Web client whose project, origin,
and callback setup validates before registration.

The runtime/login contract and detailed provider boundaries are in
[AUTHENTICATION.md](AUTHENTICATION.md).

## Redis Cloud

Redis Cloud remains an operator-created dependency. During a fresh setup, the
installer names the plan tradeoff before asking for credentials: the free 30 MB
Essentials database is appropriate for a disposable rehearsal, while
Lagniappe's configurable Redis TLS option requires paid Essentials/Flex or Pro.
The database must use Google Cloud in the saved `RESOURCE_REGION`; an existing
database is reusable only when its provider and region match. Setup then parses
the copied Redis CLI command and directs the operator back to the same database
page to select the required `volatile-ttl` policy. Redis Cloud treats that
selection as pending until **Review changes** and the confirmation modal are
completed; setup pauses until the operator confirms the saved policy. It then
validates the real connection and saves no credential after a failed check.

## Domains and DNS

`installer/domain/` creates or discovers the exact App Engine domain mapping,
verifies provider-returned DNS records, and either:

- reconciles those records through a temporary zone-scoped Cloudflare token;
  or
- prints the exact records for a provider-neutral manual flow.

Cloudflare is a DNS convenience only. Setup does not enable proxying or manage
WAF, bot, cache, ruleset, or zone-security products. The token is not stored.
After mapping, setup adds the host to Identity Platform and updates the email
action callback and Google OAuth origin/callback instructions.

Deployment waits for App Engine to report an active managed certificate before
claiming custom-domain completion. A certificate timeout leaves the App Engine
deployment available at its default URL and exits with DNS/CAA/rerun guidance.

## Validation

Provider mutation is complete only after a focused re-read confirms identity,
project, region, resource name, and relevant state. `doctor` uses the same
expectations read-only. The opt-in setup provider tests exercise the runtime
credential against its intended APIs and verify the absence of provisioning
authority; see [TESTING.md](TESTING.md#provider-contracts).
