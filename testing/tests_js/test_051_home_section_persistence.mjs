import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

function deferred() {
	let resolve;
	const promise = new Promise((done) => {
		resolve = done;
	});
	return { promise, resolve };
}

function buildHomeDom(
	document,
	{ starredCount = 0, user = "user-hash-1" } = {},
) {
	document.body.innerHTML = `
		<div lp-view data-kind="home" data-user="${user}">
			<div id="pages" lp-component data-open="false" data-persistent="true">
				<button type="button" lp-show="pages:HomePageList" data-toggle="true" aria-expanded="false">Pages</button>
				<button type="button" lp-show="pages:CreatePage" data-toggle="true">+</button>
				<form data-widget="CreatePage" data-visible="false"></form>
				<ul lp-load data-widget="HomePageList" data-visible="false" data-if-empty="CreatePage"></ul>
			</div>
			<div id="tasks" lp-component lp-prefetch data-open="false" data-persistent="true">
				<button type="button" lp-show="tasks:HomeTaskList" data-toggle="true" aria-expanded="false">Tasks</button>
				<form data-widget="CreateUserTask" data-visible="false"></form>
				<ul lp-prefetch data-widget="HomeTaskList" data-visible="false" data-if-empty="CreateUserTask"></ul>
			</div>
			<div id="projects" lp-component data-open="false" data-persistent="true">
				<button type="button" lp-show="projects:HomeProjectList" data-toggle="true" aria-expanded="false">Projects</button>
				<ul lp-load data-widget="HomeProjectList" data-visible="false"></ul>
			</div>
			<div id="starred" lp-component data-open="false" data-persistent="true">
				<button type="button" lp-show="starred:StarredList" data-toggle="true" aria-expanded="false">
					<div data-role="starred-count">${starredCount}</div>
				</button>
				<ul lp-load data-widget="StarredList" data-visible="false"></ul>
			</div>
			<div id="directory" loaded lp-component data-open="false" data-persistent="true">
				<button type="button" lp-show="directory:DirectoryList" data-toggle="true" aria-expanded="false">Directory</button>
				<ul data-widget="DirectoryList" data-visible="false"><li>Active Tasks</li></ul>
			</div>
			<div id="tools" lp-component data-open="false" data-persistent="true">
				<button type="button" lp-show="tools:ToolReportList" data-toggle="true" aria-expanded="false">Plans &amp; Reports</button>
				<div lp-load data-widget="ToolReportList" data-visible="false"></div>
			</div>
		</div>
	`;
	return document.querySelector("[lp-view]");
}

async function createHomeHarness(
	t,
	{
		initialStorage = {},
		starredCount = 0,
		widgetLoaders = {},
		beforeRenderCommit = null,
	} = {},
) {
	const dom = createBrowser(t);
	const { document } = dom.window;
	const storage = new Map(Object.entries(initialStorage));
	const writeLog = [];

	class FakeComponent {
		constructor(elt, view) {
			this.elt = elt;
			this.view = view;
			this.name = elt.id;
			this.widgets = {};
			this.widgetLoads = new Map();
			this.active = null;
			this.activeWidget = null;
		}

		async prefetch() {
			const targets = this.elt.querySelectorAll("[data-widget][lp-prefetch]");
			await Promise.all(
				Array.from(targets).map((el) => this.loadWidget(el.dataset.widget)),
			);
		}

		async loadWidget(name) {
			if (this.widgets[name]) return this.widgets[name];
			if (this.widgetLoads.has(name)) return this.widgetLoads.get(name);
			const pending = (async () => {
				const target = this.elt.querySelector(`[data-widget='${name}']`);
				const custom = widgetLoaders[name];
				const config = custom ? await custom(target) : {};
				const widget = {
					name,
					target,
					loaded: true,
					visible: false,
					itemCount:
						typeof config.itemCount === "number"
							? config.itemCount
							: target?.querySelectorAll("li").length || 0,
					enable() {
						this.visible = true;
					},
					disable() {
						this.visible = false;
					},
					reconcile() {
						if (this.target) {
							this.target.dataset.visible = this.visible ? "true" : "false";
						}
					},
				};
				this.widgets[name] = widget;
				return widget;
			})();
			this.widgetLoads.set(name, pending);
			try {
				return await pending;
			} finally {
				this.widgetLoads.delete(name);
			}
		}

		async prepareRender() {
			if (beforeRenderCommit) await beforeRenderCommit(this.name);
		}

		render(visible) {
			this.activeWidget = visible ? this.active : null;
			Object.values(this.widgets).forEach((widget) => {
				widget.reconcile();
			});
			this.elt.dataset.open =
				visible && this.active ? this.active.name : "false";
			this.view.onComponentRendered(this);
		}
	}

	class FakeCore {
		constructor(elt) {
			this.elt = elt;
			this.components = {};
			this.PollingCoordinator = null;
			this._destroyed = false;
		}

		getComponent(elt) {
			if (!elt) return null;
			const id = elt.id;
			if (!this.components[id]) {
				this.components[id] = new FakeComponent(elt, this);
			}
			return this.components[id];
		}

		async prefetch() {
			const nodes = this.elt.querySelectorAll("[lp-component][lp-prefetch]");
			await Promise.all(
				Array.from(nodes).map((el) => this.getComponent(el).prefetch()),
			);
		}

		_setLoadingTrigger(trigger) {
			trigger.dataset.loading = "true";
			trigger.setAttribute("aria-busy", "true");
			return trigger;
		}

		_clearLoadingTrigger(trigger) {
			if (!trigger) return;
			delete trigger.dataset.loading;
			trigger.removeAttribute("aria-busy");
		}

		async renderComponent(trigger) {
			const attr =
				trigger.getAttribute("lp-show") ||
				trigger.getAttribute("lp-close") ||
				"";
			const [componentId, widgetName] = attr.split(":");
			const component = this.getComponent(
				this.elt.querySelector(`#${componentId}[lp-component]`),
			);
			const closing =
				trigger.dataset.toggle === "true" &&
				component.active?.name === widgetName &&
				component.active.visible;
			component.active?.disable();
			if (closing || !widgetName) {
				component.active = null;
				component.render(false);
				return true;
			}
			const widget = await component.loadWidget(widgetName);
			component.active = widget;
			widget.enable();
			component.render(true);
			return true;
		}

		onComponentRendered() {}
		async reconcilePollingSubscriptions() {}
		destroy() {
			this._destroyed = true;
		}
	}

	const { default: Home } = await esmock.strict(
		"../../src/script/views/home.ts",
		{
			"../../src/script/shared/storage.ts": {
				localStore: {
					getJSON(key, fallback = null) {
						return storage.has(key) ? storage.get(key) : fallback;
					},
					setJSON(key, value) {
						storage.set(key, value);
						writeLog.push({ key, value });
						return true;
					},
				},
			},
			"../../src/script/shared/transitions.ts": {
				withTransition: async (callback) => callback(),
			},
			"../../src/script/views/base/core.ts": { default: FakeCore },
		},
	);

	const root = buildHomeDom(document, { starredCount });
	const home = new Home(root);
	return { document, root, home, storage, writeLog };
}

test("test_home_first_visit_opens_non_empty_tasks_and_starred_without_persisting_defaults", async (t) => {
	const loadedWidgets = [];
	const { root, home, writeLog } = await createHomeHarness(t, {
		starredCount: 2,
		widgetLoaders: {
			HomeTaskList: async () => {
				loadedWidgets.push("HomeTaskList");
				return { itemCount: 3 };
			},
			StarredList: async () => {
				loadedWidgets.push("StarredList");
				return { itemCount: 2 };
			},
		},
	});

	await home.prefetch();

	assert.deepEqual(loadedWidgets.sort(), ["HomeTaskList", "StarredList"]);
	assert.equal(
		root.querySelector("#tasks [data-widget='HomeTaskList']").dataset.visible,
		"true",
	);
	assert.equal(
		root
			.querySelector("button[lp-show='tasks:HomeTaskList']")
			.getAttribute("aria-expanded"),
		"true",
	);
	assert.equal(
		root.querySelector("#starred [data-widget='StarredList']").dataset.visible,
		"true",
	);
	assert.equal(
		root
			.querySelector("button[lp-show='starred:StarredList']")
			.getAttribute("aria-expanded"),
		"true",
	);
	assert.equal(writeLog.length, 0);
});

test("test_home_first_visit_skips_empty_tasks_and_zero_starred_without_loading_starred", async (t) => {
	let starredLoaded = false;
	const { root, home } = await createHomeHarness(t, {
		starredCount: 0,
		widgetLoaders: {
			HomeTaskList: async () => ({ itemCount: 0 }),
			StarredList: async () => {
				starredLoaded = true;
				return { itemCount: 0 };
			},
		},
	});

	await home.prefetch();

	assert.equal(starredLoaded, false);
	assert.equal(root.querySelector("#tasks").dataset.open, "false");
	assert.equal(
		root
			.querySelector("button[lp-show='tasks:HomeTaskList']")
			.getAttribute("aria-expanded"),
		"false",
	);
	assert.equal(
		root.querySelector("#tasks [data-widget='CreateUserTask']").dataset.visible,
		"false",
	);
});

test("test_home_persists_user_toggles_including_empty_selection_and_restores_saved_sections", async (t) => {
	const { root, home, storage } = await createHomeHarness(t, {
		widgetLoaders: {
			HomeTaskList: async () => ({ itemCount: 1 }),
			HomePageList: async () => ({ itemCount: 0 }),
			ToolReportList: async () => ({ itemCount: 0 }),
		},
	});
	const key = "home-open-sections:user-hash-1";

	await home.prefetch();
	const tasksToggle = root.querySelector(
		"button[lp-show='tasks:HomeTaskList']",
	);
	const directoryToggle = root.querySelector(
		"button[lp-show='directory:DirectoryList']",
	);
	const createPageToggle = root.querySelector(
		"button[lp-show='pages:CreatePage']",
	);
	const pagesToggle = root.querySelector(
		"button[lp-show='pages:HomePageList']",
	);

	// Opening a create form does not mark the Pages list toggle expanded or persist it.
	await home.renderComponent(createPageToggle);
	assert.equal(pagesToggle.getAttribute("aria-expanded"), "false");
	assert.equal(storage.has(key), false);

	// Opening Directory persists both Tasks and Directory.
	await home.renderComponent(directoryToggle);
	assert.equal(directoryToggle.getAttribute("aria-expanded"), "true");
	assert.deepEqual(storage.get(key), ["tasks", "directory"]);

	// Closing both persists an explicit empty array so defaults will not re-open Tasks.
	await home.renderComponent(tasksToggle);
	await home.renderComponent(directoryToggle);
	assert.equal(tasksToggle.getAttribute("aria-expanded"), "false");
	assert.equal(directoryToggle.getAttribute("aria-expanded"), "false");
	assert.deepEqual(storage.get(key), []);

	// Reloading with [] keeps Tasks closed even when tasks exist.
	const second = await createHomeHarness(t, {
		initialStorage: { [key]: [] },
		starredCount: 2,
		widgetLoaders: {
			HomeTaskList: async () => ({ itemCount: 4 }),
		},
	});
	await second.home.prefetch();
	assert.equal(second.root.querySelector("#tasks").dataset.open, "false");
	assert.equal(second.root.querySelector("#starred").dataset.open, "false");

	// Reloading with saved ["directory", "tools", "pages"] restores directory and tools,
	// and skips empty pages without opening CreatePage.
	const third = await createHomeHarness(t, {
		initialStorage: { [key]: ["directory", "tools", "pages"] },
		widgetLoaders: {
			HomeTaskList: async () => ({ itemCount: 2 }),
			HomePageList: async () => ({ itemCount: 0 }),
			ToolReportList: async () => ({ itemCount: 0 }),
		},
	});
	await third.home.prefetch();
	assert.equal(
		third.root.querySelector("#directory [data-widget='DirectoryList']").dataset
			.visible,
		"true",
	);
	assert.equal(
		third.root
			.querySelector("button[lp-show='directory:DirectoryList']")
			.getAttribute("aria-expanded"),
		"true",
	);
	assert.equal(
		third.root.querySelector("#tools [data-widget='ToolReportList']").dataset
			.visible,
		"true",
	);
	assert.equal(
		third.root
			.querySelector("button[lp-show='tools:ToolReportList']")
			.getAttribute("aria-expanded"),
		"true",
	);
	assert.equal(third.root.querySelector("#pages").dataset.open, "false");
	assert.equal(
		third.root.querySelector("#pages [data-widget='CreatePage']").dataset
			.visible,
		"false",
	);
	assert.equal(third.root.querySelector("#tasks").dataset.open, "false");
});

test("test_home_restore_preserves_inflight_sections_and_yields_to_user_click", async (t) => {
	const projectsLoad = deferred();
	const key = "home-open-sections:user-hash-1";
	const { root, home, storage } = await createHomeHarness(t, {
		initialStorage: { [key]: ["projects"] },
		widgetLoaders: {
			HomeTaskList: async () => ({ itemCount: 0 }),
			HomeProjectList: async () => await projectsLoad.promise,
		},
	});

	const prefetchPromise = home.prefetch();
	const directoryToggle = root.querySelector(
		"button[lp-show='directory:DirectoryList']",
	);
	const projectsToggle = root.querySelector(
		"button[lp-show='projects:HomeProjectList']",
	);

	// Toggling Directory while Projects is still restoring keeps Projects in storage.
	await home.renderComponent(directoryToggle);
	assert.deepEqual(storage.get(key), ["directory", "projects"]);

	// Finishing Projects restores it without clobbering Directory.
	projectsLoad.resolve({ itemCount: 2 });
	await prefetchPromise;
	assert.equal(projectsToggle.getAttribute("aria-expanded"), "true");
	assert.equal(projectsToggle.dataset.loading, undefined);
	assert.equal(directoryToggle.getAttribute("aria-expanded"), "true");
});

test("test_home_click_during_restore_prepare_opens_section_instead_of_closing", async (t) => {
	const prepareGate = deferred();
	const { root, home } = await createHomeHarness(t, {
		widgetLoaders: {
			HomeTaskList: async () => ({ itemCount: 2 }),
		},
		beforeRenderCommit: async (name) => {
			if (name === "tasks") await prepareGate.promise;
		},
	});

	const prefetchPromise = home.prefetch();
	await Promise.resolve();
	await Promise.resolve();

	const tasksToggle = root.querySelector(
		"button[lp-show='tasks:HomeTaskList']",
	);
	const tasksList = root.querySelector("#tasks [data-widget='HomeTaskList']");
	assert.equal(tasksList.dataset.visible, "false");

	await home.renderComponent(tasksToggle);
	prepareGate.resolve();
	await prefetchPromise;

	assert.equal(tasksList.dataset.visible, "true");
	assert.equal(tasksToggle.getAttribute("aria-expanded"), "true");
});
