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
		this._saveRestrictions = this._saveRestrictions.bind(this);
		this._restrictionPromise = null;
		this.restrictionForm = this.restrictions
			? new BaseForm({
					target: this.restrictions,
					messages: {
						submit: "Save Restrictions",
						submitting: "Saving",
						submitted: "Saved",
					},
				})
			: null;
		this._input = this._input.bind(this);
		this._click = this._click.bind(this);
		this._restrictionUpdated = this._restrictionUpdated.bind(this);
		this.modal = null;
	}

	/**
	 * @testable true
	 * @scaffolding testing/resources/form.py::Builder.restrict_to_group
	 * @matrix forms : access-restrictions group-restricted
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
			this.restrictionForm.init();
			this.restrictions.addEventListener("submit", this._saveRestrictions);
			const input = this.column.querySelector(
				"[data-role='restrict-group-input']",
			);
			this.selectGroup = new FacetsBox(input);
			this.selectGroup.init();
			this.restrictions.addEventListener("updated", this._restrictionUpdated);
		}
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003c_access_restrictions.py::test_form_admin_only_replaces_groups_until_explicitly_selected_again
	 * @matrix forms : access-restrictions explicit-submit group-restricted owner-restricted
	 */
	_restrictionUpdated(event) {
		if (this._destroyed) return;
		if (Object.keys(event.detail.options).length) {
			this.restrictions.querySelector("[name='admin']").checked = false;
		}
		const list = this.restrictions.querySelector("ul");
		const template = this.restrictions.querySelector("template");
		for (const [key, option] of Object.entries(event.detail.options)) {
			if (
				[...list.querySelectorAll("input[name='group-key']")].some(
					(input) => input.value === key,
				)
			)
				continue;
			const item = template.content.firstElementChild.cloneNode(true);
			item.querySelector("input").value = key;
			item.querySelector("span").textContent = option.name;
			item.querySelector("button").dataset.key = key;
			list.append(item);
		}
		this.selectGroup.clear({ notify: false });
		this.restrictionForm.markUnsavedState();
	}

	/**
	 * @testable true
	 * @scaffolding testing/resources/form.py::Builder.restrict_to_owner
	 * @tests tests_e2e/003_forms/test_003c_access_restrictions.py::test_form_admin_only_replaces_groups_until_explicitly_selected_again
	 * @matrix forms : access-restrictions explicit-submit owner-restricted
	 */
	_input(event) {
		if (event.target.name === "admin" && event.target.checked) {
			this.restrictions.querySelector("ul").replaceChildren();
			this.selectGroup.clear({ notify: false });
			this.restrictionForm.markUnsavedState();
		}
		if (event.target.name === "description" && this.generateForm?.target) {
			const explain = this.generateForm.target.querySelector(
				"[data-role='explain']",
			);
			if (explain) explain.dataset.visible = "true";
		}
	}

	_click(event) {
		const button = event.target.closest("[data-role]");
		if (button?.dataset.role === "generate" && this.generateForm?.target) {
			const visible = this.generateForm.target.dataset.visible === "true";
			this.generateForm.target.dataset.visible = visible ? "false" : "true";
			if (!visible) this.generateForm.target.querySelector("textarea")?.focus();
		} else if (button?.dataset.role === "cancel" && this.generateForm?.target) {
			this._generationIdentity = null;
			this.generateForm.target.dataset.visible = "false";
			this.generateForm.messages.submit = "Generate";
			this.generateForm.resetSubmitButton();
			const ta = this.generateForm.target.querySelector("textarea");
			if (ta) ta.value = "";
		} else if (button?.dataset.role === "remove-restriction") {
			button.closest("li")?.remove();
			this.restrictionForm.markUnsavedState();
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
	 * @matrix forms : access-restrictions group-restricted owner-restricted
	 * @tests tests_js/test_036_form_builder_frontend.py::test_restriction_save_submits_snapshot_and_releases_failed_submitter
	 * @tests tests_e2e/009_search/test_009e_form_restrictions.py::test_form_restrictions_reconcile_existing_descendants
	 * @matrix forms : access-restrictions explicit-submit retryable-action single-flight
	 */
	_saveRestrictions(event) {
		event.preventDefault();
		event.stopPropagation();
		if (this._restrictionPromise) return this._restrictionPromise;
		if (this._destroyed) return;
		const form = this.restrictionForm;
		const data = new FormData(this.restrictions);
		const snapshot = JSON.stringify([...data]);
		form.submitting();
		form.submitButton.disabled = true;
		this._restrictionPromise = (async () => {
			try {
				const response = await request.put(
					this.restrictions.dataset.route,
					data,
				);
				if (this._destroyed) return;
				if (response?.ok === true) {
					if (JSON.stringify([...new FormData(this.restrictions)]) === snapshot)
						form.success();
					else {
						form.resetSubmitButton();
						form.markUnsavedState();
					}
				} else
					form.showError(
						response?.error || "Could not save restrictions. Try again.",
					);
			} catch (error) {
				captureError(error, this.restrictions, {
					context: "builder-save-restrictions",
				});
				if (!this._destroyed)
					form.showError("Could not save restrictions. Try again.");
			} finally {
				if (!this._destroyed) form.submitButton.disabled = false;
				this._restrictionPromise = null;
			}
		})();
		return this._restrictionPromise;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_036_form_builder_frontend.py::test_builder_generation_failure_stays_visible_and_releases_submitter
	 * @matrix forms ui-action : persistent-error retryable-action schema-generation single-flight
	 * @matrix forms : draft-history
	 * @pair forms:stale-response
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

		this.builder.updateSchema();
		this.builder.draft.group = null;
		const identity = {
			request_id: crypto.randomUUID(),
			draft_revision: this.builder.draft.revision,
		};
		this._generationIdentity = identity;
		const draft = this.builder.captureDraft();
		data.set("schema", JSON.stringify(draft.schema));
		data.set("html_fields", JSON.stringify(draft.html_fields));
		data.set("baseline", this.builder.draft.baseline || "");
		data.set("draft_revision", String(identity.draft_revision));
		data.set("request_id", identity.request_id);
		if (submitter) {
			submitter.disabled = true;
			submitter.setAttribute("aria-disabled", "true");
			submitter.setAttribute("aria-busy", "true");
		}

		const pending = (async () => {
			try {
				const response = await request.post(ENDPOINTS.createSchema, data, {
					replaceErrorPage: false,
				});
				if (this._destroyed) return false;
				if (this._generationIdentity !== identity) return false;
				if (
					!response?.modal &&
					(identity.draft_revision !== this.builder.draft.revision ||
						response?.request_id !== identity.request_id ||
						response?.draft_revision !== identity.draft_revision)
				) {
					if (response?.ok === true) {
						this.generateForm.messages.submit = "Regenerate";
						this.generateForm.showError(
							"Your draft changed while generation was running. Regenerate using your current draft.",
						);
						return false;
					}
				}
				const success = await this._updateSchema(response);
				if (this._destroyed) return false;
				if (success || (response?.ok === true && response.modal)) {
					this.generateForm.messages.submit = "Generate";
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

	async _updateSchema(response) {
		if (this._destroyed || !this.generateForm) return false;

		if (response?.ok === true && response.operations) {
			try {
				if (!this.builder.draft.applyGeneration(response)) {
					this.generateForm.showError(
						"No changes were needed. Your draft is unchanged.",
					);
					return false;
				}
				this.builder.restoreDraft();
				this.builder.header.message(
					"Generated changes are in your draft. Save to keep them.",
					{ persistent: true },
				);
			} catch (error) {
				this.generateForm.showError(error.message);
				return false;
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
			if (response?.code === "stale_form_draft")
				this.builder.header.showConflict(response);
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
		this.restrictions?.removeEventListener("submit", this._saveRestrictions);
		this.restrictionForm?.destroy();
		this.generateForm?.destroy();
		this.selectGroup?.destroy();
		this.modal?.destroy();
		this.modal = null;
	}
}
