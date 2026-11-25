/*! Third-party licenses: /third-party-licenses.txt */
import { BaseList } from './baseList.js?v=b8e0e957';
import { b as buttons, p as primitives } from './ui-controls.js?v=b8e0e957';
import { r as request, w as withTransition } from './foundation.js?v=b8e0e957';
import { S as SelectBox, a as FacetsBox } from './forms.js?v=b8e0e957';
import './connectivity.js?v=b8e0e957';
import { E as EmbeddedTable } from './baseTable.js?v=b8e0e957';
import { S as STYLES } from './ui-resources.js?v=b8e0e957';

class Filters {
  constructor(attributes) {
    Object.assign(this, attributes);
    this.conditions = this.conditions ?? [];
    const control = (role) => {
      const element = this.target.querySelector(
        `[data-role='${role}']`
      );
      if (!element)
        throw new Error(`Filters widget is missing the ${role} element.`);
      return element;
    };
    this.options = control("options");
    this.formConditions = control("form-conditions");
    this.entityConditions = control("conditions");
    this.filters = control("filters");
    this.feedback = control("feedback");
    this.error = control("error");
    this.updateConditions = this._updateConditions.bind(this);
    this.addFilter = this._addFilter.bind(this);
    this.rangeSelector = this._rangeSelector.bind(this);
    this._formSelect = null;
    this._entitySelect = null;
    this._optionSelect = null;
    this._buttons = {};
  }
  async init() {
    this._initFilters();
    this._initButtons();
    await this._loadSavedFilters();
  }
  async _loadSavedFilters() {
    if (!this.component.elt.querySelector("[data-widget='SavedFilters']")) {
      return;
    }
    await this.component.loadWidget("SavedFilters");
  }
  _initFilters() {
    this._createConditions();
    this.options.addEventListener("click", this.addFilter);
    this.entityConditions.addEventListener("updated", this.updateConditions);
    this.formConditions.addEventListener("updated", this.updateConditions);
  }
  _rangeSelector(e) {
    const target = e.target;
    if (!(target instanceof HTMLInputElement) || !target.closest("fieldset"))
      return;
    const single = this.options.querySelector(`[data-role="single"]`);
    const range = this.options.querySelector(`[data-role="range"]`);
    if (!single || !range) return;
    if (target.value === "BETWEEN") {
      single.dataset.visible = "false";
      range.dataset.visible = "true";
    } else {
      single.dataset.visible = "true";
      range.dataset.visible = "false";
    }
  }
  async _addFilter(e) {
    if (!(e.target instanceof Element) || !e.target.closest("button[data-role='add-filter']"))
      return;
    e.preventDefault();
    e.stopPropagation();
    this._buttons.addFilter?.activate();
    const form = new FormData(this.target);
    const options = new FormData();
    this.options.querySelectorAll("[name]").forEach((elt) => {
      form.getAll(elt.name).forEach((value) => {
        options.append(elt.name, value);
      });
    });
    options.append("field", this.options.dataset.field);
    options.append("parent", this.options.dataset.parent);
    const response = await request.get(
      this.endpoints.options,
      new URLSearchParams(
        Array.from(options, ([key, value]) => [key, String(value)])
      )
    );
    withTransition(() => {
      this._updateForm(response);
    });
    this._buttons.addFilter?.deactivate();
  }
  async _updateConditions(e) {
    const { options } = e.detail;
    if (!Object.keys(options).length || !(e.target instanceof Element)) return;
    const parent = e.target.closest("[data-parent]");
    if (!parent) return;
    const params = new URLSearchParams();
    params.append("parent", parent.dataset.parent);
    Object.entries(options).forEach(([key, value]) => {
      params.append("field", key);
      if (value.hash) {
        params.append(`${key}_value`, value.hash);
        params.append(`${key}_key`, value.key);
      }
    });
    const response = await request.get(
      this.endpoints.condition,
      params
    );
    withTransition(() => {
      this._updateForm(response);
    });
  }
  _initButtons() {
    const container = this.target.querySelector("[data-role='buttons']");
    if (!container) return;
    container.querySelectorAll("button").forEach((button) => {
      const role = button.dataset.role;
      if (!role) return;
      this._buttons[role] = buttons.active({
        existingButton: button
      });
    });
    container.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const button = e.target instanceof Element ? e.target.closest("button") : null;
      if (!button) return;
      const role = button.dataset.role;
      if (role === "reset") {
        this.reset();
      } else if (role === "run") {
        await this.run();
      } else if (role === "save") {
        await this.save();
      }
    });
  }
  get contract() {
    return JSON.stringify({
      version: 1,
      conditions: this.definitions.map(
        (definition) => JSON.parse(definition)
      )
    });
  }
  get formData() {
    const data = new FormData();
    data.append("contract", this.contract);
    return data;
  }
  async save() {
    this._buttons.save?.activate();
    const response = await request.post(this.endpoints.save, this.formData);
    if (!this.view.successfulResponse(response, this.component) || !response)
      return;
    const tools = this.view.components.tools || this.component;
    const saved = await tools.loadWidget("SavedFilters");
    await tools.activate("SavedFilters");
    await saved?.created?.(response);
    await tools.prepareRender(true);
    await withTransition(
      () => {
        tools.render(true);
        this._buttons.save?.deactivate();
      },
      { label: "filters:save" }
    );
  }
  async run() {
    if (this.definitions.length === 0) {
      this.showError("Please add at least one filter condition");
      return;
    }
    this._buttons.run?.activate();
    const response = await request.get(this.endpoints.test, {
      contract: this.contract
    });
    if (!this.view.successfulResponse(response, this.component) || !response)
      return;
    const results = await this.component.loadWidget("FilterResults");
    await results?.updated?.(response);
    await this.component.activate("FilterResults");
    this.target.dataset.filterList = "filters:FilterResults";
    await this.component.prepareRender(true);
    withTransition(
      () => {
        this.component.render(true);
        this._buttons.run?.deactivate();
      },
      { label: "filters:run" }
    );
  }
  _createFormConditions(response) {
    const conditions = response.conditions;
    if (!conditions?.length) return;
    const select = this.formConditions.appendChild(
      primitives.select({
        options: conditions.map((formCondition) => ({
          label: formCondition.label,
          value: formCondition.field,
          details: formCondition
        })),
        kind: "form",
        placeholder: "add a form condition..."
      })
    );
    this._formSelect = new SelectBox(select);
    this._formSelect.init();
    this.formConditions.dataset.visible = "true";
    this.formConditions.dataset.parent = response.form;
  }
  _createConditions() {
    this.entityConditions.dataset.parent = this.key;
    const select = this.entityConditions.appendChild(
      primitives.select({
        options: this.conditions.map((condition) => ({
          label: condition.label,
          value: condition.hash ? condition.hash : condition.field,
          details: condition
        })),
        kind: this.kind,
        placeholder: "add a condition..."
      })
    );
    this._entitySelect = new SelectBox(select);
    this._entitySelect.init();
  }
  _addOptions(response) {
    this.options.innerHTML = response.options;
    this.options.dataset.visible = "true";
    this.options.dataset.kind = response.kind;
    this.options.dataset.parent = response.parent;
    this.options.dataset.field = response.field;
    const fieldType = this.options.querySelector("h3")?.dataset.fieldType;
    if (fieldType === "timestamp" || fieldType === "number") {
      this.options.addEventListener("input", this.rangeSelector);
    } else {
      this.options.removeEventListener("input", this.rangeSelector);
    }
    const select = this.options.querySelector("[lp-select]");
    if (select) {
      const facet = !!select?.querySelector("[data-index]");
      this._optionSelect = facet ? new FacetsBox(select) : new SelectBox(select);
      this._optionSelect.init();
    }
    this._buttons.addFilter = buttons.active({
      existingButton: this.options.querySelector(
        "[data-role='add-filter']"
      )
    });
  }
  get definitions() {
    return Array.from(
      this.filters.querySelectorAll(
        'input[name="definition"]'
      )
    ).map((filter) => filter.value);
  }
  _updateForm(response) {
    this._cleanup();
    if (!response) return;
    if (response.form) {
      this._cleanupFormConditions();
      this._createFormConditions(response);
    } else if (this.formConditions.dataset.parent !== response.parent) {
      this._cleanupFormConditions();
      delete this.formConditions.dataset.parent;
      this.formConditions.dataset.visible = "false";
    }
    if (response.options) {
      this._addOptions(response);
    } else if (response.html) {
      const definition = response.html.querySelector(
        'input[name="definition"]'
      );
      if (definition && !this.definitions.includes(definition.value)) {
        this.filters.append(...response.html.body.children);
        this.filters.dataset.visible = "true";
      }
    }
    if (response.error) this.showError(response.error);
    if (response.feedback) this.showFeedback(response.feedback);
  }
  _clearMessages() {
    this.feedback.dataset.visible = "false";
    this.feedback.innerHTML = "";
    this.error.dataset.visible = "false";
    this.error.innerHTML = "";
  }
  _cleanupFormConditions() {
    this._formSelect?.destroy();
    this._formSelect = null;
    this.formConditions.innerHTML = "";
    this.formConditions.dataset.visible = "false";
    this._clearMessages();
  }
  _cleanup() {
    this._optionSelect?.destroy();
    this._optionSelect = null;
    this.options.dataset.visible = "false";
    this.options.innerHTML = "";
    this._clearMessages();
    const results = this.component.widgets.FilterResults;
    if (results && "reset" in results && typeof results.reset === "function") {
      results.reset();
      delete this.target.dataset.filterList;
    }
    Object.values(this._buttons).forEach((button) => {
      button?.deactivate();
    });
  }
  reset() {
    this._cleanup();
    this._cleanupFormConditions();
    this.filters.innerHTML = "";
    this.filters.dataset.visible = "false";
    this._entitySelect?.clear();
  }
  showError(error) {
    this.error.textContent = error;
    this.error.dataset.visible = "true";
  }
  showFeedback(feedback) {
    this.feedback.textContent = feedback;
    this.feedback.dataset.visible = "true";
  }
  destroy() {
    this.reset();
  }
}
class SavedFilters extends BaseList {
}

var filters = /*#__PURE__*/Object.freeze({
	__proto__: null,
	Filters: Filters,
	SavedFilters: SavedFilters
});

class FilterResults extends EmbeddedTable {
  constructor(attributes) {
    super(attributes);
    this.badges = null;
    this.table = null;
    this.tableContainer = null;
    this.container = null;
    this.filtering = this.target.dataset.kind;
  }
  async updated(response) {
    const html = response.html;
    if (!html) return;
    this.table = html.querySelector("#embedded-table") || html.querySelector("table");
    if (this.filtering === "page") {
      this.badges = this.component.widgets.Filters.filters.cloneNode(
        true
      );
    }
  }
  get tbody() {
    return this.table?.querySelector("tbody");
  }
  get rows() {
    return this.tbody?.querySelectorAll("tr:not([data-role='empty'])");
  }
  get empty() {
    return this.tbody?.querySelector("tr[data-role='empty']");
  }
  postreconcile() {
    if (!this.table || this.target.contains(this.table)) return;
    this.container = document.createElement("div");
    this.container.dataset.role = "results-table";
    this.container.className = STYLES.table.container;
    this.tableContainer = document.createElement("div");
    this.tableContainer.className = "table-container px-4";
    this.tableContainer.dataset.role = "table";
    this.tableContainer.dataset.embedded = "true";
    this.tableContainer.appendChild(this.table);
    this.container.appendChild(this.tableContainer);
    this.table.dataset.visible = "true";
    this.initVisibility(this.table);
    if (this.filtering === "page" && this.badges) {
      this.target.replaceChildren(this.badges, this.container);
    } else {
      this.target.replaceChildren(this.container);
    }
  }
  reset() {
    if (this.badges) {
      this.badges.remove();
      this.badges = null;
    }
    if (this.container) {
      this.container.remove();
      this.container = null;
    }
    if (this.tableContainer) {
      this.tableContainer = null;
    }
    if (this.table) {
      this.table = null;
    }
  }
}

var filterResults = /*#__PURE__*/Object.freeze({
	__proto__: null,
	FilterResults: FilterResults
});

export { filterResults as a, filters as f };
