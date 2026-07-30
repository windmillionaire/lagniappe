/*! Third-party licenses: /third-party-licenses.txt */
import { C as Core, N as NavElement } from './core.js?v=b30f3f24';
import { k as debounce, w as withTransition } from './shared.js?v=b30f3f24';

/**
 * @testable infrastructure
 */
class Entity extends Core {
	constructor(node) {
		super(node);
		this.collaborating = {};
		this._renderLayout = this._renderLayout.bind(this);
		this._tabChange = this._tabChange.bind(this);
		this._defaultTabId = "info";
		this._mobileNav = null;
	}

	async init() {
		await super.init();

		this.elt.addEventListener("set-subcomponent", this._tabChange);
		this.elt.addEventListener(
			"mobile-resize",
			debounce(this._renderLayout, 100),
		);

		await this._renderLayout();
	}

	get tabsCard() {
		return this.elt.querySelector("#tabs");
	}

	get secondaryCard() {
		return null;
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity.setAttributeActive
	 * @reason attribute-specific secondary-card lookup feeds nav toggle visibility decisions
	 */
	secondaryCardForAttribute(attribute) {
		const secondary = this.secondaryCard;
		return secondary?.dataset.attribute === attribute ? secondary : null;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_page_url_tab_overrides_saved_tab
	 * @features entity-layout
	 * @dimensions query-tab persistence
	 */
	_initialTabId() {
		return (
			this.querySlug(this.queryParam("tab")) ||
			localStorage.getItem(`${this.hash}-active`)
		);
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity._prerender
	 * @reason tab lookup is part of pre-render validation
	 */
	_tabElement(tabId) {
		if (!tabId) return null;
		return (
			Array.from(
				this.elt.querySelectorAll("[lp-component][data-tab='true']"),
			).find((tab) => tab.id === tabId) || null
		);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/004_projects/test_004g_project_mobile_ui.py::test_resize_from_mobile_filters_to_desktop_preserves_selected_tab
	 * @tests tests_e2e/004_projects/test_004g_project_mobile_ui.py::test_mobile_selected_section_persists_after_reload
	 * @tests tests_e2e/005_pages/test_005c_page_mobile_ui.py::test_page_mobile_selection_persists_after_reload
	 * @features entity-layout
	 * @dimensions project-mobile page-mobile persistence reload resize
	 */
	_tabChange(event) {
		const { subcomponent } = event.detail;
		if (subcomponent.elt.dataset.tab !== "true") return;

		localStorage.setItem(`${this.hash}-active`, subcomponent.name);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/004_projects/test_004g_project_mobile_ui.py::test_mobile_nav_visibility_changes_with_viewport
	 * @tests tests_e2e/004_projects/test_004g_project_mobile_ui.py::test_mobile_flipper_reveals_section_toggles
	 * @tests tests_e2e/005_pages/test_005c_page_mobile_ui.py::test_page_mobile_nav_replaces_desktop_tabs
	 * @tests tests_e2e/005_pages/test_005c_page_mobile_ui.py::test_page_mobile_flipper_reveals_sections
	 * @features entity-layout
	 * @dimensions project-mobile page-mobile nav visibility flipper
	 */
	get mobileNav() {
		if (!this._mobileNav) {
			const tabs = this.getComponent(this.tabsCard);
			const mobileNav = this.elt.querySelector("[lp-nav][data-nav='mobile']");
			this._mobileNav = new NavElement(tabs, mobileNav);
		}
		return this._mobileNav;
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity.updateLayout
	 * @reason component lookup normalization supports the public layout updater
	 */
	_componentElement(component) {
		if (!component) return null;
		if (component.elt) return component.elt;
		if (typeof Element !== "undefined" && component instanceof Element) {
			return component;
		}

		const element = document.getElementById(component);
		return element && this.elt.contains(element) ? element : null;
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity.setAttributeActive
	 * @reason secondary toggle filtering is private attribute-state plumbing
	 */
	_isSecondaryAttributeToggle(element, attribute) {
		const show = element.getAttribute("lp-show");
		if (!show) return false;

		const [componentId] = show.split(":");
		const component = this._componentElement(componentId);
		const secondary = this.secondaryCardForAttribute(attribute);
		return (
			component === secondary &&
			component?.dataset.attribute === attribute &&
			component?.dataset.secondaryAttribute !== "true"
		);
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity.setAttributeActive
	 * @reason form attribute button state is private layout metadata plumbing
	 */
	_setAttributeSelected(attribute, active) {
		this.elt
			.querySelectorAll(
				`[data-role='attribute'][data-attribute='${attribute}']`,
			)
			.forEach((element) => {
				element.dataset.selected = active ? "true" : "false";
				const checkbox = element.querySelector("input[type='checkbox']");
				if (checkbox) checkbox.checked = active;
			});
	}

	/**
	 * @testable infrastructure
	 */
	setAttributeActive(
		attribute,
		active,
		{ includeSecondaryToggles = false } = {},
	) {
		this.elt
			.querySelectorAll(`[data-has-attribute][data-attribute='${attribute}']`)
			.forEach((element) => {
				if (
					!includeSecondaryToggles &&
					this._isSecondaryAttributeToggle(element, attribute)
				) {
					return;
				}
				element.dataset.hasAttribute = active ? "true" : "false";
			});
		this._setAttributeSelected(attribute, active);
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity.setSecondaryCardActive
	 * @reason secondary-card nav toggles are derived from secondary visibility
	 */
	setSecondaryToggleActive(attribute, active) {
		this.elt
			.querySelectorAll(`[data-has-attribute][data-attribute='${attribute}']`)
			.forEach((element) => {
				if (!this._isSecondaryAttributeToggle(element, attribute)) return;
				element.dataset.hasAttribute = active ? "true" : "false";
			});
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity.updateLayout
	 * @reason root width and card persistence are coordinated by the public layout updater
	 */
	setSecondaryCardActive(component, active) {
		const element = this._componentElement(component);
		if (!element) return;

		this.elt.dataset.secondary = active ? "true" : "false";
		this.elt.classList.toggle("max-w-7xl", active);
		this.elt.classList.toggle("max-w-5xl", !active);
		element.dataset.visible = active ? "true" : "false";
		element.dataset.persistent = active ? "true" : "false";

		if (element.dataset.attribute) {
			this.setSecondaryToggleActive(element.dataset.attribute, active);
		}
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity.updateLayout
	 * @reason callers use this to decide whether widget-only transitions should run separately
	 */
	isSecondaryCardVisible(component = this.secondaryCard) {
		const element = this._componentElement(component);
		return (
			!!element &&
			this.elt.dataset.secondary === "true" &&
			element.dataset.visible === "true"
		);
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity.updateLayout
	 * @reason transition-result metadata compares before/after layout state
	 */
	_layoutSnapshot(component = null) {
		const element = this._componentElement(component);
		return {
			secondary: this.elt.dataset.secondary === "true",
			wide: this.elt.classList.contains("max-w-7xl"),
			narrow: this.elt.classList.contains("max-w-5xl"),
			selected: this._initialTabId(),
			visible: element?.dataset.visible === "true",
			persistent: element?.dataset.persistent === "true",
		};
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity.updateLayout
	 * @reason transition-result metadata compares before/after layout state
	 */
	_layoutChanged(before, after) {
		return Object.keys(before).some((key) => before[key] !== after[key]);
	}

	/**
	 * @testable infrastructure
	 */
	async updateLayout({
		attribute = null,
		active = null,
		attributeActive = active,
		secondary = null,
		secondaryActive = active,
		activeTabId = null,
		mutate = null,
	} = {}) {
		const secondaryElement = this._componentElement(secondary);
		const before = this._layoutSnapshot(secondaryElement);
		let mutationResult = null;
		let activeLayoutTabId = null;
		let layoutChanged = false;

		await withTransition(async () => {
			if (attribute && attributeActive !== null) {
				this.setAttributeActive(attribute, attributeActive);
			}
			if (secondaryElement && secondaryActive !== null) {
				this.setSecondaryCardActive(secondaryElement, secondaryActive);
			}
			if (activeTabId) {
				localStorage.setItem(`${this.hash}-active`, activeTabId);
			}

			const prepared = this._layoutSnapshot(secondaryElement);
			layoutChanged = this._layoutChanged(before, prepared);
			mutationResult = await mutate?.({ layoutChanged });
			activeLayoutTabId = await this._renderLayoutBody();
		});

		const after = this._layoutSnapshot(secondaryElement);
		layoutChanged = layoutChanged || this._layoutChanged(before, after);
		return {
			activeTabId: activeLayoutTabId,
			layoutChanged,
			result: mutationResult,
		};
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity.mobileNav
	 * @covered-by src/script/views/base/entity.mjs::Entity._tabChange
	 * @covered-by src/script/views/base/entity.mjs::Entity._reconcileTabsCard
	 * @covered-by src/script/views/base/entity.mjs::Entity._reconcileSecondaryCard
	 * @reason layout render coordinates narrower mobile nav, tab, persistence, and secondary-card owners
	 */
	async _renderLayout() {
		return await this.updateLayout();
	}

	/**
	 * @testable true
	 * @tests tests_js/test_012_entity_layout_frontend.py::test_entity_layout_ignores_already_consumed_reconcile_callback
	 * @features entity-layout
	 * @dimensions nested-layout reconcile-callback
	 */
	async _renderLayoutBody() {
		const tabId = this._initialTabId();
		const [tabs, secondary, activeTabId] = this._prerender(tabId);
		const activeTabElt = this._tabElement(activeTabId);
		const mobileNav = this.mobileNav;
		const layout = this.elt.querySelector("#layout");

		const activeTab = this.getComponent(activeTabElt);

		tabs.nav = this.mobile ? mobileNav : null;

		Object.values(this.components).forEach((component) => {
			if (component.elt.dataset.tab === "true") {
				component.nav = this.mobile ? tabs.nav : null;
			}
		});

		await activeTab.activate("default");
		await activeTab.render(true);
		layout.dataset.visible = "true";
		// Widget post-reconcile work can trigger a nested layout render that
		// consumes these one-shot callbacks before this render resumes.
		if (typeof tabs.reconcile === "function") tabs.reconcile();
		if (typeof secondary?.reconcile === "function") secondary.reconcile();
		mobileNav.element.dataset.visible = this.mobile ? "true" : "false";
		if (this.postRender) await this.postRender();
		localStorage.setItem(`${this.hash}-active`, activeTabId);
		return activeTabId;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/004_projects/test_004g_project_mobile_ui.py::test_mobile_section_switching_updates_visible_cards_and_title
	 * @tests tests_e2e/004_projects/test_004g_project_mobile_ui.py::test_resize_from_mobile_filters_to_desktop_preserves_selected_tab
	 * @tests tests_e2e/005_pages/test_005c_page_mobile_ui.py::test_page_mobile_section_switching_updates_visible_panel_and_title
	 * @tests tests_e2e/005_pages/test_005c_page_mobile_ui.py::test_page_mobile_create_task_opens_from_tasks_section
	 * @features entity-layout
	 * @dimensions project-mobile page-mobile section-switch resize task-create
	 */
	_reconcileTabsCard(tabs, tabId) {
		tabs.reconcile = () => {
			tabs.nav.element.dataset.visible = this.mobile ? "false" : "true";

			tabs.elt
				.querySelectorAll("[lp-component][data-tab='true']")
				.forEach((component) => {
					component.dataset.visible = component.id === tabId ? "true" : "false";
				});

			tabs.reconcile = null;
		};
	}

	/**
	 * @testable true
	 * @tests tests_e2e/004_projects/test_004g_project_mobile_ui.py::test_mobile_create_model_form_opens_from_model_tasks_section
	 * @tests tests_e2e/004_projects/test_004g_project_mobile_ui.py::test_mobile_model_task_info_still_opens_in_models_section
	 * @tests tests_e2e/004_projects/test_004g_project_mobile_ui.py::test_resize_from_mobile_models_to_desktop_restores_dual_card_layout
	 * @features entity-layout
	 * @dimensions project-mobile secondary-create secondary-info secondary-card resize
	 */
	_reconcileSecondaryCard(secondary, tabId) {
		secondary.reconcile = () => {
			if (this.mobile) {
				secondary.elt.dataset.persistent = "false";
				this.tabsCard.appendChild(secondary.elt);
				secondary.elt.dataset.visible =
					tabId === secondary.name ? "true" : "false";
			} else {
				secondary.elt.dataset.persistent = "true";
				this.elt.querySelector("#layout").prepend(secondary.elt);
				secondary.elt.dataset.visible = "true";
			}

			secondary.reconcile = null;
		};
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity._renderLayout
	 * @reason pre-render selection feeds the annotated mobile layout reconciliation
	 */
	_prerender(tabId) {
		tabId ??= this._defaultTabId;
		const tabs = this.getComponent(this.tabsCard);
		const secondary = this.secondaryCard
			? this.getComponent(this.secondaryCard)
			: null;

		if (!this.mobile && tabId === secondary?.name) {
			tabId = this._defaultTabId;
		}
		if (!this._tabElement(tabId)) {
			tabId = this._defaultTabId;
		}

		this._reconcileTabsCard(tabs, tabId);
		if (secondary) {
			this._reconcileSecondaryCard(secondary, tabId);
		}

		return [tabs, secondary, tabId];
	}
}

export { Entity as E };
