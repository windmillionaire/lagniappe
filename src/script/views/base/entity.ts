import { NavElement } from "../../elements/nav.ts";
import { withTransition } from "../../shared/transitions.ts";
import { debounce } from "../../shared/utilities.ts";
import type ViewComponent from "./component.ts";
import type { SubcomponentEvent } from "./component.ts";
import Core from "./core.ts";
import type { ViewRoot } from "./shell.ts";

type ComponentReference =
	| HTMLElement
	| Pick<ViewComponent, "elt">
	| string
	| null;

export interface EntityLayoutOptions {
	secondary?: ComponentReference;
	secondaryActive?: boolean | null;
	activeTabId?: string | null;
	mutate?: ((state: { layoutChanged: boolean }) => unknown) | null;
}

export interface PreparedEntityLayout {
	activeTab: ViewComponent;
	activeTabId: string;
	layout: HTMLElement;
	secondary: ViewComponent | null;
	tabs: ViewComponent;
}

export interface EntityLayoutResult {
	activeTabId: string | null;
	layoutChanged: boolean;
	result: unknown;
}

interface LayoutSnapshot {
	secondary: boolean;
	wide: boolean;
	narrow: boolean;
	selected: string | null;
	visible: boolean;
	persistent: boolean;
}

export default class Entity extends Core {
	declare collaborating: Record<string, unknown>;
	declare _defaultTabId: string;
	declare _mobileNav: NavElement | null;
	declare postRender?: (() => unknown) | null;

	constructor(node: ViewRoot) {
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

		// Keep tab selection and widget enhancement atomic. Polling, offline replay,
		// and other private services do not begin until this view publishes.
		await this._renderLayout();
	}

	get tabsCard() {
		return this.elt.querySelector<HTMLElement>("#tabs");
	}

	get secondaryCard(): HTMLElement | null {
		return null;
	}

	_initialTabId() {
		return (
			this.querySlug(this.queryParam("tab")) ||
			localStorage.getItem(`${this.hash}-active`)
		);
	}

	_tabElement(tabId: string | null) {
		if (!tabId) return null;
		return (
			Array.from(
				this.elt.querySelectorAll<HTMLElement>(
					"[lp-component][data-tab='true']",
				),
			).find((tab) => tab.id === tabId) || null
		);
	}

	_tabChange(event: SubcomponentEvent) {
		const { subcomponent } = event.detail;
		if (subcomponent.elt.dataset.tab !== "true") return;

		localStorage.setItem(`${this.hash}-active`, subcomponent.name);
	}

	get mobileNav() {
		if (!this._mobileNav) {
			const tabs = this.getComponent(this.tabsCard);
			const mobileNav = this.elt.querySelector<HTMLElement>(
				"[lp-nav][data-nav='mobile']",
			);
			if (!tabs || !mobileNav)
				throw new Error("Entity layout requires mobile tab navigation");
			this._mobileNav = new NavElement(tabs, mobileNav);
		}
		return this._mobileNav;
	}

	_componentElement(component: ComponentReference): HTMLElement | null {
		if (!component) return null;
		if (typeof component !== "string")
			return "elt" in component ? component.elt : component;

		const element = document.getElementById(component);
		return element && this.elt.contains(element) ? element : null;
	}

	setSecondaryCardActive(component: ComponentReference, active: boolean) {
		const element = this._componentElement(component);
		if (!element) return;

		this.elt.dataset.secondary = active ? "true" : "false";
		this.elt.classList.toggle("max-w-7xl", active);
		this.elt.classList.toggle("max-w-5xl", !active);
		element.dataset.visible = active ? "true" : "false";
		element.dataset.persistent = active ? "true" : "false";
	}

	isSecondaryCardVisible(component: ComponentReference = this.secondaryCard) {
		const element = this._componentElement(component);
		return (
			!!element &&
			this.elt.dataset.secondary === "true" &&
			element.dataset.visible === "true"
		);
	}

	_layoutSnapshot(component: ComponentReference = null): LayoutSnapshot {
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

	_layoutChanged(before: LayoutSnapshot, after: LayoutSnapshot) {
		return Object.entries(before).some(
			([key, value]) => value !== after[key as keyof LayoutSnapshot],
		);
	}

	async updateLayout({
		secondary = null,
		secondaryActive = null,
		activeTabId = null,
		mutate = null,
	}: EntityLayoutOptions = {}): Promise<EntityLayoutResult> {
		const secondaryElement = this._componentElement(secondary);
		const before = this._layoutSnapshot(secondaryElement);
		let mutationResult: unknown = null;
		let commitMutation: (() => void) | null = null;
		let activeLayoutTabId: string | null = null;
		let layoutChanged = false;

		if (activeTabId) {
			localStorage.setItem(`${this.hash}-active`, activeTabId);
		}
		const preparedMutation = await mutate?.({ layoutChanged: false });
		if (typeof preparedMutation === "function") {
			commitMutation = () => preparedMutation();
		} else {
			mutationResult = preparedMutation;
		}
		const preparedSecondary =
			secondaryActive === null
				? undefined
				: secondaryActive
					? secondaryElement
					: null;
		const preparedLayout = await this._prepareLayoutBody(preparedSecondary);

		await withTransition(
			() => {
				commitMutation?.();
				if (secondaryElement && secondaryActive !== null) {
					this.setSecondaryCardActive(secondaryElement, secondaryActive);
				}
				const prepared = this._layoutSnapshot(secondaryElement);
				layoutChanged = this._layoutChanged(before, prepared);
				activeLayoutTabId = this._commitLayoutBody(preparedLayout);
			},
			{ label: "entity:update-layout" },
		);
		if (this.postRender) await this.postRender();

		const after = this._layoutSnapshot(secondaryElement);
		layoutChanged = layoutChanged || this._layoutChanged(before, after);
		return {
			activeTabId: activeLayoutTabId,
			layoutChanged,
			result: mutationResult,
		};
	}

	async _renderLayout() {
		return await this.updateLayout();
	}

	async _renderLayoutBody() {
		const prepared = await this._prepareLayoutBody();
		await withTransition(() => this._commitLayoutBody(prepared), {
			label: "entity:render-layout",
		});
		if (this.postRender) await this.postRender();
		return prepared.activeTabId;
	}

	async _prepareLayoutBody(
		secondaryElement?: HTMLElement | null,
	): Promise<PreparedEntityLayout> {
		const tabId = this._initialTabId();
		const [tabs, secondary, activeTabId] = this._prerender(
			tabId,
			secondaryElement,
		);
		const activeTabElt = this._tabElement(activeTabId);
		const layout = this.elt.querySelector<HTMLElement>("#layout");

		const activeTab = this.getComponent(activeTabElt);
		if (!activeTab || !layout)
			throw new Error(
				"Entity layout requires an active tab and layout container",
			);

		await activeTab.activate("default");
		await activeTab.prepareRender?.(true);
		return { activeTab, activeTabId, layout, secondary, tabs };
	}

	_commitLayoutBody({
		activeTab,
		activeTabId,
		layout,
		secondary,
		tabs,
	}: PreparedEntityLayout) {
		const mobileNav = this.mobileNav;
		tabs.nav = this.mobile ? mobileNav : null;
		Object.values(this.components).forEach((component) => {
			if (component.elt.dataset.tab === "true") {
				component.nav = this.mobile ? tabs.nav : null;
			}
		});

		layout.dataset.visible = "true";
		this._reconcileTabsCard(tabs, activeTabId);
		if (secondary) {
			this._reconcileSecondaryCard(secondary, activeTabId);
		}
		if (typeof tabs.reconcile === "function") tabs.reconcile();
		if (typeof secondary?.reconcile === "function") secondary.reconcile();
		tabs.elt.dataset.visible = "true";
		mobileNav.element.dataset.visible = this.mobile ? "true" : "false";
		activeTab.render(true);
		localStorage.setItem(`${this.hash}-active`, activeTabId);
		return activeTabId;
	}

	_reconcileTabsCard(tabs: ViewComponent, tabId: string) {
		tabs.reconcile = () => {
			const nav = tabs.nav;
			if (nav) nav.element.dataset.visible = this.mobile ? "false" : "true";

			tabs.elt
				.querySelectorAll<HTMLElement>("[lp-component][data-tab='true']")
				.forEach((component) => {
					component.dataset.visible = component.id === tabId ? "true" : "false";
				});

			tabs.reconcile = null;
		};
	}

	_reconcileSecondaryCard(secondary: ViewComponent, tabId: string) {
		secondary.reconcile = () => {
			if (this.mobile) {
				secondary.elt.dataset.persistent = "false";
				this.tabsCard?.appendChild(secondary.elt);
				secondary.elt.dataset.visible =
					tabId === secondary.name ? "true" : "false";
			} else {
				secondary.elt.dataset.persistent = "true";
				this.elt.querySelector("#layout")?.prepend(secondary.elt);
				secondary.elt.dataset.visible = "true";
			}

			secondary.reconcile = null;
		};
	}

	_prerender(
		tabId: string | null,
		secondaryElement?: HTMLElement | null,
	): [ViewComponent, ViewComponent | null, string] {
		tabId ??= this._defaultTabId;
		const tabs = this.getComponent(this.tabsCard);
		if (!tabs) throw new Error("Entity layout requires a tabs component");
		const resolvedSecondary =
			secondaryElement === undefined ? this.secondaryCard : secondaryElement;
		const secondary = resolvedSecondary
			? this.getComponent(resolvedSecondary)
			: null;

		if (!this.mobile && tabId === secondary?.name) {
			tabId = this._defaultTabId;
		}
		if (!this._tabElement(tabId)) {
			tabId = this._defaultTabId;
		}

		return [tabs, secondary, tabId];
	}
}
