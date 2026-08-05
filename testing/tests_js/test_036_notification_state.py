"""Node-backed checks for notification projection delivery."""


# @features notifications
# @dimensions badge redis-projection cold-seed response-header
def test_notification_state_updates_badge_and_reports_cache_miss(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const events = [];
const button = {
  dataset: { visible: "false" },
  attributes: {},
  setAttribute(name, value) { this.attributes[name] = value; },
};
const count = { textContent: "0" };
const context = {
  console,
  CustomEvent: class {
    constructor(type, options = {}) {
      this.type = type;
      this.detail = options.detail;
    }
  },
  document: {
    querySelector(selector) {
      if (selector === "[data-role='notifications']") return button;
      if (selector === "[data-role='notification-count']") return count;
      return null;
    },
  },
  window: {
    dispatchEvent(event) { events.push(event); },
  },
};
context.globalThis = context;
vm.createContext(context);
let source = fs.readFileSync(
  "src/script/shared/notificationState.mjs",
  "utf8",
);
source = source.replace(/export const /g, "const ");
source += `
globalThis.applyNotificationState = applyNotificationState;
globalThis.applyNotificationStateHeader = applyNotificationStateHeader;
`;
vm.runInContext(source, context);

const miss = context.applyNotificationState(
  '{"generation":null,"revision":null,"count":null}',
);
if (!miss?.miss || button.dataset.visible !== "false" || count.textContent !== "0") {
  throw new Error("A cache miss did not preserve the last rendered badge");
}

const applied = context.applyNotificationStateHeader({
  get(name) {
    return name === "X-Lagniappe-Notification-State"
      ? '{"generation":"generation-a","revision":4,"count":3}'
      : null;
  },
});
if (
  applied?.miss ||
  context.window.__NOTIFICATION_STATE__?.revision !== 4 ||
  count.textContent !== "3" ||
  button.dataset.visible !== "true" ||
  button.attributes["aria-label"] !== "Notifications: 3"
) {
  throw new Error("Warm notification state did not update the badge");
}
if (events.length !== 2 || events.at(-1).detail.count !== 3) {
  throw new Error("Notification state was not published to lazy consumers");
}

const before = context.window.__NOTIFICATION_STATE__;
if (context.applyNotificationState('{"revision":"bad"}') !== null ||
    context.window.__NOTIFICATION_STATE__ !== before) {
  throw new Error("Invalid notification state replaced the accepted cursor");
}
"""
    )
