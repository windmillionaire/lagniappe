import { FacetsBox, SelectBox } from "../elements/combobox/index.ts";
import { wrapDateInput } from "../elements/primitives.ts";
import { STYLES } from "../generated/styles.mjs";
import { ENDPOINTS } from "../shared/endpoints.ts";
import { createIcon } from "../shared/icons.ts";
import { request } from "../shared/index.ts";
import type { RequestResult } from "../types/api";
import type ViewComponent from "../views/base/component.ts";
import type Core from "../views/base/core.ts";
import type { IndexTable } from "./tables/indexTable.ts";

interface FilterConditionOption {
	label: string;
	field: string;
	kind?: string;
	icon?: string;
	hash?: string;
	key?: string;
}

interface FilterFieldsResponse {
	form?: string;
	conditions?: FilterConditionOption[];
	options?: string;
	kind?: string;
	parent?: string;
	field?: string;
	feedback?: string;
}

export interface SavedConditionData {
	badge: string;
	definition: Record<string, unknown>;
}

interface SavedFilterItem {
	key: string;
	fingerprint: string;
	url: string;
	unavailable: boolean;
	can_edit: boolean;
	conditions: SavedConditionData[];
}

interface SavedFiltersBarResponse {
	filters?: SavedFilterItem[];
}

interface SavedFilterBarCreateResponse {
	filter?: SavedFilterItem;
	fingerprint?: string | null;
}

interface SavedFilterBarDeleteResponse {
	fingerprint?: string | null;
}

interface ActiveChip {
	id: string;
	definition: string;
	formKey?: string;
	isFormRoot?: boolean;
	element: HTMLElement;
}

interface ActiveFormContext {
	key: string;
	hash: string;
	label: string;
	conditions: FilterConditionOption[];
}

type FilterBarView = Pick<Core, "successfulResponse" | "components" | "elt">;

interface FilterBarSettings {
	target: HTMLElement;
	component: ViewComponent;
	view: FilterBarView;
	key: string;
	kind?: string;
	conditions?: FilterConditionOption[];
}

let chipSeq = 0;

function parseHtmlElement(markup: string): HTMLElement | null {
	const template = document.createElement("template");
	template.innerHTML = markup.trim();
	return template.content.firstElementChild as HTMLElement | null;
}

function canonicalJsonValue(value: unknown): unknown {
	if (Array.isArray(value)) {
		return value.map(canonicalJsonValue);
	}
	if (value && typeof value === "object") {
		const sorted: Record<string, unknown> = {};
		for (const key of Object.keys(value).sort()) {
			sorted[key] = canonicalJsonValue((value as Record<string, unknown>)[key]);
		}
		return sorted;
	}
	return value;
}

function contractSignature(conditions: unknown[]): string {
	const normalized = conditions
		.map((condition) => JSON.stringify(canonicalJsonValue(condition)))
		.sort();
	return JSON.stringify(normalized);
}

export class FilterBar {
	declare target: HTMLElement;
	declare component: ViewComponent;
	declare view: FilterBarView;
	declare key: string;
	declare kind?: string;
	declare conditions: FilterConditionOption[];
	declare endpoints: ReturnType<typeof ENDPOINTS.Filters>;

	declare savedAnchor: HTMLElement;
	declare savedTrigger: HTMLButtonElement;
	declare savedPopover: HTMLElement;
	declare addAnchor: HTMLElement;
	declare addTrigger: HTMLButtonElement;
	declare addPopover: HTMLElement;
	declare chipsContainer: HTMLElement;
	declare barActions: HTMLElement;
	declare matchStatus: HTMLElement;
	declare saveButton: HTMLButtonElement | null;
	declare clearButton: HTMLButtonElement;

	declare _chips: ActiveChip[];
	declare _activeForm: ActiveFormContext | null;
	declare _savedFilters: SavedFilterItem[] | null;
	declare _savedContracts: Set<string>;
	declare _saveButtonLabel: string;
	declare _savedLoading: boolean;
	declare _openPopover: "saved" | "add" | null;
	declare _optionSelect: FacetsBox | SelectBox | null;
	declare _runToken: number;
	declare _saveFeedbackTimer: ReturnType<typeof setTimeout> | null;
	declare _onDocClick: (event: MouseEvent) => void;
	declare _onDocKeydown: (event: KeyboardEvent) => void;
	declare _onRangeInput: (event: Event) => void;

	constructor(attributes: FilterBarSettings) {
		Object.assign(this, attributes);
		this.conditions = this.conditions ?? [];
		this.endpoints = ENDPOINTS.Filters({ key: this.key });

		const requireEl = <T extends HTMLElement>(role: string): T => {
			const el = this.target.querySelector<T>(`[data-role='${role}']`);
			if (!el) throw new Error(`FilterBar is missing [data-role='${role}']`);
			return el;
		};

		this.savedAnchor = requireEl("saved-anchor");
		this.savedTrigger = requireEl("saved-trigger");
		this.savedPopover = requireEl("saved-popover");
		this.addAnchor = requireEl("add-anchor");
		this.addTrigger = requireEl("add-trigger");
		this.addPopover = requireEl("add-popover");
		this.chipsContainer = requireEl("chips");
		this.barActions = requireEl("bar-actions");
		this.matchStatus = requireEl("match-status");
		this.saveButton = this.target.querySelector<HTMLButtonElement>(
			"[data-role='save-filter']",
		);
		this.clearButton = requireEl("clear-filters");

		this._chips = [];
		this._activeForm = null;
		this._savedFilters = null;
		this._savedContracts = new Set();
		this._saveButtonLabel =
			this.saveButton?.textContent?.trim() || "Save filter";
		this._savedLoading = false;
		this._openPopover = null;
		this._optionSelect = null;
		this._runToken = 0;
		this._saveFeedbackTimer = null;

		this._onDocClick = this._handleDocumentClick.bind(this);
		this._onDocKeydown = this._handleDocumentKeydown.bind(this);
		this._onRangeInput = this._handleRangeInput.bind(this);
	}

	init() {
		this.savedTrigger.addEventListener("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			void this.toggleSavedPopover();
		});
		this.addTrigger.addEventListener("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			this.toggleAddPopover();
		});
		this.clearButton.addEventListener("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			void this.clearAll();
		});
		this.saveButton?.addEventListener("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			void this.saveCurrentFilter();
		});

		document.addEventListener("click", this._onDocClick);
		document.addEventListener("keydown", this._onDocKeydown);
	}

	_indexTable(): IndexTable | null {
		const tableId = this.target.dataset.tableTarget || "table";
		const tableComp =
			this.view.components[tableId] ?? this.view.components.table;
		const widget = tableComp?.widgets?.IndexTable as IndexTable | undefined;
		return widget || null;
	}

	_clampPopover(popover: HTMLElement) {
		popover.style.left = "";
		popover.style.right = "";
		popover.style.maxWidth = "";
		popover.classList.remove("right-0");
		popover.classList.add("left-0");
		const margin = 12;
		const viewportWidth =
			document.documentElement.clientWidth || window.innerWidth;
		const maxWidth = Math.max(0, viewportWidth - margin * 2);
		popover.style.maxWidth = `${maxWidth}px`;
		const rect = popover.getBoundingClientRect();
		if (rect.right > viewportWidth - margin) {
			popover.classList.remove("left-0");
			popover.classList.add("right-0");
			const flipped = popover.getBoundingClientRect();
			if (flipped.left < margin) {
				popover.classList.remove("right-0");
				const parentRect = popover.offsetParent?.getBoundingClientRect();
				if (parentRect) {
					const maxLeft = Math.max(
						margin,
						viewportWidth - margin - flipped.width,
					);
					const desiredLeft = Math.min(
						Math.max(margin, parentRect.left),
						maxLeft,
					);
					popover.style.left = `${Math.round(desiredLeft - parentRect.left)}px`;
				}
			}
		} else if (rect.left < margin) {
			const parentRect = popover.offsetParent?.getBoundingClientRect();
			if (parentRect) {
				const maxLeft = Math.max(margin, viewportWidth - margin - rect.width);
				const desiredLeft = Math.min(Math.max(margin, rect.left), maxLeft);
				popover.style.left = `${Math.round(desiredLeft - parentRect.left)}px`;
			}
		}
	}

	closePopovers() {
		this._cleanupOptionSelect();
		if (this._openPopover === "saved") {
			this.savedPopover.dataset.visible = "false";
			this.savedTrigger.setAttribute("aria-expanded", "false");
		}
		if (this._openPopover === "add") {
			this.addPopover.dataset.visible = "false";
			this.addTrigger.setAttribute("aria-expanded", "false");
		}
		this._openPopover = null;
	}

	_handleDocumentClick(event: MouseEvent) {
		if (!this._openPopover) return;
		const target = event.target as Element | null;
		// Clicking inside a popover step can replaceChildren() synchronously before bubbling finishes.
		if (!target?.isConnected) return;
		if (
			this.savedAnchor.contains(target) ||
			this.addAnchor.contains(target) ||
			target.closest(".lp-dp-popover") ||
			target.closest("[role='listbox']")
		) {
			return;
		}
		this.closePopovers();
	}

	_handleDocumentKeydown(event: KeyboardEvent) {
		if (
			event.defaultPrevented ||
			event.key !== "Escape" ||
			!this._openPopover
		) {
			return;
		}
		if (document.querySelector(".lp-dp-popover")) return;
		if (this._optionSelect?.panelOpen) return;
		event.preventDefault();
		const was = this._openPopover;
		this.closePopovers();
		if (was === "add") this.addTrigger.focus();
		else if (was === "saved") this.savedTrigger.focus();
	}

	async toggleSavedPopover() {
		if (this._openPopover === "saved") {
			this.closePopovers();
			return;
		}
		this.closePopovers();
		this._openPopover = "saved";
		this.savedPopover.dataset.visible = "true";
		this.savedTrigger.setAttribute("aria-expanded", "true");

		if (this._savedFilters === null && !this._savedLoading) {
			this._savedLoading = true;
			this.savedPopover.replaceChildren(this._emptyNode("Loading…"));
			this._clampPopover(this.savedPopover);
			try {
				const response = await request.get<SavedFiltersBarResponse>(
					this.endpoints.get,
					{ format: "bar" },
				);
				if (response?.ok && Array.isArray(response.filters)) {
					this._savedFilters = response.filters;
				} else {
					this._savedFilters = [];
				}
				this._rebuildSavedContracts();
				this._syncBarActions();
			} finally {
				this._savedLoading = false;
			}
		}

		if (this._openPopover === "saved") {
			this._renderSavedList();
			this._clampPopover(this.savedPopover);
		}
	}

	_renderSavedList() {
		const items = this._savedFilters ?? [];
		if (!items.length) {
			this.savedPopover.replaceChildren(
				this._emptyNode("No saved filters yet"),
			);
			return;
		}

		const fragment = document.createDocumentFragment();
		for (const item of items) {
			const row = document.createElement("div");
			row.className = STYLES.filterBar.savedRow;

			if (item.unavailable) {
				const span = document.createElement("span");
				span.className = STYLES.filterBar.empty;
				span.textContent = "Unavailable saved filter";
				row.appendChild(span);
			} else {
				const applyBtn = document.createElement("button");
				applyBtn.type = "button";
				applyBtn.className = STYLES.filterBar.savedApply;
				for (const cond of item.conditions) {
					const badgeEl = parseHtmlElement(cond.badge);
					if (badgeEl) applyBtn.appendChild(badgeEl);
				}
				applyBtn.addEventListener("click", (e) => {
					e.preventDefault();
					e.stopPropagation();
					this._applySavedFilter(item);
				});
				row.appendChild(applyBtn);
			}

			if (item.can_edit) {
				const delBtn = document.createElement("button");
				delBtn.type = "button";
				delBtn.dataset.role = "saved-delete";
				delBtn.dataset.kind = "delete";
				delBtn.dataset.active = "false";
				delBtn.className = STYLES.filterBar.savedDelete;
				delBtn.setAttribute("aria-label", "Delete saved filter");
				delBtn.title = "Delete saved filter";
				delBtn.append(
					createIcon("trash.active", STYLES.toggle.icon.active),
					createIcon("trash.inactive", STYLES.toggle.icon.inactive),
				);
				delBtn.addEventListener("click", (e) => {
					e.preventDefault();
					e.stopPropagation();
					void this._deleteSavedFilter(item, delBtn);
				});
				row.appendChild(delBtn);
			}

			fragment.appendChild(row);
		}
		this.savedPopover.replaceChildren(fragment);
	}

	_applySavedFilter(item: SavedFilterItem) {
		this._savedContracts.add(
			contractSignature(item.conditions.map((cond) => cond.definition)),
		);
		void this.applyConditions(item.conditions);
	}

	async applyConditions(conditions: SavedConditionData[]) {
		this._resetChipsState();
		for (const cond of conditions) {
			const badgeEl = parseHtmlElement(cond.badge);
			if (!badgeEl) continue;
			this._appendChip(badgeEl, JSON.stringify(cond.definition));
		}
		this.closePopovers();
		await this._runFilter();
	}

	async _deleteSavedFilter(item: SavedFilterItem, button: HTMLButtonElement) {
		button.disabled = true;
		const response = await request.delete<SavedFilterBarDeleteResponse>(
			`/filters/${item.key}/delete?format=bar`,
		);
		if (response?.ok) {
			if (response.fingerprint) {
				this.view.elt.dataset.fingerprint = response.fingerprint;
			}
			this._savedFilters = (this._savedFilters ?? []).filter(
				(entry) => entry.key !== item.key,
			);
			this._rebuildSavedContracts();
			this._syncBarActions();
			this._renderSavedList();
		} else {
			button.disabled = false;
		}
	}

	openAddPopover() {
		if (this._openPopover === "add") return;
		this.closePopovers();
		this._openPopover = "add";
		this.addPopover.dataset.visible = "true";
		this.addTrigger.setAttribute("aria-expanded", "true");
		this._renderFieldPicker();
		this._clampPopover(this.addPopover);
	}

	toggleAddPopover() {
		if (this._openPopover === "add") {
			this.closePopovers();
			return;
		}
		this.openAddPopover();
	}

	_renderFieldPicker(focusFormOnly = false) {
		this._cleanupOptionSelect();
		this.addPopover.replaceChildren();

		if (focusFormOnly && this._activeForm) {
			const header = document.createElement("div");
			header.className = STYLES.filterBar.stepHeader;
			const backBtn = document.createElement("button");
			backBtn.type = "button";
			backBtn.className = STYLES.filterBar.backButton;
			backBtn.appendChild(createIcon("back", "icon-xs"));
			backBtn.append("All fields");
			backBtn.addEventListener("click", (e) => {
				e.preventDefault();
				e.stopPropagation();
				this._renderFieldPicker(false);
				this._clampPopover(this.addPopover);
			});
			const title = document.createElement("span");
			title.className = "truncate text-xs font-semibold text-form-default";
			title.textContent = `${this._activeForm.label} fields`;
			header.append(backBtn, title);
			this.addPopover.appendChild(header);
		}

		const search = document.createElement("input");
		search.type = "text";
		search.placeholder = focusFormOnly
			? `Filter ${this._activeForm?.label || "form"} fields…`
			: "Search fields…";
		search.autocomplete = "off";
		search.setAttribute("aria-label", "Search filter fields");
		search.className = STYLES.filterBar.searchInput;
		this.addPopover.appendChild(search);

		const list = document.createElement("div");
		list.className = STYLES.filterBar.fieldList;
		this.addPopover.appendChild(list);

		const coreFields = this.conditions.filter((c) => !c.hash);
		const modelTaskOptions = this.conditions.filter((c) =>
			Boolean(c.hash && c.key && c.field === "model"),
		);
		const formOptions = this.conditions.filter((c) =>
			Boolean(c.hash && c.key && c.field !== "model"),
		);

		const renderList = (query: string): HTMLButtonElement | null => {
			const needle = query.trim().toLowerCase();
			list.replaceChildren();
			let firstButton: HTMLButtonElement | null = null;

			const appendGroup = (
				heading: string | null,
				items: FilterConditionOption[],
				parentKey: string,
			) => {
				const filtered = needle
					? items.filter((item) => item.label.toLowerCase().includes(needle))
					: items;
				if (!filtered.length) return;
				if (heading) {
					const label = document.createElement("div");
					label.className = STYLES.filterBar.sectionHeading;
					label.textContent = heading;
					list.appendChild(label);
				}
				for (const item of filtered) {
					const btn = document.createElement("button");
					btn.type = "button";
					btn.className = STYLES.filterBar.fieldOption;
					if (item.kind) btn.dataset.kind = item.kind;
					const iconName = item.icon || item.kind || "filter.active";
					btn.appendChild(createIcon(iconName, STYLES.filterBar.icon));
					const text = document.createElement("span");
					text.className = "truncate";
					text.textContent = item.label;
					btn.appendChild(text);
					btn.addEventListener("click", (e) => {
						e.preventDefault();
						e.stopPropagation();
						void this._selectField(item, parentKey);
					});
					if (!firstButton) firstButton = btn;
					list.appendChild(btn);
				}
			};

			if (focusFormOnly && this._activeForm) {
				appendGroup(null, this._activeForm.conditions, this._activeForm.key);
			} else {
				if (this._activeForm?.conditions.length) {
					appendGroup(
						`${this._activeForm.label} fields`,
						this._activeForm.conditions,
						this._activeForm.key,
					);
				}
				appendGroup(
					modelTaskOptions.length || formOptions.length || this._activeForm
						? "Fields"
						: null,
					coreFields,
					this.key,
				);
				if (modelTaskOptions.length) {
					appendGroup("Model Tasks", modelTaskOptions, this.key);
				}
				if (formOptions.length) {
					appendGroup("Forms", formOptions, this.key);
				}
			}

			if (!list.childElementCount) {
				list.appendChild(this._emptyNode("No matching fields"));
			}
			return firstButton;
		};

		let firstVisible = renderList("");
		search.addEventListener("input", () => {
			firstVisible = renderList(search.value);
		});
		search.addEventListener("keydown", (e) => {
			if (e.key === "Enter" && firstVisible) {
				e.preventDefault();
				firstVisible.click();
			}
		});
		search.focus({ preventScroll: true });
	}

	async _selectField(option: FilterConditionOption, parentKey: string) {
		const params = new URLSearchParams();
		params.append("parent", parentKey);
		params.append("field", option.field);
		if (option.hash && option.key) {
			params.append(`${option.field}_value`, option.hash);
			params.append(`${option.field}_key`, option.key);
		}

		this.addPopover.replaceChildren(this._emptyNode("Loading…"));
		const response = await request.get<FilterFieldsResponse>(
			this.endpoints.condition,
			params,
		);
		if (this._openPopover !== "add" || !response) return;

		if (response.error) {
			this._renderFieldPicker();
			this._showPopoverError(response.error);
			return;
		}

		if (response.form && response.html) {
			const definitionInput = response.html.querySelector<HTMLInputElement>(
				'input[name="definition"]',
			);
			const badgeEl = response.html.querySelector<HTMLElement>(".lp-badge");
			this._activeForm = {
				key: response.form,
				hash: option.hash || "",
				label: option.label,
				conditions: response.conditions || [],
			};
			if (badgeEl && definitionInput) {
				this._appendChip(badgeEl, definitionInput.value, {
					formKey: response.form,
					isFormRoot: true,
				});
				void this._runFilter();
			}
			if (this._activeForm.conditions.length) {
				this._renderFieldPicker(true);
				this._clampPopover(this.addPopover);
			} else {
				this.closePopovers();
			}
			return;
		}

		if (response.html) {
			const definitionInput = response.html.querySelector<HTMLInputElement>(
				'input[name="definition"]',
			);
			const badgeEl = response.html.querySelector<HTMLElement>(".lp-badge");
			if (badgeEl && definitionInput) {
				this._appendChip(badgeEl, definitionInput.value);
				this.closePopovers();
				void this._runFilter();
			} else {
				this.closePopovers();
			}
			return;
		}

		if (response.options) {
			this._renderConditionStep(response, option.label);
			this._clampPopover(this.addPopover);
		}
	}

	_renderConditionStep(
		response: RequestResult<FilterFieldsResponse>,
		fallbackLabel: string,
	) {
		this._cleanupOptionSelect();
		this.addPopover.replaceChildren();

		const header = document.createElement("div");
		header.className = STYLES.filterBar.stepHeader;

		const backBtn = document.createElement("button");
		backBtn.type = "button";
		backBtn.className = STYLES.filterBar.backButton;
		backBtn.appendChild(createIcon("back", "icon-xs"));
		backBtn.append("Fields");
		backBtn.addEventListener("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			this._renderFieldPicker();
			this._clampPopover(this.addPopover);
		});

		const title = document.createElement("span");
		title.className = "truncate text-sm font-semibold text-base-dark";
		title.textContent = fallbackLabel;
		header.append(backBtn, title);

		const form = document.createElement("form");
		form.className = STYLES.filterBar.stepBody;
		form.dataset.kind = response.kind || this.kind || "default";
		form.dataset.parent = response.parent || this.key;
		form.dataset.field = response.field || "";
		form.innerHTML = response.options || "";

		// Use the server-rendered field label in the compact step header, avoiding a duplicate h3.
		const heading = form.querySelector("h3");
		if (heading) {
			const label = heading.textContent?.trim();
			if (label) title.textContent = label;
			const fieldType = heading.dataset.fieldType;
			if (fieldType) form.dataset.fieldType = fieldType;
			heading.remove();
		}
		form.dataset.fieldLabel = title.textContent?.trim() || fallbackLabel;

		if (
			form.dataset.fieldType === "timestamp" ||
			form.dataset.fieldType === "number"
		) {
			form.addEventListener("input", this._onRangeInput);
		}

		// Upgrade date inputs inside filter popovers with Lagniappe's custom DatePicker.
		form
			.querySelectorAll<HTMLInputElement>('input[type="date"]')
			.forEach((dateInput) => {
				if (dateInput.closest("[data-role='date-input-wrap']")) return;
				const parent = dateInput.parentNode;
				const next = dateInput.nextSibling;
				const wrapped = wrapDateInput(dateInput);
				parent?.insertBefore(wrapped, next);
			});

		const select = form.querySelector<HTMLElement>("[lp-select]");
		if (select) {
			const isFacet = Boolean(select.querySelector("[data-index]"));
			this._optionSelect = isFacet
				? new FacetsBox(select)
				: new SelectBox(select);
			this._optionSelect.init();
		}

		const submitBtn = form.querySelector<HTMLButtonElement>(
			"button[data-role='add-filter']",
		);
		if (submitBtn) {
			submitBtn.type = "submit";
			submitBtn.textContent = "Apply";
		}

		form.addEventListener("submit", (e) => {
			e.preventDefault();
			e.stopPropagation();
			void this._submitCondition(form, submitBtn);
		});

		this.addPopover.append(header, form);

		const firstInput = form.querySelector<HTMLElement>(
			"input:not([type='hidden']):not([type='radio']), select",
		);
		firstInput?.focus({ preventScroll: true });
	}

	_handleRangeInput(event: Event) {
		const target = event.target;
		if (!(target instanceof HTMLInputElement) || !target.closest("fieldset")) {
			return;
		}
		const form = target.closest("form");
		if (!form) return;
		const single = form.querySelector<HTMLElement>("[data-role='single']");
		const range = form.querySelector<HTMLElement>("[data-role='range']");
		if (!single || !range) return;
		if (target.value === "BETWEEN") {
			single.dataset.visible = "false";
			range.dataset.visible = "true";
		} else {
			single.dataset.visible = "true";
			range.dataset.visible = "false";
		}
	}

	_validateConditionForm(form: HTMLFormElement, raw: FormData): string | null {
		const label = form.dataset.fieldLabel || form.dataset.field || "this field";
		const range = form.querySelector<HTMLElement>("[data-role='range']");
		const isRange = range?.dataset.visible === "true";

		if (isRange && range) {
			const fromInput = range.querySelector<HTMLInputElement>(
				"input[name$='_value_from']",
			);
			const toInput = range.querySelector<HTMLInputElement>(
				"input[name$='_value_to']",
			);
			const fromVal = fromInput?.value.trim() ?? "";
			const toVal = toInput?.value.trim() ?? "";
			if (!fromVal || !toVal) {
				return `Please provide a value for ${label}.`;
			}
			if (fromInput?.type === "number" && Number(fromVal) > Number(toVal)) {
				return `Please provide a valid range for ${label}.`;
			}
			if (fromInput?.type === "date" && fromVal > toVal) {
				return `Please provide a valid range for ${label}.`;
			}
			return null;
		}

		const valueEntries = Array.from(raw.entries()).filter(([key]) =>
			key.endsWith("_value"),
		);
		if (
			valueEntries.length === 0 ||
			valueEntries.every(([, val]) => String(val).trim() === "")
		) {
			return `Please provide a value for ${label}.`;
		}
		return null;
	}

	async _submitCondition(
		form: HTMLFormElement,
		submitBtn: HTMLButtonElement | null,
	) {
		form.querySelector("[data-role='popover-error']")?.remove();

		const raw = new FormData(form);
		const validationError = this._validateConditionForm(form, raw);
		if (validationError) {
			this._showPopoverError(validationError, form);
			const focusTarget = form.querySelector<HTMLElement>(
				"[data-role='range'][data-visible='true'] input, input:not([type='hidden']):not([type='radio']), select",
			);
			focusTarget?.focus({ preventScroll: true });
			return;
		}

		if (submitBtn) submitBtn.disabled = true;

		const params = new URLSearchParams();
		for (const [key, value] of raw.entries()) {
			params.append(key, String(value));
		}
		params.append("field", form.dataset.field || "");
		params.append("parent", form.dataset.parent || this.key);

		try {
			const response = await request.get<FilterFieldsResponse>(
				this.endpoints.options,
				params,
			);
			if (!response) return;
			if (response.error || !response.ok) {
				this._showPopoverError(
					response.error || "Please provide a valid filter value.",
					form,
				);
				return;
			}
			if (response.html) {
				const definitionInput = response.html.querySelector<HTMLInputElement>(
					'input[name="definition"]',
				);
				const badgeEl = response.html.querySelector<HTMLElement>(".lp-badge");
				if (badgeEl && definitionInput) {
					const parentKey = form.dataset.parent;
					const formKey =
						this._activeForm && parentKey === this._activeForm.key
							? this._activeForm.key
							: undefined;
					this._appendChip(badgeEl, definitionInput.value, { formKey });
					this.closePopovers();
					void this._runFilter();
				}
			}
		} finally {
			if (submitBtn?.isConnected) submitBtn.disabled = false;
		}
	}

	_showPopoverError(message: string, container: HTMLElement = this.addPopover) {
		container.querySelector("[data-role='popover-error']")?.remove();
		const el = document.createElement("div");
		el.dataset.role = "popover-error";
		el.setAttribute("role", "alert");
		el.className = STYLES.filterBar.error;
		el.textContent = message;
		container.prepend(el);
	}

	_appendChip(
		badgeEl: HTMLElement,
		definition: string,
		meta: { formKey?: string; isFormRoot?: boolean } = {},
	) {
		if (this._chips.some((chip) => chip.definition === definition)) {
			return;
		}

		const id = `chip-${++chipSeq}`;
		badgeEl.classList.add(STYLES.filterBar.chip);
		const removeBtn = document.createElement("button");
		removeBtn.type = "button";
		removeBtn.className = STYLES.filterBar.chipRemove;
		removeBtn.setAttribute("aria-label", "Remove filter");
		removeBtn.title = "Remove filter";
		removeBtn.appendChild(createIcon("x", "icon-xs"));
		removeBtn.addEventListener("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			this._removeChip(id);
		});
		badgeEl.appendChild(removeBtn);

		const chip: ActiveChip = {
			id,
			definition,
			formKey: meta.formKey,
			isFormRoot: meta.isFormRoot,
			element: badgeEl,
		};
		this._chips.push(chip);
		this.chipsContainer.appendChild(badgeEl);
		this._syncBarActions();
	}

	_removeChip(id: string) {
		const target = this._chips.find((c) => c.id === id);
		if (!target) return;

		const toRemove = new Set<string>([id]);
		if (target.isFormRoot && target.formKey) {
			for (const chip of this._chips) {
				if (chip.formKey === target.formKey) {
					toRemove.add(chip.id);
				}
			}
			if (this._activeForm?.key === target.formKey) {
				this._activeForm = null;
			}
		}

		this._chips = this._chips.filter((chip) => {
			if (toRemove.has(chip.id)) {
				chip.element.remove();
				return false;
			}
			return true;
		});
		this._syncBarActions();
		void this._runFilter();
	}

	_resetChipsState() {
		for (const chip of this._chips) chip.element.remove();
		this._chips = [];
		this._activeForm = null;
		this._syncBarActions();
	}

	async clearAll() {
		this.closePopovers();
		this._resetChipsState();
		await this._runFilter();
	}

	_currentContractSignature(): string {
		return contractSignature(
			this._chips.map((chip) => JSON.parse(chip.definition) as unknown),
		);
	}

	_rebuildSavedContracts() {
		this._savedContracts = new Set(
			(this._savedFilters ?? []).map((item) =>
				contractSignature(item.conditions.map((cond) => cond.definition)),
			),
		);
	}

	_syncBarActions() {
		const hasChips = this._chips.length > 0;
		this.barActions.dataset.visible = hasChips ? "true" : "false";
		if (!hasChips) {
			this.matchStatus.textContent = "";
		}
		if (this.saveButton) {
			if (this._saveFeedbackTimer) {
				clearTimeout(this._saveFeedbackTimer);
				this._saveFeedbackTimer = null;
			}
			const alreadySaved =
				hasChips && this._savedContracts.has(this._currentContractSignature());
			if (alreadySaved) {
				this.saveButton.disabled = true;
				this.saveButton.replaceChildren(
					createIcon("check", "icon-xs"),
					document.createTextNode("Saved"),
				);
			} else {
				this.saveButton.disabled = false;
				this.saveButton.textContent = this._saveButtonLabel;
			}
		}
	}

	get contract() {
		return JSON.stringify({
			version: 1,
			conditions: this._chips.map(
				(chip) => JSON.parse(chip.definition) as unknown,
			),
		});
	}

	async _runFilter() {
		const token = ++this._runToken;
		const indexTable = this._indexTable();
		if (!indexTable) return;

		if (!this._chips.length) {
			this.matchStatus.textContent = "";
			await indexTable.clearFilteredRows();
			return;
		}

		this.matchStatus.textContent = "Filtering…";
		indexTable.showLoading("Filtering…");
		const response = await request.get(this.endpoints.test, {
			mode: "rows",
			contract: this.contract,
		});
		if (token !== this._runToken) return;
		if (!response?.ok || !response.html) {
			indexTable.setEmptyRowVisibility();
			this.matchStatus.textContent = response?.error || "Filter failed";
			return;
		}

		const count = indexTable.applyFilteredRows(response.html);
		this.matchStatus.textContent = count === 1 ? "1 match" : `${count} matches`;
	}

	async saveCurrentFilter() {
		if (
			!this._chips.length ||
			!this.saveButton ||
			this._savedContracts.has(this._currentContractSignature())
		) {
			return;
		}
		this.saveButton.disabled = true;
		this.saveButton.textContent = "Saving…";

		try {
			const data = new FormData();
			data.append("contract", this.contract);
			data.append("format", "bar");
			const response = await request.post<SavedFilterBarCreateResponse>(
				this.endpoints.save,
				data,
			);
			if (response?.ok) {
				if (response.fingerprint) {
					this.view.elt.dataset.fingerprint = response.fingerprint;
				}
				const sig = this._currentContractSignature();
				if (response.filter && this._savedFilters !== null) {
					this._savedFilters = [response.filter, ...this._savedFilters];
					this._rebuildSavedContracts();
				}
				this._savedContracts.add(sig);
				this._syncBarActions();
				return;
			}
			this.saveButton.textContent = this._saveButtonLabel;
			this.saveButton.disabled = false;
		} catch {
			this.saveButton.textContent = this._saveButtonLabel;
			this.saveButton.disabled = false;
		}
	}

	_emptyNode(text: string) {
		const div = document.createElement("div");
		div.className = STYLES.filterBar.empty;
		div.textContent = text;
		return div;
	}

	_cleanupOptionSelect() {
		this._optionSelect?.destroy();
		this._optionSelect = null;
	}

	destroy() {
		this.closePopovers();
		if (this._saveFeedbackTimer) clearTimeout(this._saveFeedbackTimer);
		document.removeEventListener("click", this._onDocClick);
		document.removeEventListener("keydown", this._onDocKeydown);
	}
}
