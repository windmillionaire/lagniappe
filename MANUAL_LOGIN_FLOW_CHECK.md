# Manual Login Flow QA Checklist

Use this checklist on a disposable fresh production installation to verify the
live authentication behavior that local and E2E tests cannot fully exercise.
It covers Google Identity Services, Identity Platform, SMTP delivery, browser
password-manager behavior, real action links, and production-origin redirects.

Do not paste real Google passwords into Lagniappe. Use dedicated test accounts
and separate test passwords. Do not record passwords, OAuth secrets, action
codes, session cookies, or complete email links in this document or screenshots.

## How to use this checklist

- Record the deployed public origin as `PUBLIC_ORIGIN`.
- For an install without a custom domain, `PUBLIC_ORIGIN` is the exact App
  Engine URL printed by setup.
- For a custom-domain install, `PUBLIC_ORIGIN` is the canonical custom HTTPS
  origin.
- Treat every unchecked conditional section as either `N/A` with a reason or a
  separate QA run.
- Run destructive/provider-state edge cases only on a disposable project.
- Test in a clean browser profile first. Use a second profile or incognito
  window where a step asks for a separate browser session.

Priority labels:

- **P0 live**: cannot be meaningfully proven by the normal E2E suite.
- **P1 smoke**: automated, but worth confirming against the deployed service.
- **P2 edge**: optional controlled-failure or provider-state coverage.

## Required test identities and deployment states

Prepare dedicated accounts before starting:

- [ ] `OWNER_GOOGLE`: the Google account whose email exactly matches the owner
      email entered during installation.
- [ ] `WRONG_GOOGLE`: a Google account that is not the owner and is not in the
      Lagniappe user database.
- [ ] `INVITED_NEW`: a mailbox present in the Lagniappe user database with no
      prior successful login.
- [ ] `RETURNING_PASSWORD`: a provisioned user with a verified Identity
      Platform email/password account and a prior successful login.
- [ ] `RETURNING_GOOGLE`: a provisioned user with a prior successful Google
      login.
- [ ] `UNKNOWN_EMAIL`: a mailbox absent from the Lagniappe user database.
- [ ] A disposable mailbox that can be used for public-registration testing.
- [ ] Access to the configured authentication-email sender and recipient
      inboxes, including spam/quarantine folders.
- [ ] Read access to Google Cloud Console → Identity Platform → Users so that
      unexpected Identity accounts can be detected.

Some branches require isolated deployment states:

- [ ] **Deployment A — required:** fresh install with no custom domain, using
      the normal App Engine URL.
- [ ] **Deployment B — conditional:** fresh install or fully isolated test
      deployment using a custom domain.
- [ ] **Owner branch A — required:** initialize a fresh deployment with Google.
- [ ] **Owner branch B — conditional:** initialize a different fresh deployment
      with the separate-password fallback.

Owner branch A and owner branch B cannot both be tested as first-login flows on
the same initialized deployment. Do not delete production users or Identity
accounts merely to reset this state.

## 1. Fresh-install and origin preflight

- [ ] **P0 live:** Complete setup and confirm its final line clearly says that
      Lagniappe was installed successfully and gives the login URL.
- [ ] Open the printed URL instead of constructing an App Engine hostname by
      hand.
- [ ] Confirm the browser reaches `PUBLIC_ORIGIN` over HTTPS with a valid
      certificate.
- [ ] Confirm `/users/login` loads without a redirect loop, blank screen, or
      JavaScript error.
- [ ] Confirm the logo and owner setup UI load; there should be no instruction
      suggesting that setup repair is the next normal action.
- [ ] In Google Auth Platform, confirm the OAuth Web client contains the exact
      JavaScript origin `PUBLIC_ORIGIN`.
- [ ] Confirm its client type is **Web application**, not **Desktop app**.
- [ ] Confirm its redirect URI is exactly
      `PUBLIC_ORIGIN/users/google-signin`.
- [ ] In Identity Platform, confirm the hostname from `PUBLIC_ORIGIN` is an
      authorized domain.
- [ ] Confirm the Google provider is enabled in Identity Platform and uses the
      client created during setup.
- [ ] Confirm email/password authentication is enabled.
- [ ] Confirm normal navigation never changes from the expected App Engine or
      custom-domain origin to an unintended hostname.

For the no-custom-domain deployment specifically:

- [ ] **P0 live:** Verify Google sign-in on the exact App Engine URL. A Google
      `redirect_uri_mismatch` page is a failure.
- [ ] **P0 live:** Verify authentication email links use the exact App Engine
      hostname rather than a missing, old, custom, localhost, or regionless
      hostname.

For a custom-domain deployment, if supported in this QA run:

- [ ] **P0 live:** Repeat the OAuth checks using the custom origin.
- [ ] Confirm neither Google nor an email action link falls back to the App
      Engine hostname unless that fallback is intentional.
- [ ] Confirm authentication email links use the custom hostname.

## 2. Owner initialization — Google branch

Run this section before any successful owner login.

### Initial presentation

- [ ] **P1 smoke:** Visiting `/users/login` shows **Finish setting up
      Lagniappe**.
- [ ] The primary action is Google sign-in for the configured application
      owner.
- [ ] No email input is shown on the primary owner screen.
- [ ] No password input is shown beside the Google button.
- [ ] A separate-password fallback is available but secondary.
- [ ] Visiting a protected deep link before initialization still leads to the
      owner setup screen.

### Wrong Google account

- [ ] **P0 live:** Choose `WRONG_GOOGLE` from the owner Google button.
- [ ] Google completes its own account-selection flow and returns to Lagniappe.
- [ ] Lagniappe shows: **That Google account does not have access to this site.
      Contact the site owner if you think this is a mistake.**
- [ ] The owner setup screen remains usable after the error.
- [ ] The attempted deep-link destination, if any, is retained for a later
      authorized login.
- [ ] In Identity Platform → Users, confirm this rejected Google account was
      not created. Creation of an orphaned Identity account is a failure.
- [ ] Confirm no Lagniappe application user was created for `WRONG_GOOGLE`.

### Correct owner Google account

- [ ] **P0 live:** Choose `OWNER_GOOGLE`.
- [ ] Google returns to `PUBLIC_ORIGIN/users/google-signin` without
      `redirect_uri_mismatch`, blocked-origin, or invalid-request errors.
- [ ] The owner is signed in and reaches the home page, or the original safe
      `next` destination if the flow began from a protected deep link.
- [ ] The Lagniappe owner record has a first-login time.
- [ ] Identity Platform contains one corresponding owner identity, not
      duplicates.
- [ ] The displayed owner name/picture are sensible when Google supplies them.
- [ ] Refreshing the page keeps the owner signed in.
- [ ] Log out and confirm the owner bootstrap screen no longer appears.
- [ ] The ordinary Google-or-email method chooser now appears.

### Google cancellation and retry

- [ ] Start Google sign-in and cancel or close account selection.
- [ ] Lagniappe remains recoverable; refreshing allows another attempt.
- [ ] No partial Lagniappe user or unexpected Identity account is created.

## 3. Owner initialization — separate-password branch

Run this on a different, still-uninitialized disposable deployment.

- [ ] Open the separate-password fallback.
- [ ] Confirm it says **Create a separate Lagniappe password**.
- [ ] Confirm it explicitly says not to enter the Google password.
- [ ] Confirm the owner email is not editable and no email field is shown.
- [ ] Use **Back to Google sign-in** and confirm the password is cleared.
- [ ] Reopen the fallback.
- [ ] Submit a blank password; a useful validation message should appear.
- [ ] **P0 live:** Submit a deliberately weak disposable password and confirm a
      safe weak-password error, with no raw provider code.
- [ ] Submit a valid dedicated Lagniappe password.
- [ ] Confirm the page says a verification link was sent to the configured
      owner address.
- [ ] Confirm the message arrives from the configured sender with the expected
      app name and no secrets in the message body.
- [ ] Confirm the link begins with `PUBLIC_ORIGIN/users/login` and includes a
      `verifyEmail` mode and one-time code.
- [ ] Open the verification link in the same browser profile.
- [ ] Confirm the owner email is prefilled when browser storage is available.
- [ ] Enter the dedicated Lagniappe password and sign in successfully.
- [ ] Confirm a successful login ends owner initialization and subsequent
      anonymous visits show the ordinary method chooser.
- [ ] Reopen the used verification link and confirm it reports an invalid or
      expired link without exposing a provider error.
- [ ] On another isolated password-bootstrap run, open the unused verification
      link in a separate browser profile and confirm the flow remains
      understandable when the email cannot be prefilled.

If the owner email already has an Identity Platform account:

- [ ] **P2 edge:** Try the separate-password setup on a disposable deployment.
- [ ] Confirm the collision produces a safe account-exists message.
- [ ] Confirm the user can return to the owner Google option.
- [ ] If password recovery is required, confirm the UI offers a clear route to
      password reset or existing-password sign-in. A dead end is a defect.

## 4. Ordinary method chooser and password-manager isolation

Run after owner initialization with public registration disabled.

- [ ] **P1 smoke:** `/users/login` initially shows **Sign in to your account**.
- [ ] The only choices are Google sign-in and **Sign in with email**.
- [ ] There is no visible password field on this screen.
- [ ] Choose **Sign in with email**.
- [ ] The next screen contains only an email field, **Continue**, and **Back**.
- [ ] There is no Google button or password field on the email screen.
- [ ] Use **Back** and confirm it returns to the method chooser without an
      error or stale loading state.
- [ ] Enter a known returning email and continue.
- [ ] Confirm the password screen displays the selected email as context but
      does not allow it to be edited there.
- [ ] Confirm the only credential field is labeled **Password**.
- [ ] Confirm no Google button appears on the password screen.
- [ ] Use **Use a different email** and confirm the email screen returns.
- [ ] **P0 live/browser:** In Chrome with password-manager protection enabled,
      exercise the chooser with disposable credentials. Confirm Chrome does
      not imply that the Lagniappe password field is a Google password field or
      show a deceptive-site warning merely because Google sign-in is offered.
- [ ] Repeat the visual isolation check in one other supported browser.

Input handling:

- [ ] Blank email stays on the email screen with a validation message.
- [ ] Malformed email stays on the email screen with a validation message.
- [ ] Leading/trailing whitespace does not create a different account.
- [ ] Email casing does not create a duplicate Lagniappe user.
- [ ] Rapid double-clicks do not create duplicate requests or accounts.

## 5. Private-site Google flows

Keep public registration disabled.

### Provisioned first-time user

- [ ] Add `INVITED_NEW` through the normal owner user-management flow.
- [ ] **P0 live:** From a clean browser, choose Google and authenticate as
      `INVITED_NEW`.
- [ ] The user signs in without being asked to create a password.
- [ ] The existing Lagniappe user is updated rather than duplicated.
- [ ] Identity Platform contains one matching Google identity.
- [ ] The user reaches the home page or retained safe `next` destination.

### Returning Google user

- [ ] Log out `RETURNING_GOOGLE`.
- [ ] Choose Google and sign in again.
- [ ] The correct existing Lagniappe user is used.
- [ ] No duplicate Identity or Lagniappe user is created.
- [ ] Cancel once and then retry successfully.

### Unknown Google user

- [ ] **P0 live:** Choose `WRONG_GOOGLE` from the ordinary method chooser.
- [ ] The friendly not-authorized message is shown on the method chooser.
- [ ] No password field is shown with that error.
- [ ] Identity Platform → Users still does not contain `WRONG_GOOGLE`.
- [ ] The Lagniappe user database still does not contain `WRONG_GOOGLE`.
- [ ] Use **Sign in with email** after the Google error and confirm the flow is
      still usable.

### Existing password identity chooses Google

- [ ] **P2 edge:** As `RETURNING_PASSWORD`, choose Google with the same email.
- [ ] Confirm the provider either signs into the same Lagniappe user or gives a
      clear, user-safe instruction for resolving the provider collision.
- [ ] Confirm no duplicate user is created.
- [ ] A raw `Invalid token`, provider payload, or unstyled HTTP error is a
      failure and should be filed.

### Provider/account state errors

- [ ] **P2 edge:** Disable a disposable Identity Platform user, then try Google
      sign-in and confirm the result is safe and understandable.
- [ ] Re-enable it and confirm recovery without recreating the Lagniappe user.
- [ ] **P2 edge:** Temporarily disable the Google provider only on a disposable
      project, confirm a safe failure, restore it, and confirm sign-in recovers.

## 6. Private-site email flow — provisioned first login

- [ ] Add `INVITED_NEW` through normal owner user management and confirm it has
      never logged in.
- [ ] Choose **Sign in with email**, enter `INVITED_NEW`, and continue.
- [ ] The next screen says **Create your password**.
- [ ] The selected email is displayed but is not editable on that screen.
- [ ] No Google button appears on the password-creation screen.
- [ ] The guidance says a verification link will be sent before first sign-in.
- [ ] Blank password gives a local validation message.
- [ ] Weak password gives a safe provider-derived message with no provider
      code.
- [ ] A valid dedicated password creates the Identity account.
- [ ] The page confirms that a verification link was sent.
- [ ] The message arrives at `INVITED_NEW` and uses the correct sender/app name.
- [ ] The link uses `PUBLIC_ORIGIN`, not a Google-hosted action handler.
- [ ] Before clicking the link, a password login cannot complete as a verified
      Lagniappe session.
- [ ] Click the link and confirm the verification code is accepted.
- [ ] Sign in with the new password.
- [ ] Confirm the pre-provisioned Lagniappe user was updated rather than
      duplicated.
- [ ] Confirm the user reaches the original safe `next` destination when the
      flow began from a protected page.
- [ ] Log out; the same email should now route to the normal password screen,
      not password creation.
- [ ] Reuse the verification link and confirm a safe invalid/expired message.

Interrupted first-time setup recovery:

- [ ] Repeat with another invited user through password creation and email
      delivery.
- [ ] Apply the verification link, but close the page before the final password
      sign-in.
- [ ] Return to the ordinary login flow and enter the invited email again.
- [ ] Confirm the user can reach password sign-in without being trapped on
      **Create your password** with an account-already-exists error.
- [ ] If the flow loops between password creation and account-exists, record it
      as a recovery defect.

Separate-browser email link:

- [ ] Repeat first-time setup with another disposable invited user.
- [ ] Open the verification link in a different browser profile/device.
- [ ] Confirm the link still uses the correct origin and applies successfully.
- [ ] Confirm the user can supply their email and password when local browser
      storage from the first device is absent.
- [ ] Confirm the retained `next` destination survives this separate-browser
      handoff.

## 7. Private-site email flow — returning and unknown users

### Returning password user

- [ ] Enter `RETURNING_PASSWORD`; it advances to the password-only screen.
- [ ] Incorrect password shows **Incorrect email or password.**
- [ ] Correct password signs in and redirects correctly.
- [ ] Raw Identity Platform error names such as `EMAIL_NOT_FOUND`,
      `INVALID_LOGIN_CREDENTIALS`, or `auth/...` are never shown.
- [ ] A disabled disposable identity shows **This account has been disabled.**
- [ ] Re-enable it and confirm normal sign-in resumes.

### Google-only user chooses email

- [ ] Enter `RETURNING_GOOGLE` through **Sign in with email**.
- [ ] It advances to the same password-only screen.
- [ ] A guessed password fails generically and does not mention whether the
      account uses Google.
- [ ] Use **Forgot your password?** and verify whether Identity Platform allows
      that Google identity to establish a password.
- [ ] If reset is supported, confirm the new password signs into the same
      Lagniappe user without creating a duplicate.
- [ ] If the provider rejects it, confirm the UI remains safe and the user can
      return to the method chooser to use Google.

### Unknown email on a private site

- [ ] Enter `UNKNOWN_EMAIL`.
- [ ] It advances to the same password-only screen used for a returning user.
- [ ] Submit any disposable password.
- [ ] The response is **Incorrect email or password.**
- [ ] The UI does not say that the account is unknown or unregistered.
- [ ] No Lagniappe user is created.
- [ ] No Identity Platform user is created by the failed password attempt.
- [ ] Returning to the method chooser or refreshing does not retain a durable
      “unknown user” marker in a cookie.

### Identity-only orphan

Only on a disposable project, create an Identity Platform email/password user
that is not present in the Lagniappe user database.

- [ ] **P2 edge:** Enter the orphan email and its correct password.
- [ ] Identity Platform accepts the credential, but Lagniappe rejects access
      with the same generic **Incorrect email or password.** response.
- [ ] Lagniappe does not silently provision a private-site user.
- [ ] No user-list membership detail is exposed.

## 8. Password reset flows

### Known password user

- [ ] From the password screen, choose **Forgot your password?**
- [ ] The reset screen is prefilled with the selected email.
- [ ] Use **Back to Sign In** and confirm the selected email is retained.
- [ ] Return and send the reset email.
- [ ] The UI reports that a reset link was sent.
- [ ] **P0 live:** Confirm the message arrives with the expected sender and app
      name.
- [ ] Confirm its link starts with `PUBLIC_ORIGIN/users/login` and uses
      `mode=resetPassword`.
- [ ] Open the link, choose a new password, and submit.
- [ ] Confirm the returned email is carried into the password-only sign-in
      screen.
- [ ] Confirm the success message asks the user to sign in with the new
      password.
- [ ] Old password fails; new password succeeds.
- [ ] A protected-page `next` destination survives the reset-email round trip.
- [ ] Reusing the reset link gives a safe invalid/expired-link message.

### Unknown email

- [ ] Request a reset for `UNKNOWN_EMAIL`.
- [ ] The UI gives the same “reset link sent” response as for a known account.
- [ ] No email arrives.
- [ ] No Lagniappe or Identity Platform account is created.

### Invalid and expired reset links

- [ ] Open `/users/login?mode=resetPassword&oobCode=invalid`.
- [ ] Attempt a password update and confirm a safe invalid/expired message.
- [ ] Open reset mode with a missing code and confirm a safe failure.
- [ ] **P2 edge:** Allow a real reset link to expire, then verify the same safe
      behavior.
- [ ] Request a fresh link and confirm recovery.

## 9. Verification-email and action-link flows

- [ ] Confirm verification and reset messages are sent by the configured SMTP
      provider, not by Google's default template sender.
- [ ] Confirm text and HTML message variants both contain a usable HTTPS link.
- [ ] Confirm no SMTP credential, Google access token, Flask secret, or OAuth
      client secret appears in headers, bodies, or URLs.
- [ ] Confirm action links use the installed public origin.
- [ ] Confirm links work after copying into a different browser profile.
- [ ] Confirm successful verification enables the sign-in button.
- [ ] Open `/users/login?mode=verifyEmail&oobCode=invalid` and confirm a safe
      invalid/expired message.
- [ ] Open verification mode with a missing code and confirm a safe failure.
- [ ] Reuse a consumed verification code and confirm it cannot verify again.
- [ ] Confirm an unknown `mode` query value falls back to the normal login flow
      rather than exposing an error page.

Controlled delivery failures, disposable deployment only:

- [ ] **P2 edge:** Temporarily point the authentication-email configuration at
      a controlled failing sender or revoke its test credential.
- [ ] Trigger verification delivery and confirm the browser shows a safe
      delivery/authentication failure without provider internals.
- [ ] Trigger password reset and confirm its public response remains generic so
      delivery failure cannot enumerate accounts.
- [ ] Restore the valid sender configuration and confirm delivery recovers.

## 10. Redirect and navigation matrix

Use a safe protected target with a query string, such as
`/tasks/index?from=manual-login`. Do not use destructive destination pages.

- [ ] Owner Google initialization returns to the target.
- [ ] Owner password initialization, verification, and sign-in return to the
      target.
- [ ] Returning Google sign-in returns to the target.
- [ ] Returning password sign-in returns to the target.
- [ ] First-time invited password setup and verification return to the target.
- [ ] Password reset followed by sign-in returns to the target.
- [ ] A rejected unknown Google attempt retains the target so a later
      authorized attempt can complete it.
- [ ] Opening the action email in another browser still retains the target from
      the link itself.
- [ ] A same-origin absolute `next` URL is reduced to the correct internal
      destination.
- [ ] An external `next`, `//evil.example`, backslash-prefixed path, or login
      self-loop is rejected and falls back to home.
- [ ] Query strings and URL fragments intentionally supplied in `next` are
      preserved after successful login.

## 11. Session, remember-me, and logout flows

- [ ] Password sign-in with **Remember me** checked survives closing and
      reopening the browser.
- [ ] Password sign-in with **Remember me** unchecked does not create a durable
      remembered login after the browser session ends.
- [ ] Change the remember preference on an email/password flow, log out, then
      use Google sign-in; confirm Google honors the saved preference.
- [ ] Remember preference remains synchronized across sign-in, verification,
      and reset-related forms.
- [ ] Logout returns to the normal login page.
- [ ] After logout, revisiting a protected page redirects to login.
- [ ] Browser Back after logout does not restore usable authenticated content.
- [ ] Visiting `/users/login` while authenticated shows the logged-in state
      rather than a second login form.
- [ ] Signing in as a different test user in the same disposable browser does
      not expose the prior user's cached pages or permissions.
- [ ] Session and remember cookies are Secure, HttpOnly, and SameSite=Lax.

## 12. Public-registration flows

Run only after owner initialization. Enable public registration through the
normal public-group/site-permission UI, then use a clean browser.

### Unknown email registration

- [ ] The first screen remains the Google-or-email method chooser.
- [ ] Enter a new public mailbox through **Sign in with email**.
- [ ] It advances to **Create your password** rather than returning an
      unregistered-user error.
- [ ] Complete password creation and email verification.
- [ ] A public Lagniappe user is created only after successful authentication.
- [ ] The new user has public-user permissions and cannot access owner-only
      pages.
- [ ] Logout and sign in again with the new password.

### Unknown Google registration

- [ ] **P0 live:** Choose Google with a new public-registration test account.
- [ ] Google sign-in succeeds rather than showing the private-site access
      error.
- [ ] Exactly one public Lagniappe user and one Identity account are created.
- [ ] The user receives public permissions, not owner or private-group access.
- [ ] Returning Google sign-in uses the same account.

### Disable public registration again

- [ ] Disable public registration.
- [ ] A new unknown Google account receives the private-site access message and
      is not created in Identity Platform.
- [ ] A new unknown email receives the generic password screen and generic
      incorrect-credential result.
- [ ] Existing public users behave according to the intended site policy after
      public registration is disabled; record any access-policy discrepancy
      separately from authentication.

## 13. Rate limits, network failures, and recovery

Use disposable accounts and avoid generating excessive real email.

- [ ] **P2 edge:** Repeated wrong password attempts eventually show a safe
      too-many-attempts response and a later retry succeeds after the window.
- [ ] Repeated user-status checks eventually receive a safe rate-limit result.
- [ ] Repeated password-reset requests are limited without identifying whether
      the email exists.
- [ ] Repeated verification-email requests are limited.
- [ ] Repeated Google callbacks are limited without creating partial users.
- [ ] Disable the browser network before submitting email/password; confirm a
      clear network error and successful retry after reconnecting.
- [ ] Interrupt the network after Google account selection; confirm refreshing
      and retrying is safe.
- [ ] Interrupt the network while sending a verification/reset request; confirm
      no permanent loading state and that a later retry is possible.
- [ ] Confirm raw stack traces, provider JSON, tokens, and credentials never
      appear in a browser error response.

## 14. Optional agent-login flow

When agent access is disabled:

- [ ] `/users/agent-login` returns 404.

On a disposable deployment with agent access intentionally enabled:

- [ ] The page contains only the agent access-code flow, not Google/password
      user login.
- [ ] A wrong code gives a generic invalid-code response.
- [ ] The configured code signs in the configured agent user.
- [ ] A safe `next` destination is honored.
- [ ] Logout clears the agent session normally.
- [ ] Rate limiting activates after repeated invalid codes.

## 15. OAuth and origin troubleshooting checks

On a disposable project, verify the installer guard and focused recovery mode:

- [ ] Confirm setup prints the exact absolute path ending in
      `config/files/google_oauth_credentials.json`.
- [ ] **P2 edge:** Create a **Desktop app** OAuth client, download its JSON, and
      move it to that exact path.
- [ ] Confirm setup identifies the Desktop JSON and rejects it before contacting
      the OAuth authorization endpoint, registering the Identity Platform
      provider, configuring Redis, or offering deployment.
- [ ] Create a Web application client but temporarily omit or alter its
      JavaScript origin or authorized redirect URI. Download its JSON to the
      expected path and confirm setup reports the exact missing value locally.
- [ ] Correct the Web client, replace the JSON at the same path, and confirm the
      installer reloads it without restarting.
- [ ] After local validation, confirm an unpropagated client remains at OAuth
      setup and offers to retry Google or reload a replacement JSON.
- [ ] Press Enter once and confirm setup retries the same locally verified
      client.
- [ ] Choose the stop option on a separate attempt and confirm setup exits
      nonzero with the exact repair action.
- [ ] Correct the Web client's JavaScript origin and redirect URI, allow Google
      configuration time to propagate, and run `./setup.sh oauth`.
- [ ] Confirm the focused command displays the saved project's exact origin and
      callback and credential-file path, validates the replacement JSON, updates
      Identity Platform, saves only the public client ID, and offers deployment.
- [ ] Confirm setup says the JSON is not needed by runtime and may be deleted or
      moved to secure storage, and identifies `./setup.sh oauth` as the future
      rotation path.
- [ ] **P2 edge:** Run `./setup.sh oauth`, rotate the secret on the same Web
      client, download the new JSON to the printed path, and confirm Identity
      Platform is updated while the public client ID remains unchanged.
- [ ] Accept deployment and confirm Google sign-in now uses the replacement
      client successfully.
- [ ] On a separate disposable rerun, decline the deployment offer. Confirm the
      command warns that the new setting is local only and that Google sign-in
      may remain unavailable until deployment; then rerun and accept deployment.
- [ ] Rerun `./setup.sh oauth` with the same valid Web client and confirm the
      operation remains safe and Google sign-in still works.

If Google returns `Error 400: redirect_uri_mismatch`:

- [ ] Copy the actual `redirect_uri` from Google's error details without
      copying credentials or tokens.
- [ ] Compare it character-for-character with
      `PUBLIC_ORIGIN/users/google-signin` in the OAuth Web client.
- [ ] Check scheme, hostname, App Engine region component, port, path, trailing
      slash, and custom-domain choice.
- [ ] Confirm the installed configuration's Google login URI uses that same
      value.
- [ ] Confirm the OAuth client ID shown in setup is the client enabled in
      Identity Platform.
- [ ] Confirm `PUBLIC_ORIGIN` is also an authorized JavaScript origin.
- [ ] Confirm its hostname is authorized in Identity Platform.
- [ ] Run `./setup.sh oauth` to verify and apply a corrected or replacement Web
      client; do not rerun the entire installation solely for this repair.
- [ ] After correcting console state, allow propagation time and retry in a
      clean browser profile.

If Chrome labels the site dangerous or warns about a Google password:

- [ ] Confirm the visible screen did not contain both Google sign-in and a
      password field.
- [ ] Confirm the tester used a dedicated Lagniappe password, not a Google
      password.
- [ ] Confirm the certificate and displayed hostname are correct.
- [ ] Reproduce in a clean browser profile and record the exact screen and step
      where the warning appears.
- [ ] Do not dismiss the warning as legitimate until the hostname, certificate,
      OAuth origin, and form isolation have all been checked.

## 16. Final fresh-install acceptance

- [ ] App Engine/default-origin Google owner login works.
- [ ] Wrong Google accounts are rejected before Identity account creation.
- [ ] Owner separate-password setup works on an isolated fresh deployment or is
      marked `N/A` with a reason.
- [ ] Invited-user Google login works.
- [ ] Invited-user password creation, SMTP verification, and sign-in work.
- [ ] Returning password and returning Google login work.
- [ ] Unknown private-site Google and email behavior matches the expected safe
      responses.
- [ ] Password reset works with a real delivered email.
- [ ] Verification and reset links use the correct public origin.
- [ ] Safe deep-link redirects survive Google, verification, and reset flows.
- [ ] Public registration Google and email paths work, or are marked `N/A`.
- [ ] Remember-me, logout, and session isolation work.
- [ ] No tested flow creates duplicate or unauthorized users.
- [ ] No raw provider errors, secrets, tokens, or stack traces are exposed.
- [ ] No browser password/deceptive-site warning is caused by mixing Google and
      password controls on one screen.

## QA run record

| Field | Value |
| --- | --- |
| Date/time | |
| Tester | |
| Commit/version | |
| Google Cloud project | |
| App Engine region | |
| Public origin | |
| Custom domain used | Yes / No |
| Authentication-email provider | |
| Public registration tested | Yes / No / N/A |
| Owner Google branch tested | Yes / No |
| Owner password branch tested | Yes / No / N/A |
| Browser(s) | |
| Result | Pass / Fail / Conditional |

## Defects and observations

| ID | Section/step | Account state | Expected | Actual | Evidence location |
| --- | --- | --- | --- | --- | --- |
| | | | | | |
