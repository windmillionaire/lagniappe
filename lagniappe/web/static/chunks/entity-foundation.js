/*! Third-party licenses: /third-party-licenses.txt */
import { C as Core, N as NavElement } from './core-foundation.js?v=b6c361d7';
import { d as debounce, w as withTransition } from './foundation.js?v=b6c361d7';

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
      debounce(this._renderLayout, 100)
    );
    await this._renderLayout();
  }
  get tabsCard() {
    return this.elt.querySelector("#tabs");
  }
  get secondaryCard() {
    return null;
  }
  _initialTabId() {
    return this.querySlug(this.queryParam("tab")) || localStorage.getItem(`${this.hash}-active`);
  }
  _initialTabWidget(_tabId) {
    return "default";
  }
  _tabElement(tabId) {
    if (!tabId) return null;
    return Array.from(
      this.elt.querySelectorAll(
        "[lp-component][data-tab='true']"
      )
    ).find((tab) => tab.id === tabId) || null;
  }
  _tabChange(event) {
    const { subcomponent } = event.detail;
    if (subcomponent.elt.dataset.tab !== "true") return;
    localStorage.setItem(`${this.hash}-active`, subcomponent.name);
  }
  get mobileNav() {
    if (!this._mobileNav) {
      const tabs = this.getComponent(this.tabsCard);
      const mobileNav = this.elt.querySelector(
        "[lp-nav][data-nav='mobile']"
      );
      if (!tabs || !mobileNav)
        throw new Error("Entity layout requires mobile tab navigation");
      this._mobileNav = new NavElement(tabs, mobileNav);
    }
    return this._mobileNav;
  }
  _componentElement(component) {
    if (!component) return null;
    if (typeof component !== "string")
      return "elt" in component ? component.elt : component;
    const element = document.getElementById(component);
    return element && this.elt.contains(element) ? element : null;
  }
  setSecondaryCardActive(component, active) {
    const element = this._componentElement(component);
    if (!element) return;
    this.elt.dataset.secondary = active ? "true" : "false";
    this.elt.classList.toggle("max-w-7xl", active);
    this.elt.classList.toggle("max-w-5xl", !active);
    element.dataset.visible = active ? "true" : "false";
    element.dataset.persistent = active ? "true" : "false";
  }
  isSecondaryCardVisible(component = this.secondaryCard) {
    const element = this._componentElement(component);
    return !!element && this.elt.dataset.secondary === "true" && element.dataset.visible === "true";
  }
  _layoutSnapshot(component = null) {
    const element = this._componentElement(component);
    return {
      secondary: this.elt.dataset.secondary === "true",
      wide: this.elt.classList.contains("max-w-7xl"),
      narrow: this.elt.classList.contains("max-w-5xl"),
      selected: this._initialTabId(),
      visible: element?.dataset.visible === "true",
      persistent: element?.dataset.persistent === "true"
    };
  }
  _layoutChanged(before, after) {
    return Object.entries(before).some(
      ([key, value]) => value !== after[key]
    );
  }
  async updateLayout({
    secondary = null,
    secondaryActive = null,
    activeTabId = null,
    mutate = null
  } = {}) {
    const secondaryElement = this._componentElement(secondary);
    const before = this._layoutSnapshot(secondaryElement);
    let mutationResult = null;
    let commitMutation = null;
    let activeLayoutTabId = null;
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
    const preparedSecondary = secondaryActive === null ? void 0 : secondaryActive ? secondaryElement : null;
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
      { label: "entity:update-layout" }
    );
    if (this.postRender) await this.postRender();
    const after = this._layoutSnapshot(secondaryElement);
    layoutChanged = layoutChanged || this._layoutChanged(before, after);
    return {
      activeTabId: activeLayoutTabId,
      layoutChanged,
      result: mutationResult
    };
  }
  async _renderLayout() {
    return await this.updateLayout();
  }
  async _renderLayoutBody() {
    const prepared = await this._prepareLayoutBody();
    await withTransition(() => this._commitLayoutBody(prepared), {
      label: "entity:render-layout"
    });
    if (this.postRender) await this.postRender();
    return prepared.activeTabId;
  }
  async _prepareLayoutBody(secondaryElement) {
    const tabId = this._initialTabId();
    const [tabs, secondary, activeTabId] = this._prerender(
      tabId,
      secondaryElement
    );
    const activeTabElt = this._tabElement(activeTabId);
    const layout = this.elt.querySelector("#layout");
    const activeTab = this.getComponent(activeTabElt);
    if (!activeTab || !layout)
      throw new Error(
        "Entity layout requires an active tab and layout container"
      );
    await activeTab.activate(this._initialTabWidget(activeTabId));
    await activeTab.prepareRender?.(true);
    return { activeTab, activeTabId, layout, secondary, tabs };
  }
  _commitLayoutBody({
    activeTab,
    activeTabId,
    layout,
    secondary,
    tabs
  }) {
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
  _reconcileTabsCard(tabs, tabId) {
    tabs.reconcile = () => {
      const nav = tabs.nav;
      if (nav) nav.element.dataset.visible = this.mobile ? "false" : "true";
      tabs.elt.querySelectorAll("[lp-component][data-tab='true']").forEach((component) => {
        component.dataset.visible = component.id === tabId ? "true" : "false";
      });
      tabs.reconcile = null;
    };
  }
  _reconcileSecondaryCard(secondary, tabId) {
    secondary.reconcile = () => {
      if (this.mobile) {
        secondary.elt.dataset.persistent = "false";
        this.tabsCard?.appendChild(secondary.elt);
        secondary.elt.dataset.visible = tabId === secondary.name ? "true" : "false";
      } else {
        secondary.elt.dataset.persistent = "true";
        this.elt.querySelector("#layout")?.prepend(secondary.elt);
        secondary.elt.dataset.visible = "true";
      }
      secondary.reconcile = null;
    };
  }
  _prerender(tabId, secondaryElement) {
    tabId ??= this._defaultTabId;
    const tabs = this.getComponent(this.tabsCard);
    if (!tabs) throw new Error("Entity layout requires a tabs component");
    const resolvedSecondary = secondaryElement === void 0 ? this.secondaryCard : secondaryElement;
    const secondary = resolvedSecondary ? this.getComponent(resolvedSecondary) : null;
    if (!this.mobile && tabId === secondary?.name) {
      tabId = this._defaultTabId;
    }
    if (!this._tabElement(tabId)) {
      tabId = this._defaultTabId;
    }
    return [tabs, secondary, tabId];
  }
}

export { Entity as E };
