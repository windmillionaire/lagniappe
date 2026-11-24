import { analytics } from "../shared/analytics.ts";
import { request } from "../shared/request.ts";

async function getUserStatus(email) {
	const response = await fetch(
		`/users/check-user-status?email=${encodeURIComponent(email)}`,
	);
	return await response.json();
}

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

async function handleIdentityUser(user, form) {
	const body = JSON.stringify({
		authResult: user.idToken,
		name: user.displayName,
		email: user.email,
		remember: form.remember(),
	});
	let csrfToken = (await request.token()) || form.getToken();
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
		try {
			await form.auth.sendEmailVerification(user, csrfToken);
		} catch (_error) {
			document.dispatchEvent(
				new CustomEvent("login:show-signin", {
					detail: {
						action: "verification-delivery-failed",
						email: user.email,
					},
				}),
			);
			return;
		}
		localStorage.setItem("verificationEmail", user.email);
		form.showConfirmation(
			form.verificationSuccessMessage ||
				`An email verification link has been sent to ${user.email}.`,
		);
	} else {
		form.showError(results.error || "Authentication failed. Please try again.");
	}
}

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
