"""Node-backed checks for the focused Identity Platform browser client."""


# @matrix login : action-codes auth-errors browser-fetch email-password identity-platform
def test_identity_platform_rest_client_contract(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const calls = [];
const responses = [
  { idToken: "signup-token", email: "user@example.test" },
  { idToken: "signin-token", email: "user@example.test" },
  { success: true },
  { success: true },
  { email: "user@example.test" },
  { email: "user@example.test" },
  { email: "user@example.test" },
];
let auth;
async function fakeFetch(url, options) {
  "use strict";
  if (this === auth) {
    throw new Error("Global fetch was attached to the client instance");
  }
  calls.push({
    url,
    body: JSON.parse(options.body),
    method: options.method,
    headers: options.headers,
  });
  return {
    ok: true,
    status: 200,
    async json() {
      return responses.shift();
    },
  };
}
const context = { fetch: fakeFetch, URLSearchParams };
vm.createContext(context);
let source = fs.readFileSync("src/script/login/identity.mjs", "utf8");
source = source.replace(
  /export \{[^}]+\};/,
  "globalThis.IdentityPlatformClient = IdentityPlatformClient;" +
    "globalThis.IdentityPlatformError = IdentityPlatformError;",
);
vm.runInContext(source, context);

(async () => {
  auth = new context.IdentityPlatformClient({
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

  const methods = calls.map((call) => call.url.split("/").pop().split("?")[0]);
  const expected = [
    "accounts:signUp",
    "accounts:signInWithPassword",
    "send-password-reset-email",
    "send-verification-email",
    "accounts:resetPassword",
    "accounts:resetPassword",
    "accounts:update",
  ];
  if (JSON.stringify(methods) !== JSON.stringify(expected)) {
    throw new Error(`Unexpected Identity Platform methods: ${JSON.stringify(methods)}`);
  }
  if (![calls[0], calls[1], calls[4], calls[5], calls[6]].every(
    (call) => call.url.endsWith("?key=public%20key"),
  )) {
    throw new Error("Public API key was not encoded on provider requests");
  }
  if (
    calls[2].url !== "/users/send-password-reset-email" ||
    calls[2].body.email !== "user@example.test" ||
    calls[2].headers["X-CSRFToken"] !== "csrf-token"
  ) {
    throw new Error("Password reset used the wrong Lagniappe endpoint");
  }
  if (
    calls[3].url !== "/users/send-verification-email" ||
    calls[3].body.idToken !== "signup-token" ||
    calls[3].headers["X-CSRFToken"] !== "csrf-token"
  ) {
    throw new Error("Email verification did not use authenticated app delivery");
  }
  if (
    calls[4].body.oobCode !== "reset-code" ||
    Object.hasOwn(calls[4].body, "newPassword")
  ) {
    throw new Error("Password reset link validation attempted to change the password");
  }
  if (
    calls[5].body.oobCode !== "reset-code" ||
    calls[5].body.newPassword !== "new-password"
  ) {
    throw new Error("Password reset did not carry its action code and password");
  }

  const signInErrors = [
    ["EMAIL_NOT_FOUND", "auth/user-not-found"],
    ["INVALID_PASSWORD", "auth/wrong-password"],
    ["INVALID_LOGIN_CREDENTIALS", "auth/invalid-credential"],
  ];
  for (const [providerCode, expectedCode] of signInErrors) {
    context.fetch = async () => ({
      ok: false,
      status: 400,
      async json() {
        return { error: { message: providerCode } };
      },
    });
    const rejected = new context.IdentityPlatformClient({
      apiKey: "key",
      projectId: "project-1",
    });
    try {
      await rejected.signInWithPassword("user@example.test", "bad");
      throw new Error(`${providerCode} unexpectedly succeeded`);
    } catch (error) {
      if (error.code !== expectedCode) {
        throw new Error(
          `Unexpected ${providerCode} mapping: ${error.code}`,
        );
      }
    }
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )
