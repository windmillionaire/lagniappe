import { analytics } from "../shared/analytics";
import { request } from "../shared/request";

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001b_login.py::test_check_user_status_endpoint_does_not_enumerate_accounts
 * @tests tests_e2e/001_site/test_001b_login.py::test_check_user_status_endpoint_returns_first_time_setup
 * @features login
 * @dimensions endpoint account-enumeration first-time-setup
 */
async function getUserStatus(email) {
	const response = await fetch(`/users/check-user-status?email=${email}`);
	return await response.json();
}

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001b_login.py::test_unknown_email_transitions_to_sign_in_without_leaking_existence
 * @tests tests_e2e/001_site/test_001b_login.py::test_known_registered_email_shows_sign_in
 * @features login
 * @dimensions account-enumeration sign-in-transition
 */
async function checkUserStatus(email, form) {
	try {
		const userData = await getUserStatus(email);

		if (!userData.success) {
			form.showError(userData.error);
			return;
		}

		if (userData.next === "first_time_setup") {
			document.dispatchEvent(
				new CustomEvent("login:show-first-time-setup", {
					detail: { email },
				}),
			);
		} else {
			document.dispatchEvent(
				new CustomEvent("login:show-signin", { detail: { email } }),
			);
		}
	} catch (_error) {
		form.showError("System error. Please try again.");
	}
}

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001b_login.py::test_login_identity_client_handoff_redirects_or_requires_verification
 * @tests tests_js/test_009_request_csrf.py::test_login_handoff_refreshes_csrf_before_submit_and_retries_once
 * @tests tests_js/test_009_request_csrf.py::test_login_verification_email_reuses_refreshed_csrf
 * @features login
 * @dimensions identity-platform redirect verify-email remember-preference csrf-refresh
 */
async function handleIdentityUser(user, form) {
	const body = JSON.stringify({
		authResult: user.idToken,
		name: user.displayName,
		email: user.email,
		remember: form.remember(),
	});
	let csrfToken = (await request.token()) || form.getToken();
	/**
	 * @testable false
	 * @covered-by src/script/login/tools.mjs::handleIdentityUser
	 * @reason retryable login request helper is private to Identity Platform handoff
	 */
	const send = () =>
		fetch("/users/login-identity", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				"X-CSRFToken": csrfToken,
			},
			body,
		});
	let response = await send();
	if (request.csrfFailed(response)) {
		csrfToken = await request.token();
		if (csrfToken) response = await send();
	}
	if (request.csrfFailed(response)) {
		form.showError("Your sign-in session expired. Please try again.");
		return;
	}

	const results = await response.json();

	if (results.success && results.redirect) {
		analytics.tag("login", {
			page_title: "Login",
			path: window.location.pathname,
			user_email: user.email,
		});
		window.location.href = results.redirect;
	} else if (results.requires_verification) {
		await form.auth.sendEmailVerification(user, csrfToken);
		localStorage.setItem("verificationEmail", user.email);
		form.showSuccess(
			`An email verification link has been sent to ${user.email}.`,
		);
	} else {
		form.showError(results.error || "Authentication failed. Please try again.");
	}
}

/**
 * @testable true
 * @tests tests_e2e/001_site/test_001b_login.py::test_login_auth_error_messages_are_user_safe
 * @features login
 * @dimensions auth-errors
 */
function getAuthErrorMessage(error) {
	switch (error.code) {
		case "auth/wrong-password":
		case "auth/invalid-credential":
		case "auth/user-not-found":
			return "Incorrect email or password.";
		case "auth/user-disabled":
			return "This account has been disabled.";
		case "auth/email-already-in-use":
			return "An account with this email already exists.";
		case "auth/invalid-email":
			return "Please enter a valid email address.";
		case "auth/weak-password":
			return "Password must be at least 6 characters long.";
		case "auth/operation-not-allowed":
			return "This sign-in method is not allowed.";
		case "auth/too-many-requests":
			return "Too many failed attempts. Please wait before trying again.";
		case "auth/requires-recent-login":
			return "Please sign in again to complete this action.";
		case "auth/user-token-expired":
			return "Your session has expired. Please sign in again.";
		case "auth/network-request-failed":
			return "Network error. Please check your connection.";
		case "auth/invalid-action-code":
		case "auth/expired-action-code":
			return "This link is invalid or expired. Please request a new one.";
		default:
			return "Authentication failed. Please try again.";
	}
}

export { checkUserStatus, getAuthErrorMessage, handleIdentityUser };
