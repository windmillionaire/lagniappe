"""Node-backed checks for the frontend request CSRF retry envelope."""

import textwrap

def run_request_check(run_node, assertion: str):
    script = f"""
const fs = require("node:fs");
const vm = require("node:vm");

const tokenElt = {{ value: "stale-token" }};
const entityEvents = [];
const networkErrors = [];
const fetchCalls = [];
const listeners = {{}};

class FakeFormData {{
  constructor() {{
    this.fields = new Map();
  }}

  append(name, value) {{
    this.fields.set(name, value);
  }}

  entries() {{
    return this.fields.entries();
  }}

  has(name) {{
    return this.fields.has(name);
  }}
}}

function cloneHeaders(headers) {{
  if (!headers) return {{}};
  if (headers instanceof Headers) return Object.fromEntries(headers.entries());
  return {{ ...headers }};
}}

const context = {{
  clearTimeout,
  DOMParser: class {{
    parseFromString(text, type) {{
      return {{ text, type }};
    }}
  }},
  document: {{
    documentElement: {{ innerHTML: "" }},
    getElementById(id) {{
      return id === "token" ? tokenElt : null;
    }},
    addEventListener(type, handler) {{
      listeners[type] = handler;
    }},
    listeners,
    querySelector() {{
      return {{ innerHTML: "" }};
    }},
    title: "",
  }},
  fetchCalls,
  entityEvents,
  FormData: FakeFormData,
  Headers,
  networkErrors,
  Response,
  setTimeout,
  tokenElt,
  URLSearchParams,
  CustomEvent: class {{
    constructor(type, options = {{}}) {{
      this.type = type;
      this.detail = options.detail;
    }}
  }},
  window: {{
    dispatchEvent(event) {{ entityEvents.push(event); }},
    location: {{ href: "" }},
  }},
}};

context.fetch = async (url, config = {{}}) => {{
  const requestUrl = typeof url === "string" ? url : url.url;
  fetchCalls.push({{
    url: requestUrl,
    body: config.body,
    cache: config.cache || url.cache,
    headers: cloneHeaders(config.headers),
    keepalive: Boolean(config.keepalive),
    method: config.method || "GET",
  }});

  if (requestUrl === "/upstream-reset") {{
    return new Response(
      "upstream connect error or disconnect/reset before headers. reset reason: connection termination",
      {{
        status: 503,
        statusText: "Service Unavailable",
        headers: {{ "Content-Type": "text/plain" }},
      }},
    );
  }}

  if (requestUrl === "/bad-request") {{
    return new Response("invalid payload", {{
      status: 400,
      statusText: "Bad Request",
      headers: {{ "Content-Type": "text/plain" }},
    }});
  }}

  if (requestUrl === "/validation-json") {{
    return new Response(JSON.stringify({{
      error: "Invalid polling request.",
      code: "invalid_poll_contract",
      path: "subscriptions[0].revision",
      reason: "type",
    }}), {{
      status: 422,
      statusText: "Unprocessable Content",
      headers: {{ "Content-Type": "application/json" }},
    }});
  }}

  if (requestUrl === "/validation-text") {{
    return new Response("Specific validation message.", {{
      status: 422,
      statusText: "Unprocessable Entity",
      headers: {{ "Content-Type": "text/plain" }},
    }});
  }}

  if (requestUrl === "/html-error") {{
    return new Response("<main>replacement error page</main>", {{
      status: 500,
      statusText: "Internal Server Error",
      headers: {{ "Content-Type": "text/html" }},
    }});
  }}

  if (requestUrl === "/unchanged") {{
    return new Response(JSON.stringify({{ rows: [] }}), {{
      status: 200,
      headers: {{
        "Content-Type": "application/json",
        "X-Lagniappe-Updated": "false",
      }},
    }});
  }}

  if (requestUrl === "/not-modified") {{
    return new Response(null, {{
      status: 304,
      headers: {{ ETag: '"deferred-state"' }},
    }});
  }}

  if (requestUrl === "/invalidate") {{
    return new Response(JSON.stringify({{ targets: [] }}), {{
      status: 200,
      headers: {{
        "Content-Type": "application/json",
        "X-Lagniappe-Invalidate-Cache": "True",
      }},
    }});
  }}

  if (requestUrl === "/entity-response") {{
    return new Response(JSON.stringify({{ saved: true }}), {{
      status: 200,
      headers: {{
        "Content-Type": "application/json",
        "X-Lagniappe-Entity-Revisions": JSON.stringify([
          {{ key: "entity-key", fingerprint: "entity-fingerprint" }},
          {{ key: "owner-key", fingerprint: "owner-fingerprint" }},
        ]),
      }},
    }});
  }}

  if (requestUrl === "/l/token") {{
    await new Promise((resolve) => setTimeout(resolve, 5));
    return new Response("fresh-token", {{ status: 200 }});
  }}

  if (config.headers?.["X-CSRFToken"] === "fresh-token") {{
    const data = requestUrl.endsWith("/users/logout")
      ? {{ success: true, redirect: "/users/login" }}
      : {{ accepted: true }};
    return new Response(JSON.stringify(data), {{
      status: 200,
      headers: {{ "Content-Type": "application/json" }},
    }});
  }}

  return new Response("stale csrf", {{
    status: 400,
    statusText: "Bad Request",
    headers: {{ "X-Lagniappe-CSRF": "invalid" }},
  }});
}};

vm.createContext(context);
let source = fs.readFileSync("src/script/shared/request.mjs", "utf8");
source = source.replace(
  'import {{ captureNetworkError }} from "./errors.mjs";',
  "const captureNetworkError = (...args) => networkErrors.push(args);",
);
source = source.replace(
  'import {{ applyNotificationStateHeader }} from "./notificationState.mjs";',
  "const applyNotificationStateHeader = () => null;",
);
source = source.replace("export const request = {{", "const request = {{");
source += "\\nglobalThis.request = request;";
vm.runInContext(source, context);
const request = context.request;
const document = context.document;
const FormData = context.FormData;
const window = context.window;

let logoutSource = fs.readFileSync("src/script/shared/logout.mjs", "utf8");
logoutSource = logoutSource.replace('import {{ request }} from "./request";', "");
logoutSource = logoutSource.replace(
  "export const initializeLogoutForms =",
  "const initializeLogoutForms =",
);
logoutSource += "\\nglobalThis.initializeLogoutForms = initializeLogoutForms;";
vm.runInContext(logoutSource, context);
const initializeLogoutForms = context.initializeLogoutForms;

(async () => {{
{textwrap.indent(assertion, "  ")}
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""

    run_node(script)


# @features csrf
# @dimensions stale-token concurrent-refresh
def test_concurrent_stale_writes_share_server_controlled_token_refresh(run_node):
    run_request_check(
        run_node,
        """
const [post, put] = await Promise.all([
  request.post("/l/sync", { value: 1 }, { keepalive: true }),
  request.put("/pages/page-1/update", { value: 2 }),
]);

if (!post.ok || !put.ok) {
  throw new Error("stale writes did not retry successfully");
}

const tokenCalls = fetchCalls.filter((call) => call.url === "/l/token");
if (tokenCalls.length !== 1) {
  throw new Error(`Expected one shared token refresh, got ${tokenCalls.length}`);
}
if (tokenCalls[0].cache !== undefined) {
  throw new Error(`Frontend forced token cache mode: ${tokenCalls[0].cache}`);
}
if (tokenCalls[0].headers["Cache-Control"] !== undefined) {
  throw new Error("Frontend sent a token cache-control request header");
}
if (tokenElt.value !== "fresh-token") {
  throw new Error(`Hidden token was not updated: ${tokenElt.value}`);
}

const writeCalls = fetchCalls.filter((call) => call.url !== "/l/token");
const staleWrites = writeCalls.filter(
  (call) => call.headers["X-CSRFToken"] === "stale-token",
);
const freshWrites = writeCalls.filter(
  (call) => call.headers["X-CSRFToken"] === "fresh-token",
);

if (staleWrites.length !== 2 || freshWrites.length !== 2) {
  throw new Error(
    `Expected two stale attempts and two fresh retries, got ${staleWrites.length}/${freshWrites.length}`,
  );
}
if (!writeCalls.some((call) => call.keepalive)) {
  throw new Error("Keepalive option was not preserved across the retry path");
}
""",
    )


# @features csrf request-errors
# @dimensions retry-classification
def test_non_csrf_bad_request_is_not_retried(run_node):
    run_request_check(
        run_node,
        """
const response = await request.post("/bad-request", { value: "invalid" });

if (response.ok || response.error !== "invalid payload") {
  throw new Error(`Unexpected bad-request result: ${JSON.stringify(response)}`);
}
const calls = fetchCalls.filter((call) => call.url === "/bad-request");
if (calls.length !== 1) {
  throw new Error(`Non-CSRF 400 was retried ${calls.length} times`);
}
if (fetchCalls.some((call) => call.url === "/l/token")) {
  throw new Error("Non-CSRF 400 triggered a token refresh");
}
""",
    )


# @features request-errors polling
# @dimensions structured-validation diagnostics
def test_request_preserves_structured_validation_error(run_node):
    run_request_check(
        run_node,
        """
const response = await request.post("/validation-json", { value: "invalid" });

if (response.ok || response.status !== 422 ||
    response.code !== "invalid_poll_contract" ||
    response.path !== "subscriptions[0].revision" ||
    response.reason !== "type") {
  throw new Error(`Structured validation was lost: ${JSON.stringify(response)}`);
}
""",
    )


# @features request-errors
# @dimensions plain-validation diagnostics
def test_request_preserves_plain_validation_error(run_node):
    run_request_check(
        run_node,
        """
const response = await request.post("/validation-text", { value: "invalid" });

if (response.ok || response.status !== 422 ||
    response.error !== "Specific validation message.") {
  throw new Error(`Plain validation was lost: ${JSON.stringify(response)}`);
}
""",
    )


# @features request-errors edited-entity-notice
# @dimensions non-invasive-probe reload-fallback
def test_request_can_return_html_error_without_replacing_page(run_node):
    run_request_check(
        run_node,
        """
document.documentElement.innerHTML = "mounted page";
const response = await request.get("/html-error", null, {
  replaceErrorPage: false,
});

if (response.ok || response.error !== "Internal Server Error") {
  throw new Error(`Unexpected HTML error result: ${JSON.stringify(response)}`);
}
if (document.documentElement.innerHTML !== "mounted page") {
  throw new Error("HTML error response replaced the mounted page");
}
""",
    )


# @features cache request
# @dimensions conditional-response dom-refresh
def test_request_exposes_service_worker_updated_marker(run_node):
    run_request_check(
        run_node,
        """
const response = await request.get("/unchanged");
if (response.updated !== false) {
  throw new Error(`Expected updated=false, got ${response.updated}`);
}
if (!Array.isArray(response.rows)) {
  throw new Error("Response body was not parsed alongside the update marker");
}
""",
    )


# @pair cache:conditional-response
# @pair cache:etag
# @pair request:conditional-response
# @pair request:etag
# @pair request:post-headers
# @pair deferred-jobs:conditional-response
# @pair deferred-jobs:etag
# @pair deferred-jobs:post-headers
def test_request_supports_conditional_post_not_modified(run_node):
    run_request_check(
        run_node,
        """
const response = await request.post(
  "/not-modified",
  { operations: ["operation-a"] },
  { headers: { "If-None-Match": '"deferred-state"' } },
);
if (!response.ok || !response.unchanged || response.etag !== '"deferred-state"') {
  throw new Error(`Unexpected 304 result: ${JSON.stringify(response)}`);
}
const call = fetchCalls.find((item) => item.url === "/not-modified");
if (call.headers["If-None-Match"] !== '"deferred-state"') {
  throw new Error(`Conditional POST header was lost: ${JSON.stringify(call)}`);
}
""",
    )


# @features cache request
# @dimensions invalidation reload
def test_request_exposes_client_cache_invalidation_marker(run_node):
    run_request_check(
        run_node,
        """
const response = await request.post("/invalidate", { targets: [] });
if (response.reload !== true) {
  throw new Error(`Expected reload=true, got ${response.reload}`);
}
if (!Array.isArray(response.targets)) {
  throw new Error("Response body was not parsed alongside the invalidation marker");
}
""",
    )


# @features edited-entity-notice request
# @dimensions acknowledgement response-headers multiple-entities
def test_request_dispatches_entity_fingerprint_acknowledgement(run_node):
    run_request_check(
        run_node,
        """
const response = await request.put("/entity-response", { value: "saved" });
if ("entity" in response) {
  throw new Error(`Singular response entity compatibility remained: ${JSON.stringify(response.entity)}`);
}
if (response.entities?.length !== 2) {
  throw new Error(`Missing response revisions: ${JSON.stringify(response.entities)}`);
}
if (entityEvents.length !== 2 || entityEvents[0].type !== "entity-updated") {
  throw new Error("Entity acknowledgement event was not dispatched");
}
if (entityEvents[0].detail.fingerprint !== "entity-fingerprint") {
  throw new Error("Entity acknowledgement event carried the wrong baseline");
}
if (entityEvents[1].detail.key !== "owner-key") {
  throw new Error("Related owner acknowledgement was not dispatched");
}
entityEvents.splice(0);
const probe = await request.get("/entity-response", null, {
  acknowledgeEntities: false,
});
if (probe.entities?.length !== 2) {
  throw new Error("Revision probe did not retain plural response entities");
}
if (entityEvents.length !== 0) {
  throw new Error("Revision probe dispatched an entity acknowledgement");
}
""",
    )


# @features request-errors
# @dimensions proxy-text-error ajax-upload
def test_plain_text_upstream_error_stays_in_request_error_path(run_node):
    run_request_check(
        run_node,
        """
document.documentElement.innerHTML = "<html><body>app still mounted</body></html>";

const data = new FormData();
data.append("assets", "{}");
const response = await request.post("/upstream-reset", data);

if (response.ok) {
  throw new Error("plain text upstream error was treated as ok");
}
if (response.error !== "Upload fewer files?") {
  throw new Error(`Unexpected error message: ${response.error}`);
}
if (document.documentElement.innerHTML !== "<html><body>app still mounted</body></html>") {
  throw new Error("request wrapper replaced the whole document for a text/plain error");
}
""",
    )


# @features login
# @dimensions logout button
def test_logout_button_posts_without_hidden_form(run_node):
    run_request_check(
        run_node,
        """
initializeLogoutForms();

const button = {
  dataset: {
    action: "logout",
    route: "https://example.test/users/logout",
  },
  disabled: false,
  closest(selector) {
    return selector === "[data-action='logout'][data-route]" ? this : null;
  },
};
let defaultPrevented = false;

await document.listeners.click({
  target: button,
  preventDefault() {
    defaultPrevented = true;
  },
});

if (!defaultPrevented) {
  throw new Error("logout button click did not prevent default navigation");
}
if (window.location.href !== "/users/login") {
  throw new Error(`Expected logout redirect, got ${window.location.href}`);
}
if (!button.disabled) {
  throw new Error("logout button was not disabled during submission");
}
if (button.dataset.submitting !== "true") {
  throw new Error("logout button did not track its submitting state");
}

const tokenCalls = fetchCalls.filter((call) => call.url === "/l/token");
if (tokenCalls.length !== 1) {
  throw new Error(`Expected one token refresh, got ${tokenCalls.length}`);
}

const logoutCalls = fetchCalls.filter((call) =>
  call.url.endsWith("/users/logout"),
);
if (logoutCalls.length !== 2) {
  throw new Error(`Expected stale logout plus retry, got ${logoutCalls.length}`);
}
if (logoutCalls[0].headers["X-CSRFToken"] !== "stale-token") {
  throw new Error("initial logout button request did not use the current page token");
}
if (logoutCalls[1].headers["X-CSRFToken"] !== "fresh-token") {
  throw new Error("retried logout button request did not use the refreshed token");
}
if (logoutCalls.some((call) => call.body)) {
  throw new Error("logout button should not send form data");
}
""",
    )


# @features login
# @dimensions csrf-refresh
def test_login_handoff_refreshes_csrf_before_submit_and_retries_once(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const calls = [];
const errors = [];
const tokenElt = { value: "expired-page-token" };
const refreshedTokens = ["fresh-token", "race-retry-token"];
let handoffAttempts = 0;

const context = {
  Response,
  analytics: {
    tag(name, data) {
      calls.push({ type: "analytics", name, data });
    },
  },
  document: {
    getElementById(id) {
      return id === "token" ? tokenElt : null;
    },
  },
  request: {
    csrfFailed(response) {
      return response.status === 400 &&
        response.headers.get("X-Lagniappe-CSRF") === "invalid";
    },
    async token() {
      const token = refreshedTokens.shift();
      calls.push({ type: "token", token });
      tokenElt.value = token;
      return token;
    },
  },
  window: {
    location: { href: "", pathname: "/users/login" },
  },
};

context.fetch = async (url, config) => {
  handoffAttempts += 1;
  calls.push({
    type: "handoff",
    url,
    token: config.headers["X-CSRFToken"],
    body: JSON.parse(config.body),
  });
  if (handoffAttempts === 1) {
    return new Response("expired csrf", {
      status: 400,
      headers: { "X-Lagniappe-CSRF": "invalid" },
    });
  }
  return new Response(
    JSON.stringify({ success: true, redirect: "/home" }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
};

vm.createContext(context);
let source = fs.readFileSync("src/script/login/tools.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace(
  /export \{[^}]+\};/,
  "globalThis.handleIdentityUser = handleIdentityUser;",
);
vm.runInContext(source, context);

const user = {
  displayName: "Test User",
  email: "test@example.test",
  idToken: "identity-id-token",
};
const form = {
  auth: {},
  getToken() {
    return tokenElt.value;
  },
  remember() {
    return true;
  },
  showError(message) {
    errors.push(message);
  },
  showSuccess(message) {
    throw new Error(`Unexpected success message: ${message}`);
  },
};

(async () => {
  await context.handleIdentityUser(user, form);

  const securityCalls = calls.filter((call) =>
    call.type === "token" || call.type === "handoff"
  );
  const sequence = securityCalls.map((call) => `${call.type}:${call.token}`);
  const expected = [
    "token:fresh-token",
    "handoff:fresh-token",
    "token:race-retry-token",
    "handoff:race-retry-token",
  ];
  if (JSON.stringify(sequence) !== JSON.stringify(expected)) {
    throw new Error(`Unexpected CSRF sequence: ${JSON.stringify(sequence)}`);
  }
  if (errors.length !== 0) {
    throw new Error(`Login showed an error: ${JSON.stringify(errors)}`);
  }
  if (context.window.location.href !== "/home") {
    throw new Error(`Login did not redirect: ${context.window.location.href}`);
  }
  const handoffs = calls.filter((call) => call.type === "handoff");
  if (handoffs.some((call) => call.body.authResult !== "identity-id-token")) {
    throw new Error("Login retry did not preserve the Identity Platform credential");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @features login
# @dimensions csrf-refresh verify-email
def test_login_verification_email_reuses_refreshed_csrf(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const verificationCalls = [];
const stored = [];
const context = {
  analytics: { tag() {} },
  localStorage: {
    setItem(key, value) {
      stored.push({ key, value });
    },
  },
  request: {
    csrfFailed() {
      return false;
    },
    async token() {
      return "fresh-verification-token";
    },
  },
  window: {
    location: { href: "", pathname: "/users/login" },
  },
  fetch: async () => ({
    async json() {
      return { requires_verification: true };
    },
  }),
};

vm.createContext(context);
let source = fs.readFileSync("src/script/login/tools.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace(
  /export \{[^}]+\};/,
  "globalThis.handleIdentityUser = handleIdentityUser;",
);
vm.runInContext(source, context);

const user = {
  displayName: "Test User",
  email: "test@example.test",
  idToken: "identity-id-token",
};
const form = {
  auth: {
    async sendEmailVerification(sentUser, csrfToken) {
      verificationCalls.push({ sentUser, csrfToken });
    },
  },
  getToken() {
    return "expired-page-token";
  },
  remember() {
    return false;
  },
  showError(message) {
    throw new Error(`Unexpected error: ${message}`);
  },
  showSuccess() {},
};

(async () => {
  await context.handleIdentityUser(user, form);
  if (
    verificationCalls.length !== 1 ||
    verificationCalls[0].sentUser !== user ||
    verificationCalls[0].csrfToken !== "fresh-verification-token"
  ) {
    throw new Error(
      `Verification email did not reuse refreshed CSRF: ${JSON.stringify(verificationCalls)}`
    );
  }
  if (
    stored.length !== 1 ||
    stored[0].key !== "verificationEmail" ||
    stored[0].value !== user.email
  ) {
    throw new Error(`Verification state was not retained: ${JSON.stringify(stored)}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )
