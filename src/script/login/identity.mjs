const IDENTITY_PLATFORM_API = "https://identitytoolkit.googleapis.com/v1";

const ERROR_CODES = new Map([
	["EMAIL_EXISTS", "auth/email-already-in-use"],
	["EMAIL_NOT_FOUND", "auth/user-not-found"],
	["INVALID_PASSWORD", "auth/wrong-password"],
	["INVALID_LOGIN_CREDENTIALS", "auth/invalid-credential"],
	["USER_DISABLED", "auth/user-disabled"],
	["INVALID_EMAIL", "auth/invalid-email"],
	["WEAK_PASSWORD", "auth/weak-password"],
	["OPERATION_NOT_ALLOWED", "auth/operation-not-allowed"],
	["TOO_MANY_ATTEMPTS_TRY_LATER", "auth/too-many-requests"],
	["TOKEN_EXPIRED", "auth/user-token-expired"],
	["EXPIRED_OOB_CODE", "auth/expired-action-code"],
	["INVALID_OOB_CODE", "auth/invalid-action-code"],
]);

/**
 * @testable true
 * @tests tests_js/test_033_identity_platform.py::test_identity_platform_rest_client_contract
 * @features login
 * @dimensions identity-platform auth-errors
 */
class IdentityPlatformError extends Error {
	constructor(providerMessage, status = 0) {
		const providerCode = String(providerMessage || "")
			.split(" : ", 1)[0]
			.trim();
		super(providerCode || "IDENTITY_PLATFORM_REQUEST_FAILED");
		this.name = "IdentityPlatformError";
		this.providerCode = providerCode;
		this.status = status;
		this.code =
			ERROR_CODES.get(providerCode) ||
			(status === 0
				? "auth/network-request-failed"
				: "auth/identity-platform-request-failed");
	}
}

/**
 * @testable true
 * @tests tests_js/test_033_identity_platform.py::test_identity_platform_rest_client_contract
 * @features login
 * @dimensions identity-platform email-password action-codes browser-fetch
 */
class IdentityPlatformClient {
	constructor(config) {
		this.apiKey = String(config?.apiKey || "").trim();
		this.projectId = String(config?.projectId || "").trim();
		if (!this.apiKey || !this.projectId) {
			throw new IdentityPlatformError("INVALID_CLIENT_CONFIG");
		}
	}

	async request(method, payload) {
		let response;
		try {
			response = await fetch(
				`${IDENTITY_PLATFORM_API}/${method}?key=${encodeURIComponent(this.apiKey)}`,
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify(payload),
				},
			);
		} catch (_error) {
			throw new IdentityPlatformError("", 0);
		}

		let data = {};
		try {
			data = await response.json();
		} catch (_error) {
			// An invalid provider response is handled like any other failed request.
		}
		if (!response.ok) {
			throw new IdentityPlatformError(data?.error?.message, response.status);
		}
		return data;
	}

	async appRequest(path, payload, csrfToken) {
		let response;
		try {
			response = await fetch(path, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					"X-CSRFToken": csrfToken || "",
				},
				body: JSON.stringify(payload),
			});
		} catch (_error) {
			throw new IdentityPlatformError("", 0);
		}

		let data = {};
		try {
			data = await response.json();
		} catch (_error) {
			// Invalid application responses are normalized below.
		}
		if (!response.ok || !data.success) {
			throw new IdentityPlatformError(
				response.status === 429 ? "TOO_MANY_ATTEMPTS_TRY_LATER" : data?.error,
				response.status,
			);
		}
		return data;
	}

	signUp(email, password) {
		return this.request("accounts:signUp", {
			email,
			password,
			returnSecureToken: true,
		});
	}

	signInWithPassword(email, password) {
		return this.request("accounts:signInWithPassword", {
			email,
			password,
			returnSecureToken: true,
		});
	}

	sendPasswordResetEmail(email, csrfToken) {
		return this.appRequest(
			"/users/send-password-reset-email",
			{
				email,
			},
			csrfToken,
		);
	}

	sendEmailVerification(user, csrfToken) {
		return this.appRequest(
			"/users/send-verification-email",
			{
				idToken: user.idToken,
			},
			csrfToken,
		);
	}

	confirmPasswordReset(oobCode, newPassword) {
		return this.request("accounts:resetPassword", {
			oobCode,
			newPassword,
		});
	}

	verifyPasswordResetCode(oobCode) {
		return this.request("accounts:resetPassword", { oobCode });
	}

	applyActionCode(oobCode) {
		return this.request("accounts:update", { oobCode });
	}
}

export { IdentityPlatformClient, IdentityPlatformError };
