import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

test("test_home_starred_count_updates_immediately_and_task_feedback_dismisses", async (t) => {
	const dom = createBrowser(t);
	const { document } = dom.window;
	document.body.innerHTML = `
		<div lp-view data-kind="home" data-user="u1">
			<div id="tasks" lp-component data-open="false" data-persistent="true">
				<button type="button" lp-show="tasks:HomeTaskList" data-toggle="true" aria-expanded="false">Tasks</button>
				<div data-role="task-feedback" data-visible="true">
					<span data-role="task-feedback-text">Saved</span>
					<button type="button" data-role="dismiss-task-feedback">Dismiss</button>
				</div>
			</div>
			<div id="starred" lp-component data-open="StarredList" data-persistent="true">
				<button type="button" lp-show="starred:StarredList" data-toggle="true" aria-expanded="false" class="opacity-50 pointer-events-none">
					<div data-role="starred-count">0</div>
				</button>
				<ul data-widget="StarredList" data-visible="false"></ul>
			</div>
		</div>
	`;

	class FakeCore {
		constructor(elt) {
			this.elt = elt;
			this.components = {};
			this._destroyed = false;
		}
		_click() {}
		destroy() {
			this._destroyed = true;
		}
	}

	const { default: Home } = await esmock.strict(
		"../../src/script/views/home.ts",
		{
			"../../src/script/shared/storage.ts": {
				localStore: { getJSON: () => null, setJSON: () => true },
			},
			"../../src/script/shared/transitions.ts": {
				withTransition: async (callback) => callback(),
			},
			"../../src/script/views/base/core.ts": { default: FakeCore },
		},
	);

	const root = document.querySelector("[lp-view]");
	const home = new Home(root);
	const starredToggle = root.querySelector(
		"button[lp-show='starred:StarredList']",
	);
	const starredCount = root.querySelector("[data-role='starred-count']");
	const starredList = root.querySelector("[data-widget='StarredList']");

	// Optimistic star bump unlocks Starred immediately.
	home._adjustStarredCount(1);
	assert.equal(starredCount.textContent, "1");
	assert.equal(starredToggle.classList.contains("opacity-50"), false);
	assert.equal(starredToggle.classList.contains("pointer-events-none"), false);

	// Returning to 0 disables toggle, hides list, and clears aria-expanded.
	starredList.dataset.visible = "true";
	starredToggle.setAttribute("aria-expanded", "true");
	home.components.starred = {
		name: "starred",
		elt: root.querySelector("#starred"),
		active: { name: "StarredList" },
		activeWidget: { target: starredList },
	};
	home._setStarredCount(0);
	assert.equal(starredCount.textContent, "0");
	assert.equal(starredToggle.classList.contains("opacity-50"), true);
	assert.equal(starredToggle.classList.contains("pointer-events-none"), true);
	assert.equal(starredList.dataset.visible, "false");
	assert.equal(home.components.starred.active, null);
	assert.equal(starredToggle.getAttribute("aria-expanded"), "false");

	// Dismissing task feedback hides the banner.
	const feedback = root.querySelector("[data-role='task-feedback']");
	const dismissBtn = root.querySelector("[data-role='dismiss-task-feedback']");
	let prevented = false;
	home._click({
		target: dismissBtn,
		preventDefault() {
			prevented = true;
		},
	});
	assert.equal(prevented, true);
	assert.equal(feedback.dataset.visible, "false");

	// Opening CreateUserTask also clears any visible task feedback banner.
	feedback.dataset.visible = "true";
	home.onComponentRendered({
		name: "tasks",
		elt: root.querySelector("#tasks"),
		active: { name: "CreateUserTask" },
		activeWidget: null,
	});
	assert.equal(feedback.dataset.visible, "false");
});

test("test_home_task_list_updates_my_page_count_and_feedback_on_create", async (t) => {
	const dom = createBrowser(t);
	const { document } = dom.window;
	document.body.innerHTML = `
		<div lp-view data-kind="home">
			<a data-kind="user" href="/pages/me">
				<div class="text-project-default font-bold ml-auto" data-role="user-task-count">0</div>
			</a>
			<div id="tasks" lp-component>
				<button type="button" lp-show="tasks:HomeTaskList" data-toggle="true">
					<div data-role="task-count">0</div>
				</button>
				<div data-role="task-feedback" data-visible="false">
					<span data-role="task-feedback-text"></span>
				</div>
				<ul data-widget="HomeTaskList" data-visible="false"></ul>
			</div>
		</div>
	`;

	const { HomeTaskList } = await esmock.strict(
		"../../src/script/widgets/home/tasks.ts",
		{
			"../../src/script/elements/combobox/index.ts": {
				Dropdown: class {
					init() {}
					destroy() {}
				},
			},
			"../../src/script/generated/styles.mjs": {
				STYLES: {
					task: { home: { group: "group", item: "item" } },
					checkbox: { default: "cb", icon: "icon" },
				},
			},
			"../../src/script/shared/icons.ts": { setIcon() {} },
			"../../src/script/shared/index.ts": { request: {} },
			"../../src/script/shared/transitions.ts": {
				withTransition: async (cb) => cb(),
			},
		},
	);

	const tasksElt = document.querySelector("#tasks");
	const listTarget = tasksElt.querySelector("[data-widget='HomeTaskList']");
	const widget = new HomeTaskList({
		target: listTarget,
		name: "HomeTaskList",
		component: { elt: tasksElt, active: null },
		view: { online: true, addFlash() {} },
		endpoints: {
			completeTask: (k) => `/tasks/${k}/complete`,
			changeDueDate: (k) => `/tasks/${k}/due`,
		},
	});

	const userTaskCount = document.querySelector("[data-role='user-task-count']");
	const feedback = document.querySelector("[data-role='task-feedback']");
	const feedbackText = document.querySelector(
		"[data-role='task-feedback-text']",
	);

	// 1. Unscheduled task creation updates My Page count & color and shows banner.
	widget.created({
		removed: true,
		count: 1,
		name: "Order extra frames",
		scheduled: false,
	});
	widget.postreconcile();
	assert.equal(userTaskCount.textContent, "1");
	assert.equal(userTaskCount.classList.contains("text-task-default"), true);
	assert.equal(userTaskCount.classList.contains("text-project-default"), false);
	assert.equal(feedback.dataset.visible, "true");
	assert.equal(
		feedbackText.textContent,
		"“Order extra frames” saved to My Page (unscheduled).",
	);

	// 2. Task scheduled beyond this week updates count and message.
	widget.created({
		removed: true,
		count: 2,
		name: "Winter wrap",
		scheduled: true,
	});
	widget.postreconcile();
	assert.equal(userTaskCount.textContent, "2");
	assert.equal(
		feedbackText.textContent,
		"“Winter wrap” saved to My Page (scheduled beyond this week).",
	);

	// 3. Near-term task appearing in HomeTaskList updates count and clears banner.
	const frag = document.createElement("div");
	frag.innerHTML = `<li lp-entity data-key="t-1" data-due-date="2026-11-25">Today task</li>`;
	widget.created({ html: frag, count: 3 });
	listTarget.dataset.visible = "true";
	widget.postreconcile();
	assert.equal(userTaskCount.textContent, "3");
	assert.equal(feedback.dataset.visible, "false");
	assert.equal(feedbackText.textContent, "");
});
