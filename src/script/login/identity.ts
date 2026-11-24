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

export interface IdentityPlatformConfig {
	apiKey?: string;
	projectId?: string;
}

export interface IdentityUser {
	idToken: string;
	email: string;
	displayName?: string;
}

interface IdentityResponses {
	"accounts:signUp": IdentityUser;
	"accounts:signInWithPassword": IdentityUser;
	"accounts:resetPassword": { email?: string };
	"accounts:update": { email?: string };
}

type ActionCode = string | null | undefined;
type CsrfToken = string | null | undefined;
type ProviderError = { error?: { message?: string } };
type AppResponse = { success?: boolean; error?: string };

class IdentityPlatformError extends Error {
	declare providerCode: string;
	declare status: number;
	declare code: string;

	constructor(providerMessage: unknown, status = 0) {
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

class IdentityPlatformClient {
	declare apiKey: string;
	declare projectId: string;

	constructor(config: IdentityPlatformConfig | null) {
		this.apiKey = String(config?.apiKey || "").trim();
		this.projectId = String(config?.projectId || "").trim();
		if (!this.apiKey || !this.projectId) {
			throw new IdentityPlatformError("INVALID_CLIENT_CONFIG");
		}
	}

	async request<Method extends keyof IdentityResponses>(
		method: Method,
		payload: object,
	): Promise<IdentityResponses[Method]> {
		let response: Response;
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

		let data: (Partial<IdentityResponses[Method]> & ProviderError) | null = {};
		try {
			data = await response.json();
		} catch (_error) {
			// An invalid provider response is handled like any other failed request.
		}
		if (!response.ok) {
			throw new IdentityPlatformError(data?.error?.message, response.status);
		}
		return data as IdentityResponses[Method];
	}

	async appRequest(path: string, payload: object, csrfToken: CsrfToken) {
		let response: Response;
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

		let data: AppResponse | null = {};
		try {
			data = await response.json();
		} catch (_error) {
			// Invalid application responses are normalized below.
		}
		if (!response.ok || !data?.success) {
			throw new IdentityPlatformError(
				response.status === 429 ? "TOO_MANY_ATTEMPTS_TRY_LATER" : data?.error,
				response.status,
			);
		}
		return data;
	}

	signUp(email: string, password: string) {
		return this.request("accounts:signUp", {
			email,
			password,
			returnSecureToken: true,
		});
	}

	signInWithPassword(email: string, password: string) {
		return this.request("accounts:signInWithPassword", {
			email,
			password,
			returnSecureToken: true,
		});
	}

	sendPasswordResetEmail(email: string, csrfToken: CsrfToken) {
		return this.appRequest(
			"/users/send-password-reset-email",
			{
				email,
			},
			csrfToken,
		);
	}

	sendEmailVerification(
		user: Pick<IdentityUser, "idToken">,
		csrfToken: CsrfToken,
	) {
		return this.appRequest(
			"/users/send-verification-email",
			{
				idToken: user.idToken,
			},
			csrfToken,
		);
	}

	confirmPasswordReset(oobCode: ActionCode, newPassword: string) {
		return this.request("accounts:resetPassword", {
			oobCode,
			newPassword,
		});
	}

	verifyPasswordResetCode(oobCode: ActionCode) {
		return this.request("accounts:resetPassword", { oobCode });
	}

	applyActionCode(oobCode: ActionCode) {
		return this.request("accounts:update", { oobCode });
	}
}

export { IdentityPlatformClient, IdentityPlatformError };
