import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";

/** @matrix home polling : foreground lazy-widget mounted-scope targeted-refresh */
test("test_home_polling_subscribes_loaded_widgets_and_refreshes_only_owner", async () => {
	class Core {
		constructor(element) {
			this.elt = element;
			this.components = {};
			this.PollingCoordinator = null;
		}

		async prefetch() {}

		async reconcilePollingSubscriptions() {}

		destroy() {
			this.coreDestroyed = true;
		}
	}
	const { default: Home } = await esmock.strict(
		"../../src/script/views/home.mjs",
		{
			"../../src/script/shared/transitions.mjs": {
				withTransition: (callback) => callback(),
			},
			"../../src/script/views/base/core.mjs": { default: Core },
		},
	);
	const descriptors = new Map();
	const hooks = new Map();
	const removed = [];
	const refreshed = [];
	const coordinator = {
		subscribe(descriptor, options) {
			descriptors.set(descriptor.id, descriptor);
			hooks.set(descriptor.id, options);
			return () => {
				removed.push(descriptor.id);
				descriptors.delete(descriptor.id);
				hooks.delete(descriptor.id);
			};
		},
	};
	const notes = {
		name: "HomeActivityList",
		loaded: true,
		route: "/l/get/notes",
		target: { dataset: { pollRevision: "notes-1" } },
		async refresh() {
			refreshed.push("notes");
		},
	};
	const tasks = {
		name: "HomeTaskList",
		loaded: true,
		route: "/l/get/tasks",
		target: { dataset: { pollRevision: "tasks-1" } },
		async refresh() {
			refreshed.push("tasks");
		},
	};
	const pages = {
		name: "HomePageList",
		loaded: false,
		route: "/l/get/pages",
		target: { dataset: { pollRevision: "pages-1" } },
		async refresh() {
			refreshed.push("pages");
		},
	};
	const component = { widgets: { notes, tasks, pages } };
	const home = new Home({});
	home.PollingCoordinator = coordinator;
	home.components = { dashboard: component };
	home.load = async (_component, route) => ({
		updated: true,
		pollChannel: route.endsWith("notes") ? "home-notes" : "tasks",
		pollRevision: `${route}-next`,
	});

	home._syncHomePollingSubscriptions();
	assert.equal(descriptors.size, 2);
	assert.equal(descriptors.has("home:channel:pages"), false);
	const notesDescriptor = descriptors.get("home:channel:home-notes");
	const notesHook = hooks.get("home:channel:home-notes");
	assert.equal(notesDescriptor?.revision, "notes-1");
	assert.equal(notesHook?.mode, "foreground");
	assert.equal(notesHook?.initial, "scheduled");
	await notesHook.onResult({ status: "changed" });
	assert.deepEqual(refreshed, ["notes"]);

	pages.loaded = true;
	home._syncHomePollingSubscriptions();
	assert.equal(descriptors.has("home:channel:pages"), true);
	tasks.loaded = false;
	home._syncHomePollingSubscriptions();
	assert.equal(removed.includes("home:channel:tasks"), true);

	home.destroy();
	assert.equal(home.coreDestroyed, true);
	assert.equal(descriptors.size, 0);
});
