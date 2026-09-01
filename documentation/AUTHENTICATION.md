# Authentication

Lagniappe uses standalone Google Cloud Identity Platform for provider identity
and Flask-Login for application sessions. Provider accounts never grant
application access by themselves: the server verifies the credential, applies
Lagniappe's account and permission rules, and only then creates a session.

Key implementation areas:

| Area | Location |
| --- | --- |
| Provider setup | `installer/identity.py`, `installer/admin.py` |
| Authentication email | `installer/auth_email.py` |
| Runtime settings | `config/files/lagniappe_settings.yaml` |
| Provider service | `lagniappe/core/tools/services/identity_platform.py` |
| Session routes | `lagniappe/web/routes/users/login.py` |
| Login interface | `lagniappe/web/templates/users/login.html`, `src/script/login/` |

See [INFRA_SETUP_CLOUD.md](INFRA_SETUP_CLOUD.md) for provisioning and recovery
commands.

## Provider configuration

Email/password authentication is always enabled through standalone Identity
Platform. Setup initializes the service, confirms the live subtype, enables
the provider, preserves authorized domains, and adds the application host. It
stores only the project ID and public Web API key in
`IDENTITY_PLATFORM_CONFIG`.

The browser key identifies the project and attributes API quota. It is not a
Google Cloud credential, application session, or authorization to Lagniappe
data. Administrative setup is authorized by the installer's ADC identity and
the enabled Identity Toolkit service.

Google sign-in is optional. `GOOGLE_SIGNIN_ENABLED` records the operator's
choice and defaults to enabled; an absent value is normalized to enabled. When
disabled, email/password remains available and setup skips OAuth and Google
provider reconciliation without deleting provider resources.

For Google sign-in, the operator creates a Web application client using the
origin and `/users/google-signin` callback printed by setup. Setup verifies the
downloaded client JSON before updating Identity Platform. Lagniappe stores the
public client ID; Identity Platform stores the client secret.

## Authentication email

Lagniappe sends verification and password-reset mail through its configured
SMTP provider. `AUTH_EMAIL_CONFIG` contains the host, port, TLS mode,
credentials, sender address, and sender name. New settings replace the active
sender only after a successful test message, and TLS certificate validation is
always enabled.

The server requests an action code from Identity Platform, embeds it in the
local `/users/login` action URL, and sends that URL through SMTP. Provider
access tokens and SMTP credentials never reach the browser.

Custom-domain setup validates the sender and guides SPF, DKIM, and DMARC
configuration. AI email uses the same sender but separate receive and send
credentials; see [AI_EMAIL.md](AI_EMAIL.md).

On an existing installation, `./setup.sh email` replaces the active delivery
configuration transactionally. Without a custom application domain it guides
a new Gmail or Google Workspace App Password, defaults the sender to the
permanent Owner, tests delivery before saving, and then offers to deploy. With
a custom domain it uses the configured SMTP-provider path instead. A failed or
cancelled test leaves the deployed sender unchanged.

## Browser/server trust boundary

`GET /l/identity-config` returns the public project ID and Web API key. The
browser uses the Identity Platform REST endpoints for account creation,
password sign-in, and action-code application, then sends the short-lived ID
token to `POST /users/login-identity`. It does not persist provider refresh
tokens.

Immediately before session handoff, the client refreshes the Flask-WTF token
from `GET /l/token`. A response explicitly identified as a CSRF failure is
refreshed and retried once.

The server verifies:

- Secure Token signature;
- exact project audience and issuer;
- subject and email;
- verification state; and
- the matching Lagniappe account and access policy.

Unknown and returning addresses receive the same ordinary password failure so
the sign-in route does not enumerate accounts. Identity Platform account
creation on a public-registration site still does not create a Lagniappe
session until the application rules pass.

## Google sign-in path

Google Identity Services renders its control in Google's iframe. The CSP
allows only the required Google `/gsi/` script, style, connection, and frame
paths; `frame-ancestors 'self'` controls who may embed Lagniappe.

The GIS credential is posted to `POST /users/google-signin`. The server:

1. verifies the Google double-submit CSRF token;
2. verifies the credential for the configured OAuth client;
3. enforces private-site provisioning;
4. exchanges it through Identity Platform `accounts:signInWithIdp`;
5. verifies the resulting Identity Platform token; and
6. applies the same Lagniappe account rules used by password sign-in.

Lagniappe does not store Google provider refresh tokens.

## Application accounts and roles

Provider identity, Lagniappe roles, and Google Cloud IAM are independent.
`owner` is the singleton application row matching `ADMIN_EMAIL`; `admin` is an
ordinary application role. Neither role follows from a Cloud IAM binding.

Until the owner completes a login, `/users/login` presents owner setup. Google
sign-in is offered when enabled; password setup always uses the email
verification flow.

For a delegated installation, setup enables Google Sign-In and sets
`BOOTSTRAP_ADMIN_EMAIL` to the confirmed installer automatically. On a private
site, that exact address can be provisioned as an
additional Administrator through the Google callback only until the owner has
a `last_login`. The setting is not an address pattern, does not authorize the
password handoff, and does not delete an administrator account when cleared.
The permanent Owner address collected by setup must likewise be the exact
Google account that will sign in, rather than a forwarding alias. Delegated
setup also verifies that account's direct Project Owner binding before setting
the temporary application Administrator. The verified delegated workflow makes
that scoped bootstrap assignment; the IAM binding itself is a handoff
prerequisite, not a general source of Lagniappe application authority. This is
an IAM-policy read performed by the installer session and does not require the
Owner to authenticate on the installer's computer.

After owner initialization:

- a provisioned user without `last_login` enters first-time password setup;
- returning and unknown addresses see the same password screen;
- public sites may offer account creation; and
- Google sign-in on a private site must match a provisioned user.

Adopting a user from the public group applies the owner-defined name, page, AI,
and group settings before subsequent authentication.

## Verification and password reset

Password creation produces an unverified provider credential. After the server
confirms delivery of the verification link, the creation controls are removed.
If delivery fails, the UI returns to ordinary sign-in with safe guidance; the
provider error is reported through the private error path. Signing in with the
created password retries delivery after the sender is repaired.

A user can verify an account and close the page before completing sign-in. If a
later first-time attempt receives `EMAIL_EXISTS`, the client treats the account
as already initialized and opens ordinary password sign-in.

Password reset validates the action code before exposing password controls.
Consumed, invalid, and expired links show a safe message and retain a **Request
a new reset link** action. A successful reset returns to password sign-in.

Before reset lookup, the server checks SMTP availability without using the
submitted address. Sender failure returns the same `503` for every address;
subsequent account lookup and delivery outcomes retain a generic success
response. Provider details go to error reporting, not the browser.

## Availability and failure behavior

Google controls require both explicit operator enablement and usable provider
state. In production, the server reads the live Identity Platform Google
provider configuration. An absent or disabled provider omits the control. A
control-plane read failure leaves an explicitly enabled control available so a
temporary administrative outage does not remove a working sign-in method.

Known provider rejections are normalized whether returned as HTTP errors or an
`errorMessage`. Disabled accounts and providers receive safe UI messages; raw
codes, credentials, and provider text are limited to the privacy-reduced error
path.

Only local post-login destinations survive Google, verification, and reset
handoffs. Authentication routes have focused rate limits. Session and remember
cookies are Secure, HttpOnly, and SameSite=Lax; the non-sensitive remember
preference is separate from authentication state.

Recovery verifies live Identity Platform state and distinguishes absent,
forbidden, mismatched, and unavailable responses. It repairs Lagniappe-managed
configuration without deleting operator-owned APIs, OAuth clients, or provider
resources.

## Agent access

Optional browser-review access uses `AGENT_ACCESS_ENABLED`,
`AGENT_ACCESS_EMAIL`, `AGENT_ACCESS_NAME`, and `AGENT_ACCESS_CODE`. It is off by
default. A successful `/users/agent-login` submission resolves to a normal user
whose permissions remain group-managed in the owner interface.

## External-agent API keys

External-agent API authentication is independent of browser sessions. An
eligible non-public user with `ASK` or `CREATE` AI access can generate one
30-day bearer key from their own Settings panel. Only a digest is persisted,
rotation invalidates the previous key, and `/api/v1` never falls back to a
login cookie. The API has no separate deployment-wide feature gate. See
[External Agent API](AI_EXTERNAL_API.md).
