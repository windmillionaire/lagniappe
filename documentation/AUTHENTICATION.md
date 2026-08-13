# Authentication

This document is the canonical contract for Lagniappe authentication. It covers
installation choices, Identity Platform, the browser/server trust boundary,
Google sign-in, email delivery, login UI state, recovery behavior, and safe
failure handling.

Key implementation areas:

- `installer/identity.py`, `installer/admin.py`, and `installer/auth_email.py`
  provision authentication.
- `config/files/lagniappe_settings.yaml` stores runtime-safe authentication
  settings.
- `lagniappe/core/tools/identity_platform.py` owns server-side Identity
  Platform operations.
- `lagniappe/web/routes/users/login.py` owns login routes and session creation.
- `lagniappe/web/templates/users/login.html` and `src/script/login/` own the
  unauthenticated forms and browser REST client.

## Installation contract

### Standalone Identity Platform

Email/password authentication always uses standalone Google Cloud Identity
Platform. `installer/identity.py`:

- initializes `projects.identityPlatform.initializeAuth` and requires the
  resulting subtype to be `IDENTITY_PLATFORM`;
- accepts the provider's already-initialized responses only after re-reading
  and verifying live state;
- enables email/password sign-in;
- preserves authorized domains and adds the App Engine or custom-domain host;
- stores `IDENTITY_PLATFORM_CONFIG` with only the project ID and public Web API
  key; and
- sends the confirmed ADC project as `x-goog-user-project` for installer quota.

Identity Platform email/password setup is unconditional. Google sign-in is an
optional provider layered on top of it.

`initializeAuth` creates the default browser key. Lagniappe reads
`config.client.apiKey`; setup does not create a key through the API Keys API or
assign its API targets and browser-referrer restrictions. The enabled Identity
Toolkit service and the installer's ADC OAuth scope authorize administrative
setup requests. They are not authority embedded in the public browser key.

### Google sign-in choice and OAuth

`GOOGLE_SIGNIN_ENABLED` is the persisted operator intent. Fresh setup asks
before beginning Google Auth Platform or OAuth work and defaults to enabled for
backward compatibility. When false:

- email/password authentication remains available;
- OAuth instructions and Google-provider reconciliation are skipped;
- custom-domain setup still reconciles the Identity Platform authorized
  domain; and
- retained OAuth clients and provider resources are not deleted.

Existing and recovered settings without the key migrate to `true`. A successful
focused `./setup.sh oauth` run stores `true` explicitly.

When Google sign-in is enabled, the operator creates a Web application client
in Google Auth Platform with the exact origin and `/users/google-signin`
callback printed by setup. The downloaded JSON must be placed at the exact
temporary path printed by the installer. Setup verifies its client type,
project, origin, callback, and Google propagation before changing Identity
Platform. It persists only the public client ID. Identity Platform stores the
client secret; the deployed application does not need it. The downloaded JSON
may then be removed or transferred to secure storage.

### Authentication email

Lagniappe, rather than Google's default mailer, delivers verification and
password-reset messages. `AUTH_EMAIL_CONFIG` stores the selected SMTP provider,
host, port, TLS mode, username, password or API key, sender address, and sender
name. The sender is independent of the installer, deployer, application owner,
and Google Cloud IAM identities.

Without a custom domain, setup can bootstrap a Gmail or Google Workspace
mailbox with a Google App Password over STARTTLS. With a custom domain, setup
supports a tested provider-neutral SMTP configuration and a Resend shortcut.
New values replace the previous sender only after a successful test message.
SMTP TLS always verifies certificates.

At runtime the server uses authenticated ADC and
`accounts:sendOobCode` with `returnOobLink: true`. It embeds the returned code
in Lagniappe's existing `/users/login` action URL on the configured login
origin, then sends that local URL through SMTP. The browser never receives the
runtime Google access token or SMTP credential.

### Recovery

Recovery verifies live standalone Identity Platform state and keeps absent,
forbidden, mismatched, and unavailable results distinct. Repair does not delete
operator-owned cloud APIs, OAuth clients, or provider resources.

## Browser and server trust boundary

### Public client configuration and API key

`GET /l/identity-config` returns the Identity Platform project ID and Web API
key. These are public client configuration. The key selects the Google Cloud
project and attributes browser API usage/quota; it is not a Lagniappe session,
Google Cloud credential, installer credential, or authorization to application
data.

The browser can use that key with the Identity Platform client endpoints that
the project enables, including account creation and email/password sign-in.
Consequently, on a public-registration installation someone may be able to
create an Identity Platform account through the same public API. That alone
does not grant access to Lagniappe. Every application session is created by the
server only after token verification and the application's owner,
provisioning, public-registration, and disabled-account rules pass.

The browser does not persist Identity Platform refresh tokens. It hands the
short-lived ID token to Lagniappe for session creation.

### Email/password path

The browser's focused REST client calls Identity Platform directly for account
creation, password sign-in, and action-code application. It sends the returned
ID token to `POST /users/login-identity`. Immediately before that handoff, the
client refreshes the Flask-WTF token from `GET /l/token`; a CSRF-specific `400`
is refreshed and retried once.

The server verifies the Secure Token signature, exact project audience and
issuer, subject, email, and verification state. It then applies Lagniappe's
access rules and creates the Flask-Login session. Unknown and returning email
addresses receive deliberately generic password errors so the ordinary sign-in
path does not enumerate accounts.

### Google path

Google Identity Services renders its own sign-in control in a provider-owned
iframe. That iframe is part of Google's button implementation, not a place
where Lagniappe embeds its authentication application. The response CSP
explicitly permits only Google's `/gsi/` script, style, connection, and frame
paths. Independently, `frame-ancestors 'self'` limits which sites may embed
Lagniappe.

The GIS control posts a Google credential to `POST /users/google-signin`. The
server:

1. validates the Google double-submit CSRF token;
2. verifies the Google credential for the configured OAuth client;
3. prevents an unprovisioned account from being auto-created on private sites;
4. exchanges the credential through Identity Platform's
   `accounts:signInWithIdp` endpoint;
5. verifies the resulting Identity Platform token for the configured project;
   and
6. applies the same Lagniappe access rules before creating a session.

No Google provider refresh token is persisted by the application.

## Login UI and account state

`src/script/login.mjs` initializes the client and selects one of the server
rendered forms. Forms communicate through `login:show-*` events; all workflow
forms use the shared login card, heading, guidance, error, and user-kind
confirmation styles.

### Owner bootstrap

Until the configured owner completes a Lagniappe login, `/users/login` opens
owner setup. With Google available it begins with Google sign-in and offers a
separate-password alternative. Without Google it opens the password path
directly. A separately created password must be verified through the normal
email flow before it can create a session.

### Invited and returning users

After owner initialization, users choose Google or email sign-in. Email is
collected before the password:

- a provisioned local user with no completed login enters first-time password
  setup;
- returning and unknown addresses see the same ordinary password screen and
  generic failure; and
- a public site may direct an unknown address into account creation.

Google sign-in on a private site must match a provisioned local user. A user
adopted from the public group becomes non-public and receives the owner-created
name, page, AI, and group settings before later authentication.

### Verification-link recovery

Creating a password produces an unverified Identity Platform credential. The
server generates and sends the verification link. Once delivery is confirmed,
the password field and create action are removed from the form rather than left
active beneath the confirmation.

If verification delivery fails, the browser catches the generic application
error and opens ordinary sign-in for the same email with safe visible guidance;
it does not leave an unhandled promise or expose SMTP/provider detail. The
server reports the underlying provider exception to Sentry. The password was
already created, so signing in with it retries verification delivery. Restoring
the sender configuration therefore recovers without creating another Identity
Platform account.

An invited user can apply the verification link and close the page before the
final password sign-in. Their local `last_login` is still empty, so a later
email check may offer first-time setup again. The repeated provider create then
returns `EMAIL_EXISTS`. This is recovery state, not a terminal error: the
browser opens ordinary password sign-in for the same email and displays
guidance that the password is already set. The user can sign in with
the password created before verification.

Password reset follows the same local-link delivery model. The browser validates
the action code before enabling or showing the password controls. A consumed,
invalid, or expired link displays the safe invalid/expired message immediately;
it does not render a usable-looking reset action. The invalid-link state retains
a **Request a new reset link** action that opens the existing forgot-password
form without requiring URL editing. After a successful reset, the UI returns to
ordinary password sign-in with confirmation feedback.

Before generating a reset link, the server checks SMTP availability without
consulting the submitted address. An unavailable sender therefore returns the
same generic `503` for every address; the forgot-password form retains its email
and action controls and displays safe retry guidance. Account lookup and any
later account-specific delivery outcome retain the generic success response so
password-reset behavior cannot be used to enumerate accounts. The backend
reports both failure classes to Sentry without exposing provider detail in the
browser.

## Google availability and safe failures

Google controls require both operator intent and usable provider state:

1. `GOOGLE_SIGNIN_ENABLED` must be exactly true. When false, the server omits
   Google UI, skips the live provider read, and rejects a direct callback.
2. In production, the server reads the live Identity Platform Google-provider
   configuration with the runtime service account. Disabled or absent state
   omits the controls.

Identity Platform uses protobuf JSON encoding. A disabled provider may omit the
default-false `enabled` field entirely; that omission is treated as disabled.
A control-plane read failure is fail-open so a transient administrative outage
does not remove an otherwise working login method. This exception does not
override an explicit false operator setting or an explicit disabled response.

Known sign-in rejections are normalized whether Google returns them as an HTTP
error or a successful-response `errorMessage`. A disabled Identity Platform
user returns to the method chooser with a safe visible account-disabled
message. A disabled Google provider returns safely without raw provider text;
the next page render omits the unavailable control. Raw provider codes and
credentials are captured only through the privacy-reduced error path, not
shown to users or placed in redirect URLs.

## Redirects, cookies, and rate limits

Only locally safe post-login destinations are retained through Google,
verification, and password-reset handoffs. Authentication routes have focused
rate limits. Session and remember cookies are Secure, HttpOnly, and
SameSite=Lax; the non-sensitive remember preference used across login forms is
separate from authentication state.

## Agent access

Optional browser-review agent access uses `AGENT_ACCESS_ENABLED`,
`AGENT_ACCESS_EMAIL`, `AGENT_ACCESS_NAME`, and `AGENT_ACCESS_CODE`. It is off by
default. Successful agent access resolves to a normal user account, so its
application permissions remain group-managed in the ordinary owner UI.
