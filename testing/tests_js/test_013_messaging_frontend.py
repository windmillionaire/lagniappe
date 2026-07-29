"""Node-backed checks for frontend messaging initialization."""

import textwrap

def run_messaging_check(run_node, assertion: str):
    script = f"""
const fs = require("node:fs");
const vm = require("node:vm");

class MemoryStorage {{
  constructor() {{
    this.values = new Map();
  }}

  getItem(key) {{
    return this.values.has(key) ? this.values.get(key) : null;
  }}

  setItem(key, value) {{
    this.values.set(key, String(value));
  }}

  clear() {{
    this.values.clear();
  }}
}}

const capturedErrors = [];
const getTokenCalls = [];
const modalCalls = [];
let configRequestCalls = 0;
let getMessagingCalls = 0;
let messagingSupported = true;
let configResponse = {{
  ok: true,
  apiKey: "api-key",
  appId: "app-id",
  projectId: "project-id",
  messagingSenderId: "sender-id",
  vapidKey: "vapid-key",
}};
let currentToken = "fresh-token";
let modalPermission = "default";
let notificationPermission = "default";
let pushSubscription = null;
let requestPermissionCalls = 0;

function makeSubscription() {{
  return {{
    endpoint: "https://push.example.test/subscription",
    expirationTime: null,
    getKey: () => new ArrayBuffer(1),
  }};
}}

function nextTurn() {{
  return new Promise((resolve) => setTimeout(resolve, 0));
}}

const registration = {{
  scope: "https://lagniappe.test/",
  active: {{ state: "activated" }},
  waiting: null,
  installing: null,
  pushManager: {{
    getSubscription: async () => pushSubscription,
  }},
}};

const context = {{
  ArrayBuffer,
  capturedErrors,
  clearTimeout,
  console,
  crypto,
  document: {{
    visibilityState: "visible",
  }},
  getMessaging: () => {{
    getMessagingCalls += 1;
    return {{}};
  }},
  getMessagingToken: async (...args) => {{
    getTokenCalls.push(args);
    return currentToken;
  }},
  getTokenCalls,
  isMessagingSupported: async () => messagingSupported,
  indexedDB: {{
    databases: async () => [],
  }},
  initializeApp: (config) => ({{ config }}),
  localStorage: new MemoryStorage(),
  makeSubscription,
  MessagingModal: class {{
    async init(options = {{}}) {{
      modalCalls.push(options);
      return modalPermission;
    }}
  }},
  modalCalls,
  navigator: {{
    onLine: true,
    serviceWorker: {{
      controller: {{ state: "activated" }},
      getRegistration: async () => registration,
      ready: Promise.resolve(registration),
    }},
  }},
  nextTurn,
  Notification: {{
    get permission() {{
      return notificationPermission;
    }},
    requestPermission: async () => {{
      requestPermissionCalls += 1;
      return notificationPermission;
    }},
  }},
  request: {{
    get: async () => {{
      configRequestCalls += 1;
      return configResponse;
    }},
  }},
  sessionStorage: new MemoryStorage(),
  setTimeout,
  URL,
  window: {{ __TESTING__: false }},
}};

context.captureError = (...args) => capturedErrors.push(args);

Object.defineProperties(context, {{
  configResponse: {{
    get: () => configResponse,
    set: (value) => {{
      configResponse = value;
    }},
  }},
  configRequestCalls: {{
    get: () => configRequestCalls,
  }},
  currentToken: {{
    get: () => currentToken,
    set: (value) => {{
      currentToken = value;
    }},
  }},
  modalPermission: {{
    get: () => modalPermission,
    set: (value) => {{
      modalPermission = value;
    }},
  }},
  getMessagingCalls: {{
    get: () => getMessagingCalls,
  }},
  messagingSupported: {{
    get: () => messagingSupported,
    set: (value) => {{
      messagingSupported = value;
    }},
  }},
  notificationPermission: {{
    get: () => notificationPermission,
    set: (value) => {{
      notificationPermission = value;
    }},
  }},
  pushSubscription: {{
    get: () => pushSubscription,
    set: (value) => {{
      pushSubscription = value;
    }},
  }},
  requestPermissionCalls: {{
    get: () => requestPermissionCalls,
  }},
}});

vm.createContext(context);
let source = fs.readFileSync("src/script/shared/messaging.mjs", "utf8");
source = source.replace(
  'import {{ initializeApp }} from "firebase/app";',
  "const initializeApp = globalThis.initializeApp;",
);
source = source.replace(
  `import {{
\tgetMessaging,
\tgetToken as getMessagingToken,
\tisSupported as isMessagingSupported,
}} from "firebase/messaging";`,
  `const getMessaging = globalThis.getMessaging;
const getMessagingToken = globalThis.getMessagingToken;
const isMessagingSupported = globalThis.isMessagingSupported;`,
);
source = source.replace(
  'import {{ captureError }} from "./errors";',
  "const captureError = globalThis.captureError;",
);
source = source.replace(
  'import {{ MessagingModal }} from "./modal";',
  "const MessagingModal = globalThis.MessagingModal;",
);
source = source.replace(
  'import {{ request }} from "./request";',
  "const request = globalThis.request;",
);
source = source.replace(
  "export async function initializeMessaging",
  "async function initializeMessaging",
);
source += "\\nglobalThis.initializeMessaging = initializeMessaging;";
vm.runInContext(source, context);
const initializeMessaging = context.initializeMessaging;
const document = context.document;
const localStorage = context.localStorage;

(async () => {{
{textwrap.indent(assertion, "  ")}
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""

    run_node(script)


# @features messaging
# @dimensions cached-token permission-modal
def test_cached_token_with_existing_subscription_skips_permission_prompt(run_node):
    run_messaging_check(
        run_node,
        """
localStorage.setItem("firebase", JSON.stringify({
  ok: true,
  apiKey: "api-key",
  appId: "app-id",
  projectId: "project-id",
  messagingSenderId: "sender-id",
  vapidKey: "vapid-key",
  fcmToken: "cached-token",
}));
notificationPermission = "default";
pushSubscription = makeSubscription();

const token = await initializeMessaging();

if (token !== "cached-token") {
  throw new Error(`Expected cached token, got ${token}`);
}
if (modalCalls.length !== 0) {
  throw new Error("Permission modal opened despite an existing subscription");
}
if (requestPermissionCalls !== 0) {
  throw new Error("Notification.requestPermission was called");
}
if (getTokenCalls.length !== 0) {
  throw new Error("Firebase getToken was called for cached-token reuse");
}
if (capturedErrors.length !== 0) {
  throw new Error(`Unexpected captured errors: ${capturedErrors.length}`);
}
""",
    )


# @features messaging
# @dimensions hidden-document permission-modal
def test_hidden_default_permission_skips_permission_prompt(run_node):
    run_messaging_check(
        run_node,
        """
document.visibilityState = "hidden";
notificationPermission = "default";
pushSubscription = null;

const token = await initializeMessaging();

if (token !== null) {
  throw new Error(`Expected no token while hidden, got ${token}`);
}
if (modalCalls.length !== 0) {
  throw new Error("Permission modal opened while the document was hidden");
}
if (requestPermissionCalls !== 0) {
  throw new Error("Notification.requestPermission was called while hidden");
}
if (capturedErrors.length !== 0) {
  throw new Error(`Unexpected captured errors: ${capturedErrors.length}`);
}
""",
    )


# @features messaging
# @dimensions unsupported-browser graceful-fallback
def test_unsupported_browser_skips_firebase_messaging(run_node):
    run_messaging_check(
        run_node,
        """
messagingSupported = false;

const token = await initializeMessaging();
await nextTurn();

if (token !== null) {
  throw new Error(`Expected no token on an unsupported browser, got ${token}`);
}
if (configRequestCalls !== 0) {
  throw new Error("Firebase config was requested on an unsupported browser");
}
if (getMessagingCalls !== 0) {
  throw new Error("Firebase messaging was initialized on an unsupported browser");
}
if (capturedErrors.length !== 0) {
  throw new Error(`Unexpected captured errors: ${capturedErrors.length}`);
}
""",
    )


# @features messaging
# @dimensions sentry-context diagnostics
def test_messaging_diagnostics_context_is_sentry_object_shaped(run_node):
    run_messaging_check(
        run_node,
        """
configResponse = { ok: false };
localStorage.clear();

const token = await initializeMessaging();
await nextTurn();
await nextTurn();

if (token !== null) {
  throw new Error(`Expected no token for bad config, got ${token}`);
}
if (capturedErrors.length !== 1) {
  throw new Error(`Expected one captured error, got ${capturedErrors.length}`);
}

const context = capturedErrors[0][2];
if (!context?.firebase_messaging) {
  throw new Error("Missing firebase_messaging context");
}
if (Object.hasOwn(context, "component")) {
  throw new Error("Top-level component context should not be a string");
}
if (context.firebase_messaging.component !== "firebase_messaging") {
  throw new Error("Missing firebase messaging component marker");
}
""",
    )
