import { BaseForm } from "../../../elements/base/baseForm";
import { FacetsBox } from "../../../elements/combobox";
import { captureError, ENDPOINTS, Modal, request } from "../../../shared";

/**
 * @testable infrastructure
 */
export class FormSettings {
	constructor(builder) {
		this._destroyed = false;
		this._generationPromise = null;
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
			this.generateForm.error.setAttribute("role", "status");
			this.generateForm.error.setAttribute("aria-live", "polite");
			this.generateForm.error.setAttribute("aria-atomic", "true");
		} else {
			this.generateForm = null;
		}

		this._generateSchema = this._generateSchema.bind(this);
		this._addRestriction = this._addRestriction.bind(this);
		this._input = this._input.bind(this);
		this._click = this._click.bind(this);
		this._restrictionUpdated = this._restrictionUpdated.bind(this);
		this.modal = null;
	}

	/**
	 * @testable true
	 * @scaffolding testing/resources/form.py::Builder.restrict_to_group
	 * @features forms
	 * @dimensions access-restrictions group-restricted
	 */
	init() {
		if (this._destroyed) return;
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
			this.restrictions.addEventListener("updated", this._restrictionUpdated);
		}
	}

	_restrictionUpdated(event) {
		if (this._destroyed) return;
		const data = new FormData();
		data.set("action", "add");

		Object.keys(event.detail.options).forEach((key) => {
			data.append("group-key", key);
		});
		void this._addRestriction(data);
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
		if (this._destroyed || !this.restrictions) return;

		const route = this.restrictions.dataset.route;

		const response = await request.put(route, data);
		if (this._destroyed) return;
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
		this.selectGroup?.clear({ notify: false });
	}

	async _removeRestriction(button) {
		if (this._destroyed || !this.restrictions || button.disabled) return;

		const route = this.restrictions.dataset.route;
		const key = button.dataset.key;
		const item = button.closest("li");
		if (!item) return;
		const hadFocus = document.activeElement === button;
		let removed = false;
		button.disabled = true;
		button.setAttribute("aria-disabled", "true");
		button.setAttribute("aria-busy", "true");
		item.classList.add("opacity-50", "pointer-events-none");
		this.builder.header.clearMessage();

		const data = new FormData();
		data.set("action", "remove");
		data.set("group-key", key);

		try {
			const response = await request.put(route, data);
			if (this._destroyed) return;
			if (response?.ok === true) {
				removed = true;
				item.remove();
			} else {
				this.builder.header.message(
					response?.error || "Could not remove this restriction. Try again.",
					{ persistent: true },
				);
			}
		} catch (error) {
			captureError(error, button, { context: "builder-remove-restriction" });
			this.builder.header.message(
				"Could not remove this restriction. Try again.",
				{ persistent: true },
			);
		} finally {
			if (!removed && !this._destroyed && button.isConnected !== false) {
				button.disabled = false;
				button.setAttribute("aria-disabled", "false");
				button.removeAttribute("aria-busy");
				item.classList.remove("opacity-50", "pointer-events-none");
				if (
					hadFocus &&
					(!document.activeElement ||
						document.activeElement === document.body ||
						document.activeElement === button)
				) {
					button.focus({ preventScroll: true });
				}
			}
		}
	}

	/**
	 * @testable true
	 * @tests tests_js/test_036_form_builder_frontend.py::test_builder_generation_failure_stays_visible_and_releases_submitter
	 * @features forms ui-action
	 * @dimensions schema-generation single-flight retryable-action persistent-error
	 */
	_generateSchema(event) {
		event.preventDefault();
		event.stopPropagation();
		if (this._generationPromise) return this._generationPromise;
		if (this._destroyed || !this.generateForm?.target) {
			return Promise.resolve(false);
		}

		const data = new FormData(this.generateForm.target);
		const prompt = data.get("description");
		const submitter = event.submitter || this.generateForm.submitButton;

		if (!prompt) {
			this.generateForm.showError("Please enter a description");
			return Promise.resolve(false);
		} else if (submitter?.dataset.explain) {
			data.append("explain", submitter.dataset.explain);
		}

		const acknowledgement = {
			wasSaved: this.builder.header.saveButton?.dataset.saved === "true",
			name: this.builder.header.persistenceState.name,
		};
		if (submitter) {
			submitter.disabled = true;
			submitter.setAttribute("aria-disabled", "true");
			submitter.setAttribute("aria-busy", "true");
		}

		const pending = (async () => {
			try {
				const response = await request.post(ENDPOINTS.createSchema, data);
				if (this._destroyed) return false;
				const success = await this._updateSchema(response, acknowledgement);
				if (this._destroyed) return false;
				if (success || (response?.ok === true && response.modal)) {
					this.generateForm.resetSubmitButton();
				}
				if (success) this.generateForm.target.dataset.visible = "false";
				return success;
			} catch (error) {
				captureError(error, submitter, { context: "builder-generate-schema" });
				if (!this._destroyed) {
					this.generateForm.showError(
						"Could not generate this form. Try again.",
					);
				}
				return false;
			} finally {
				if (submitter && !this._destroyed && submitter.isConnected !== false) {
					submitter.disabled = false;
					submitter.setAttribute("aria-disabled", "false");
					submitter.removeAttribute("aria-busy");
				}
			}
		})();
		this._generationPromise = pending;
		const clearPending = () => {
			if (this._generationPromise === pending) this._generationPromise = null;
		};
		pending.then(clearPending, clearPending);
		return pending;
	}

	async _updateSchema(response, acknowledgement = null) {
		if (this._destroyed || !this.generateForm) return false;

		if (response?.ok === true && response.schema) {
			if (response.schema.length === 0) {
				this.generateForm.showError("No form elements generated");
				return false;
			}

			for (const element of response.schema) {
				if (this._destroyed) return false;
				if (this.builder.elements.get(element.id)) continue;
				const newElement = await this.builder.createElement(element);
				if (this._destroyed) return false;
				this.builder.model.panel.appendChild(newElement);
			}
			this.builder.updateSchemaOrder();
			if (acknowledgement?.wasSaved) {
				this.builder.header.acknowledge({
					schema: response.schema,
					name: acknowledgement.name,
				});
			} else {
				this.builder.header.unsaved();
			}
			return true;
		} else if (response?.ok === true && response.modal) {
			this.modal?.destroy();
			this.modal = new Modal(this.builder);
			void this.modal.attach(response.modal, this.generateForm);
		} else {
			this.generateForm.showError(
				response?.error || "Could not generate this form. Try again.",
			);
		}
		return false;
	}

	destroy() {
		if (this._destroyed) return;
		this._destroyed = true;
		this.generateForm?.target?.removeEventListener(
			"submit",
			this._generateSchema,
		);
		this.column?.removeEventListener("input", this._input);
		this.column?.removeEventListener("click", this._click);
		this.restrictions?.removeEventListener("updated", this._restrictionUpdated);
		this.generateForm?.destroy();
		this.selectGroup?.destroy();
		this.modal?.destroy();
		this.modal = null;
	}
}
