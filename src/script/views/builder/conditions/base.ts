import type { ComboboxOption } from "../../../elements/combobox/combobox.ts";
import { SelectBox } from "../../../elements/combobox/index.ts";
import { primitives } from "../../../elements/primitives.ts";
import { FormController } from "../../../forms/controller.ts";
import { STYLES } from "../../../generated/styles.mjs";
import { setIcon } from "../../../shared/icons.ts";
import { withTransition } from "../../../shared/transitions.ts";
import type { FieldCondition } from "../../../types/forms.d.ts";
import type FormBuilder from "../builder.ts";
import type { BuilderElement } from "../builder.ts";
import type { ConditionList } from "../config.ts";
import type { DraftDocument } from "../draftDocument.ts";

export type ConditionSelectionEvent = CustomEvent<{
	options: Record<string, ComboboxOption>;
}>;

export class Condition<Setting extends object = object> {
	declare builder: FormBuilder;
	declare element: BuilderElement;
	declare target: HTMLDivElement;
	declare submitButton: HTMLButtonElement;
	declare header: HTMLDivElement;
	declare progress: HTMLDivElement;
	declare form: FormController | null;
	declare destroyables: { destroy?(): void }[];
	declare options: Map<string, HTMLElement>;
	declare complete: boolean;
	declare focusTarget: HTMLElement | null;
	declare index: number;
	declare _successTimer: number | null;
	declare key?: ConditionList;
	declare messages: { submit: string };
	declare setting?: Setting;
	declare draftSetting?: object | null;
	declare expand?: boolean;
	declare document?: DraftDocument | null;

	constructor(builder: FormBuilder) {
		this.builder = builder;
		this.element = builder.selectedElement as BuilderElement;
		this.target = document.createElement("div");
		this.target.className = "flex flex-col gap-4";
		this.submitButton = this._createSubmitButton();
		this.header = this._createHeader();
		this.progress = this._createProgress();
		this.form = null;
		this.destroyables = [];
		this.options = new Map();
		this.complete = false;
		this.focusTarget = null;
		this.index = -1;
		this._successTimer = null;
	}

	get html() {
		return [this.progress];
	}

	init(): Promise<boolean> | undefined {
		this.destroy();
		if (this.draftSetting) {
			this.setting = structuredClone(this.draftSetting) as Setting;
			delete this.draftSetting;
		}
		this.complete = false;
		this.form = new FormController(this);
		this.form.init();
		return;
	}

	showSuccess() {
		clearTimeout(this._successTimer ?? undefined);
		const status = document.createElement("span");
		const icon = status.appendChild(document.createElement("span"));
		status.dataset.kind = "success";
		setIcon(icon, "check", "ml-2 text-kind-default");
		this.header.querySelector("[data-role='title']")?.appendChild(status);

		this._successTimer = setTimeout(() => {
			void withTransition(() => status.remove(), {
				label: "builder:condition-success",
			});
		}, 1000);
	}

	_createProgress() {
		const progress = document.createElement("div");
		progress.dataset.role = "updates";
		progress.dataset.visible = "false";
		progress.className = "flex flex-col gap-4";
		return progress;
	}

	showProgress() {
		for (const option of this.options.values()) {
			if (!this.progress.contains(option)) {
				this.progress.appendChild(option);
			}
		}
		this.progress.dataset.visible = "true";
		if (this.complete) {
			this.form?.showSubmitButton();
		}
	}

	hideProgress() {
		withTransition(() => {
			this.progress.dataset.visible = "false";
		});
	}

	focus() {
		const target = this.focusTarget || this.target;
		const inputSelector = "input:not([type='hidden']):not([disabled])";
		const textareaSelector = "textarea:not([disabled])";
		const selectSelector = "select:not([disabled])";
		const selector = `${inputSelector}, ${textareaSelector}, ${selectSelector}`;
		const focusable = target?.matches?.(selector)
			? target
			: (target?.querySelector?.<HTMLInputElement>(inputSelector) ??
				target?.querySelector?.<HTMLTextAreaElement>(textareaSelector) ??
				target?.querySelector?.<HTMLSelectElement>(selectSelector));

		focusable?.focus();
	}

	_createHeader() {
		const header = document.createElement("div");
		header.className = STYLES.form.header.container;

		const title = header.appendChild(document.createElement("div"));
		title.className = STYLES.form.header.title;
		title.dataset.role = "title";

		const controls = header.appendChild(document.createElement("div"));
		controls.className = STYLES.form.header.controls;

		const helpToggle = primitives.toggle({
			icon: "help",
			data: { kind: "help", role: "help" },
		});
		helpToggle.setAttribute("lp-control", "help");
		helpToggle.setAttribute("lp-help", "form_settings");
		helpToggle.setAttribute("aria-label", "Help");
		helpToggle.title = "Help";
		controls.appendChild(helpToggle);

		const closeToggle = primitives.toggle({
			icon: "close",
			data: { kind: "close", role: "close" },
		});
		closeToggle.setAttribute("aria-label", "Close panel");
		closeToggle.title = "Close panel";
		controls.appendChild(closeToggle);

		return header;
	}

	setTitle(title: string) {
		const node = this.header.querySelector("[data-role='title']");
		if (node) node.textContent = title;
	}

	_createSubmitButton() {
		const submitButton = document.createElement("button");
		submitButton.className = `${STYLES.button.submit}`;
		submitButton.dataset.visible = "false";
		submitButton.dataset.role = "save";
		return submitButton;
	}

	validate() {
		return false;
	}

	refreshSavedState() {}

	clearOptions() {
		for (const option of this.options.values()) option.remove();
		this.options.clear();
	}

	destroy() {
		clearTimeout(this._successTimer ?? undefined);
		this._successTimer = null;
		this.form?.destroy?.();
		this.form = null;
		this.destroyables.forEach((destroyable) => {
			destroyable?.destroy?.();
		});
		this.clearOptions();
		this.destroyables = [];
		this.focusTarget = null;
	}
}

export class ConditionTarget extends Condition<FieldCondition> {
	declare setting: FieldCondition;
	addTargetSelect() {
		const selectElt = primitives.select({
			options: this.builder.getEligibleConditionTargets(),
			placeholder: "select a target element...",
			id: "target-element",
		});

		this.header.after(selectElt);
		const selectBox = new SelectBox(selectElt);

		if (this.setting.id) {
			selectBox.values.add(this.setting.id);
		}
		selectBox.init();
		this.destroyables.push(selectBox);
		this.focusTarget = selectElt;

		selectElt.addEventListener("updated", (e) => {
			this.clearOptions();
			const options = Object.values(
				(e as ConditionSelectionEvent).detail.options,
			);
			this.setting.id = options[0].id;
			this.setting.name = options[0].name;
			this.showProgress();
		});
	}

	addCheckboxTarget() {
		if (this.options.has("checkbox")) return;

		delete this.setting.value;

		this.setting.type = "checkbox";
		this.setting.checked = true;

		const checkboxMessage = document.createElement("p");
		checkboxMessage.dataset.kind = "success";
		checkboxMessage.textContent = "is checked";
		checkboxMessage.className = "font-semibold text-medium text-kind-default";

		this.options.set("checkbox", checkboxMessage);
	}

	addChooseValue() {
		if (this.options.has("value")) return;

		const element =
			this.setting.id && this.builder.elements.get(this.setting.id);
		if (!element) return;
		this.setting.type = element.schema.type;

		const options = element.schema.options || [];

		if (options.length > 0) {
			const selectElt = primitives.select({
				options: options.map((option) => ({
					label: option.label,
					value: option.value,
					details: {
						icon: this.setting.type === "radio" ? "radio" : "select",
						kind: "form",
						name: option.label,
					},
				})),
				placeholder: "select an option...",
				id: "eligible-options",
			});

			const selectBox = new SelectBox(selectElt);
			if (typeof this.setting.value === "string" && this.setting.value) {
				selectBox.values.add(this.setting.value);
			}
			selectBox.init();
			this.destroyables.push(selectBox);
			this.options.set("value", selectElt);
			this.focusTarget = selectElt;

			selectElt.addEventListener("updated", (e) => {
				const options = Object.values(
					(e as ConditionSelectionEvent).detail.options,
				);
				this.setting.value = options[0].id;
				this.setting.label = options[0].name;
				this.showProgress();
			});
		} else {
			this.form?.showError("The target element must have at least one option.");
		}
	}

	validate() {
		if (!this.setting.id) {
			this.form?.showError("Please select a target element.");
			return false;
		} else if (this.setting.checked) {
			return true;
		} else if (this.setting.value) {
			return true;
		} else {
			this.form?.showError("Please select an option.");
			return false;
		}
	}
}
