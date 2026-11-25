import { BaseList } from "../elements/base/baseList.ts";
import { buttons } from "../elements/buttons.ts";
import { FacetsBox, SelectBox } from "../elements/combobox/index.ts";
import { primitives } from "../elements/primitives.ts";
import type { ENDPOINTS } from "../shared/endpoints.ts";
import { request } from "../shared/index.ts";
import { withTransition } from "../shared/transitions.ts";

import type { RequestResult } from "../types/api";
import type ViewComponent from "../views/base/component.ts";
import type Core from "../views/base/core.ts";

interface FilterConditionOption {
	label: string;
	field: string;
	hash?: string;
	key?: string;
}
interface FilterFields {
	form: string;
	conditions: FilterConditionOption[];
	options: string;
	kind: string;
	parent: string;
	field: string;
	feedback: string;
}
type FilterResponse = RequestResult<FilterFields>;
type FilterOptionSelection = CustomEvent<{
	options: Record<string, Pick<FilterConditionOption, "key" | "hash">>;
}>;
type FilterView = Pick<Core, "successfulResponse" | "components">;
interface FilterSettings {
	target: HTMLFormElement;
	component: ViewComponent;
	view: FilterView;
	key: string;
	kind?: string;
	conditions?: FilterConditionOption[];
	endpoints: ReturnType<typeof ENDPOINTS.Filters>;
}

export class Filters {
	declare target: HTMLFormElement;
	declare component: ViewComponent;
	declare view: FilterView;
	declare key: string;
	declare kind?: string;
	declare endpoints: FilterSettings["endpoints"];
	declare conditions: FilterConditionOption[];
	declare options: HTMLElement;
	declare formConditions: HTMLElement;
	declare entityConditions: HTMLElement;
	declare filters: HTMLElement;
	declare feedback: HTMLElement;
	declare error: HTMLElement;
	declare updateConditions: (event: Event) => Promise<void>;
	declare addFilter: (event: MouseEvent) => Promise<void>;
	declare rangeSelector: (event: Event) => void;
	declare _formSelect: SelectBox | null;
	declare _entitySelect: SelectBox | null;
	declare _optionSelect: FacetsBox | SelectBox | null;
	declare _buttons: Partial<Record<string, ReturnType<typeof buttons.active>>>;

	constructor(attributes: FilterSettings) {
		Object.assign(this, attributes);
		this.conditions = this.conditions ?? [];

		const control = (role: string) => {
			const element = this.target.querySelector<HTMLElement>(
				`[data-role='${role}']`,
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

	_rangeSelector(e: Event) {
		const target = e.target;
		if (!(target instanceof HTMLInputElement) || !target.closest("fieldset"))
			return;

		const single =
			this.options.querySelector<HTMLElement>(`[data-role="single"]`);
		const range =
			this.options.querySelector<HTMLElement>(`[data-role="range"]`);
		if (!single || !range) return;
		if (target.value === "BETWEEN") {
			single.dataset.visible = "false";
			range.dataset.visible = "true";
		} else {
			single.dataset.visible = "true";
			range.dataset.visible = "false";
		}
	}

	async _addFilter(e: MouseEvent) {
		if (
			!(e.target instanceof Element) ||
			!e.target.closest("button[data-role='add-filter']")
		)
			return;

		e.preventDefault();
		e.stopPropagation();

		this._buttons.addFilter?.activate();

		const form = new FormData(this.target);
		const options = new FormData();

		this.options
			.querySelectorAll<
				HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
			>("[name]")
			.forEach((elt) => {
				form.getAll(elt.name).forEach((value) => {
					options.append(elt.name, value);
				});
			});
		options.append("field", this.options.dataset.field as string);
		options.append("parent", this.options.dataset.parent as string);

		const response = await request.get<FilterFields>(
			this.endpoints.options,
			new URLSearchParams(
				Array.from(options, ([key, value]) => [key, String(value)]),
			),
		);
		withTransition(() => {
			this._updateForm(response);
		});

		this._buttons.addFilter?.deactivate();
	}

	async _updateConditions(e: Event) {
		const { options } = (e as FilterOptionSelection).detail;
		if (!Object.keys(options).length || !(e.target instanceof Element)) return;

		const parent = e.target.closest<HTMLElement>("[data-parent]");
		if (!parent) return;

		const params = new URLSearchParams();
		params.append("parent", parent.dataset.parent as string);
		Object.entries(options).forEach(([key, value]) => {
			params.append("field", key);
			if (value.hash) {
				params.append(`${key}_value`, value.hash);
				params.append(`${key}_key`, value.key as string);
			}
		});

		const response = await request.get<FilterFields>(
			this.endpoints.condition,
			params,
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
				existingButton: button,
			});
		});

		container.addEventListener("click", async (e) => {
			e.preventDefault();
			e.stopPropagation();

			const button =
				e.target instanceof Element ? e.target.closest("button") : null;
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
				(definition) => JSON.parse(definition) as unknown,
			),
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
			{ label: "filters:save" },
		);
	}

	async run() {
		if (this.definitions.length === 0) {
			this.showError("Please add at least one filter condition");
			return;
		}

		this._buttons.run?.activate();

		const response = await request.get(this.endpoints.test, {
			contract: this.contract,
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
			{ label: "filters:run" },
		);
	}

	_createFormConditions(response: FilterResponse) {
		const conditions = response.conditions;
		if (!conditions?.length) return;

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
		this.formConditions.dataset.parent = response.form as string;
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

	_addOptions(response: FilterResponse) {
		this.options.innerHTML = response.options as string;
		this.options.dataset.visible = "true";
		this.options.dataset.kind = response.kind as string;
		this.options.dataset.parent = response.parent as string;
		this.options.dataset.field = response.field as string;

		const fieldType = this.options.querySelector("h3")?.dataset.fieldType;
		if (fieldType === "timestamp" || fieldType === "number") {
			this.options.addEventListener("input", this.rangeSelector);
		} else {
			this.options.removeEventListener("input", this.rangeSelector);
		}

		const select = this.options.querySelector<HTMLElement>("[lp-select]");
		if (select) {
			const facet = !!select?.querySelector("[data-index]");

			this._optionSelect = facet
				? new FacetsBox(select)
				: new SelectBox(select);
			this._optionSelect.init();
		}

		this._buttons.addFilter = buttons.active({
			existingButton: this.options.querySelector<HTMLButtonElement>(
				"[data-role='add-filter']",
			),
		});
	}

	get definitions() {
		return Array.from(
			this.filters.querySelectorAll<HTMLInputElement>(
				'input[name="definition"]',
			),
		).map((filter) => filter.value);
	}

	_updateForm(response: FilterResponse | undefined) {
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
			const definition = response.html.querySelector<HTMLInputElement>(
				'input[name="definition"]',
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

	showError(error: string) {
		this.error.textContent = error;
		this.error.dataset.visible = "true";
	}

	showFeedback(feedback: string) {
		this.feedback.textContent = feedback;
		this.feedback.dataset.visible = "true";
	}

	destroy() {
		this.reset();
	}
}

export class SavedFilters extends BaseList {}
