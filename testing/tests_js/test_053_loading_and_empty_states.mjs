import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser, useClock } from "../utility/js/environment.mjs";

function installMatchMedia() {
	window.matchMedia = () => ({
		matches: false,
		addEventListener() {},
		removeEventListener() {},
	});
}

test("test_entity_index_loading_skeleton_skips_fast_loads_and_shows_after_delay", async (t) => {
	createBrowser(t, {
		html: `
			<div lp-view data-index="tasks">
				<table id="table" lp-component lp-prefetch>
					<thead>
						<tr>
							<th data-column="name">Name</th>
							<th data-column="due_date">Due Date</th>
							<th data-column="selector"></th>
						</tr>
					</thead>
					<tbody data-widget="IndexTable" lp-prefetch data-route="/tasks/rows">
						<tr data-role="empty" data-visible="false"><td colspan="3">No tasks created yet</td></tr>
					</tbody>
				</table>
			</div>
		`,
	});
	installMatchMedia();
	const clock = useClock(t);
	const { default: EntityIndex, INDEX_LOADING_DELAY_MS } = await import(
		"../../src/script/views/base/index.ts"
	);
	const { IndexTable } = await import(
		"../../src/script/widgets/tables/indexTable.ts"
	);

	const root = document.querySelector("[lp-view]");
	const tableElt = document.querySelector("#table");
	const tbody = document.querySelector("tbody");
	const view = new EntityIndex(root);
	let indexTable = null;
	try {
		// Fast load: rows arrive before the grace delay — skeleton must never appear.
		view._scheduleTableLoading(tableElt);
		clock.tick(INDEX_LOADING_DELAY_MS - 50);
		assert.equal(tbody.querySelector("tr[data-role='loading']"), null);
		assert.equal(tbody.getAttribute("aria-busy"), null);

		indexTable = new IndexTable({
			component: {
				elt: tableElt,
				name: "table",
				widgets: {},
				loadWidget: async () => null,
			},
			view,
			target: tbody,
			name: "IndexTable",
		});
		const row = document.createElement("tr");
		row.setAttribute("lp-entity", "");
		row.dataset.key = "task-1";
		indexTable._updated = [row];
		indexTable.postreconcile();
		clock.tick(INDEX_LOADING_DELAY_MS + 100);
		assert.equal(
			tbody.querySelector("tr[data-role='loading']"),
			null,
			"Fast/cached load should never show the loading skeleton",
		);

		// Slow load: empty table waiting past the grace delay reveals the skeleton,
		// then clears as soon as rows arrive.
		row.remove();
		tbody.removeAttribute("loaded");
		view._scheduleTableLoading(tableElt);
		clock.tick(INDEX_LOADING_DELAY_MS);
		// Allow the dynamic STYLES import to resolve.
		for (let i = 0; i < 10; i += 1) {
			await new Promise((resolve) => setImmediate(resolve));
			if (tbody.querySelector("tr[data-role='loading']")) break;
		}

		const loadingRows = tbody.querySelectorAll("tr[data-role='loading']");
		assert.equal(
			loadingRows.length,
			1,
			"Slow load should render a single low-key loading row",
		);
		assert.equal(tbody.getAttribute("aria-busy"), "true");
		const loadingCell = loadingRows[0].querySelector("td");
		assert.equal(loadingCell?.colSpan, 3);
		assert.equal(loadingCell?.getAttribute("role"), "status");
		assert.equal(loadingCell?.textContent, "Loading…");

		const lateRow = document.createElement("tr");
		lateRow.setAttribute("lp-entity", "");
		lateRow.dataset.key = "task-2";
		indexTable._updated = [lateRow];
		indexTable.postreconcile();

		assert.equal(
			tbody.querySelector("tr[data-role='loading']"),
			null,
			"Loading skeleton should clear as soon as the first batch arrives",
		);
		assert.equal(tbody.getAttribute("aria-busy"), null);
	} finally {
		indexTable?.destroy();
		view.destroy();
	}
});

test("test_home_notes_empty_state_shows_hint_and_restores_on_last_delete", async (t) => {
	createBrowser(t, {
		html: `
			<div id="notes" lp-component>
				<ul data-widget="HomeActivityList" data-visible="false" loaded>
					<li data-role="empty">No notes yet — use + to add a quick note.</li>
				</ul>
			</div>
		`,
	});
	const { HomeActivityList } = await import(
		"../../src/script/widgets/home/activity.ts"
	);
	const listElt = document.querySelector("ul");
	const component = { elt: document.querySelector("#notes"), name: "notes" };
	let synced = 0;
	const widget = new HomeActivityList({
		target: listElt,
		name: "HomeActivityList",
		component,
		view: {
			online: true,
			addFlash() {},
			syncHomeSectionState() {
				synced += 1;
			},
		},
		visible: true,
	});
	component.active = widget;
	t.after(() => widget.destroy());

	// Opening an empty Notes section renders visible with the empty-state hint.
	widget.postreconcile();
	assert.equal(listElt.dataset.visible, "true");
	assert.ok(listElt.querySelector("li[data-role='empty']"));

	// Creating a note removes the empty-state hint.
	const note = document.createElement("li");
	note.dataset.key = "offline:note-1";
	note.textContent = "Quick reminder";
	widget._created = [note];
	widget.postreconcile();
	assert.equal(listElt.querySelector("li[data-role='empty']"), null);
	assert.equal(listElt.querySelectorAll("li").length, 1);

	// Deleting the last note restores the empty-state hint instead of hiding.
	widget._commitRemoveItem(note);
	assert.equal(listElt.dataset.visible, "true");
	assert.match(
		listElt.querySelector("li[data-role='empty']")?.textContent ?? "",
		/No notes yet/,
	);
	assert.equal(synced, 1);
});

test("test_notifications_empty_popover_opens_for_zero_notifications", async (t) => {
	createBrowser(t, {
		html: `
			<button type="button" data-role="notifications" data-visible="true">
				<span data-role="notification-count">0</span>
			</button>
		`,
	});
	installMatchMedia();
	const prevIO = globalThis.IntersectionObserver;
	globalThis.IntersectionObserver = class {
		observe() {}
		disconnect() {}
	};
	window.IntersectionObserver = globalThis.IntersectionObserver;
	t.after(() => {
		globalThis.IntersectionObserver = prevIO;
	});
	const { Combobox } = await esmock.strict(
		"../../src/script/elements/combobox/combobox.ts",
		{
			"@floating-ui/dom": {
				autoUpdate: (_ref, _panel, update) => {
					update();
					return () => {};
				},
				computePosition: async () => ({ x: 10, y: 20 }),
				flip: () => null,
				offset: () => null,
				shift: () => null,
			},
			"../../src/script/generated/styles.mjs": {
				STYLES: { dropdown: { panel: "panel", option: { multiple: "" } } },
			},
			"../../src/script/shared/errors.ts": {
				captureError(error) {
					throw error;
				},
			},
			"../../src/script/shared/utilities.ts": {
				generateElementId: () => "notif-combo",
			},
			"../../src/script/elements/primitives.ts": { primitives: {} },
		},
	);
	const { Dropdown } = await esmock.strict(
		"../../src/script/elements/combobox/dropdown.ts",
		{
			"../../src/script/elements/combobox/combobox.ts": { Combobox },
			"../../src/script/generated/styles.mjs": {
				STYLES: { dropdown: { option: { action: "action" }, icon: "icon" } },
			},
			"../../src/script/shared/icons.ts": { setIcon() {} },
		},
	);

	let serverHtml = "";
	const { Notifications } = await esmock.strict(
		"../../src/script/elements/notifications.ts",
		{
			"../../src/script/generated/styles.mjs": {
				STYLES: {
					dropdown: {
						panel: "panel",
						option: { action: "action" },
						icon: "icon",
						empty: "empty-row",
						emptyWithAction: "empty-row-border",
					},
				},
			},
			"../../src/script/shared/icons.ts": {
				createIcon: () => ({ outerHTML: "" }),
			},
			"../../src/script/shared/index.ts": {
				ENDPOINTS: { notifications: "/l/notifications" },
				request: {
					async get() {
						return {
							ok: true,
							html:
								serverHtml === ""
									? ""
									: new DOMParser().parseFromString(serverHtml, "text/html"),
						};
					},
				},
			},
			"../../src/script/shared/notificationState.ts": {
				renderNotificationBadge() {},
			},
			"../../src/script/shared/transitions.ts": {
				withTransition: (callback) => callback(),
			},
			"../../src/script/elements/combobox/dropdown.ts": { Dropdown },
			"../../src/script/elements/messageComposer.ts": {
				ensureMessageComposer: () => ({ open() {} }),
			},
		},
	);

	const notifications = new Notifications({ online: true });
	notifications.init();
	try {
		// Zero notifications & no messaging permission: popover opens with dialog semantics and status message.
		const openedEmpty = await notifications.dropdown.showPanel();
		assert.equal(openedEmpty, true);
		assert.equal(notifications.button?.getAttribute("role"), null);
		assert.equal(notifications.button?.getAttribute("aria-haspopup"), "dialog");
		assert.equal(notifications.dropdown.panel?.getAttribute("role"), "dialog");
		assert.equal(notifications.dropdown.panel?.dataset.visible, "true");
		assert.equal(
			notifications.dropdown.panel?.querySelectorAll("[role='group']").length,
			0,
		);
		assert.equal(
			notifications.dropdown.panel?.querySelector("[data-role='empty']")
				?.textContent,
			"No unread notifications",
		);

		// Zero notifications & messaging permission: shows Message a user + empty status.
		serverHtml =
			'<button role="option" type="button" data-key="__message_user__" data-action="message-user">Message a user</button>';
		await notifications.refresh();
		assert.equal(
			notifications.dropdown.panel?.querySelectorAll("[role='group']").length,
			1,
		);
		assert.equal(
			notifications.dropdown.panel?.querySelector("[data-role='empty']")
				?.className,
			"empty-row-border",
		);

		// Real notification present: empty notice disappears.
		serverHtml =
			'<div role="option" data-key="notif-1">Task assigned to you</div>';
		await notifications.refresh();
		assert.equal(
			notifications.dropdown.panel?.querySelector("[data-role='empty']"),
			null,
		);
	} finally {
		notifications.destroy();
	}
});

test("test_messages_empty_pane_prompts_and_opens_composer", async (t) => {
	createBrowser(t, {
		html: `
			<div lp-view data-kind="messages" data-current-user="user-1">
				<button type="button" data-action="compose-message">+</button>
				<button type="button" data-role="conversation-selector">
					<span data-role="conversation-selector-label"></span>
				</button>
				<span data-role="mobile-clear-conversation-container">
					<button type="button" data-role="mobile-clear-conversation"></button>
				</span>
				<div data-role="conversation-list"></div>
				<button type="button" data-action="load-conversations" class="hidden"></button>
				<div data-role="message-header">Choose a conversation</div>
				<div data-role="message-history"></div>
				<button type="button" data-action="load-messages" class="hidden"></button>
				<form data-role="message-reply" class="hidden">
					<textarea name="body"></textarea>
					<p data-role="message-reply-error" class="hidden"></p>
					<button type="submit"><span data-role="icon"></span></button>
				</form>
			</div>
		`,
	});
	let composerOpened = 0;
	class CoreStub {
		constructor(elt) {
			this.elt = elt;
			this.mobile = false;
		}
		async init() {
			return this;
		}
		destroy() {}
	}
	const { default: Messages } = await esmock.strict(
		"../../src/script/views/messages.ts",
		{
			"../../src/script/elements/messageComposer.ts": {
				ensureMessageComposer: () => ({
					open() {
						composerOpened += 1;
					},
				}),
			},
			"../../src/script/generated/styles.mjs": {
				STYLES: {
					list: { itemHeader: "item-header" },
					toggle: {
						container: "toggle",
						icon: { active: "active", inactive: "inactive" },
					},
					messages: {
						sidebarEmpty: "sidebar-empty",
						empty: {
							container: "empty-container",
							title: "empty-title",
							body: "empty-body",
							action: "empty-action",
						},
					},
				},
			},
			"../../src/script/shared/icons.ts": {
				createIcon: () => document.createElement("span"),
			},
			"../../src/script/shared/index.ts": {
				ENDPOINTS: {
					messages: {
						conversations: "/l/messages/conversations",
						clearModal: (key) => `/clear/${key}`,
						read: (key) => `/read/${key}`,
						history: (key) => `/history/${key}`,
						send: "/messages",
					},
				},
				request: {
					async get() {
						return { ok: true, conversations: [], cursor: null };
					},
				},
			},
			"../../src/script/views/base/core.ts": { default: CoreStub },
		},
	);

	const root = document.querySelector("[lp-view]");
	const view = new Messages(root);
	await view.init();
	t.after(() => view.destroy());

	assert.equal(
		root.querySelector("[data-role='conversation-list'] [data-role='empty']")
			?.textContent,
		"No conversations yet.",
	);
	const emptyPane = root.querySelector(
		"[data-role='message-history'] [data-role='empty']",
	);
	assert.ok(emptyPane);
	assert.match(emptyPane.textContent, /No conversations yet/);
	const cta = emptyPane.querySelector("[data-action='start-conversation']");
	assert.ok(cta);
	cta.click();
	assert.equal(composerOpened, 1);

	// Without compose permission, empty pane renders read-only hint and no CTA.
	view.composer = undefined;
	view.renderEmptyHistory();
	assert.equal(root.querySelector("[data-action='start-conversation']"), null);
	assert.match(
		root.querySelector("[data-role='message-history']")?.textContent ?? "",
		/Direct messages from other users will appear here/,
	);
});
