/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bfd37afb';
import { B as BaseForm } from './baseForm.js?v=bfd37afb';
import { s as setIcon } from './icons.js?v=bfd37afb';
import { w as withTransition } from './foundation.js?v=bfd37afb';
import './connectivity.js?v=bfd37afb';
import { p as primitives } from './primitives.js?v=bfd37afb';
import { S as SelectBox } from './select2.js?v=bfd37afb';

/**
 * @testable infrastructure
 */
class Condition {
	constructor(builder) {
		this.builder = builder;
		this.element = builder.selectedElement;
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
		this.index = null;
	}

	get html() {
		return [this.progress];
	}

	init() {
		this.destroy();
		this.form = new BaseForm(this);
		this.form.init();
	}

	showSuccess() {
		const status = document.createElement("span");
		const icon = status.appendChild(document.createElement("span"));
		status.dataset.kind = "success";
		setIcon(icon, "check", "ml-2 text-kind-default");
		this.header.querySelector("[data-role='title']").appendChild(status);

		setTimeout(() => {
			status.style.animation = "fade-out 300ms ease-out forwards";
			status.addEventListener(
				"animationend",
				() => {
					status.remove();
				},
				{ once: true },
			);
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
		this.options.values().forEach((option) => {
			if (!this.progress.contains(option)) {
				this.progress.appendChild(option);
			}
		});
		this.progress.dataset.visible = "true";
		if (this.complete) {
			this.form.showSubmitButton();
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
			: (target?.querySelector?.(inputSelector) ??
				target?.querySelector?.(textareaSelector) ??
				target?.querySelector?.(selectSelector));

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

		controls.appendChild(
			primitives.toggle({ icon: "help", data: { kind: "help", role: "help" } }),
		);
		controls.appendChild(
			primitives.toggle({
				icon: "close",
				data: { kind: "close", role: "close" },
			}),
		);

		return header;
	}

	setTitle(title) {
		this.header.querySelector("[data-role='title']").textContent = title;
	}

	_createSubmitButton() {
		const submitButton = document.createElement("button");
		submitButton.className = `${STYLES.button.submit}`;
		submitButton.dataset.visible = "false";
		submitButton.dataset.role = "save";
		return submitButton;
	}

	clearOptions() {
		this.options.values().forEach((option) => {
			option.remove();
		});
		this.options.clear();
	}

	destroy() {
		this.destroyables.forEach((destroyable) => {
			destroyable?.destroy?.();
		});
		this.clearOptions();
		this.destroyables = [];
		this.focusTarget = null;
	}
}

/**
 * @testable infrastructure
 * @covered-by src/script/views/builder/conditions/status.mjs::Status
 * @covered-by src/script/views/builder/conditions/visibility.mjs::Visibility
 */
class ConditionTarget extends Condition {
	addTargetSelect() {
		const selectElt = primitives.select({
			title: this.targetSelectTitle,
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
			const options = Object.values(e.detail.options);
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

		const element = this.builder.elements.get(this.setting.id);
		this.setting.type = element.schema.type;

		const options = element.schema.options || [];

		if (options.length > 0) {
			const selectElt = primitives.select({
				title: "has the value",
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
			if (this.setting.value) {
				selectBox.values.add(this.setting.value);
			}
			selectBox.init();
			this.destroyables.push(selectBox);
			this.options.set("value", selectElt);
			this.focusTarget = selectElt;

			selectElt.addEventListener("updated", (e) => {
				const options = Object.values(e.detail.options);
				this.setting.value = options[0].id;
				this.setting.label = options[0].name;
				this.showProgress();
			});
		} else {
			this.form.showError("The target element must have at least one option.");
		}
	}

	validate() {
		if (!this.setting.id) {
			this.form.showError("Please select a target element.");
			return false;
		} else if (this.setting.checked) {
			return true;
		} else if (this.setting.value) {
			return true;
		} else {
			this.form.showError("Please select an option.");
			return false;
		}
	}
}

export { Condition as C, ConditionTarget as a };
