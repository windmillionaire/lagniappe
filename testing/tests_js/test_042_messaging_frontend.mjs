import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";

function replaceGlobal(t, name, value) {
	const descriptor = Object.getOwnPropertyDescriptor(globalThis, name);
	Object.defineProperty(globalThis, name, {
		configurable: true,
		writable: true,
		value,
	});
	t.after(() => {
		if (descriptor) Object.defineProperty(globalThis, name, descriptor);
		else delete globalThis[name];
	});
}

/** @matrix mentions : keyboard mouse node-attributes pending-occurrence profile-link query-detection */
test("test_mention_node_collection_insertion_and_keyboard_contract", async () => {
	const searches = [];
	const queryKeys = [];
	class QueryLifecycle {
		invalidate() {}
		destroy() {}
		async run(key, loader, publisher) {
			queryKeys.push(key);
			const response = await loader({ key, signal: null });
			await publisher(response);
			return true;
		}
	}
	const { LagniappeMention, MentionSuggestions, collectMentions } =
		await esmock.strict(
			"../../src/script/elements/editor/extensions/mention.mjs",
			{
				"@floating-ui/dom": {
					autoUpdate: () => () => {},
					computePosition: async () => ({ x: 0, y: 0 }),
					flip: () => null,
					offset: () => null,
					shift: () => null,
				},
				"../../src/script/generated/styles.mjs": { STYLES: { dropdown: {} } },
				"../../src/script/shared/errors.mjs": {
					captureError(error) {
						throw error;
					},
				},
				"../../src/script/shared/queryLifecycle.mjs": { QueryLifecycle },
				"../../src/script/shared/request.mjs": {
					request: {
						async get(endpoint, params) {
							searches.push([endpoint, params.get("q")]);
							return { ok: false };
						},
					},
				},
				"../../src/script/shared/utilities.mjs": {
					debounce(callback) {
						const debounced = (...args) => callback(...args);
						debounced.cancel = () => {};
						return debounced;
					},
					generateElementId: () => "mention-popup",
				},
			},
		);
	const queryEditor = {
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
		view: { dom: { setAttribute() {}, removeAttribute() {} } },
	};
	const querySuggestions = new MentionSuggestions(queryEditor, {
		documentKey: "document-key",
	});
	querySuggestions.popup = { classList: { add() {} }, dataset: {} };
	await querySuggestions.search();
	assert.equal(queryKeys[0], "8:12:Bob", "detects exact query range and value");

	const rendered = LagniappeMention.config.renderHTML({
		HTMLAttributes: {
			occurrenceId: "mention-1234",
			recipient: "recipient-key",
			displayName: "Bob Example",
		},
	});
	assert.deepEqual(
		[
			rendered[0],
			rendered[1]["data-type"],
			rendered[1]["data-mention-id"],
			rendered[1]["data-recipient"],
			rendered[1].occurrenceId,
			rendered[1].recipient,
			rendered[2],
		],
		[
			"span",
			"lagniappe-mention",
			"mention-1234",
			"recipient-key",
			undefined,
			undefined,
			"@Bob Example",
		],
	);
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
	assert.deepEqual(
		collectMentions({
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
		}),
		[
			{
				occurrence_id: "mention-1234",
				recipient: "recipient-key",
				display_name: "Bob Example",
			},
		],
	);
	const inserted = [];
	const pending = [];
	const chain = {
		focus() {
			return this;
		},
		deleteRange(value) {
			inserted.push(["delete", value]);
			return this;
		},
		insertContent(value) {
			inserted.push(["insert", value]);
			return this;
		},
		run() {
			inserted.push(["run"]);
			return true;
		},
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
	assert.equal(inserted[1][1][0].attrs.profilePage, "profile-page-key");
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

	let editorText = "Hello @Absent";
	const dismissedEditor = {
		state: { selection: null },
		view: { dom: { setAttribute() {}, removeAttribute() {} } },
	};
	const setEditorText = (text) => {
		editorText = text;
		dismissedEditor.state.selection = {
			empty: true,
			from: editorText.length + 1,
			$from: {
				parentOffset: editorText.length,
				parent: { textBetween: () => editorText },
			},
		};
	};
	setEditorText(editorText);
	const popupClasses = new Set();
	const dismissed = new MentionSuggestions(dismissedEditor, {
		documentKey: "document-key",
	});
	dismissed.popup = {
		classList: {
			add: (name) => popupClasses.add(name),
			contains: (name) => popupClasses.has(name),
		},
		dataset: {},
	};
	dismissed.active = { query: "Absent", from: 7, to: 14 };
	let escapePrevented = false;
	dismissed._keydown({
		key: "Escape",
		preventDefault: () => {
			escapePrevented = true;
		},
	});
	assert.equal(escapePrevented, true);
	assert.equal(popupClasses.has("hidden"), true);
	setEditorText("Hello @Absent still typing");
	await dismissed.search();
	assert.deepEqual(searches.slice(1), []);
	setEditorText("Hello ");
	await dismissed.search();
	setEditorText("Hello @New");
	await dismissed.search();
	assert.deepEqual(searches.at(-1), ["/l/search-index/user", "New"]);
});

/** @matrix messaging : compose-modal operation-id prefilled-peer selection-focus user-kind */
test("test_message_composer_prefills_peer_and_reuses_operation_on_submit", async (t) => {
	const posts = [];
	const calls = [];
	const formData = new Map([
		["body", "hello"],
		["recipient", "recipient-key"],
	]);
	class FormDataBoundary {
		constructor() {
			this.values = new Map(formData);
		}
		set(key, value) {
			this.values.set(key, value);
		}
		get(key) {
			return this.values.get(key);
		}
	}
	replaceGlobal(t, "FormData", FormDataBoundary);
	replaceGlobal(t, "document", {
		createElement: () => ({ dataset: {}, setAttribute() {} }),
	});
	const { MessageComposer } = await esmock.strict(
		"../../src/script/elements/messageComposer.mjs",
		{
			"../../src/script/generated/styles.mjs": {
				STYLES: {
					modal: { wrapper: "", content: "", header: "", actions: "" },
					button: { close: "", submit: "standard-submit" },
					input: "",
					textarea: "",
				},
			},
			"../../src/script/shared/icons.mjs": {
				createIcon: () => ({ outerHTML: "" }),
			},
			"../../src/script/shared/index.mjs": {
				ENDPOINTS: { messages: { send: "/l/messages" } },
				Modal: class {},
				request: {
					async post(endpoint, data) {
						posts.push([
							endpoint,
							data.get("operation_id"),
							data.get("recipient"),
						]);
						return { ok: true, created: true };
					},
				},
			},
			"../../src/script/elements/combobox/index.mjs": { FacetsBox: class {} },
		},
	);
	const textarea = { value: "hello", focus: () => calls.push("focus-body") };
	const composer = Object.create(MessageComposer.prototype);
	composer.view = { operationId: () => "operation-1234" };
	composer.operationId = null;
	composer.error = {
		textContent: "old",
		classList: { add: () => calls.push("hide-error"), remove() {} },
	};
	composer.recipient = {
		clear: (options) => calls.push(["clear", options.notify]),
		addOption: (option, preload) => calls.push(["peer", option, preload]),
		selectedOptions: [
			{ id: "recipient-page-key", recipient_key: "recipient-key" },
		],
	};
	composer.dialog = {
		showModal: () => calls.push("show"),
		close: () => calls.push("close"),
	};
	composer.confirmation = {
		textContent: "",
		classList: {
			add: () => calls.push("hide-confirmation"),
			remove: () => calls.push("show-confirmation"),
		},
	};
	composer.input = { focus: () => calls.push("focus-input") };
	composer.body = textarea;
	composer.submit = {
		disabled: false,
		querySelector: () => ({ dataset: { visible: "false" } }),
	};
	composer.form = { querySelector: () => textarea };
	composer.onSent = (response) => calls.push(["sent", response.created]);
	composer._activate({ id: "recipient-key", name: "Bob", available: true });
	assert.equal(composer.operationId, "operation-1234");
	assert.ok(calls.some((call) => Array.isArray(call) && call[0] === "peer"));
	composer._recipientUpdated({ detail: { options: { recipient: {} } } });
	assert.ok(calls.includes("focus-body"));
	await composer._submit({ preventDefault: () => calls.push("prevent") });
	assert.deepEqual(posts[0], [
		"/l/messages",
		"operation-1234",
		"recipient-key",
	]);
	assert.ok(calls.some((call) => Array.isArray(call) && call[0] === "sent"));
	assert.equal(composer.confirmation.textContent, "Message sent.");
	assert.ok(calls.includes("show-confirmation"));
	assert.equal(composer.submit.disabled, false);
	const modal = composer._buildModal();
	assert.match(modal.innerHTML, /standard-submit/);
	assert.match(modal.innerHTML, /data-role="icon"/);
});

async function loadNotifications({
	request,
	renderNotificationBadge,
	composer,
}) {
	return await esmock.strict.p("../../src/script/elements/notifications.mjs", {
		"../../src/script/generated/styles.mjs": {
			STYLES: { dropdown: { panel: "", option: { action: "" }, icon: "" } },
		},
		"../../src/script/shared/icons.mjs": {
			createIcon: () => ({ outerHTML: "" }),
		},
		"../../src/script/shared/index.mjs": {
			ENDPOINTS: { notifications: "/l/notifications" },
			request,
		},
		"../../src/script/shared/notificationState.mjs": {
			renderNotificationBadge,
		},
		"../../src/script/shared/transitions.mjs": {
			withTransition: (callback) => callback(),
		},
		"../../src/script/elements/combobox/dropdown.mjs": { Dropdown: class {} },
		"../../src/script/elements/messageComposer.mjs": {
			ensureMessageComposer: composer,
		},
	});
}

/** @matrix notifications : bounded-page exact-count message-ordering */
test("test_notification_menu_keeps_authoritative_aggregate_count", async (t) => {
	replaceGlobal(t, "window", {});
	const rendered = [];
	const actions = [];
	const { Notifications } = await loadNotifications({
		request: {},
		renderNotificationBadge: (count) => rendered.push(count),
		composer: (view) => ({ open: () => actions.push(["compose", view]) }),
	});
	const menu = Object.create(Notifications.prototype);
	menu.view = { name: "view" };
	menu.state = { count: 54 };
	menu.loaded = true;
	menu.stale = false;
	menu.notifications = [
		...Array.from({ length: 25 }, (_, index) => ({ key: `n-${index}` })),
		{ key: "__message_user__", action: "message-user" },
		{ key: "__message_aggregate__", action: "open-messages" },
	];
	menu._updateCount();
	assert.equal(rendered.at(-1), 54);
	const dropdownItems = menu._dropdownItems();
	assert.deepEqual(
		[
			dropdownItems[0]?.action,
			dropdownItems[1]?.action,
			dropdownItems[2]?.key,
			dropdownItems[3]?.key,
		],
		["message-user", "open-messages", "__clear_all_notifications__", "n-0"],
	);
	for (const style of ["border-y", "!rounded-none", "bg-base-bg"]) {
		assert.ok(dropdownItems[2].html.includes(style));
	}
	for (const style of ["-mt-1", "mb-1"]) {
		assert.ok(!dropdownItems[2].html.includes(style));
	}
	let prevented = false;
	await menu._selectNotification(
		{ dataset: { action: "message-user" } },
		{
			preventDefault: () => {
				prevented = true;
			},
		},
	);
	assert.equal(prevented, true);
	assert.deepEqual(actions[0], ["compose", menu.view]);
});

/** @matrix notifications : menu-open reconnect */
test("test_notification_refresh_waits_for_pending_connectivity", async (t) => {
	const windowBoundary = {};
	replaceGlobal(t, "window", windowBoundary);
	const calls = [];
	const html = {};
	const { Notifications } = await loadNotifications({
		request: {
			async get(path) {
				calls.push(path);
				return { ok: true, html };
			},
		},
		renderNotificationBadge() {},
		composer: () => ({}),
	});
	const menu = Object.create(Notifications.prototype);
	menu.view = { online: false };
	menu.dropdown = {};
	menu._optionsFromHtml = (received) => {
		assert.equal(received, html);
		return [{ key: "notification" }];
	};
	const rendered = [];
	menu._updateDropdown = () => rendered.push(menu.notifications);
	let recover;
	windowBoundary.__CONNECTIVITY_READY__ = new Promise((resolve) => {
		recover = resolve;
	});
	const opening = menu.refresh();
	assert.deepEqual(calls, []);
	menu.view.online = true;
	recover();
	assert.equal(await opening, true);
	assert.deepEqual(calls, ["/l/notifications"]);
	assert.equal(menu.loaded, true);
	assert.equal(rendered[0][0].key, "notification");
	menu.view.online = false;
	windowBoundary.__CONNECTIVITY_READY__ = Promise.resolve();
	assert.equal(await menu.refresh(), false);
	assert.equal(calls.length, 1);
	windowBoundary.__CONNECTIVITY_READY__ = new Promise((resolve) => {
		recover = resolve;
	});
	const destroyed = menu.refresh();
	menu.dropdown = null;
	menu.view.online = true;
	recover();
	assert.equal(await destroyed, false);
	assert.equal(calls.length, 1);
});

/** @matrix messaging : active-polling clear-confirmation inline-reply list-race polling-revision preserve-selection read-race responsive-peer-selector selection-race */
test("test_messages_view_refreshes_read_races_and_uses_delete_modal", async (t) => {
	const calls = [];
	const stored = new Map();
	let resolveHistory;
	class FormDataBoundary extends Map {}
	replaceGlobal(t, "FormData", FormDataBoundary);
	replaceGlobal(t, "crypto", { randomUUID: () => "fallback-operation" });
	replaceGlobal(t, "localStorage", {
		getItem: (key) => stored.get(key) || null,
		setItem: (key, value) => stored.set(key, value),
		removeItem: (key) => stored.delete(key),
	});
	const request = {
		async get(endpoint) {
			calls.push(["history-request", endpoint]);
			return new Promise((resolve) => {
				resolveHistory = resolve;
			});
		},
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
	};
	class Core {
		reconcileChange() {
			calls.push(["core-reconcile"]);
		}
	}
	const { default: Messages } = await esmock.strict(
		"../../src/script/views/messages.mjs",
		{
			"../../src/script/elements/messageComposer.mjs": {
				ensureMessageComposer: () => {},
			},
			"../../src/script/generated/styles.mjs": {
				STYLES: { list: { itemHeader: "item-header" } },
			},
			"../../src/script/shared/icons.mjs": {
				createIcon: () => ({ outerHTML: "" }),
			},
			"../../src/script/shared/index.mjs": {
				ENDPOINTS: {
					messages: {
						clearModal: (key) => `/clear/${key}`,
						read: (key) => `/read/${key}`,
						history: (key) => `/history/${key}`,
						send: "/messages",
					},
				},
				request,
			},
			"../../src/script/views/base/core.mjs": { default: Core },
		},
	);
	let pollDescriptor = null;
	let pollHooks = null;
	const pollingView = Object.create(Messages.prototype);
	pollingView.PollingCoordinator = {
		subscribe(descriptor, hooks) {
			pollDescriptor = descriptor;
			pollHooks = hooks;
		},
		boost(id, options) {
			calls.push(["boost", id, options.durationMs, options.pollAfterMs]);
		},
	};
	pollingView.current = { id: "conversation-live" };
	pollingView.preferredConversation = "conversation-live";
	pollingView.conversations = new Map([
		["conversation-live", pollingView.current],
		["conversation-other", { id: "conversation-other", unread: 1 }],
	]);
	pollingView.loadConversations = async () =>
		calls.push(["poll-conversations"]);
	pollingView.openConversation = async (key) =>
		calls.push(["poll-history", key]);
	pollingView._initPollingSubscription();
	assert.deepEqual(
		{
			id: pollDescriptor?.id,
			channel: pollDescriptor?.channel,
			mode: pollHooks?.mode,
			initial: pollHooks?.initial,
		},
		{
			id: "view:channel:messages",
			channel: "messages",
			mode: "periodic",
			initial: "scheduled",
		},
	);
	await pollHooks.onResult({ status: "unchanged" });
	assert.ok(!calls.some((call) => call[0] === "poll-history"));
	await pollHooks.onResult({ status: "changed" });
	assert.ok(calls.some((call) => call[0] === "poll-conversations"));
	assert.ok(
		calls.some(
			(call) => call[0] === "poll-history" && call[1] === "conversation-live",
		),
	);
	assert.ok(
		calls.some(
			(call) => call[0] === "boost" && call[2] === 60_000 && call[3] === 2_000,
		),
	);

	const raceView = Object.create(Messages.prototype);
	raceView.current = { id: "conversation-a", peer: { name: "Peer A" } };
	raceView.preferredConversation = "conversation-a";
	raceView.conversationSelectionRevision = 0;
	raceView.conversations = new Map([
		["conversation-a", raceView.current],
		["conversation-b", { id: "conversation-b", peer: { name: "Peer B" } }],
	]);
	raceView.PollingCoordinator = pollingView.PollingCoordinator;
	let pendingLoads = [];
	let raceOpens = [];
	raceView.loadConversations = () =>
		new Promise((resolve) => pendingLoads.push(resolve));
	raceView.openConversation = async (key, options) => {
		raceOpens.push([key, options]);
		raceView.current = raceView.conversations.get(key);
		raceView.preferredConversation = key;
		return true;
	};
	const sentToOtherConversation = raceView.handleMessageSent({
		conversation: { id: "conversation-b" },
	});
	const pollWhileSending = raceView._refreshMessages();
	pendingLoads.shift()();
	await sentToOtherConversation;
	pendingLoads.shift()();
	await pollWhileSending;
	assert.equal(raceOpens.length, 1);
	assert.equal(raceOpens[0][0], "conversation-a");
	assert.equal(raceView.preferredConversation, "conversation-a");

	raceView.current = raceView.conversations.get("conversation-a");
	raceView.preferredConversation = "conversation-a";
	raceView.conversationSelectionRevision = 0;
	pendingLoads = [];
	raceOpens = [];
	const sentToActiveConversation = raceView.handleMessageSent({
		conversation: { id: "conversation-a" },
	});
	pendingLoads.shift()();
	await sentToActiveConversation;
	assert.deepEqual(
		raceOpens.map(([key]) => key),
		["conversation-a"],
	);

	raceView.current = null;
	raceView.preferredConversation = null;
	raceView.conversationSelectionRevision = 0;
	pendingLoads = [];
	raceOpens = [];
	const firstSentConversation = raceView.handleMessageSent({
		conversation: { id: "conversation-b" },
	});
	const firstConversationPoll = raceView._refreshMessages();
	pendingLoads.shift()();
	await firstSentConversation;
	pendingLoads.shift()();
	await firstConversationPoll;
	assert.equal(raceOpens.length, 2);
	assert.ok(
		raceOpens.every(
			([key, options]) =>
				key === "conversation-b" && options?.selectionRevision === 1,
		),
	);

	raceView.current = raceView.conversations.get("conversation-a");
	raceView.preferredConversation = "conversation-a";
	raceView.conversationSelectionRevision = 0;
	pendingLoads = [];
	raceOpens = [];
	const stalePoll = raceView._refreshMessages();
	const explicitRevision =
		raceView._beginConversationSelection("conversation-b");
	pendingLoads.shift()();
	await stalePoll;
	await raceView.openConversation("conversation-b", {
		selectionRevision: explicitRevision,
	});
	assert.deepEqual(
		raceOpens.map(([key]) => key),
		["conversation-b"],
	);

	const view = Object.create(Messages.prototype);
	view.current = { id: "conversation-a", revision: 7 };
	view.conversationSelectionRevision = 0;
	view.conversations = new Map([["conversation-a", view.current]]);
	view.openConversation = async (key) => calls.push(["refresh", key]);
	view.renderConversations = () => calls.push(["render"]);
	view.renderReply = () => calls.push(["render-reply"]);
	view.history = { replaceChildren: () => calls.push(["empty"]) };
	view.header = { textContent: "" };
	await view.markRead();
	const readIndex = calls.findIndex((call) => call[0] === "read");
	assert.deepEqual(calls.slice(readIndex, readIndex + 2), [
		["read", "/read/conversation-a", "7"],
		["refresh", "conversation-a"],
	]);
	await view.reconcileChange({ type: "delete", key: "conversation-a" });
	assert.equal(view.conversations.has("conversation-a"), false);
	assert.equal(view.current, null);
	assert.ok(calls.some((call) => call[0] === "empty"));

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
		classList: { add() {}, remove() {} },
	};
	view.PollingCoordinator = pollingView.PollingCoordinator;
	view.loadConversations = async () => calls.push(["reload-conversations"]);
	view.openConversation = async (key, options) =>
		calls.push(["open", key, options]);
	await view.sendReply({ preventDefault: () => calls.push(["prevent-reply"]) });
	assert.deepEqual(
		calls.find((call) => call[0] === "reply"),
		[
			"reply",
			"/messages",
			"peer-a",
			"conversation-a",
			"hello back",
			"reply-operation",
		],
	);
	assert.ok(calls.some((call) => call[0] === "focus-reply"));
	assert.deepEqual(
		[view.replySubmit.disabled, view.replySpinner.dataset.visible],
		[false, "false"],
	);
	assert.ok(
		calls.filter(
			(call) => call[0] === "boost" && call[1] === "view:channel:messages",
		).length >= 2,
	);

	view.current = { id: "conversation-a", peer: { name: "Peer" } };
	view.conversationSelectionRevision = 0;
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
		setAttribute: (name, value) =>
			calls.push(["selector-attribute", name, value]),
	};
	view.mobileClearConversation = {
		dataset: {},
		disabled: true,
		setAttribute: (name, value) => calls.push(["clear-attribute", name, value]),
		title: "",
	};
	view.mobileClearConversationContainer = { dataset: { visible: "false" } };
	view.conversationDropdown = {
		updateOptions: (items) => calls.push(["dropdown-items", items]),
	};
	view.renderConversationSelector();
	const dropdownItems = calls.find((call) => call[0] === "dropdown-items")?.[1];
	assert.equal(view.selectorLabel.textContent, "Peer");
	assert.equal(dropdownItems?.[0]?.name, "Peer");
	assert.equal(dropdownItems?.[1]?.name, "Unread Peer (2 unread)");
	assert.equal(view.mobileClearConversation.disabled, false);
	assert.equal(
		view.mobileClearConversation.dataset.deleteModalRoute,
		"/clear/conversation-a",
	);
	assert.equal(view.mobileClearConversationContainer.dataset.visible, "true");
	dropdownItems[1].onClick();
	assert.ok(
		calls.some(
			(call) =>
				call[0] === "open" &&
				call[1] === "conversation-b" &&
				call[2]?.selectionRevision === 1,
		),
	);
	assert.equal(view.conversationSelectionRevision, 1);

	const staleView = Object.create(Messages.prototype);
	staleView.current = null;
	staleView.conversationSelectionRevision = 0;
	const staleOpen = staleView.openConversation("conversation-stale", {
		selectionRevision: 0,
	});
	staleView.conversationSelectionRevision = 1;
	resolveHistory({
		ok: true,
		conversation: { id: "conversation-stale", peer: { name: "Stale Peer" } },
		messages: [],
	});
	assert.equal(await staleOpen, false);
	assert.equal(staleView.current, null);

	const listView = Object.create(Messages.prototype);
	listView.conversationListRevision = 0;
	listView.conversationCursor = null;
	listView.conversations = new Map();
	const listRenders = [];
	listView.renderConversations = () =>
		listRenders.push([...listView.conversations.keys()]);
	const listResolvers = [];
	request.get = async () =>
		new Promise((resolve) => listResolvers.push(resolve));
	const olderList = listView.loadConversations();
	const newerList = listView.loadConversations();
	listResolvers[1]({
		ok: true,
		conversations: [{ id: "conversation-new" }],
		cursor: null,
	});
	await newerList;
	listResolvers[0]({
		ok: true,
		conversations: [{ id: "conversation-old" }],
		cursor: null,
	});
	await olderList;
	assert.deepEqual([...listView.conversations.keys()], ["conversation-new"]);
	assert.deepEqual(listRenders, [["conversation-new"]]);

	view.conversationStorageKey = "messages-user-a-active";
	view.rememberConversation("conversation-b");
	assert.equal(view.preferredConversation, "conversation-b");
	assert.equal(stored.get("messages-user-a-active"), "conversation-b");
	view.current = null;
	view.preferredConversation = null;
	view.conversations.clear();
	view.renderConversationSelector();
	assert.equal(view.selectorLabel.textContent, "");
	assert.equal(view.mobileClearConversation.disabled, true);
	assert.ok(
		calls.some(
			(call) =>
				call[0] === "selector-class" &&
				call[1] === "hidden" &&
				call[2] === true,
		),
	);
	assert.equal(view.mobileClearConversationContainer.dataset.visible, "false");
});
