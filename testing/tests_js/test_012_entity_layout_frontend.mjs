import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

async function setupEntityLayout(t) {
	createBrowser(t, {
		html: `
			<div id="root">
				<div id="layout">
					<section id="photo" lp-component data-attribute="photo"
						data-persistent="false" data-tab="true" data-visible="false"></section>
				</div>
				<section id="tabs" data-visible="false">
					<section id="info" lp-component data-tab="true"></section>
				</section>
				<nav id="mobile-nav" lp-nav data-nav="mobile"></nav>
			</div>
		`,
	});
	const root = document.querySelector("#root");
	const layout = document.querySelector("#layout");
	const tabsElement = document.querySelector("#tabs");
	const infoElement = document.querySelector("#info");
	const photoElement = document.querySelector("#photo");
	const desktopNav = document.createElement("nav");
	desktopNav.id = "desktop-nav";
	tabsElement.navElement = desktopNav;
	const events = [];
	let transitionCalls = 0;
	let transitionDepth = 0;
	const withTransition = async (callback) => {
		transitionCalls += 1;
		transitionDepth += 1;
		try {
			return await callback();
		} finally {
			transitionDepth -= 1;
		}
	};
	class FakeComponent {
		constructor(element, view) {
			this.elt = element;
			this.view = view;
			this.name = element.id;
			this.widgets = {};
			this._nav = null;
			this.reconcile = null;
		}

		get nav() {
			if (this._nav) return this._nav;
			if (this.elt.navElement) {
				this._nav = { element: this.elt.navElement };
			}
			return this._nav;
		}

		set nav(value) {
			this._nav = value;
		}

		async activate(show) {
			events.push(`${this.name}:activate:${show}`);
		}

		async prepareRender(visible) {
			events.push(`${this.name}:prepare:${visible}`);
		}

		render(visible) {
			events.push(`${this.name}:render:${visible}`);
		}
	}
	class FakeCore {
		constructor(node) {
			this.elt = node;
			this.components = {};
			this.hash = "entity-layout-test";
			this.kind = "page";
			this.mobile = false;
			this.readonly = false;
		}

		async init() {}

		getComponent(element) {
			if (!element) throw new Error("Missing component element");
			this.components[element.id] ??= new FakeComponent(element, this);
			return this.components[element.id];
		}

		queryParam() {
			return null;
		}

		querySlug(value) {
			return value;
		}
	}
	class NavElement {
		constructor(component, element) {
			this.component = component;
			this.element = element;
		}
	}
	const { default: Entity } = await esmock.strict(
		"../../src/script/views/base/entity.mjs",
		{
			"../../src/script/elements/nav.mjs": { NavElement },
			"../../src/script/shared/transitions.mjs": { withTransition },
			"../../src/script/shared/utilities.mjs": {
				debounce: (callback) => callback,
			},
			"../../src/script/views/base/core.mjs": { default: FakeCore },
		},
	);
	return {
		Entity,
		elements: { infoElement, layout, photoElement, root, tabsElement },
		events,
		transitionActive: () => transitionDepth > 0,
		transitionCalls: () => transitionCalls,
		withTransition,
	};
}

/** @matrix entity-layout : nested-layout reconcile-callback */
test("test_entity_layout_ignores_already_consumed_reconcile_callback", async (t) => {
	const context = await setupEntityLayout(t);
	const { Entity, elements, events } = context;
	const view = new Entity(elements.root);
	const outer = await view._prepareLayoutBody();
	const inner = await view._prepareLayoutBody();
	await context.withTransition(() => {
		view._commitLayoutBody(inner);
		view._commitLayoutBody(outer);
	});
	assert.equal(
		events.filter((event) => event === "info:render:true").length,
		2,
	);
	assert.equal(elements.layout.dataset.visible, "true");
	assert.equal(elements.tabsElement.dataset.visible, "true");
	assert.equal(view.getComponent(elements.tabsElement).reconcile, null);
});

/** @pair startup:view-ready */
test("test_initial_entity_layout_prepares_widget_before_one_transition", async (t) => {
	const context = await setupEntityLayout(t);
	const { Entity, elements } = context;
	const view = new Entity(elements.root);
	const info = view.getComponent(elements.infoElement);
	let resolveActivation;
	let markActivationStarted;
	let activationTransitioned = false;
	const activationStarted = new Promise((resolve) => {
		markActivationStarted = resolve;
	});
	info.activate = () => {
		activationTransitioned = context.transitionActive();
		markActivationStarted();
		return new Promise((resolve) => {
			resolveActivation = resolve;
		});
	};
	const initializing = view.init();
	await activationStarted;
	assert.notEqual(elements.layout.dataset.visible, "true");
	assert.notEqual(elements.tabsElement.dataset.visible, "true");
	assert.notEqual(elements.infoElement.dataset.visible, "true");
	assert.equal(context.transitionCalls(), 0);
	assert.equal(activationTransitioned, false);
	resolveActivation();
	await initializing;
	assert.equal(context.transitionCalls(), 1);
	assert.equal(elements.layout.dataset.visible, "true");
	assert.equal(elements.tabsElement.dataset.visible, "true");
	assert.equal(elements.infoElement.dataset.visible, "true");
});

/** @pair entity-layout:dynamic-secondary */
test("test_dynamic_mobile_secondary_uses_final_layout_state", async (t) => {
	const { Entity, elements } = await setupEntityLayout(t);
	const view = new Entity(elements.root);
	view.mobile = true;
	Object.defineProperty(view, "secondaryCard", {
		get() {
			return elements.root.dataset.secondary === "true"
				? elements.photoElement
				: null;
		},
	});
	await view.updateLayout({
		activeTabId: "photo",
		secondary: elements.photoElement,
		secondaryActive: true,
	});
	assert.equal(elements.photoElement.parentElement, elements.tabsElement);
	assert.equal(elements.photoElement.dataset.visible, "true");
	assert.equal(elements.photoElement.dataset.persistent, "false");
	assert.equal(elements.infoElement.dataset.visible, "false");
	await view.updateLayout({ activeTabId: "info" });
	assert.equal(elements.photoElement.dataset.visible, "false");
	assert.equal(elements.infoElement.dataset.visible, "true");
});

/** @matrix entity-layout : dynamic-secondary nested-layout page-mobile */
test("test_overlapping_mobile_layout_updates_keep_secondary_nonpersistent", async (t) => {
	const { Entity, elements } = await setupEntityLayout(t);
	const view = new Entity(elements.root);
	view.mobile = true;
	await Promise.all([
		view.updateLayout({
			activeTabId: "photo",
			secondary: elements.photoElement,
			secondaryActive: true,
		}),
		view.updateLayout({
			activeTabId: "photo",
			secondary: elements.photoElement,
			secondaryActive: true,
		}),
	]);
	assert.equal(elements.photoElement.parentElement, elements.tabsElement);
	assert.equal(elements.photoElement.dataset.persistent, "false");
	assert.equal(elements.photoElement.dataset.visible, "true");
	await view.updateLayout({
		activeTabId: "info",
		secondary: elements.photoElement,
		secondaryActive: true,
	});
	assert.equal(elements.photoElement.dataset.persistent, "false");
	assert.equal(elements.photoElement.dataset.visible, "false");
	assert.equal(elements.infoElement.dataset.visible, "true");
});
