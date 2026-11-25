/*! Third-party licenses: /third-party-licenses.txt */
import { e as localStore, w as withTransition } from '../foundation.js?v=bf7d4d98';
import { C as Core } from '../core-foundation.js?v=bf7d4d98';
import '../upstreamUnavailable.js?v=bf7d4d98';
import '../connectivity.js?v=bf7d4d98';

const HOME_CHANNELS = Object.freeze({
  HomeActivityList: "home-notes",
  HomeTaskList: "tasks",
  StarredList: "starred",
  HomePageList: "pages",
  HomeProjectList: "projects",
  HomeCategoryList: "categories",
  IngressList: "ingress",
  ToolReportList: "tool-reports"
});
const HOME_SECTIONS = Object.freeze({
  pages: "HomePageList",
  notes: "HomeActivityList",
  tasks: "HomeTaskList",
  projects: "HomeProjectList",
  categories: "HomeCategoryList",
  starred: "StarredList",
  directory: "DirectoryList",
  tools: "ToolReportList"
});
function isHomeSectionId(value) {
  return typeof value === "string" && value in HOME_SECTIONS;
}
class Home extends Core {
  constructor(elt) {
    super(elt);
    this.hash = "home";
    this._homePollUnsubscribers = /* @__PURE__ */ new Map();
    this._openSections = /* @__PURE__ */ new Set();
    this._restoringSections = /* @__PURE__ */ new Set();
    this._interactedSections = /* @__PURE__ */ new Set();
    this._suppressSectionPersist = false;
  }
  get _sectionStorageKey() {
    const user = this.elt?.dataset?.user;
    return user ? `home-open-sections:${user}` : "home-open-sections";
  }
  _initPollingSubscription() {
  }
  async prefetch() {
    await Promise.all([super.prefetch(), this._restoreOpenSections()]);
    this._syncHomePollingSubscriptions();
  }
  _savedOpenSections() {
    const saved = localStore.getJSON(this._sectionStorageKey);
    if (!Array.isArray(saved)) return null;
    const unique = /* @__PURE__ */ new Set();
    for (const item of saved) {
      if (isHomeSectionId(item)) unique.add(item);
    }
    return [...unique];
  }
  _defaultOpenSections() {
    const defaults = ["tasks"];
    const starredCountText = this.elt?.querySelector?.("[data-role='starred-count']")?.textContent?.trim();
    const starredCount = Number.parseInt(starredCountText || "0", 10);
    if (!Number.isNaN(starredCount) && starredCount > 0) {
      defaults.push("starred");
    }
    return defaults;
  }
  _sectionElement(sectionId) {
    return this.elt?.querySelector?.(`#${sectionId}[lp-component]`) ?? null;
  }
  _sectionToggle(sectionId, component) {
    const widgetName = HOME_SECTIONS[sectionId];
    const root = component?.elt ?? this._sectionElement(sectionId);
    return root?.querySelector?.(
      `button[lp-show='${sectionId}:${widgetName}'][data-toggle]`
    ) ?? null;
  }
  _isSectionListOpen(sectionId, component) {
    const widgetName = HOME_SECTIONS[sectionId];
    const resolved = component ?? this.components[sectionId] ?? null;
    if (!resolved || resolved.active?.name !== widgetName) return false;
    const target = resolved.activeWidget?.target ?? resolved.elt?.querySelector?.(
      `[data-widget='${widgetName}']`
    );
    return target?.dataset?.visible === "true";
  }
  _canRestoreWidget(sectionId, widget) {
    if (sectionId === "tools") return true;
    const list = widget;
    if (typeof list.itemCount === "number") return list.itemCount > 0;
    return Boolean(widget.target?.querySelector?.("li"));
  }
  _persistOpenSections() {
    const ordered = /* @__PURE__ */ new Set([
      ...this._openSections,
      ...this._restoringSections
    ]);
    localStore.setJSON(this._sectionStorageKey, [...ordered]);
  }
  async _restoreOpenSections() {
    const saved = this._savedOpenSections();
    const sections = saved !== null ? saved : this._defaultOpenSections();
    if (sections.length === 0) return;
    await Promise.all(
      sections.map((sectionId) => this._restoreSection(sectionId))
    );
  }
  async _restoreSection(sectionId) {
    if (this._destroyed || this._interactedSections.has(sectionId)) return;
    const elt = this._sectionElement(sectionId);
    const component = this.getComponent(elt);
    if (!component || component.active) return;
    const widgetName = HOME_SECTIONS[sectionId];
    const toggle = this._sectionToggle(sectionId, component);
    const target = component.elt.querySelector(
      `[data-widget='${widgetName}']`
    );
    const loadingTrigger = toggle && target?.hasAttribute("lp-load") ? this._setLoadingTrigger(toggle, component, widgetName) : null;
    this._restoringSections.add(sectionId);
    try {
      const widget = await component.loadWidget(widgetName);
      if (!widget || this._destroyed || !this._restoringSections.has(sectionId) || this._interactedSections.has(sectionId) || component.active || !this._canRestoreWidget(sectionId, widget)) {
        return;
      }
      await widget.prereconcile?.();
      await component.prepareRender(true);
      if (this._destroyed || !this._restoringSections.has(sectionId) || this._interactedSections.has(sectionId) || component.active) {
        return;
      }
      await withTransition(
        () => {
          if (this._destroyed || !this._restoringSections.has(sectionId) || this._interactedSections.has(sectionId) || component.active) {
            return;
          }
          this._suppressSectionPersist = true;
          try {
            component.active = widget;
            widget.enable();
            component.render(true);
          } finally {
            this._suppressSectionPersist = false;
          }
        },
        { label: `home:restore-${sectionId}` }
      );
    } finally {
      this._restoringSections.delete(sectionId);
      this._clearLoadingTrigger(loadingTrigger);
    }
  }
  renderComponent(trigger) {
    const attribute = trigger?.getAttribute("lp-show") || trigger?.getAttribute("lp-close") || "";
    const [componentId] = attribute.split(":");
    if (isHomeSectionId(componentId)) {
      this._interactedSections.add(componentId);
      this._restoringSections.delete(componentId);
    }
    return super.renderComponent(trigger);
  }
  syncHomeSectionState(component) {
    const sectionId = component?.name || component?.elt?.id;
    if (!isHomeSectionId(sectionId)) return;
    const resolved = (component && "active" in component ? component : null) ?? this.components[sectionId] ?? null;
    const isOpen = this._isSectionListOpen(sectionId, resolved);
    const toggle = this._sectionToggle(sectionId, resolved);
    toggle?.setAttribute("aria-expanded", isOpen ? "true" : "false");
    if (isOpen) this._openSections.add(sectionId);
    else this._openSections.delete(sectionId);
  }
  _click(e) {
    const target = e?.target;
    if (e && target instanceof Element && target.closest("[data-role='dismiss-task-feedback']")) {
      e.preventDefault();
      const feedback = this.elt?.querySelector?.(
        "[data-role='task-feedback']"
      );
      if (feedback) {
        void withTransition(
          () => {
            feedback.dataset.visible = "false";
          },
          { label: "home:dismiss-task-feedback" }
        );
      }
      return;
    }
    super._click(e);
  }
  _setStarredCount(count) {
    const safeCount = Math.max(0, count);
    const countElt = this.elt?.querySelector?.(
      "[data-role='starred-count']"
    );
    if (countElt) countElt.textContent = String(safeCount);
    const toggle = this._sectionToggle("starred");
    if (toggle) {
      toggle.classList.toggle("opacity-50", safeCount === 0);
      toggle.classList.toggle("pointer-events-none", safeCount === 0);
    }
    if (safeCount === 0) {
      const list = this._sectionElement(
        "starred"
      )?.querySelector?.("[data-widget='StarredList']");
      if (list) list.dataset.visible = "false";
      this.syncHomeSectionState(this.components.starred);
    }
  }
  _adjustStarredCount(delta) {
    const countElt = this.elt?.querySelector?.(
      "[data-role='starred-count']"
    );
    if (!countElt) return;
    const current = Number.parseInt(countElt.textContent?.trim() || "0", 10);
    if (Number.isNaN(current)) return;
    this._setStarredCount(current + delta);
  }
  onComponentRendered(component) {
    const sectionId = component.name;
    if (!isHomeSectionId(sectionId)) return;
    if (sectionId === "tasks" && component.active?.name === "CreateUserTask") {
      const feedback = component.elt.querySelector(
        "[data-role='task-feedback']"
      );
      if (feedback) feedback.dataset.visible = "false";
    }
    const wasOpen = this._openSections.has(sectionId);
    this.syncHomeSectionState(component);
    const isOpen = this._openSections.has(sectionId);
    if (!this._suppressSectionPersist && isOpen !== wasOpen) {
      this._persistOpenSections();
    }
  }
  async reconcilePollingSubscriptions() {
    await super.reconcilePollingSubscriptions();
    this._syncHomePollingSubscriptions();
  }
  _syncHomePollingSubscriptions() {
    if (!this.PollingCoordinator) return;
    const loaded = /* @__PURE__ */ new Set();
    for (const component of Object.values(this.components)) {
      for (const widget of Object.values(component.widgets)) {
        const channel = widget && HOME_CHANNELS[widget.name];
        if (!widget?.loaded || !channel) continue;
        const id = `home:channel:${channel}`;
        loaded.add(id);
        if (this._homePollUnsubscribers.has(id)) continue;
        const unsubscribe = this.PollingCoordinator.subscribe(
          {
            id,
            type: "channel",
            channel,
            revision: widget.target?.dataset.pollRevision ?? null
          },
          {
            mode: "foreground",
            initial: "scheduled",
            onResult: async (result) => {
              if (result.status !== "changed") return;
              return await this._refreshHomeWidget(component, widget);
            }
          }
        );
        this._homePollUnsubscribers.set(id, unsubscribe);
      }
    }
    for (const [id, unsubscribe] of this._homePollUnsubscribers) {
      if (loaded.has(id)) continue;
      unsubscribe?.();
      this._homePollUnsubscribers.delete(id);
    }
  }
  async _prepareHomeWidgetRefresh(component, widget) {
    if (!widget?.loaded || !widget.route) return null;
    const response = await this.load(component, widget.route);
    if (!response || response.updated === false) return null;
    const commit = widget.prepareRefresh ? await widget.prepareRefresh(response) : () => widget.refresh?.(response);
    return () => {
      if (typeof commit === "function") commit();
      if (response.pollChannel && widget.target) {
        widget.target.dataset.pollChannel = response.pollChannel;
      }
      if (response.pollRevision && widget.target) {
        widget.target.dataset.pollRevision = response.pollRevision;
      }
    };
  }
  async _refreshHomeWidget(component, widget) {
    const commit = await this._prepareHomeWidgetRefresh(component, widget);
    if (!commit) return false;
    await withTransition(commit, { label: `home:refresh-${widget.name}` });
    return true;
  }
  async refreshSupplementalCollections(changes = []) {
    if (changes.some(({ type }) => type === "star" || type === "unstar")) {
      await this._refreshStarred();
    }
    if (changes.some(({ type }) => type === "delete")) this._hideEmptyLists();
  }
  async _refreshStarred() {
    const starredComponent = this.getComponent(
      document.getElementById("starred")
    );
    if (!starredComponent) return;
    const existingWidget = starredComponent.widgets.StarredList;
    const widget = existingWidget || await starredComponent.loadWidget("StarredList");
    if (!widget) return;
    const commit = existingWidget ? await this._prepareHomeWidgetRefresh(starredComponent, widget) : null;
    await starredComponent.prepareRender(true);
    await withTransition(
      () => {
        if (commit) commit();
        if (starredComponent.active === widget) {
          this._suppressSectionPersist = true;
          try {
            starredComponent.render(true);
          } finally {
            this._suppressSectionPersist = false;
          }
        }
      },
      { label: "home:refresh-starred" }
    );
    this._syncHomePollingSubscriptions();
  }
  _hideEmptyLists() {
    for (const component of Object.values(this.components)) {
      let hidAny = false;
      for (const widget of Object.values(component.widgets)) {
        const target = widget?.target;
        if (target?.tagName === "UL" && target.children.length === 0) {
          if (widget.name === "HomeActivityList" && "ensureEmptyState" in widget && typeof widget.ensureEmptyState === "function") {
            widget.ensureEmptyState();
            continue;
          }
          target.dataset.visible = "false";
          hidAny = true;
        }
      }
      if (hidAny) this.syncHomeSectionState(component);
    }
  }
  destroy() {
    for (const unsubscribe of this._homePollUnsubscribers.values()) {
      unsubscribe?.();
    }
    this._homePollUnsubscribers.clear();
    this._openSections.clear();
    this._restoringSections.clear();
    this._interactedSections.clear();
    super.destroy();
  }
}

export { Home as default };
