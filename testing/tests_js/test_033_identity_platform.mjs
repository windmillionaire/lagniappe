import assert from "node:assert/strict";
import { test } from "node:test";
import { IdentityPlatformClient } from "../../src/script/login/identity.mjs";
import { mockFetch } from "../utility/js/environment.mjs";

/** @matrix login : action-codes auth-errors browser-fetch email-password identity-platform */
test("test_identity_platform_rest_client_contract", async (t) => {
	const responses = [
		{ idToken: "signup-token", email: "user@example.test" },
		{ idToken: "signin-token", email: "user@example.test" },
		{ success: true },
		{ success: true },
		{ email: "user@example.test" },
		{ email: "user@example.test" },
		{ email: "user@example.test" },
	];
	let providerError = null;
	const network = mockFetch(
		t,
		() => {
			if (providerError) {
				return Response.json(
					{ error: { message: providerError } },
					{ status: 400 },
				);
			}
			return Response.json(responses.shift());
		},
		null,
	);
	const auth = new IdentityPlatformClient({
		apiKey: "public key",
		projectId: "project-1",
	});
	await auth.signUp("user@example.test", "password");
	await auth.signInWithPassword("user@example.test", "password");
	await auth.sendPasswordResetEmail("user@example.test", "csrf-token");
	await auth.sendEmailVerification({ idToken: "signup-token" }, "csrf-token");
	await auth.verifyPasswordResetCode("reset-code");
	await auth.confirmPasswordReset("reset-code", "new-password");
	await auth.applyActionCode("verify-code");

	assert.equal(
		network.fetch.mock.calls.slice(0, 7).every((call) => call.this !== auth),
		true,
		"Global fetch was attached to the client instance",
	);
	const calls = network.calls.slice(0, 7).map((call) => ({
		...call,
		body: JSON.parse(call.init.body),
		headers: call.init.headers,
	}));
	assert.deepEqual(
		calls.map((call) => call.url.pathname.split("/").pop()),
		[
			"accounts:signUp",
			"accounts:signInWithPassword",
			"send-password-reset-email",
			"send-verification-email",
			"accounts:resetPassword",
			"accounts:resetPassword",
			"accounts:update",
		],
		`Unexpected Identity Platform methods: ${JSON.stringify(
			calls.map((call) => call.url.pathname.split("/").pop()),
		)}`,
	);
	assert.equal(
		[calls[0], calls[1], calls[4], calls[5], calls[6]].every((call) =>
			call.url.href.endsWith("?key=public%20key"),
		),
		true,
		"Public API key was not encoded on provider requests",
	);
	assert.equal(
		calls[2].input,
		"/users/send-password-reset-email",
		"Password reset used the wrong Lagniappe endpoint",
	);
	assert.equal(
		calls[2].body.email,
		"user@example.test",
		"Password reset used the wrong Lagniappe endpoint",
	);
	assert.equal(
		calls[2].headers["X-CSRFToken"],
		"csrf-token",
		"Password reset used the wrong Lagniappe endpoint",
	);
	assert.equal(
		calls[3].input,
		"/users/send-verification-email",
		"Email verification did not use authenticated app delivery",
	);
	assert.equal(
		calls[3].body.idToken,
		"signup-token",
		"Email verification did not use authenticated app delivery",
	);
	assert.equal(
		calls[3].headers["X-CSRFToken"],
		"csrf-token",
		"Email verification did not use authenticated app delivery",
	);
	assert.equal(
		calls[4].body.oobCode,
		"reset-code",
		"Password reset link validation attempted to change the password",
	);
	assert.equal(
		Object.hasOwn(calls[4].body, "newPassword"),
		false,
		"Password reset link validation attempted to change the password",
	);
	assert.equal(
		calls[5].body.oobCode,
		"reset-code",
		"Password reset did not carry its action code and password",
	);
	assert.equal(
		calls[5].body.newPassword,
		"new-password",
		"Password reset did not carry its action code and password",
	);

	for (const [providerCode, expectedCode] of [
		["EMAIL_NOT_FOUND", "auth/user-not-found"],
		["INVALID_PASSWORD", "auth/wrong-password"],
		["INVALID_LOGIN_CREDENTIALS", "auth/invalid-credential"],
	]) {
		providerError = providerCode;
		const rejected = new IdentityPlatformClient({
			apiKey: "key",
			projectId: "project-1",
		});
		await assert.rejects(
			rejected.signInWithPassword("user@example.test", "bad"),
			(error) => {
				assert.equal(
					error.code,
					expectedCode,
					`Unexpected ${providerCode} mapping: ${error.code}`,
				);
				return true;
			},
			`${providerCode} unexpectedly succeeded`,
		);
	}
});
