/*! Third-party licenses: /third-party-licenses.txt */
import { BaseList } from './baseList.js?v=b881d5e5';
import { b as buttons } from './buttons.js?v=b881d5e5';
import { r as request, w as withTransition } from './foundation.js?v=b881d5e5';
import './connectivity.js?v=b881d5e5';
import { p as primitives } from './primitives.js?v=b881d5e5';
import { F as FacetsBox } from './facets.js?v=b881d5e5';
import { S as SelectBox } from './select2.js?v=b881d5e5';
import './styles.js?v=b881d5e5';
import './icons.js?v=b881d5e5';
import './formatting.js?v=b881d5e5';
import './remote.js?v=b881d5e5';
import './queryLifecycle.js?v=b881d5e5';
import './combobox.js?v=b881d5e5';
import './results.js?v=b881d5e5';
import './storage.js?v=b881d5e5';
import './submitter.js?v=b881d5e5';

/**
 * @testable infrastructure
 */
class Filters {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.conditions = this.conditions ?? [];

		this.options = this.target.querySelector("[data-role='options']");
		this.formConditions = this.target.querySelector(
			"[data-role='form-conditions']",
		);
		this.entityConditions = this.target.querySelector(
			"[data-role='conditions']",
		);
		this.filters = this.target.querySelector("[data-role='filters']");
		this.feedback = this.target.querySelector("[data-role='feedback']");
		this.error = this.target.querySelector("[data-role='error']");

		this.updateConditions = this._updateConditions.bind(this);
		this.addFilter = this._addFilter.bind(this);
		this.rangeSelector = this._rangeSelector.bind(this);

		this._formSelect = null;
		this._entitySelect = null;
		this._optionSelect = null;
		this._buttons = {};
	}

	/**
	 * @testable true
	 * @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filters_tab_opens
	 * @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filters_form_opens
	 * @pair filters:tab-open
	 */
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
		if (!e.target.closest("fieldset")) return;

		const single = this.options.querySelector(`[data-role="single"]`);
		const range = this.options.querySelector(`[data-role="range"]`);
		if (e.target.value === "BETWEEN") {
			single.dataset.visible = "false";
			range.dataset.visible = "true";
		} else {
			single.dataset.visible = "true";
			range.dataset.visible = "false";
		}
	}

	async _addFilter(e) {
		if (!e.target.closest("button[data-role='add-filter']")) return;

		e.preventDefault();
		e.stopPropagation();

		this._buttons.addFilter.activate();

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
			new URLSearchParams(options),
		);
		withTransition(() => {
			this._updateForm(response);
		});

		this._buttons.addFilter.deactivate();
	}

	async _updateConditions(e) {
		if (!Object.keys(e.detail.options).length) return;

		const parent = e.target.closest("[data-parent]");

		const params = new URLSearchParams();
		params.append("parent", parent.dataset.parent);
		Object.entries(e.detail.options).forEach(([key, value]) => {
			params.append("field", key);
			if (value.hash) {
				params.append(`${key}_value`, value.hash);
				params.append(`${key}_key`, value.key);
			}
		});

		const response = await request.get(this.endpoints.condition, params);
		withTransition(() => {
			this._updateForm(response);
		});
	}

	_initButtons() {
		const container = this.target.querySelector("[data-role='buttons']");
		container.querySelectorAll("button").forEach((button) => {
			this._buttons[button.dataset.role] = buttons.active({
				existingButton: button,
			});
		});

		container.addEventListener("click", async (e) => {
			e.preventDefault();
			e.stopPropagation();

			const button = e.target.closest("button");
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
			conditions: this.definitions.map((definition) => JSON.parse(definition)),
		});
	}

	get formData() {
		const data = new FormData();
		data.append("contract", this.contract);
		return data;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_save
	 * @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_saved_filter_save_and_run
	 * @pair filters:save
	 */
	async save() {
		this._buttons.save.activate();
		const response = await request.post(this.endpoints.save, this.formData);
		if (!this.view.successfulResponse(response, this.component)) return;

		const tools = this.view.components.tools || this.component;
		const saved = await tools.loadWidget("SavedFilters");
		await tools.activate("SavedFilters");
		await saved.created(response);
		await tools.prepareRender(true);

		await withTransition(
			() => {
				tools.render(true);
				this._buttons.save.deactivate();
			},
			{ label: "filters:save" },
		);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_filters_require_at_least_one_condition
	 * @pair filters:empty-validation
	 */
	async run() {
		if (this.definitions.length === 0) {
			this.showError("Please add at least one filter condition");
			return;
		}

		this._buttons.run.activate();

		const response = await request.get(this.endpoints.test, {
			contract: this.contract,
		});
		if (!this.view.successfulResponse(response, this.component)) return;

		const results = await this.component.loadWidget("FilterResults");
		await results.updated(response);
		await this.component.activate("FilterResults");
		this.target.dataset.filterList = "filters:FilterResults";
		await this.component.prepareRender(true);

		withTransition(
			() => {
				this.component.render(true);
				this._buttons.run.deactivate();
			},
			{ label: "filters:run" },
		);
	}

	_createFormConditions(response) {
		const conditions = response.conditions;
		if (!conditions.length) return;

		const select = this.formConditions.appendChild(
			primitives.select({
				options: conditions.map((formCondition) => ({
					label: formCondition.label,
					value: formCondition.field,
					details: formCondition,
				})),
				kind: "form",
				placeholder: "add a form condition...",
			}),
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
					details: condition,
				})),
				kind: this.kind,
				placeholder: "add a condition...",
			}),
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

		const fieldType = this.options.querySelector("h3").dataset.fieldType;
		if (["timestamp", "number"].includes(fieldType)) {
			this.options.addEventListener("input", this.rangeSelector);
		} else {
			this.options.removeEventListener("input", this.rangeSelector);
		}

		const select = this.options.querySelector("[lp-select]");
		if (select) {
			const facet = !!select?.querySelector("[data-index]");

			this._optionSelect = facet
				? new FacetsBox(select)
				: new SelectBox(select);
			this._optionSelect.init();
		}

		this._buttons.addFilter = buttons.active({
			existingButton: this.options.querySelector("[data-role='add-filter']"),
		});
	}

	get definitions() {
		return Array.from(
			this.filters.querySelectorAll('input[name="definition"]'),
		).map((filter) => filter.value);
	}

	_updateForm(response) {
		this._cleanup();

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
				'input[name="definition"]',
			);

			if (definition && !this.definitions.includes(definition.value)) {
				this.filters.append(...response.html.querySelector("body").children);
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

		if (this.component.widgets.FilterResults) {
			this.component.widgets.FilterResults.reset();
			delete this.target.dataset.filterList;
		}
		Object.values(this._buttons).forEach((button) => {
			button.deactivate();
		});
	}

	/**
	 * @testable true
	 * @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_reset
	 * @pair filters:reset
	 */
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

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_save
 * @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_saved_filters_empty_state
 * @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_saved_filter_save_and_run
 * @matrix filters : empty-state reload-persistence save saved-filters
 */
class SavedFilters extends BaseList {}

export { Filters, SavedFilters };
