/*! Third-party licenses: /third-party-licenses.txt */
import { w as withTransition } from './foundation.js?v=b74a2211';
import { C as Core } from './core-foundation.js?v=b74a2211';

class TableVisibilityState {
  constructor({
    component,
    view,
    selected = [],
    columns = []
  }) {
    this.component = component;
    this.view = view;
    this.selected = selected;
    this.columns = columns;
    this.columnIndexes = /* @__PURE__ */ new Map();
    this.hiddenColumns = [];
    this.stylesheet = null;
    this.initialized = false;
    this._toggle = this._toggle.bind(this);
  }
  init() {
    if (this.initialized) return this;
    this.initialized = true;
    this.component.elt.querySelectorAll("th[data-column]").forEach((th, i) => {
      if (th.dataset.column !== void 0)
        this.columnIndexes.set(th.dataset.column, i + 1);
    });
    const saved = localStorage.getItem(`columns-${this.view.hash}`);
    try {
      const parsed = saved ? JSON.parse(saved) : null;
      this.hiddenColumns = Array.isArray(parsed) && parsed.every((index) => typeof index === "number") ? parsed : this.defaultHiddenColumns();
    } catch {
      this.hiddenColumns = this.defaultHiddenColumns();
    }
    this.apply();
    this.view.elt.addEventListener("toggle-column-visibility", this._toggle);
    return this;
  }
  get visibleColumns() {
    return this.columns.map((column) => column.field).filter((field) => {
      const index = this.columnIndexes.get(field);
      return index && !this.hiddenColumns.includes(index);
    });
  }
  defaultHiddenColumns() {
    const hidden = this.selected.length ? this.columns.filter((column) => !this.selected.includes(column.field)) : this.columns.filter((column) => column.selected !== true);
    return hidden.map((column) => this.columnIndexes.get(column.field)).filter((index) => index !== void 0);
  }
  _toggle(event) {
    if (!("detail" in event)) return;
    const { detail } = event;
    if (detail && typeof detail === "object" && "active" in detail && typeof detail.active === "boolean" && "column" in detail && typeof detail.column === "string") {
      this.toggle(detail.column, detail.active);
    }
  }
  toggle(column, visible) {
    if (column === void 0) return;
    const index = this.columnIndexes.get(column);
    if (!index) return;
    this.hiddenColumns = visible ? this.hiddenColumns.filter((value) => value !== index) : [.../* @__PURE__ */ new Set([...this.hiddenColumns, index])];
    this.apply();
    void this.component.widgets.TableEditor?.refreshCheckboxes?.();
  }
  apply() {
    localStorage.setItem(
      `columns-${this.view.hash}`,
      JSON.stringify(this.hiddenColumns)
    );
    if (!this.stylesheet) {
      this.stylesheet = new CSSStyleSheet();
      document.adoptedStyleSheets.push(this.stylesheet);
    }
    const id = this.component.elt.id;
    const rowSelector = `#${id} tr:not([data-widget], [data-embedded], [data-role="empty"], [data-role="loading"]) > td:not([data-column="delete"])`;
    const thSelector = `#${id} th:not([data-column="selector"], [data-embedded])`;
    this.stylesheet.replaceSync(
      this.hiddenColumns.map(
        (index) => `${rowSelector}:nth-child(${index}), ${thSelector}:nth-child(${index}) { display: none; }`
      ).join("\n")
    );
  }
  destroy() {
    this.view?.elt?.removeEventListener(
      "toggle-column-visibility",
      this._toggle
    );
    document.adoptedStyleSheets = document.adoptedStyleSheets.filter(
      (sheet) => sheet !== this.stylesheet
    );
    this.stylesheet = null;
    this.initialized = false;
  }
}

const INDEX_LOADING_DELAY_MS = 200;
const INDEX_SKELETON_ROWS = 4;
function isTableColumn(value) {
  return Boolean(
    value && typeof value === "object" && "field" in value && typeof value.field === "string" && (!("title" in value) || typeof value.title === "string") && (!("selected" in value) || typeof value.selected === "boolean")
  );
}
class EntityIndex extends Core {
  constructor(node) {
    super(node);
    this.dropdown = null;
    this.nav = null;
    this.toolsObserver = null;
    this._tableLoadingTimer = null;
    this._tableLoadingTarget = null;
    this._tableLoadingToken = 0;
  }
  async init() {
    await super.init();
    const table = this.getComponent(this.elt.querySelector("#table"));
    if (!table) throw new Error("Entity index requires a table component");
    const tools = this.elt.querySelector("#tools");
    const mobileControls = this.elt.querySelector("#mobile-controls");
    let indexTable = null;
    if (this.mobile && tools) {
      await this._createDropdown();
      const toolsNav = document.querySelector(
        "nav[data-nav='tools']"
      );
      if (toolsNav) toolsNav.style.display = "none";
    }
    const selected = table.preload("selected");
    const columns = table.preload("columns");
    this.TableVisibilityState = new TableVisibilityState({
      component: table,
      view: this,
      selected: Array.isArray(selected) ? selected.filter((field) => typeof field === "string") : [],
      columns: Array.isArray(columns) ? columns.filter(isTableColumn) : []
    }).init();
    if (!table.elt.hasAttribute("lp-prefetch")) {
      indexTable = await table.loadWidget("IndexTable");
    }
    await table.prepareRender(true);
    await withTransition(
      () => {
        table.render(true);
      },
      { label: "index:initial-table" }
    );
    if (table.elt.hasAttribute("lp-prefetch")) {
      this._scheduleTableLoading(table.elt);
    }
    const continuation = indexTable?.target?.querySelector("tr[lp-load]");
    if (continuation && indexTable?.target) {
      const route = continuation.dataset.route;
      continuation.remove();
      indexTable.target.removeAttribute("loaded");
      indexTable.loaded = false;
      indexTable.loading = true;
      void table.load(indexTable, route);
    }
    this._indexMobileResize = async () => {
      const toolsNav = document.querySelector(
        "nav[data-nav='tools']"
      );
      if (this.mobile) await this._createDropdown();
      await withTransition(
        () => {
          if (!this.mobile) {
            if (mobileControls) mobileControls.dataset.visible = "false";
            this._setMobileControlsDropdownOpen(false);
            toolsNav?.removeAttribute("style");
          } else {
            if (tools) this.getComponent(tools)?.deactivate(false);
            if (toolsNav) toolsNav.style.display = "none";
          }
          table.widgets.TableSorting?.reset();
        },
        { label: "index:mobile-resize" }
      );
    };
    this.elt.addEventListener("mobile-resize", this._indexMobileResize);
    if (!tools) {
      return;
    }
    const thead = table.elt.querySelector("thead");
    this.toolsObserver = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.attributeName === "data-visible") {
          const visible = tools?.dataset.visible === "true";
          thead?.classList.toggle("sticky", !visible);
        }
      }
    });
    this.toolsObserver.observe(tools, { attributes: true });
    await this._renderDefaultTool(tools);
  }
  _click(e) {
    const { target } = e;
    if (!(target instanceof Element)) return;
    const toolsTrigger = target.closest("[data-role='tools-dropdown']");
    if (this.mobile && toolsTrigger && !this.dropdown) {
      e.preventDefault();
      e.stopPropagation();
      void this.runColdAction(
        toolsTrigger,
        () => this._createDropdown(),
        (dropdown) => dropdown?.showPanel?.(),
        toolsTrigger
      );
      return;
    }
    const tableControls = target.closest(
      "button[lp-show='table:MobileTableControls']"
    );
    if (this.mobile && tableControls) {
      this.dropdown?.hidePanel();
      this._setMobileControlsDropdownOpen(false);
      const tools = this.elt.querySelector("#tools");
      if (tools?.dataset.visible === "true") {
        this.getComponent(tools)?.deactivate(false);
      }
    }
    super._click(e);
  }
  _defaultToolSlug() {
    return this.querySlug(this.queryParam("tool"));
  }
  _defaultToolTarget(tools) {
    const tool = this._defaultToolSlug();
    if (!tool) return null;
    const buttons = tools.querySelectorAll(
      "nav[data-nav='tools'] button[lp-show]"
    );
    for (const button of buttons) {
      const attribute = button.getAttribute("lp-show");
      if (!attribute) continue;
      const [componentId, widgetName] = attribute.split(":");
      const candidates = [
        componentId,
        widgetName,
        attribute.replace(":", "-"),
        button.textContent
      ];
      if (candidates.some((candidate) => this.querySlug(candidate) === tool)) {
        return { componentId, widgetName };
      }
    }
    const widget = Array.from(
      tools.querySelectorAll("[data-widget]")
    ).find((elt) => this.querySlug(elt.dataset.widget) === tool);
    if (!widget) return null;
    return {
      componentId: widget.closest("[lp-component]")?.id || tools.id,
      widgetName: widget.dataset.widget
    };
  }
  async _renderDefaultTool(tools) {
    const target = this._defaultToolTarget(tools);
    if (!target) return;
    const component = this.getComponent(
      document.getElementById(target.componentId)
    );
    if (!component) return;
    const activated = await component.activate(target.widgetName || "default");
    await component.prepareRender(activated);
    await withTransition(
      () => {
        component.render(activated);
      },
      { label: "index:default-tool" }
    );
  }
  _setMobileControlsDropdownOpen(open) {
    const mobileControls = this.elt.querySelector("#mobile-controls");
    if (!mobileControls) return;
    mobileControls.classList.toggle("opacity-50", open);
    mobileControls.classList.toggle("pointer-events-none", open);
  }
  async _createDropdown() {
    if (this.dropdown) return;
    if (this._dropdownPromise) return this._dropdownPromise;
    const trigger = this.elt.querySelector(
      "[data-role='tools-dropdown']"
    );
    if (!trigger) return;
    this._dropdownPromise = Promise.all([
      import('./combobox.js?v=b74a2211').then(function (n) { return n.e; }),
      import('./ui-resources.js?v=b74a2211').then(function (n) { return n.a; })
    ]).then(([{ Dropdown }, { STYLES }]) => {
      if (this._destroyed || !this.mobile) return null;
      const items = [];
      const createOption = (button) => {
        const option = button.cloneNode(true);
        option.setAttribute("role", "option");
        option.removeAttribute("data-selected");
        option.className = STYLES.index.tools.dropdown.toggle;
        return option.outerHTML;
      };
      document.querySelectorAll("nav[data-nav='tools'] button").forEach((button) => {
        if (button.dataset.visible === "false") return;
        items.push({
          html: createOption(button),
          onClick: () => {
            const mobileControls = this.elt.querySelector("#mobile-controls");
            const table = this.getComponent(
              this.elt.querySelector("#table")
            );
            if (table?.active?.name === "MobileTableControls") {
              table.deactivate(false);
            } else if (mobileControls) {
              mobileControls.dataset.visible = "false";
            }
            this._setMobileControlsDropdownOpen(false);
            this.renderComponent(button);
          }
        });
      });
      this.dropdown = new Dropdown(trigger);
      this.dropdown.init({
        items,
        placement: "bottom-end",
        styles: {
          panel: STYLES.index.tools.dropdown.panel
        },
        onShow: () => this._setMobileControlsDropdownOpen(true),
        onHide: () => this._setMobileControlsDropdownOpen(false)
      });
      return this.dropdown;
    }).catch((error) => {
      this.reportStartupError(error, trigger, "index-tools-dropdown");
      return null;
    }).finally(() => {
      this._dropdownPromise = null;
    });
    return this._dropdownPromise;
  }
  async prefetch() {
    try {
      await super.prefetch();
    } finally {
      const table = this.getComponent(this.elt.querySelector("#table"));
      const indexTable = table?.widgets?.IndexTable;
      if (!indexTable?.loading || indexTable.loaded) {
        this.clearTableLoading();
      }
    }
  }
  _scheduleTableLoading(tableElt) {
    const tbody = tableElt.querySelector(
      "tbody[data-widget='IndexTable']"
    );
    if (!tbody || tbody.hasAttribute("loaded") || tbody.querySelector("tr[lp-entity]")) {
      return;
    }
    this.clearTableLoading();
    this._tableLoadingTarget = tbody;
    const token = ++this._tableLoadingToken;
    this._tableLoadingTimer = setTimeout(() => {
      this._tableLoadingTimer = null;
      void this._showTableLoading(tableElt, tbody, token);
    }, INDEX_LOADING_DELAY_MS);
  }
  async _showTableLoading(tableElt, tbody, token) {
    if (this._destroyed || token !== this._tableLoadingToken || !tbody.isConnected || tbody.hasAttribute("loaded") || tbody.querySelector("tr[lp-entity]") || tbody.querySelector("tr[data-role='loading']")) {
      return;
    }
    const { STYLES } = await import('./ui-resources.js?v=b74a2211').then(function (n) { return n.a; });
    if (this._destroyed || token !== this._tableLoadingToken || !tbody.isConnected || tbody.hasAttribute("loaded") || tbody.querySelector("tr[lp-entity]") || tbody.querySelector("tr[data-role='loading']")) {
      return;
    }
    const columnCount = tableElt.querySelectorAll("thead > tr:first-child > th").length || 1;
    const row = document.createElement("tr");
    row.dataset.role = "loading";
    row.dataset.visible = "true";
    row.setAttribute("aria-live", "polite");
    const cell = document.createElement("td");
    cell.colSpan = columnCount;
    cell.className = STYLES.table.loading.cell;
    const srLabel = document.createElement("span");
    srLabel.className = "sr-only";
    srLabel.setAttribute("role", "status");
    srLabel.textContent = "Loading rows";
    cell.append(srLabel);
    const list = document.createElement("div");
    list.className = STYLES.table.loading.list;
    list.setAttribute("aria-hidden", "true");
    for (let i = 0; i < INDEX_SKELETON_ROWS; i += 1) {
      const item = document.createElement("div");
      item.className = STYLES.table.loading.item;
      const primary = document.createElement("span");
      primary.className = STYLES.table.loading.barPrimary;
      const secondary = document.createElement("span");
      secondary.className = STYLES.table.loading.barSecondary;
      item.append(primary, secondary);
      list.append(item);
    }
    cell.append(list);
    row.append(cell);
    tbody.setAttribute("aria-busy", "true");
    tbody.prepend(row);
  }
  clearTableLoading() {
    this._tableLoadingToken += 1;
    if (this._tableLoadingTimer !== null && this._tableLoadingTimer !== void 0) {
      clearTimeout(this._tableLoadingTimer);
      this._tableLoadingTimer = null;
    }
    const tbody = this._tableLoadingTarget || this.elt.querySelector(
      "#table tbody[data-widget='IndexTable']"
    );
    this._tableLoadingTarget = null;
    if (!tbody) return;
    tbody.removeAttribute("aria-busy");
    tbody.querySelector("tr[data-role='loading']")?.remove();
  }
  destroy() {
    this.clearTableLoading();
    if (this._indexMobileResize)
      this.elt.removeEventListener("mobile-resize", this._indexMobileResize);
    super.destroy();
    this._setMobileControlsDropdownOpen(false);
    this.dropdown?.destroy();
    this.dropdown = null;
    this.toolsObserver?.disconnect();
    this.toolsObserver = null;
    this.TableVisibilityState?.destroy();
    this.TableVisibilityState = null;
  }
}

export { EntityIndex as E, INDEX_LOADING_DELAY_MS as I, TableVisibilityState as T };
