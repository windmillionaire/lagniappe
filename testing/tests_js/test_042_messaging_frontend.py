"""Node-backed contracts for messaging, mentions, and aggregate badges."""

import textwrap


# @pairs mentions:node-attributes mentions:pending-occurrence mentions:query-detection
# @pairs mentions:keyboard mentions:mouse
# @pair mentions:profile-link
# @source src/script/elements/editor/extensions/mention.mjs::LagniappeMention
# @source src/script/elements/editor/extensions/mention.mjs::MentionSuggestions
# @source src/script/elements/editor/extensions/mention.mjs::collectMentions
def test_mention_node_collection_insertion_and_keyboard_contract(run_node):
    run_node(
        textwrap.dedent(
            r"""
            import assert from "node:assert/strict";
            import fs from "node:fs";
            import vm from "node:vm";
            import { Node, mergeAttributes } from "@tiptap/core";

            const context = {
              Node,
              mergeAttributes,
              request: {},
              console,
              crypto: globalThis.crypto,
            };
            context.globalThis = context;
            vm.createContext(context);
            let source = fs.readFileSync(
              "src/script/elements/editor/extensions/mention.mjs",
              "utf8",
            );
            source = source.replace(/^import[\s\S]*?;\r?\n/gm, "");
            source = source.replace(/export const /g, "const ");
            source = source.replace("export class MentionSuggestions", "class MentionSuggestions");
            source += `
              globalThis.LagniappeMention = LagniappeMention;
              globalThis.MentionSuggestions = MentionSuggestions;
              globalThis.collectMentions = collectMentions;
              globalThis.currentQuery = currentQuery;
            `;
            vm.runInContext(source, context);
            const { LagniappeMention, MentionSuggestions, collectMentions } = context;

            assert.deepEqual(
              { ...context.currentQuery({
                state: {
                  selection: {
                    empty: true,
                    from: 12,
                    $from: {
                      parentOffset: 12,
                      parent: { textBetween: () => "Hello @Bob" },
                    },
                  },
                },
              }) },
              { query: "Bob", from: 8, to: 12 },
            );

            const rendered = LagniappeMention.config.renderHTML({
              HTMLAttributes: {
                occurrenceId: "mention-1234",
                recipient: "recipient-key",
                displayName: "Bob Example",
              },
            });
            assert.equal(rendered[0], "span");
            assert.equal(rendered[1]["data-type"], "lagniappe-mention");
            assert.equal(rendered[1]["data-mention-id"], "mention-1234");
            assert.equal(rendered[1]["data-recipient"], "recipient-key");
            assert.equal(rendered[1].occurrenceId, undefined);
            assert.equal(rendered[1].recipient, undefined);
            assert.equal(rendered[2], "@Bob Example");

            const linked = LagniappeMention.config.renderHTML({
              HTMLAttributes: {
                occurrenceId: "mention-linked",
                recipient: "recipient-key",
                displayName: "Bob Example",
                profilePage: "profile-page-key",
              },
            });
            assert.equal(linked[0], "a");
            assert.equal(linked[1]["data-profile-page"], "profile-page-key");
            assert.equal(linked[1].href, "/pages/profile-page-key");
            assert.match(linked[1].class, /bg-user-bg/);

            assert.equal(
              JSON.stringify(collectMentions({
                type: "doc",
                content: [
                  {
                    type: "paragraph",
                    content: [
                      {
                        type: "lagniappeMention",
                        attrs: {
                          occurrenceId: "mention-1234",
                          recipient: "recipient-key",
                          displayName: "Bob Example",
                        },
                      },
                      { type: "lagniappeMention", attrs: {} },
                    ],
                  },
                ],
              })),
              JSON.stringify([
                {
                  occurrence_id: "mention-1234",
                  recipient: "recipient-key",
                  display_name: "Bob Example",
                },
              ]),
            );

            const inserted = [];
            const pending = [];
            const chain = {
              focus() { return this; },
              deleteRange(value) { inserted.push(["delete", value]); return this; },
              insertContent(value) { inserted.push(["insert", value]); return this; },
              run() { inserted.push(["run"]); return true; },
            };
            const suggestions = new MentionSuggestions(
              { chain: () => chain },
              {
                documentKey: "document-key",
                onInsert: (mention) => pending.push(mention),
              },
            );
            suggestions.active = { from: 4, to: 8 };
            suggestions.hide = () => inserted.push(["hide"]);
            suggestions.insert({
              dataset: {
                id: "profile-page-key",
                details: JSON.stringify({ recipient_key: "recipient-key" }),
                name: "Bob Example",
              },
            });
            assert.equal(pending.length, 1);
            assert.equal(pending[0].recipient, "recipient-key");
            assert.equal(pending[0].display_name, "Bob Example");
            assert.ok(pending[0].occurrence_id);
            assert.equal(inserted[1][1][0].type, "lagniappeMention");
            assert.equal(
              inserted[1][1][0].attrs.profilePage,
              "profile-page-key",
            );

            const keys = [];
            suggestions.popup = { classList: { contains: () => false } };
            suggestions.options = [{ id: 1 }, { id: 2 }];
            suggestions.focused = 0;
            suggestions.render = () => keys.push("render");
            suggestions.insert = (option) => keys.push(option.id);
            suggestions._keydown({
              key: "ArrowDown",
              preventDefault: () => keys.push("prevent"),
            });
            suggestions._keydown({
              key: "Enter",
              preventDefault: () => keys.push("prevent"),
            });
            suggestions._click({
              target: { closest: () => ({ dataset: { index: "0" } }) },
            });
            assert.deepEqual(keys, ["prevent", "render", "prevent", 2, 1]);
            """
        ),
        module=True,
    )


# @pairs messaging:compose-modal messaging:prefilled-peer messaging:operation-id
# @pairs messaging:user-kind messaging:selection-focus
# @source src/script/elements/messageComposer.mjs::MessageComposer
# @source src/script/elements/messageComposer.mjs::ensureMessageComposer
def test_message_composer_prefills_peer_and_reuses_operation_on_submit(run_node):
    run_node(
        r"""
(async () => {
const fs = require("node:fs");
const vm = require("node:vm");

const posts = [];
const context = {
  console,
  crypto: { randomUUID: () => "fallback-operation" },
  clearTimeout: () => {},
  setTimeout: (callback) => { calls.push("confirmation-timer"); return callback; },
  FacetsBox: class {},
  STYLES: {
    modal: { wrapper: "modal-wrapper", content: "modal-content", header: "modal-header" },
    button: { close: "close-button" },
    input: "input",
    textarea: "textarea",
  },
  Modal: class {},
  ENDPOINTS: { messages: { send: "/l/messages" } },
  request: {
    async post(endpoint, data) {
      posts.push([endpoint, data.get("operation_id"), data.get("recipient")]);
      return { ok: true, created: true };
    },
  },
  FormData,
};
context.globalThis = context;
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/messageComposer.mjs", "utf8");
source = source.replace(/^import .*;$/gm, "");
source = source.replace("export class MessageComposer", "class MessageComposer");
source = source.replace("export const ensureMessageComposer", "const ensureMessageComposer");
source += "\nglobalThis.MessageComposer = MessageComposer;";
vm.runInContext(source, context);

const calls = [];
const textarea = { value: "hello", focus: () => calls.push("focus-body") };
const formData = new Map([["body", "hello"], ["recipient", "recipient-key"]]);
context.FormData = class {
  constructor() { this.values = new Map(formData); }
  set(key, value) { this.values.set(key, value); }
  get(key) { return this.values.get(key); }
};
const composer = Object.create(context.MessageComposer.prototype);
composer.view = { operationId: () => "operation-1234" };
composer.operationId = null;
composer.error = {
  textContent: "old",
  classList: { add: () => calls.push("hide-error"), remove: () => {} },
};
composer.recipient = {
  clear: (options) => calls.push(["clear", options.notify]),
  addOption: (option, preload) => calls.push(["peer", option, preload]),
  selectedOptions: [{ id: "recipient-page-key", recipient_key: "recipient-key" }],
};
composer.dialog = {
  showModal: () => calls.push("show"),
  close: () => calls.push("close"),
};
composer.confirmation = {
  textContent: "",
  classList: { add: () => calls.push("hide-confirmation"), remove: () => calls.push("show-confirmation") },
};
composer.input = { focus: () => calls.push("focus-input") };
composer.body = textarea;
composer.submit = {
  disabled: false,
  querySelector: () => ({ dataset: { visible: "false" } }),
};
composer.form = {
  querySelector: () => textarea,
};
composer.onSent = (response) => calls.push(["sent", response.created]);

composer._activate({ id: "recipient-key", name: "Bob", available: true });
if (composer.operationId !== "operation-1234") throw new Error("operation not allocated");
if (!calls.some((call) => Array.isArray(call) && call[0] === "peer")) {
  throw new Error("peer was not prefilled");
}
composer._recipientUpdated({ detail: { options: { recipient: {} } } });
if (!calls.includes("focus-body")) throw new Error("selection did not focus body");
await composer._submit({ preventDefault: () => calls.push("prevent") });
if (posts[0][1] !== "operation-1234" || posts[0][2] !== "recipient-key") {
  throw new Error(`unexpected submit: ${JSON.stringify(posts)}`);
}
if (!calls.some((call) => Array.isArray(call) && call[0] === "sent")) {
  throw new Error("success callback not invoked");
}
if (composer.confirmation.textContent !== "Message sent." || !calls.includes("show-confirmation")) {
  throw new Error("success confirmation was not shown");
}
if (composer.submit.disabled) throw new Error("submit button stayed disabled");
if (!source.includes("STYLES.button.submit") || !source.includes("data-role=\"icon\"")) {
  throw new Error("composer did not use the standard spinner submit control");
}
})().catch((error) => { console.error(error); process.exit(1); });
""",
    )


# @pairs notifications:exact-count notifications:bounded-page
# @source src/script/elements/notifications.mjs::Notifications
def test_notification_menu_keeps_authoritative_aggregate_count(run_node):
    run_node(
        r"""
(async () => {
const fs = require("node:fs");
const vm = require("node:vm");

const rendered = [];
const actions = [];
const context = {
  console,
  renderNotificationBadge: (count) => rendered.push(count),
  STYLES: { dropdown: { panel: "", option: { action: "" }, icon: "" } },
  ENDPOINTS: {},
  request: {},
  createIcon: () => ({ outerHTML: "" }),
  withTransition: () => {},
  ensureMessageComposer: (view) => ({
    open: () => actions.push(["compose", view]),
  }),
  Dropdown: class {},
  window: {},
  document: {},
};
context.globalThis = context;
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/notifications.mjs", "utf8");
source = source.replace(/^import .*;$/gm, "");
source = source.replace("export class Notifications", "class Notifications");
source = source.replace(
  'const { ensureMessageComposer } = await import("./messageComposer");',
  "const { ensureMessageComposer } = globalThis;",
);
source += "\nglobalThis.Notifications = Notifications;";
vm.runInContext(source, context);

const menu = Object.create(context.Notifications.prototype);
menu.view = { name: "view" };
menu.state = { count: 54 };
menu.loaded = true;
menu.stale = false;
menu.notifications = [
  ...Array.from({ length: 25 }, (_, index) => ({ key: `n-${index}` })),
  { key: "__message_user__", action: "message-user" },
];
menu._updateCount();
if (rendered.at(-1) !== 54) {
  throw new Error(`bounded menu replaced exact count: ${rendered.at(-1)}`);
}
const dropdownItems = menu._dropdownItems();
if (
  dropdownItems[0]?.action !== "message-user" ||
  dropdownItems[1]?.key !== "__clear_all_notifications__" ||
  dropdownItems[2]?.key !== "n-0"
) {
  throw new Error(`unexpected notification action order: ${JSON.stringify(dropdownItems)}`);
}
for (const style of ["-mt-1", "border-y", "bg-base-bg"]) {
  if (!dropdownItems[1].html.includes(style)) {
    throw new Error(`clear action is missing ${style}: ${dropdownItems[1].html}`);
  }
}
if (dropdownItems[1].html.includes("mb-1")) {
  throw new Error(`clear action retained a bottom gap: ${dropdownItems[1].html}`);
}
let prevented = false;
await menu._selectNotification(
  { dataset: { action: "message-user" } },
  { preventDefault: () => { prevented = true; } },
);
if (!prevented || actions[0]?.[0] !== "compose" || actions[0]?.[1] !== menu.view) {
  throw new Error("notification compose action was not forwarded to the modal");
}
})().catch((error) => { console.error(error); process.exit(1); });
"""
    )


# @pairs messaging:read-race messaging:clear-confirmation messaging:inline-reply
# @pair messaging:responsive-peer-selector
# @source src/script/views/messages.mjs::Messages
def test_messages_view_refreshes_read_races_and_uses_delete_modal(run_node):
    run_node(
        r"""
(async () => {
const fs = require("node:fs");
const vm = require("node:vm");

const calls = [];
const stored = new Map();
const context = {
  console,
  Core: class { reconcileChange() { calls.push(["core-reconcile"]); } },
  ensureMessageComposer: () => {},
  STYLES: { list: { itemHeader: "item-header" } },
  ENDPOINTS: {
    messages: {
      clearModal: (key) => "/clear/" + key,
      read: (key) => `/read/${key}`,
      send: "/messages",
    },
  },
  request: {
    async post(endpoint, data) {
      if (endpoint === "/messages") {
        calls.push([
          "reply",
          endpoint,
          data.get("recipient"),
          data.get("conversation"),
          data.get("body"),
          data.get("operation_id"),
        ]);
        return { ok: true, conversation: { id: "conversation-a" } };
      }
      calls.push(["read", endpoint, data.get("revision")]);
      return { ok: false, conversation: { revision: 8 } };
    },
  },
  FormData,
  crypto: { randomUUID: () => "fallback-operation" },
  localStorage: {
    getItem: (key) => stored.get(key) || null,
    setItem: (key, value) => stored.set(key, value),
    removeItem: (key) => stored.delete(key),
  },
  document: {},
};
context.globalThis = context;
vm.createContext(context);
let source = fs.readFileSync("src/script/views/messages.mjs", "utf8");
source = source.replace(/^import .*;$/gm, "");
source = source.replace("export default class Messages", "class Messages");
source += "\nglobalThis.Messages = Messages;";
vm.runInContext(source, context);

const view = Object.create(context.Messages.prototype);
view.current = { id: "conversation-a", revision: 7 };
view.conversations = new Map([["conversation-a", view.current]]);
view.openConversation = async (key) => calls.push(["refresh", key]);
view.renderConversations = () => calls.push(["render"]);
view.renderReply = () => calls.push(["render-reply"]);
view.history = { replaceChildren: () => calls.push(["empty"]) };
view.header = { textContent: "" };

await view.markRead();
if (JSON.stringify(calls.slice(0, 2)) !== JSON.stringify([
  ["read", "/read/conversation-a", "7"],
  ["refresh", "conversation-a"],
])) throw new Error(`read race did not refresh: ${JSON.stringify(calls)}`);

await view.reconcileChange({ type: "delete", key: "conversation-a" });
if (view.conversations.has("conversation-a") || view.current !== null) {
  throw new Error("delete-modal reconciliation retained the cleared conversation");
}
if (!calls.some((call) => call[0] === "empty")) {
  throw new Error("cleared conversation history was not emptied");
}
if (
  source.includes("window.confirm") ||
  !source.includes("deleteModalRoute") ||
  !source.includes('setAttribute("lp-control", "delete")')
) {
  throw new Error("conversation clearing does not use the shared delete modal");
}

view.current = {
  id: "conversation-a",
  peer: { id: "peer-a", name: "Peer", replyable: true },
};
view.replyOperationId = "reply-operation";
view.replyTextarea = {
  value: "hello back",
  focus: () => calls.push(["focus-reply"]),
};
view.replySubmit = { disabled: false };
view.replySpinner = { dataset: { visible: "false" } };
view.replyError = {
  textContent: "",
  classList: { add: () => {}, remove: () => {} },
};
view.loadConversations = async () => calls.push(["reload-conversations"]);
view.openConversation = async (key) => calls.push(["open", key]);
await view.sendReply({ preventDefault: () => calls.push(["prevent-reply"]) });
const reply = calls.find((call) => call[0] === "reply");
if (JSON.stringify(reply) !== JSON.stringify([
  "reply",
  "/messages",
  "peer-a",
  "conversation-a",
  "hello back",
  "reply-operation",
])) throw new Error(`unexpected reply: ${JSON.stringify(reply)}`);
if (!source.includes("sendReply(") || !calls.some((call) => call[0] === "focus-reply")) {
  throw new Error("messages view did not complete the inline reply flow");
}
if (view.replySubmit.disabled || view.replySpinner.dataset.visible !== "false") {
  throw new Error("reply submit state was not restored");
}
view.current = {
  id: "conversation-a",
  peer: { name: "Peer" },
};
view.conversations = new Map([
  ["conversation-a", view.current],
  [
    "conversation-b",
    { id: "conversation-b", peer: { name: "Unread Peer" }, unread: 2 },
  ],
]);
view.selectorLabel = { textContent: "" };
view.selector = {
  classList: {
    toggle: (name, force) => calls.push(["selector-class", name, force]),
  },
  setAttribute: (name, value) => calls.push(["selector-attribute", name, value]),
};
view.mobileClearConversation = {
  dataset: {},
  disabled: true,
  setAttribute: (name, value) => calls.push(["clear-attribute", name, value]),
  title: "",
};
view.mobileClearConversationContainer = {
  dataset: { visible: "false" },
};
view.conversationDropdown = {
  updateOptions: (items) => calls.push(["dropdown-items", items]),
};
view.renderConversationSelector();
const dropdownItems = calls.find((call) => call[0] === "dropdown-items")?.[1];
if (
  view.selectorLabel.textContent !== "Peer" ||
  dropdownItems?.[0]?.name !== "Peer" ||
  dropdownItems?.[1]?.name !== "Unread Peer (2 unread)" ||
  view.mobileClearConversation.disabled ||
  view.mobileClearConversation.dataset.deleteModalRoute !==
    "/clear/conversation-a" ||
  view.mobileClearConversationContainer.dataset.visible !== "true"
) {
  throw new Error("messages view did not render its responsive conversation controls");
}
dropdownItems[1].onClick();
if (!calls.some((call) => call[0] === "open" && call[1] === "conversation-b")) {
  throw new Error("messages dropdown did not open the selected conversation");
}
view.conversationStorageKey = "messages-user-a-active";
view.rememberConversation("conversation-b");
if (
  view.preferredConversation !== "conversation-b" ||
  stored.get("messages-user-a-active") !== "conversation-b"
) {
  throw new Error("messages view did not persist the selected conversation");
}
view.current = null;
view.preferredConversation = null;
view.conversations.clear();
view.renderConversationSelector();
if (
  view.selectorLabel.textContent !== "" ||
  !view.mobileClearConversation.disabled ||
  !calls.some(
    (call) =>
      call[0] === "selector-class" && call[1] === "hidden" && call[2] === true,
  ) ||
  view.mobileClearConversationContainer.dataset.visible !== "false"
) {
  throw new Error("empty messages view did not hide its unselected dropdown");
}
if (!source.includes('../elements/combobox/dropdown')) {
  throw new Error("messages view does not use the shared dropdown combobox");
}
})().catch((error) => { console.error(error); process.exit(1); });
""",
    )
