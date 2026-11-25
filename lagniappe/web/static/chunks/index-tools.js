/*! Third-party licenses: /third-party-licenses.txt */
import { B as BaseTable } from './baseTable.js?v=b8c49d0d';
import { c as captureError, w as withTransition, j as sessionStore } from './foundation.js?v=b8c49d0d';
import { p as primitives } from './ui-controls.js?v=b8c49d0d';
import { T as TableVisibilityState } from './index-foundation.js?v=b8c49d0d';

class IndexTable extends BaseTable {
  constructor(attributes) {
    super(attributes);
    this.refreshScope = "collection";
    this.loading = false;
    this.loaded = !this.prefetched || this.target.hasAttribute("loaded");
    this._empty = false;
    this._updated = [];
    this._created = [];
  }
  async updated(response) {
    const html = response.html || null;
    this._updated = html?.querySelectorAll("tr[lp-entity]") || [];
    const append = html?.querySelector("tr[lp-load]");
    this.loaded = !append;
    return append;
  }
  async created(response) {
    this._created = (response.html || null)?.querySelectorAll("tr") || [];
  }
  get selector() {
    return this.component.elt.querySelector(
      "th[data-column='selector'] button"
    );
  }
  _clearLoadingState() {
    this.target.removeAttribute("aria-busy");
    for (const row of this.target.querySelectorAll("tr[data-role='loading']")) {
      row.remove();
    }
    this.view.clearTableLoading?.();
  }
  setEmptyRowVisibility() {
    this._clearLoadingState();
    const emptyRow = this.target.querySelector(
      "tr[data-role='empty']"
    );
    const notEmpty = this.target.querySelector("tr[lp-entity]");
    if (emptyRow) {
      if (!this.view.mobile) {
        emptyRow.dataset.visible = notEmpty ? "false" : "true";
      } else {
        emptyRow.style.display = notEmpty ? "none" : "block";
      }
    }
    if (!notEmpty) {
      this.loaded = true;
      this.target.setAttribute("loaded", "");
    }
  }
  get prefetched() {
    return this.target.hasAttribute("lp-prefetch");
  }
  refreshDescriptor() {
    if (this.component.name !== "table" || !this.target.hasAttribute("loaded")) {
      return null;
    }
    const supported = Boolean(this.view.key) || ["forms", "tasks", "users"].includes(this.view.elt.dataset.index ?? "");
    if (!supported) return null;
    return {
      rows: Array.from(
        this.target.querySelectorAll("tr[lp-entity]"),
        (row) => ({
          key: row.dataset.key,
          hash: row.dataset.hash || "",
          fingerprint: row.dataset.fingerprint || ""
        })
      )
    };
  }
  _parseRefreshRow(html) {
    if (!html) return null;
    const template = document.createElement("template");
    template.innerHTML = html.trim();
    return template.content.querySelector("tr[lp-entity]");
  }
  refreshDelta(delta) {
    const editor = this.component?.widgets?.TableEditor;
    const existing = new Map(
      Array.from(
        this.target.querySelectorAll("tr[lp-entity]"),
        (row) => [row.dataset.key, row]
      )
    );
    editor?.releaseRows([
      ...(delta.remove || []).map((key) => existing.get(key)),
      ...(delta.upsert || []).map(({ key }) => existing.get(key))
    ]);
    for (const key of delta.remove || []) {
      existing.get(key)?.remove();
      existing.delete(key);
    }
    const added = [];
    for (const update of delta.upsert || []) {
      const row = this._parseRefreshRow(update.html);
      if (!row || row.dataset.key !== update.key) {
        throw new Error("Invalid table refresh row");
      }
      const current = existing.get(update.key);
      if (current) {
        current.replaceWith(row);
      } else added.push(row);
      existing.set(update.key, row);
    }
    const order = Array.isArray(delta.order) ? delta.order : [];
    let next = this.target.querySelector("tr[lp-entity]");
    for (const key of order) {
      const row = existing.get(key);
      if (!row) throw new Error("Table refresh order references a missing row");
      if (row !== next) this.target.insertBefore(row, next);
      else {
        next = next.nextElementSibling;
        while (next && !next.matches("tr[lp-entity]")) {
          next = next.nextElementSibling;
        }
      }
    }
    for (const row of added) this.view.addFlash(row);
    let empty = this.target.querySelector("tr[data-role='empty']");
    if (!order.length && !empty && delta.empty) {
      const template = document.createElement("template");
      template.innerHTML = delta.empty.trim();
      empty = template.content.querySelector("tr[data-role='empty']");
      if (empty) this.target.append(empty);
    }
    this.setEmptyRowVisibility();
    this.sortingWidget?.refreshRows?.();
    void editor?.refreshCheckboxes().catch(captureError);
  }
  refresh(response) {
    if (!response?.html) return;
    const editor = this.component?.widgets?.TableEditor;
    const newRows = [
      ...response.html.querySelectorAll("tr[lp-entity]")
    ];
    const newKeys = new Set(
      newRows.map((row) => row.dataset.key).filter(Boolean)
    );
    const prepend = [];
    editor?.releaseRows(
      Array.from(
        this.target.querySelectorAll("tr[lp-entity]")
      ).filter((row) => !this.prefetched || newKeys.has(row.dataset.key ?? ""))
    );
    for (const newRow of newRows) {
      const key = newRow.dataset.key;
      if (!key) continue;
      const existing = this.target.querySelector(`tr[data-key="${key}"]`);
      if (existing) {
        existing.replaceWith(newRow);
      } else prepend.push(newRow);
    }
    if (prepend.length) {
      const anchor = this.target.querySelector("tr[lp-entity]");
      if (anchor) anchor.before(...prepend);
      else this.target.append(...prepend);
      for (const row of prepend) this.view.addFlash(row);
    }
    if (!this.prefetched) {
      this.target.querySelectorAll("tr[lp-entity]").forEach((row) => {
        if (!newKeys.has(row.dataset.key ?? "")) {
          row.remove();
        }
      });
    }
    this.setEmptyRowVisibility();
    this.sortingWidget?.refreshRows?.();
    void editor?.refreshCheckboxes().catch(captureError);
  }
  async prereconcile() {
    const loaded = this.target.hasAttribute("loaded");
    if (!this.loaded || loaded) return;
    const sorting = await this.component.loadWidget("TableSorting");
    await sorting?.init?.();
    this._finishLoading = true;
  }
  postreconcile() {
    const target = this.target;
    let rowsChanged = false;
    const sortingWasInitialized = this.sortingWidget?.initialized === true;
    if (this._created.length > 0) {
      target.prepend(...this._created);
      for (const row of this._created) this.view.addFlash(row);
      this._created = [];
      rowsChanged = true;
      if (this.view.mobile) {
        target.scrollIntoView({ behavior: "auto", block: "start" });
      }
    }
    if (this._updated.length > 0) {
      target.append(...this._updated);
      this._updated = [];
      rowsChanged = true;
    }
    if (this._finishLoading) {
      this._finishLoading = false;
      this.target.setAttribute("loaded", "");
      this.setEmptyRowVisibility();
      target.dataset.visible = "true";
      this.loading = false;
    }
    if (rowsChanged) {
      this.setEmptyRowVisibility();
      if (sortingWasInitialized) this.sortingWidget?.refreshRows?.();
      void this.component?.widgets?.TableEditor?.refreshCheckboxes().catch(
        captureError
      );
    } else if (this.target.hasAttribute("loaded")) {
      this._clearLoadingState();
    }
  }
  destroy() {
    this._clearLoadingState();
    super.destroy();
  }
}

var indexTable = /*#__PURE__*/Object.freeze({
	__proto__: null,
	IndexTable: IndexTable
});

class MobileTableControls {
  constructor(attributes) {
    Object.assign(this, attributes);
  }
  get target() {
    return this.view.elt.querySelector(
      "[data-widget='MobileTableControls']"
    );
  }
  async init() {
    await this.component.loadWidget("TableVisibility");
    const visibility = this.component.widgets.TableVisibility;
    this._syncVisibilityButtons(visibility?.visibleColumns ?? []);
    this.target?.addEventListener("click", (e) => this._handleButtonClick(e));
  }
  postreconcile() {
    const sorting = this.component.widgets.TableSorting;
    if (sorting?.initialized) sorting.refreshRows?.();
  }
  _syncVisibilityButtons(visibleColumns) {
    this.target?.querySelectorAll("button[data-toggle='visibility']").forEach((button) => {
      const column = button.closest("[data-column]")?.dataset.column;
      button.dataset.active = column !== void 0 && visibleColumns.includes(column) ? "true" : "false";
    });
  }
  _handleButtonClick(e) {
    const button = e.target instanceof Element ? e.target.closest("button") : null;
    if (!button) return;
    const active = button.dataset.active === "false";
    button.dataset.active = active ? "true" : "false";
    if (button.matches("[data-toggle='visibility']")) {
      this._dispatchVisibilityToggle(button, active);
    } else if (button.matches("[data-toggle='filter']")) {
      this._dispatchFilterToggle(button);
    }
  }
  _dispatchVisibilityToggle(button, active) {
    const event = new CustomEvent(
      "toggle-column-visibility",
      {
        detail: {
          column: button.closest("[data-column]")?.dataset.column,
          active
        },
        bubbles: true
      }
    );
    this.target?.dispatchEvent(event);
  }
  _dispatchFilterToggle(button) {
    const event = new CustomEvent(
      "toggle-column-filter",
      {
        detail: {
          column: button.closest("[data-column]")?.dataset.column
        },
        bubbles: true
      }
    );
    this.target?.dispatchEvent(event);
  }
}

var mobileControls = /*#__PURE__*/Object.freeze({
	__proto__: null,
	MobileTableControls: MobileTableControls
});

class TableSorting {
  constructor(attributes) {
    Object.assign(this, attributes);
    const columns = this.component.preload("columns");
    this.columns = Array.isArray(columns) ? columns : [];
    this.sorts = /* @__PURE__ */ new Map();
    this.containers = /* @__PURE__ */ new Map();
    this.toggles = /* @__PURE__ */ new Map();
    this.headers = /* @__PURE__ */ new Map();
    this.lastReorderColumn = null;
    this.initialized = false;
    this._destroyed = false;
    this._onFilterToggle = this._filterToggle.bind(this);
  }
  get storageKey() {
    return `sorts-${this.view.hash}`;
  }
  get header() {
    return this.component.elt.querySelector(
      "thead > tr:first-child"
    );
  }
  get body() {
    return this.component.elt.querySelector("tbody");
  }
  get rows() {
    return Array.from(this.body?.querySelectorAll("tr") ?? []).filter(
      (row) => row.dataset.visible !== "false" && row.dataset.role !== "loading"
    );
  }
  init() {
    if (this._destroyed || this.initialized) return;
    this.initialized = true;
    this._setSortingToggles();
    const saved = this._loadState();
    this.header?.querySelectorAll("th[data-ordering]").forEach((th) => {
      const column = th.dataset.column;
      const ordering = th.dataset.ordering;
      if (!column || !ordering) return;
      this.headers.set(column, th);
      const sort = this._enableSort(this._createSort(column, ordering));
      sort.restore(saved?.sorts?.[column]);
    });
    this._restoreLastReorderColumn(saved);
    if (this._hasActiveSorts()) this.sort();
    this.view.elt.addEventListener(
      "toggle-column-filter",
      this._onFilterToggle
    );
  }
  _filterToggle(e) {
    if (this._destroyed || !("detail" in e)) return;
    const { detail } = e;
    if (!detail || typeof detail !== "object" || !("column" in detail) || typeof detail.column !== "string")
      return;
    const { column } = detail;
    if (this.view.mobile) {
      void withTransition(
        () => {
          if (this._destroyed) return;
          const current = this.sorts.get(column);
          if (!current) return;
          const sort = this._enableSort(current);
          if (sort.active) {
            const toggle = this.toggles.get(column);
            if (toggle) toggle.dataset.active = "true";
          }
          const container = this.containers.get(column);
          if (!container) return;
          const visible = container.dataset.visible === "true";
          container.dataset.visible = visible ? "false" : "true";
        },
        { label: "table-sorting:toggle-mobile" }
      );
    } else {
      void this._toggleColumn(
        column,
        "button" in detail && detail.button instanceof HTMLElement ? detail.button : null
      );
    }
  }
  reset() {
    if (this._destroyed) return;
    this.containers.forEach((container) => {
      container.remove();
    });
    this.sorts.forEach((sort) => {
      sort.clear();
    });
    this._clearState();
    this.containers = /* @__PURE__ */ new Map();
    this.toggles = /* @__PURE__ */ new Map();
    this.headers = /* @__PURE__ */ new Map();
    this.lastReorderColumn = null;
    this._setSortingToggles();
    this.header?.querySelectorAll("th[data-ordering]").forEach((th) => {
      const column = th.dataset.column;
      const ordering = th.dataset.ordering;
      if (!column || !ordering) return;
      this.headers.set(column, th);
      th.dataset.sorting = "false";
      this._enableSort(this._createSort(column, ordering));
    });
  }
  /**
   * Rebuild row-value caches after server row replacement while preserving active sorts.
   *
   */
  refreshRows() {
    if (this._destroyed || !this.initialized) return;
    const saved = {
      lastReorderColumn: this.lastReorderColumn,
      sorts: Object.fromEntries(
        Array.from(this.sorts, ([column, sort]) => [
          column,
          sort.state
        ])
      )
    };
    this.containers.forEach((container) => {
      container.remove();
    });
    this.sorts = /* @__PURE__ */ new Map();
    this.containers = /* @__PURE__ */ new Map();
    this.toggles = /* @__PURE__ */ new Map();
    this.headers = /* @__PURE__ */ new Map();
    this.lastReorderColumn = null;
    this._setSortingToggles();
    this.header?.querySelectorAll("th[data-ordering]").forEach((th) => {
      const column = th.dataset.column;
      const ordering = th.dataset.ordering;
      if (!column || !ordering) return;
      this.headers.set(column, th);
      th.dataset.sorting = "false";
      const sort = this._enableSort(this._createSort(column, ordering));
      sort.restore(saved.sorts[column]);
    });
    this._restoreLastReorderColumn(saved);
    if (this._hasActiveSorts()) this.sort();
  }
  _loadState() {
    const saved = sessionStore.getJSON(this.storageKey);
    if (saved === null) return null;
    if (typeof saved === "object" && saved !== null && !Array.isArray(saved))
      return saved;
    sessionStore.remove(this.storageKey);
    return null;
  }
  _saveState() {
    const sorts = {};
    this.sorts.forEach((sort) => {
      const state = sort.state;
      if (state) sorts[sort.column] = state;
    });
    if (Object.keys(sorts).length) {
      sessionStore.setJSON(this.storageKey, {
        lastReorderColumn: this.lastReorderColumn,
        sorts
      });
    } else {
      this._clearState();
    }
  }
  _clearState() {
    sessionStore.remove(this.storageKey);
  }
  _restoreLastReorderColumn(saved) {
    const savedSort = saved?.lastReorderColumn ? this.sorts.get(saved.lastReorderColumn) : void 0;
    if (savedSort?.active && savedSort.reordering) {
      this.lastReorderColumn = savedSort.column;
      return;
    }
    const activeSort = Array.from(this.sorts.values()).find((sort) => {
      return sort.active && sort.reordering;
    });
    this.lastReorderColumn = activeSort?.column || null;
  }
  _hasActiveSorts() {
    return Array.from(this.sorts.values()).some((sort) => sort.active);
  }
  _markSortActive(sort) {
    const header = this.headers.get(sort.column);
    if (header) header.dataset.sorting = "true";
    if (!this.view.mobile) return;
    const toggle = this.toggles.get(sort.column);
    if (toggle) toggle.dataset.active = "true";
  }
  _setSortingToggles() {
    const container = this.view.mobile ? document.getElementById("mobile-controls") : this.header;
    container?.querySelectorAll("button[data-toggle='filter']").forEach((button) => {
      const column = button.closest("[data-column]")?.dataset.column;
      if (column) this.toggles.set(column, button);
    });
  }
  async _toggleColumn(column, button) {
    await withTransition(
      () => {
        if (this._destroyed) return;
        const current = this.sorts.get(column);
        if (!current) return;
        const sort = this._enableSort(current);
        if (sort.disabled) return;
        const visible = this.visible;
        const container = this.containers.get(column);
        if (!container) return;
        this.containers.forEach((candidate) => {
          if (candidate !== container) candidate.dataset.visible = "false";
        });
        if (button && sort.active) {
          this.visible = false;
          sort.sortedBy = null;
          this.sort();
        } else if (this.visible && container.dataset.visible === "true") {
          this.visible = false;
        } else {
          container.dataset.visible = "true";
          this.visible = true;
        }
        this.modified = visible !== this.visible;
        if (this.modified && this.visible) {
          this.component.active = this;
          this.component.render(true);
        } else if (this.modified && !this.visible) {
          this.component.active = null;
          this.component.render(false);
        }
      },
      { label: "table-sorting:toggle" }
    );
  }
  _resetRows(reorderRows, showRows) {
    if (!reorderRows && showRows.size === 0) return null;
    const initialOrder = reorderRows ? /* @__PURE__ */ new WeakMap() : null;
    this.body?.querySelectorAll("tr").forEach((row) => {
      if (showRows.has(row)) {
        row.dataset.visible = "true";
      }
      if (!initialOrder) return;
      const modifiedColumn = Number(
        row.querySelector(`td[data-column="modified"]`)?.dataset.sortValue || 0
      );
      initialOrder.set(row, modifiedColumn * -1);
    });
    return initialOrder;
  }
  sort() {
    if (this._destroyed) return;
    let reorderRows = false;
    const showRows = /* @__PURE__ */ new Set();
    this.sorts.forEach((sort) => {
      if (sort.reordering && this.lastReorderColumn !== sort.column) {
        sort.sortedBy = null;
      }
      if (sort.active || !sort.sorted) return;
      for (const row of sort.hiddenRows ?? []) showRows.add(row);
      if (sort.reordering) reorderRows = true;
      this._resetSort(sort);
    });
    this.sorts.forEach((sort) => {
      if (!sort.active || !sort.hiddenRows) return;
      sort.hiddenRows.forEach((row) => {
        showRows.add(row);
      });
    });
    const initialOrder = this._resetRows(reorderRows, showRows);
    this.sorts.forEach((sort) => {
      if (!sort.active || sort.reordering) return;
      sort.sort();
      this._markSortActive(sort);
    });
    const reorderingSort = this.lastReorderColumn === null ? void 0 : this.sorts.get(this.lastReorderColumn);
    if (reorderingSort?.active) {
      reorderingSort.sort();
      this._markSortActive(reorderingSort);
    } else if (initialOrder) {
      const rows = this.rows;
      rows.sort((a, b) => {
        return (initialOrder.get(a) ?? 0) - (initialOrder.get(b) ?? 0);
      });
      this.body?.append(...rows);
      this.lastReorderColumn = null;
    }
    this._saveState();
  }
  _createContainer(column) {
    const container = this.view.mobile ? this._createSection(column) : this._createCell(column);
    this.containers.set(column, container);
    return container;
  }
  _createCell(column) {
    const cell = document.createElement("td");
    cell.colSpan = this.component.elt.querySelectorAll("th").length;
    cell.className = `p-3 border-t bg-kind-bg border-slate-300`;
    cell.dataset.sorts = column;
    cell.dataset.visible = "false";
    this.target.appendChild(cell);
    return cell;
  }
  _createSection(column) {
    const section = document.createElement("div");
    section.className = `flex flex-col gap-2 p-4 bg-white outline-kind-default rounded-md outline-1`;
    section.dataset.sorts = column;
    section.dataset.visible = "false";
    const controls = document.getElementById("mobile-controls");
    controls?.querySelector(`[data-column="${column}"]`)?.after(section);
    return section;
  }
  _createCheckboxElement(sort) {
    const container = this.containers.get(sort.column);
    if (!container) return;
    const element = container.appendChild(document.createElement("div"));
    if (sort.options === null) return;
    if (Object.keys(sort.options).length > 4 && !this.view.mobile) {
      element.className = `grid grid-cols-[repeat(auto-fit,minmax(120px,1fr))] gap-4`;
    } else if (!this.view.mobile) {
      element.className = `flex flex-row flex-wrap gap-4`;
    } else {
      element.className = `flex flex-col gap-2`;
    }
    sort.createOptions(element);
  }
  _createRadioElement(sort) {
    const container = this.containers.get(sort.column);
    if (!container) return;
    const element = container.appendChild(document.createElement("fieldset"));
    element.className = `flex flex-row flex-wrap gap-4`;
    sort.createOptions(element);
  }
  _createSortElement(sort) {
    if (sort instanceof CheckboxSort) {
      this._createCheckboxElement(sort);
    } else {
      this._createRadioElement(sort);
    }
  }
  _enableSort(sort) {
    sort.init();
    const toggle = this.toggles.get(sort.column);
    if (toggle) toggle.dataset.visible = sort.disabled ? "false" : "true";
    if (sort.disabled) return sort;
    const container = this.containers.get(sort.column) ?? this._createContainer(sort.column);
    if (!container.children.length) {
      this._createSortElement(sort);
    }
    return sort;
  }
  _resetSort(sort) {
    sort.clear();
    const container = this.containers.get(sort.column);
    if (container) {
      container.remove();
      this.containers.delete(sort.column);
    }
    const header = this.headers.get(sort.column);
    if (header) header.dataset.sorting = "false";
    if (this.view.mobile) {
      const toggle = this.toggles.get(sort.column);
      if (toggle) toggle.dataset.active = "false";
    }
  }
  _createSort(column, ordering) {
    const sort = ordering === "categorical" ? new CheckboxSort(this, column) : new RadioSort(this, column, ordering);
    this.sorts.set(column, sort);
    return sort;
  }
  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;
    this.initialized = false;
    this.visible = false;
    this.view.elt.removeEventListener(
      "toggle-column-filter",
      this._onFilterToggle
    );
    for (const container of this.containers.values()) container.remove();
    this.containers.clear();
    this.sorts.clear();
    this.toggles.clear();
    this.headers.clear();
    this.lastReorderColumn = null;
  }
}
class RadioSort {
  constructor(orchestrator, column, ordering) {
    this.orchestrator = orchestrator;
    this.column = column;
    this.ordering = ordering;
    this.reordering = this.ordering === "numeric" || this.ordering === "lexical";
    this.rowValues = null;
    this.hiddenRows = null;
    this.sortedBy = null;
    this.sortValue = null;
    this.initialized = false;
    this.sorted = false;
  }
  get disabled() {
    return false;
  }
  get active() {
    return this.sortedBy != null;
  }
  get defaultValue() {
    return ["boolean", "exists"].includes(this.ordering) ? "all" : "none";
  }
  get state() {
    return this.active ? { value: this.sortValue } : null;
  }
  get options() {
    const setOptions = (options) => {
      if (this.sortValue === null) this.sortValue = this.defaultValue;
      return options;
    };
    switch (this.ordering) {
      case "boolean":
        return setOptions([
          { value: "all", label: "All" },
          { value: "true", label: "True" },
          { value: "false", label: "False" }
        ]);
      case "exists":
        return setOptions([
          { value: "all", label: "All" },
          { value: "with", label: "With" },
          { value: "without", label: "Without" }
        ]);
      case "numeric":
        return setOptions([
          { value: "none", label: "None" },
          { value: "asc", label: "Low \u2192 High" },
          { value: "desc", label: "High \u2192 Low" }
        ]);
      default:
        return setOptions([
          { value: "none", label: "None" },
          { value: "asc", label: "A \u2192 Z" },
          { value: "desc", label: "Z \u2192 A" }
        ]);
    }
  }
  createOptions(element) {
    for (const option of this.options) {
      element.appendChild(
        primitives.radio({
          name: this.column,
          value: option.value,
          label: option.label,
          kind: this.orchestrator.kind,
          checked: this.sortValue === option.value
        })
      );
    }
    element.addEventListener("change", (e) => {
      if (!(e.target instanceof HTMLInputElement)) return;
      this.sortValue = e.target.value;
      this.sortedBy = this.sortBy(this.sortValue);
      if (!this.rowValues) this.init();
      if (this.reordering) {
        this.orchestrator.lastReorderColumn = this.sortedBy !== null ? this.column : null;
      }
      this.orchestrator.sort();
    });
  }
  restore(state) {
    if (typeof state?.value !== "string" || !state.value) return;
    if (!this.options.some((option) => option.value === state.value)) return;
    this.sortValue = state.value;
    this.sortedBy = this.sortBy(this.sortValue);
    if (!this.active) return;
    this.orchestrator.containers.get(this.column)?.querySelectorAll("input[type='radio']").forEach((input) => {
      if (input.name === this.column) {
        input.checked = input.value === this.sortValue;
      }
    });
  }
  init() {
    if (this.initialized) return;
    const rowValues = /* @__PURE__ */ new WeakMap();
    this.rowValues = rowValues;
    this.orchestrator.rows.forEach((row) => {
      const cell = row.querySelector(
        `td[data-column="${this.column}"][data-sort-value]`
      );
      if (cell?.dataset.sortValue === void 0) return;
      rowValues.set(row, JSON.parse(cell.dataset.sortValue));
    });
    this.initialized = true;
    return this;
  }
  sortBy(value) {
    switch (value) {
      case "none":
        return null;
      case "all":
        return null;
      case "asc":
        return 1;
      case "desc":
        return -1;
      case "true":
        return true;
      case "false":
        return false;
      case "with":
        return true;
      case "without":
        return false;
      default:
        return null;
    }
  }
  sort() {
    const { rowValues, sortedBy } = this;
    if (!rowValues || sortedBy === null) return;
    const hiddenRows = /* @__PURE__ */ new Set();
    this.hiddenRows = hiddenRows;
    const rows = this.orchestrator.rows;
    if (typeof sortedBy === "boolean") {
      rows.forEach((row) => {
        const data = rowValues.get(row);
        if ((data ?? false) === sortedBy) {
          row.dataset.visible = "true";
        } else {
          row.dataset.visible = "false";
          hiddenRows.add(row);
        }
      });
      this.sorted = true;
      return;
    }
    const visible = [];
    const hidden = [];
    this.orchestrator.rows.forEach((row) => {
      const value = rowValues.get(row);
      if (value) visible.push(row);
      else hidden.push(row);
    });
    hidden.forEach((row) => {
      row.dataset.visible = "false";
      hiddenRows.add(row);
    });
    if (this.ordering === "numeric") {
      visible.sort((a, b) => {
        const aVal = rowValues.get(a);
        const bVal = rowValues.get(b);
        return (Number(aVal) - Number(bVal)) * sortedBy;
      });
    } else if (this.ordering === "lexical") {
      visible.sort((a, b) => {
        const aVal = rowValues.get(a);
        const bVal = rowValues.get(b);
        return String(aVal).localeCompare(String(bVal)) * sortedBy;
      });
    }
    this.orchestrator.body?.append(...visible);
    this.sorted = true;
  }
  clear() {
    this.initialized = false;
    this.sortedBy = null;
    this.hiddenRows = null;
    this.rowValues = null;
    this.sorted = false;
    this.sortValue = this.defaultValue;
  }
}
const OPTIONS = /* @__PURE__ */ Symbol("options");
class CheckboxSort {
  constructor(orchestrator, column) {
    this.orchestrator = orchestrator;
    this.column = column;
    this.ordering = "categorical";
    this.reordering = false;
    this.rowValues = null;
    this.hiddenRows = null;
    this.options = OPTIONS;
    this.sortedBy = null;
    this.sortValues = [];
    this.initialized = false;
    this.sorted = false;
  }
  get active() {
    return this.sortedBy != null;
  }
  get state() {
    return this.active ? { values: this.sortValues } : null;
  }
  get disabled() {
    if (this.options === OPTIONS) this.init();
    return this.options === null;
  }
  init() {
    if (this.initialized) return;
    this.rowValues = /* @__PURE__ */ new WeakMap();
    const options = {};
    for (const row of this.orchestrator.body?.querySelectorAll("tr") ?? []) {
      const cell = row.querySelector(
        `td[data-column="${this.column}"][data-sort-value]`
      );
      if (cell?.dataset.sortValue === void 0) continue;
      const parsed = JSON.parse(cell.dataset.sortValue);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        continue;
      for (const [key, label] of Object.entries(parsed))
        options[key] = String(label);
      this.rowValues.set(row, Object.keys(parsed));
    }
    this.options = Object.keys(options).length ? options : null;
    this.initialized = true;
    return this;
  }
  createOptions(element) {
    if (this.options === null || this.options === OPTIONS) return;
    Object.entries(this.options).forEach(([key, value]) => {
      element.appendChild(
        primitives.checkbox({
          name: key,
          kind: this.orchestrator.kind,
          label: value,
          checked: this.sortValues.includes(key)
        })
      );
    });
    element.addEventListener("change", (e) => {
      if (!(e.target instanceof HTMLInputElement)) return;
      const { checked, name } = e.target;
      this.sortValues = checked ? [...this.sortValues, name] : this.sortValues.filter((value) => value !== name);
      this.sortedBy = this.sortValues.length ? this.sortValues : null;
      this.orchestrator.sort();
    });
  }
  restore(state) {
    const { options } = this;
    if (options === null || options === OPTIONS || !Array.isArray(state?.values))
      return;
    this.sortValues = state.values.filter((value) => {
      return typeof value === "string" && Object.hasOwn(options, value);
    });
    this.sortedBy = this.sortValues.length ? this.sortValues : null;
    if (!this.active) return;
    this.orchestrator.containers.get(this.column)?.querySelectorAll("input[type='checkbox']").forEach((input) => {
      input.checked = this.sortValues.includes(input.name);
    });
  }
  sort() {
    const hiddenRows = /* @__PURE__ */ new Set();
    this.orchestrator.rows.forEach((row) => {
      const values = this.rowValues?.get(row) || [];
      if (values.some((value) => this.sortValues.includes(value))) {
        row.dataset.visible = "true";
      } else {
        row.dataset.visible = "false";
        hiddenRows.add(row);
      }
    });
    this.hiddenRows = hiddenRows;
    this.sorted = true;
  }
  clear() {
    this.sortedBy = null;
    this.sortValues = [];
    this.rowValues = null;
    this.hiddenRows = null;
    this.sorted = false;
    this.options = OPTIONS;
    this.initialized = false;
  }
}

var sorting = /*#__PURE__*/Object.freeze({
	__proto__: null,
	TableSorting: TableSorting
});

class TableVisibility {
  constructor(attributes) {
    Object.assign(this, attributes);
    const selected = this.component.preload("selected");
    const columns = this.component.preload("columns");
    this.selected = Array.isArray(selected) ? selected.filter((field) => typeof field === "string") : [];
    this.columns = Array.isArray(columns) ? columns.filter(
      (column) => column !== null && typeof column === "object" && typeof column.field === "string"
    ) : [];
    this.state = this.view.TableVisibilityState || new TableVisibilityState({
      component: this.component,
      view: this.view,
      selected: this.selected,
      columns: this.columns
    });
    this._ownsState = !this.view.TableVisibilityState;
    this._preservedEditor = null;
  }
  init() {
    this.state.init();
    this._createController();
  }
  get visibleColumns() {
    return this.state.visibleColumns;
  }
  _toggleColumn(column, visible) {
    this.state.toggle(column, visible);
  }
  /**
   * Keep quick edit active while the column picker is temporarily displayed.
   *
   */
  preserveEditor(editor) {
    this._preservedEditor = editor;
  }
  postreconcile() {
    if (this.visible || !this._preservedEditor) return;
    const editor = this._preservedEditor;
    this._preservedEditor = null;
    if (!editor.visible) return;
    if (!this.component.active || this.component.active === this) {
      this.component.active = editor;
    }
  }
  _createController() {
    const cell = this.target.appendChild(document.createElement("td"));
    cell.colSpan = this.component.elt.querySelectorAll("th").length;
    cell.className = `p-3 border-t bg-kind-bg border-slate-300 group`;
    const container = cell.appendChild(document.createElement("div"));
    container.className = "flex flex-wrap gap-3";
    const visibleColumns = this.visibleColumns;
    for (const column of this.columns) {
      const checkbox = container.appendChild(
        primitives.checkbox({
          name: column.field,
          checked: visibleColumns.includes(column.field),
          kind: this.kind,
          label: column.title
        })
      );
      checkbox.dataset.role = "selector";
    }
    cell.addEventListener("change", (e) => {
      if (!(e.target instanceof HTMLInputElement) || e.target.type !== "checkbox")
        return;
      this._toggleColumn(e.target.name, e.target.checked);
    });
  }
  destroy() {
    if (this._ownsState) this.state.destroy();
  }
}

var visibility = /*#__PURE__*/Object.freeze({
	__proto__: null,
	TableVisibility: TableVisibility
});

export { indexTable as i, mobileControls as m, sorting as s, visibility as v };
