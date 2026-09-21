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

const emptyButtons = { active: () => null };
const emptyRequest = {};
class EmptySiteSetting {}
class EmptySelectBox {}

/** @matrix admin : deployment-settings memory-pressure scaling-controls */
test("test_site_deployment_caps_workers_only_for_f2_and_b2", async () => {
	const { SiteDeployment } = await esmock.strict(
		"../../src/script/widgets/siteSettings/deployment.mjs",
		{
			"../../src/script/elements/buttons.mjs": { buttons: emptyButtons },
			"../../src/script/elements/combobox/index.mjs": {
				SelectBox: EmptySelectBox,
			},
			"../../src/script/shared/index.mjs": { request: emptyRequest },
			"../../src/script/widgets/siteSettings/base.mjs": {
				SiteSetting: EmptySiteSetting,
			},
		},
	);
	const instanceClass = { value: "B2" };
	const workerInput = { value: "8", max: "20" };
	const guidance = { textContent: "" };
	const form = {
		querySelector(selector) {
			if (selector === "[name='DEPLOY_INSTANCE_CLASS']") return instanceClass;
			if (selector === "[name='DEPLOY_WORKER_COUNT']") return workerInput;
			if (selector === "[data-role='deployment-worker-guidance']") {
				return guidance;
			}
			return null;
		},
	};
	const deployment = Object.create(SiteDeployment.prototype);
	deployment.deploymentForm = form;

	for (const limited of ["B2", "F2"]) {
		instanceClass.value = limited;
		workerInput.value = "8";
		deployment._syncWorkerLimit();
		assert.deepEqual(
			{
				max: workerInput.max,
				value: workerInput.value,
				guided: guidance.textContent.includes("at most three workers"),
			},
			{ max: "3", value: "3", guided: true },
			`${limited} enforces the memory-safe worker limit`,
		);
	}
	for (const configurable of ["B1", "B4", "B8", "F1", "F4", "F4_1G"]) {
		instanceClass.value = configurable;
		workerInput.value = "8";
		deployment._syncWorkerLimit();
		assert.deepEqual(
			{
				max: workerInput.max,
				value: workerInput.value,
				guided: guidance.textContent.includes("multiply application memory"),
			},
			{ max: "20", value: "8", guided: true },
			`${configurable} remains configurable`,
		);
	}
});

/** @matrix admin : composite-widgets persistence sections site-settings */
test("test_site_settings_coordinates_section_widgets", async (t) => {
	class FakeToggle {
		constructor() {
			this.dataset = {};
			this.attributes = {};
			this.title = "";
		}
		setAttribute(name, value) {
			this.attributes[name] = value;
		}
	}
	class FakeSection {
		constructor(name) {
			this.dataset = { section: name, open: "false" };
			this.body = { dataset: { visible: "false" } };
			this.toggle = new FakeToggle();
		}
		querySelector(selector) {
			if (selector === "[data-role='section-body']") return this.body;
			if (selector === "[data-role='expand']") return this.toggle;
			return null;
		}
	}
	const names = [
		"maintenance",
		"administrators",
		"installation-access",
		"deployment",
		"ai-models",
		"service-providers",
		"site-image",
	];
	const sections = names.map((name) => new FakeSection(name));
	const target = {
		attributes: {},
		listeners: {},
		querySelectorAll: () => sections,
		addEventListener(type, listener) {
			this.listeners[type] = listener;
		},
		removeEventListener(type, listener) {
			if (this.listeners[type] === listener) delete this.listeners[type];
		},
		setAttribute(name, value) {
			this.attributes[name] = value;
		},
	};
	const loaded = [];
	const widgets = new Map();
	const component = {
		async loadWidget(name) {
			loaded.push(name);
			const widget = {
				modified: false,
				responses: [],
				openedCount: 0,
				updated(response) {
					this.responses.push(response);
				},
				async opened() {
					this.openedCount += 1;
				},
			};
			widgets.set(name, widget);
			return widget;
		},
	};
	const storage = new Map([["lagniappe:site-settings-section", "missing"]]);
	replaceGlobal(t, "localStorage", {
		getItem: (key) => storage.get(key) || null,
		setItem: (key, value) => storage.set(key, value),
		removeItem: (key) => storage.delete(key),
	});
	const { SiteSettings } = await esmock.strict(
		"../../src/script/widgets/siteSettings.mjs",
		{
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (callback) => await callback(),
			},
			"../../src/script/widgets/siteSettings/publicPages.mjs": {
				SitePublicPages: class {},
			},
		},
	);
	const settings = new SiteSettings({ component, target });
	await settings.init();
	const expectedWidgets = [
		"SiteMaintenance",
		"SiteAdministrators",
		"SiteInstallationAccess",
		"SiteDeployment",
		"SiteAiModels",
		"SiteServiceProviders",
		"SiteImage",
	];
	assert.deepEqual(
		loaded.sort(),
		expectedWidgets.sort(),
		"loads every section widget",
	);
	assert.equal(
		target.attributes.initialized,
		"",
		"publishes after initialization",
	);
	assert.deepEqual(
		[sections[0].dataset.open, sections[0].body.dataset.visible],
		["true", "true"],
		"invalid saved state falls back to Maintenance",
	);
	const response = { deployment: { DEPLOY_SCALING_TYPE: "basic" } };
	settings.updated(response);
	for (const widget of widgets.values()) {
		assert.equal(widget.responses[0], response, "forwards aggregate response");
		assert.equal(widget.modified, true, "marks child modified");
	}
	await settings._toggleSection("site-image");
	assert.deepEqual(
		{
			opened: widgets.get("SiteImage").openedCount,
			stored: storage.get("lagniappe:site-settings-section"),
			image: sections.at(-1).dataset.open,
			maintenance: sections[0].dataset.open,
		},
		{ opened: 1, stored: "site-image", image: "true", maintenance: "false" },
		"opens one section and persists it",
	);
	await settings._toggleSection("site-image");
	assert.ok(
		!storage.has("lagniappe:site-settings-section"),
		"clears collapsed state",
	);
	assert.ok(
		sections.every((section) => section.dataset.open === "false"),
		"collapses active section",
	);
	settings.destroy();
	assert.equal(
		target.listeners.click,
		undefined,
		"removes coordinator listener",
	);
});

async function loadAiModels() {
	return await esmock.strict(
		"../../src/script/widgets/siteSettings/aiModels.mjs",
		{
			"../../src/script/elements/buttons.mjs": { buttons: emptyButtons },
			"../../src/script/elements/combobox/index.mjs": {
				SelectBox: EmptySelectBox,
			},
			"../../src/script/shared/index.mjs": { request: emptyRequest },
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (callback) => await callback(),
			},
			"../../src/script/widgets/siteSettings/base.mjs": {
				SiteSetting: EmptySiteSetting,
			},
		},
	);
}

/** @matrix admin : ai-settings model-options saved-values */
test("test_site_settings_initializes_ai_selects_before_syncing_saved_values", async () => {
	const { SiteAiModels } = await loadAiModels();
	const calls = [];
	const settings = Object.create(SiteAiModels.prototype);
	settings.aiForm = { querySelector: () => null };
	settings._initAiSelectBoxes = () => calls.push("init");
	settings._populateAiModelSelect = (name) => calls.push(`populate:${name}`);
	settings._setAiField = (name, value) => calls.push(`set:${name}:${value}`);
	settings.updateSummary = () => calls.push("summary");
	settings._renderAiSettings(
		{
			AI_MODEL: "saved-primary",
			AI_UTILITY_MODEL: "saved-utility",
			AI_IMAGE_MODEL: "saved-image",
			AI_LOCATION: "global",
		},
		{ text: [], image: [] },
	);
	assert.equal(calls[0], "init", "initializes selects first");
	const firstSet = calls.findIndex((call) => call.startsWith("set:"));
	const lastPopulate = calls.reduce(
		(index, call, current) => (call.startsWith("populate:") ? current : index),
		-1,
	);
	assert.ok(
		firstSet > lastPopulate,
		"syncs saved values after populating options",
	);
	assert.ok(
		calls.includes("set:AI_MODEL:saved-primary"),
		"syncs primary model",
	);
	assert.ok(
		calls.includes("set:AI_UTILITY_MODEL:saved-utility"),
		"syncs utility model",
	);
});

/** @matrix admin : ai-settings model-selection submission */
test("test_site_settings_ai_submission_uses_visible_combobox_values", async (t) => {
	class FormDataBoundary {
		constructor(form) {
			this.data = new Map(form.initialData);
		}
		get(name) {
			return this.data.get(name);
		}
		set(name, value) {
			this.data.set(name, value);
		}
	}
	replaceGlobal(t, "FormData", FormDataBoundary);
	const { SiteAiModels } = await loadAiModels();
	const primary = {
		name: "AI_MODEL",
		value: "stale-native-primary",
		closest: () => ({ _lp_combobox: { values: new Set(["visible-primary"]) } }),
	};
	const utility = {
		name: "AI_UTILITY_MODEL",
		value: "native-utility",
		closest: () => ({ _lp_combobox: { values: new Set() } }),
	};
	const form = {
		initialData: [
			["AI_MODEL", "stale-form-primary"],
			["AI_UTILITY_MODEL", "stale-form-utility"],
			["AI_IMAGE_MODEL", "saved-image"],
			["AI_LOCATION", "global"],
		],
		querySelectorAll: () => [primary, utility],
	};
	const settings = Object.create(SiteAiModels.prototype);
	settings.aiForm = form;
	const data = settings._aiSettingsFormData();
	assert.equal(
		data.get("AI_MODEL"),
		"visible-primary",
		"submits visible selection",
	);
	assert.equal(
		data.get("AI_UTILITY_MODEL"),
		"native-utility",
		"uses native fallback",
	);
	assert.deepEqual(
		[data.get("AI_IMAGE_MODEL"), data.get("AI_LOCATION")],
		["saved-image", "global"],
		"preserves non-combobox fields",
	);
});

/** @matrix form-schema forms : canonical-list legacy-object-rejected visibility */
test("test_renderer_visibility_requires_canonical_condition_lists", async () => {
	const { FormRenderer } = await esmock.strict(
		"../../src/script/forms/renderer.mjs",
		{
			"../../src/script/elements/loader.mjs": {
				getFormElement: async () => null,
			},
			"../../src/script/shared/errors.mjs": {
				captureError(error) {
					throw error;
				},
			},
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (callback) => await callback(),
			},
			"../../src/script/shared/utilities.mjs": {
				generateElementId: () => "renderer-test",
			},
		},
	);
	const triggerNode = {};
	const targetNode = { dataset: {} };
	const trigger = {
		id: "trigger-renderer-test",
		schema: { id: "trigger", type: "checkbox" },
		elt: triggerNode,
		active: (value) => value === true,
	};
	const target = {
		id: "conditional-renderer-test",
		schema: {
			id: "conditional",
			type: "input",
			visibility: [{ id: "trigger", value: true }],
		},
		elt: targetNode,
	};
	const renderer = new FormRenderer({
		target: { dataset: {} },
		readonly: false,
	});
	renderer.elements.set(trigger.id, trigger);
	renderer.elements.set(target.id, target);
	await renderer._initVisibilityTriggers();
	renderer._updateDerivedState();
	assert.equal(
		targetNode.dataset.visible,
		"true",
		"matches canonical visibility",
	);
	assert.ok(
		renderer.visibilityTriggers.get(trigger)?.has(target),
		"registers trigger owner",
	);
	target.schema.visibility = { id: "trigger", value: true };
	await assert.rejects(
		renderer._initVisibilityTriggers(),
		/filter/,
		"rejects legacy object visibility",
	);
});

class BuilderNode {
	constructor() {
		this.children = [];
		this.dataset = {};
		this.classList = { add() {} };
	}
	appendChild(child) {
		this.children.push(child);
		return child;
	}
}

/** @matrix form-schema forms : builder immutable-schema presentation-defaults */
test("test_builder_model_defaults_are_presentation_only", async (t) => {
	const calls = [];
	const primitive = (kind) => (attributes) => {
		calls.push({ kind, attributes });
		return new BuilderNode();
	};
	replaceGlobal(t, "document", {
		createElement: () => new BuilderNode(),
		getElementById: () => new BuilderNode(),
	});
	const { ModelElement } = await esmock.strict(
		"../../src/script/views/builder/panels/model.mjs",
		{
			sortablejs: { default: { create: () => ({ destroy() {} }) } },
			"../../src/script/elements/primitives.mjs": {
				primitives: {
					badge: primitive("badge"),
					checkbox: primitive("checkbox"),
					input: primitive("input"),
					label: primitive("label"),
					radio: primitive("radio"),
					select: primitive("select"),
					textarea: primitive("textarea"),
				},
			},
			"../../src/script/generated/styles.mjs": {
				STYLES: {
					badge: { builder: "" },
					builder: { model: "" },
					radio: { fieldset: { column: "" }, label: "" },
				},
			},
			"../../src/script/views/builder/config.mjs": {
				CONFIG: {
					PRESENTATION_DEFAULTS: {
						input: { title: "Input", input: "text" },
						link: { title: "Link", location: "out" },
					},
				},
			},
		},
	);
	const inputSchema = { id: "field", type: "input" };
	const linkSchema = { id: "link", type: "link" };
	const before = JSON.stringify([inputSchema, linkSchema]);
	ModelElement.input(inputSchema);
	ModelElement.link(linkSchema);
	assert.equal(
		JSON.stringify([inputSchema, linkSchema]),
		before,
		"does not mutate schema",
	);
	const inputCall = calls.find((call) => call.kind === "input");
	const linkCall = calls.find((call) => call.kind === "label");
	assert.deepEqual(
		[inputCall?.attributes?.label, inputCall?.attributes?.type],
		["Input", "text"],
		"applies input presentation defaults",
	);
	assert.deepEqual(
		[linkCall?.attributes?.label, linkCall?.attributes?.icon],
		["Link", "out"],
		"applies link presentation defaults",
	);
});

class FakeNode {
	constructor() {
		this.textContent = "";
		this.dataset = {};
		this.children = [];
		this.nodes = {};
		this.events = {};
		this.disabled = false;
		this.open = false;
	}
	querySelector(selector) {
		return this.nodes[selector] || null;
	}
	replaceChildren() {
		this.children = [];
	}
	appendChild(child) {
		this.children.push(child);
		return child;
	}
	addEventListener(name, callback) {
		this.events[name] = callback;
	}
	get childElementCount() {
		return this.children.length;
	}
}

function maintenanceTarget() {
	const title = new FakeNode();
	const summary = new FakeNode();
	const results = new FakeNode();
	const errors = new FakeNode();
	const updateButton = new FakeNode();
	const cacheButton = new FakeNode();
	const migrationPanel = new FakeNode();
	migrationPanel.nodes = {
		"[data-role='migration-status-title']": title,
		"[data-role='migration-status-summary']": summary,
		"[data-role='migration-status-results']": results,
		"[data-role='migration-status-errors']": errors,
	};
	const cacheTitle = new FakeNode();
	const cacheSummary = new FakeNode();
	const cacheErrors = new FakeNode();
	const cachePanel = new FakeNode();
	cachePanel.nodes = {
		"[data-role='cache-status-title']": cacheTitle,
		"[data-role='cache-status-summary']": cacheSummary,
		"[data-role='cache-status-errors']": cacheErrors,
	};
	const target = new FakeNode();
	target.nodes = {
		"[data-role='migration-status']": migrationPanel,
		"[data-role='cache-status']": cachePanel,
		"[data-role='site-update']": updateButton,
		"[data-role='rebuild-cache']": cacheButton,
	};
	return {
		cacheButton,
		cacheErrors,
		cachePanel,
		cacheSummary,
		cacheTitle,
		errors,
		migrationPanel,
		results,
		summary,
		target,
		title,
		updateButton,
	};
}

const maintenanceStyles = {
	link: { emphasized: "link-emphasized" },
	siteSettings: {
		migration: {
			releaseSummary: "release-summary",
			migrationList: "migration-list",
			completion: "completion",
			attemptList: "attempt-list",
		},
	},
};

async function loadMaintenance({
	buttons = emptyButtons,
	request = emptyRequest,
	clear = () => {},
} = {}) {
	return await esmock.strict(
		"../../src/script/widgets/siteSettings/maintenance.mjs",
		{
			"../../src/script/elements/buttons.mjs": { buttons },
			"../../src/script/generated/styles.mjs": { STYLES: maintenanceStyles },
			"../../src/script/shared/index.mjs": { Modal: class {}, request },
			"../../src/script/shared/storage.mjs": {
				clearRecentSearchResults: clear,
			},
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (callback) => await callback(),
			},
			"../../src/script/widgets/siteSettings/base.mjs": {
				SiteSetting: EmptySiteSetting,
			},
		},
	);
}

const completedMigration = {
	id: "FSM-001",
	sequence: 1,
	introduced_in: "0.1",
	label: "Canonical form schemas",
	state: "complete",
	completed_at: "2026-07-14T00:00:00+00:00",
	completed_version: "0.1",
	completed_build_id: "old-build",
	attempts: [
		{
			status: "failed",
			totals: { changed: 0, repaired: 0, failed: 1 },
			repairs: [],
			errors: [
				{
					key: "stale-error-key",
					message: "A failure resolved by the later attempt",
					url: "/forms/already-repaired-form",
					link_label: "Open form",
				},
			],
		},
		{
			status: "complete",
			totals: { changed: 1, repaired: 1, failed: 0 },
			repairs: [
				{
					key: "long-repair-key",
					message: "Removed invalid schema data",
					url: "/forms/repairable-form",
					link_label: "Open form",
				},
			],
			errors: [],
		},
	],
};

/**
 * @matrix admin database-migrations : actionable-links audit-error cache-gate current failed fresh-install pending repair-filtering repairs running version-history
 * @template home/site_settings.html::site_settings
 */
test("test_site_settings_migration_status_uses_generic_release_states", async (t) => {
	replaceGlobal(t, "document", { createElement: () => new FakeNode() });
	const { SiteMaintenance } = await loadMaintenance();
	const ui = maintenanceTarget();
	const settings = Object.create(SiteMaintenance.prototype);
	settings.target = ui.target;
	settings._renderMigrationStatus({
		status: "current",
		current_version: "0.3.0",
		cache_refresh_allowed: true,
		counts: { complete: 3, total: 3 },
		migrations: [
			{ ...completedMigration, source: "fresh-install" },
			{ ...completedMigration, id: "MSG-001", source: "fresh-install" },
			{ ...completedMigration, id: "AST-001", source: "fresh-install" },
		],
	});
	assert.equal(
		ui.summary.textContent,
		"Version 0.3.0. No site updates are required.",
	);
	assert.equal(
		ui.results.childElementCount,
		0,
		"hides fresh-install baselines",
	);

	settings._renderMigrationStatus({
		status: "current",
		current_version: "0.3",
		cache_refresh_allowed: true,
		counts: { complete: 1, total: 1 },
		migrations: [completedMigration],
	});
	assert.equal(ui.title.textContent, "Site updates are current");
	assert.deepEqual(
		[ui.updateButton.disabled, ui.cacheButton.disabled],
		[true, false],
	);
	const completedRelease = ui.results.children[0].children[0];
	assert.equal(
		completedRelease.open,
		false,
		"collapses completed release history",
	);
	assert.equal(
		completedRelease.children[0].textContent,
		"Version 0.1 — 1/1 completed",
	);
	const completedItem = completedRelease.children[1].children[0];
	assert.match(
		completedItem.children[0].textContent,
		/version 0\.1, build old-build/,
	);
	const repairNotes = completedItem.children[2];
	const repairLink = repairNotes.children[0].children[0];
	assert.deepEqual(
		[repairLink?.href, repairLink?.textContent],
		["/forms/repairable-form", "Open form"],
	);
	assert.ok(!repairNotes.children[0].textContent.includes("long-repair-key"));
	assert.equal(
		ui.errors.childElementCount,
		0,
		"does not expose resolved errors",
	);

	settings._renderMigrationStatus({
		status: "current",
		current_version: "0.3",
		cache_refresh_allowed: true,
		counts: { complete: 1, total: 1 },
		migrations: [
			{
				...completedMigration,
				id: "MSG-001",
				label: "Messaging notification aggregates",
			},
		],
	});
	const messagingItem =
		ui.results.children[0].children[0].children[1].children[0];
	assert.equal(
		messagingItem.children.length,
		2,
		"omits routine MSG-001 repairs",
	);

	const pending = {
		id: "NEXT-001",
		sequence: 2,
		introduced_in: "0.3",
		label: "Next durable update",
		state: "pending",
		attempts: [],
	};
	settings._renderMigrationStatus({
		status: "pending",
		current_version: "0.3",
		cache_refresh_allowed: false,
		counts: { complete: 1, pending: 1, failed: 0, interrupted: 0, blocked: 0 },
		migrations: [completedMigration, pending],
	});
	assert.deepEqual(
		[ui.title.textContent, ui.summary.textContent],
		["Site updates are ready", "Version 0.3. 1 pending site update."],
	);
	assert.deepEqual(
		[
			ui.updateButton.disabled,
			ui.cacheButton.disabled,
			ui.results.childElementCount,
		],
		[false, true, 2],
		"gates pending controls and preserves release ordering",
	);
	assert.equal(
		ui.results.children[1].children[0].open,
		true,
		"expands pending release",
	);

	const failed = {
		...pending,
		state: "failed",
		attempts: [
			{
				status: "failed",
				totals: { changed: 0, repaired: 0, failed: 1 },
				repairs: [],
				errors: [
					{
						key: "long-error-key",
						message: "schema is not valid JSON",
						url: "/forms/unreadable-form",
						link_label: "Open form",
					},
				],
			},
		],
	};
	settings._renderMigrationStatus({
		status: "failed",
		current_version: "0.3",
		cache_refresh_allowed: false,
		counts: { complete: 1, failed: 1, interrupted: 0, blocked: 1, pending: 0 },
		migrations: [
			completedMigration,
			failed,
			{ ...pending, id: "LAST-001", sequence: 3, state: "blocked" },
		],
	});
	assert.deepEqual(
		[ui.title.textContent, ui.updateButton.disabled, ui.cacheButton.disabled],
		["Site updates need attention", false, true],
	);
	assert.deepEqual(
		[
			ui.errors.children[0].children[0]?.href,
			ui.errors.children[0].children[0]?.textContent,
		],
		["/forms/unreadable-form", "Open form"],
		"links affected form",
	);

	settings._renderMigrationStatus({
		status: "failed",
		cache_refresh_allowed: false,
		counts: { failed: 1 },
		migrations: [
			{
				...failed,
				id: "FIL-001",
				attempts: [
					{
						status: "failed",
						errors: [
							{
								key: "raw-file-key",
								message: "File has multiple owners",
								url: "/files/encoded-file",
								link_label: "Invoice <original>",
							},
						],
					},
				],
			},
		],
	});
	const fileError = ui.errors.children[0];
	assert.equal(fileError.textContent, "FIL-001: File has multiple owners ");
	assert.deepEqual(
		[fileError.children[0]?.href, fileError.children[0]?.textContent],
		["/files/encoded-file", "Invoice <original>"],
		"uses named file link instead of raw key",
	);

	settings._renderMigrationStatus({
		status: "running",
		current_version: "0.3",
		cache_refresh_allowed: false,
		counts: { running: 1 },
		migrations: [{ ...pending, state: "running" }],
	});
	assert.deepEqual(
		[ui.title.textContent, ui.updateButton.disabled],
		["Site updates are running", true],
		"blocks concurrent update",
	);
	settings._renderMigrationStatus({
		status: "audit-error",
		current_version: "0.3",
		cache_refresh_allowed: false,
		counts: { audit_error: 1 },
		migrations: [
			{
				...pending,
				state: "audit-error",
				audit_error: "Stored sequence does not match",
			},
		],
	});
	assert.deepEqual(
		[
			ui.title.textContent,
			ui.updateButton.disabled,
			ui.errors.childElementCount,
		],
		["Site update history needs repair", true, 1],
		"renders blocking audit repair",
	);
});

/**
 * @matrix cache : failure-isolation actionable-links
 * @template home/site_settings.html::site_settings
 */
test("test_site_settings_cache_refresh_displays_linked_failures", async (t) => {
	replaceGlobal(t, "document", { createElement: () => new FakeNode() });
	let response = {
		ok: true,
		cache_status: {
			status: "partial",
			processed: 7,
			failed: 2,
			errors: [
				{
					message: "Missing task parent",
					url: "/tasks/broken",
					link_label: "Broken task",
				},
			],
		},
	};
	let cleared = 0;
	const buttons = {
		active: ({ existingButton, completedText }) => ({
			element: existingButton,
			activate() {},
			deactivate(text) {
				existingButton.textContent = text || completedText;
			},
		}),
	};
	const { SiteMaintenance } = await loadMaintenance({
		buttons,
		request: { post: async () => response },
		clear: () => {
			cleared += 1;
		},
	});
	const ui = maintenanceTarget();
	const settings = Object.create(SiteMaintenance.prototype);
	settings.target = ui.target;
	settings.endpoints = { rebuildCache: "/l/rebuild-cache" };
	settings._initActions();
	await ui.cacheButton.events.click();
	assert.equal(ui.cachePanel.dataset.visible, "true");
	assert.equal(ui.cacheTitle.textContent, "Cache refreshed with errors");
	assert.match(ui.cacheSummary.textContent, /7 records processed; 2 skipped/);
	assert.match(ui.cacheSummary.textContent, /Showing 1 errors/);
	assert.deepEqual(
		[
			ui.cacheErrors.children[0].children[0].href,
			ui.cacheErrors.children[0].children[0].textContent,
		],
		["/tasks/broken", "Broken task"],
	);
	assert.match(ui.cacheButton.textContent, /Review Errors/);
	assert.equal(cleared, 1);
	settings.postreconcile();
	assert.equal(
		ui.cacheErrors.children.length,
		1,
		"retains partial failure after reconcile",
	);
	response = {
		ok: true,
		cache_status: { status: "complete", processed: 9, failed: 0, errors: [] },
	};
	await ui.cacheButton.events.click();
	assert.equal(ui.cacheTitle.textContent, "Cache refreshed");
	assert.equal(ui.cacheErrors.children.length, 0);
	assert.equal(ui.cacheButton.textContent, "Cache Refreshed");
});
