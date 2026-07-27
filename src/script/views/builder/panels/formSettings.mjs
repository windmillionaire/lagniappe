import { BaseForm } from "../../../elements/base/baseForm";
import { FacetsBox } from "../../../elements/combobox";
import { ENDPOINTS, Modal, request } from "../../../shared";

/**
 * @testable infrastructure
 */
export class FormSettings {
	constructor(builder) {
		this.builder = builder;
		this.column = document.getElementById("form-settings-panel");
		this.restrictions = document.querySelector("[data-role='restrict-access']");
		this.selectGroup = null;

		const generateTarget = this.column?.querySelector("#generate");
		if (generateTarget) {
			this.generateForm = new BaseForm({
				target: generateTarget,
				submitGroup: generateTarget.querySelector("[data-role='submit-group']"),
				messages: {
					submit: "Generate",
					submitting: "Thinking...",
					submitted: "Generated",
				},
			});
		} else {
			this.generateForm = null;
		}

		this._generateSchema = this._generateSchema.bind(this);
		this._addRestriction = this._addRestriction.bind(this);
		this._input = this._input.bind(this);
		this._click = this._click.bind(this);
	}

	/**
	 * @testable true
	 * @scaffolding testing/resources/form.py::Builder.restrict_to_group
	 * @features forms
	 * @dimensions access-restrictions group-restricted
	 */
	init() {
		if (this.generateForm) {
			this.generateForm.init();
			this.generateForm.target.addEventListener("submit", this._generateSchema);
		}

		this.column?.addEventListener("input", this._input);
		this.column?.addEventListener("click", this._click);

		if (this.restrictions) {
			const input = this.column.querySelector(
				"[data-role='restrict-group-input']",
			);
			this.selectGroup = new FacetsBox(input);
			this.selectGroup.init();
			this.restrictions.addEventListener("updated", (event) => {
				const data = new FormData();
				data.set("action", "add");

				Object.keys(event.detail.options).forEach((key) => {
					data.append("group-key", key);
				});
				this._addRestriction(data);
			});
		}
	}

	/**
	 * @testable true
	 * @scaffolding testing/resources/form.py::Builder.restrict_to_owner
	 * @features forms
	 * @dimensions access-restrictions owner-restricted
	 */
	_input(event) {
		if (event.target.name === "description" && this.generateForm?.target) {
			const explain = this.generateForm.target.querySelector(
				"[data-role='explain']",
			);
			if (explain) explain.dataset.visible = "true";
		} else if (event.target.dataset.role === "specific-access") {
			const data = new FormData();
			data.set("action", event.target.checked ? "add" : "remove");
			data.set("specific", event.target.name);
			this._addRestriction(data);
		}
	}

	_click(event) {
		const button = event.target.closest("[data-role]");
		if (button?.dataset.role === "generate" && this.generateForm?.target) {
			const visible = this.generateForm.target.dataset.visible === "true";
			this.generateForm.target.dataset.visible = visible ? "false" : "true";
			if (!visible) this.generateForm.target.querySelector("textarea")?.focus();
		} else if (button?.dataset.role === "cancel" && this.generateForm?.target) {
			this.generateForm.target.dataset.visible = "false";
			this.generateForm.resetSubmitButton();
			const ta = this.generateForm.target.querySelector("textarea");
			if (ta) ta.value = "";
		} else if (button?.dataset.role === "remove-restriction") {
			this._removeRestriction(button);
		}
	}

	get visible() {
		return this.column.dataset.visible === "true";
	}

	set visible(value) {
		this.column.dataset.visible = value ? "true" : "false";
	}

	/**
	 * @testable true
	 * @scaffolding testing/resources/form.py::Builder.restrict_to_owner
	 * @scaffolding testing/resources/form.py::Builder.restrict_to_group
	 * @features forms
	 * @dimensions access-restrictions owner-restricted group-restricted
	 */
	async _addRestriction(data) {
		if (!this.restrictions) return;

		const route = this.restrictions.dataset.route;

		const response = await request.put(route, data);
		if (response.html) {
			const list = this.restrictions.querySelector("ul");
			const nodes =
				typeof response.html === "string"
					? null
					: Array.from(response.html.body.children);

			if (nodes?.length) {
				list?.append(...nodes.map((node) => document.importNode(node, true)));
			} else if (typeof response.html === "string") {
				list?.insertAdjacentHTML("beforeend", response.html);
			}
		}
		this.selectGroup?.clear();
	}

	async _removeRestriction(button) {
		if (!this.restrictions) return;

		const route = this.restrictions.dataset.route;
		const key = button.dataset.key;
		const item = button.closest("li");
		item.classList.add("opacity-50", "pointer-events-none");

		const data = new FormData();
		data.set("action", "remove");
		data.set("group-key", key);

		const response = await request.put(route, data);
		if (response.ok) {
			item.remove();
		}
	}

	async _generateSchema(event) {
		if (!this.generateForm?.target) return;

		event.preventDefault();
		event.stopPropagation();

		const data = new FormData(this.generateForm.target);
		const prompt = data.get("description");
		event.submitter.disabled = true;

		if (!prompt) {
			this.generateForm.showError("Please enter a description");
			return;
		} else if (event.submitter.dataset.explain) {
			data.append("explain", event.submitter.dataset.explain);
		}

		const response = await request.post(ENDPOINTS.createSchema, data);
		const success = await this._updateSchema(response);

		event.submitter.disabled = false;
		this.generateForm.resetSubmitButton();

		if (success) {
			this.generateForm.target.dataset.visible = "false";
		}
	}

	async _updateSchema(response) {
		if (!this.generateForm) return false;

		if (response.ok && response.schema) {
			if (response.schema.length === 0) {
				this.generateForm.showError("No form elements generated");
				return;
			}

			for (const element of response.schema) {
				if (this.builder.elements.get(element.id)) continue;
				const newElement = await this.builder.createElement(element);
				this.builder.model.panel.appendChild(newElement);
			}
			this.builder.updateSchemaOrder();
			this.builder.header.saved();
			return true;
		} else if (response.ok && response.modal) {
			const modal = new Modal(this.builder);
			modal.attach(response.modal, this.generateForm);
		} else if (response.error) {
			this.generateForm.showError(response.error);
		}
		return false;
	}

	destroy() {
		this.generateForm?.destroy();
		this.selectGroup?.destroy();
	}
}
