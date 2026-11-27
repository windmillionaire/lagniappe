import { FormController } from "../../../forms/controller.ts";
import { captureError, ENDPOINTS, request } from "../../../shared/index.ts";
import type { RequestResult } from "../../../types/api.d.ts";
import type FormBuilder from "../builder.ts";
import type { DraftGenerationResponse } from "../types.ts";

export class FormSettings {
	declare builder: FormBuilder;
	declare _destroyed: boolean;
	declare _generationPromise: Promise<boolean> | null;
	declare _generationIdentity: {
		request_id: string;
		draft_revision: number;
	} | null;
	declare _restrictionPromise: Promise<void> | null;
	declare column: HTMLElement | null;
	declare restrictions: HTMLFormElement | null;
	declare restrictionForm: FormController | null;
	declare generateForm: FormController | null;

	constructor(builder: FormBuilder) {
		this._destroyed = false;
		this._generationPromise = null;
		this.builder = builder;
		this.column = document.getElementById("form-settings-panel");
		this.restrictions = document.querySelector<HTMLFormElement>(
			"[data-role='restrict-access']",
		);

		const generateTarget =
			this.column?.querySelector<HTMLFormElement>("#generate");
		if (generateTarget) {
			this.generateForm = new FormController({
				target: generateTarget,
				submitGroup: generateTarget.querySelector<HTMLElement>(
					"[data-role='submit-group']",
				),
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
			? new FormController({
					target: this.restrictions,
					messages: {
						submit: "Save Restrictions",
						submitting: "Saving",
						submitted: "Saved",
					},
				})
			: null;
		this._click = this._click.bind(this);
	}

	/**
	 * @scaffolding testing/resources/form.py::Builder.restrict_to_group
	 */
	async init() {
		if (this._destroyed) return;
		if (this.generateForm) {
			await this.generateForm.init();
			if (this._destroyed) return;
			this.generateForm.target.addEventListener("submit", this._generateSchema);
		}

		this.column?.addEventListener("click", this._click);

		if (this.restrictions && this.restrictionForm) {
			this.restrictions.addEventListener("submit", this._saveRestrictions);
			await this.restrictionForm.init();
			if (this._destroyed) return;
			if (this._restrictionPromise) {
				this.restrictionForm.setSubmitButton({
					message: "submitting",
					icon: "spinner",
					disabled: true,
				});
			}
		}
	}

	_click(event: MouseEvent) {
		const button = (event.target as Element | null)?.closest<HTMLElement>(
			"[data-role]",
		);
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
		}
	}

	get visible() {
		return this.column?.dataset.visible === "true";
	}

	set visible(value) {
		if (this.column) this.column.dataset.visible = value ? "true" : "false";
	}

	/**
	 * @scaffolding testing/resources/form.py::Builder.restrict_to_owner
	 * @scaffolding testing/resources/form.py::Builder.restrict_to_group
	 */
	_saveRestrictions(event: Event) {
		event.preventDefault();
		event.stopPropagation();
		if (this._restrictionPromise) return this._restrictionPromise;
		if (this._destroyed) return;
		const form = this.restrictionForm;
		const restrictions = this.restrictions;
		const route = restrictions?.dataset.route;
		if (!form || !restrictions || !route) return;
		const data = new FormData(restrictions);
		const snapshot = JSON.stringify([...data]);
		if (typeof form.setSubmitButton === "function") {
			form.setSubmitButton({
				message: "submitting",
				icon: "spinner",
				disabled: true,
			});
			form.hideError?.();
		} else {
			form.submitting();
			if (form.submitButton) form.submitButton.disabled = true;
		}
		this._restrictionPromise = (async () => {
			let handled = false;
			try {
				const response = await request.put(route, data);
				if (this._destroyed) return;
				if (response?.ok === true) {
					if (JSON.stringify([...new FormData(restrictions)]) === snapshot)
						form.success();
					else {
						form.resetSubmitButton();
						form.markUnsavedState();
					}
					handled = true;
				} else {
					form.showError(
						response?.error || "Could not save restrictions. Try again.",
					);
					handled = true;
				}
			} catch (error) {
				captureError(error, this.restrictions, {
					context: "builder-save-restrictions",
				});
				if (!this._destroyed) {
					form.showError("Could not save restrictions. Try again.");
					handled = true;
				}
			} finally {
				this._restrictionPromise = null;
				if (!this._destroyed && form.submitButton) {
					if (!handled) {
						if (typeof form.setSubmitButton === "function") {
							form.setSubmitButton({
								message: "submit",
								icon: form.icon,
								disabled: false,
							});
						} else {
							form.submitButton.disabled = false;
						}
					} else {
						form.submitButton.disabled = false;
						form.submitButton.setAttribute?.("aria-disabled", "false");
					}
				}
			}
		})();
		return this._restrictionPromise;
	}

	_generateSchema(event: Event) {
		event.preventDefault();
		event.stopPropagation();
		if (this._generationPromise) return this._generationPromise;
		const form = this.generateForm;
		const builderDraft = this.builder.draft;
		if (this._destroyed || !form?.target || !builderDraft) {
			return Promise.resolve(false);
		}

		const data = new FormData(form.target as HTMLFormElement);
		const prompt = data.get("description");
		const submitter =
			((event as SubmitEvent).submitter as
				| HTMLButtonElement
				| HTMLInputElement
				| null) || form.submitButton;

		if (!prompt) {
			form.showError("Please enter a description");
			return Promise.resolve(false);
		}

		this.builder.updateSchema();
		builderDraft.group = null;
		const identity = {
			request_id: crypto.randomUUID(),
			draft_revision: builderDraft.revision,
		};
		this._generationIdentity = identity;
		const draft = this.builder.captureDraft();
		data.set("schema", JSON.stringify(draft.schema));
		data.set("html_fields", JSON.stringify(draft.html_fields));
		data.set("baseline", builderDraft.baseline || "");
		data.set("draft_revision", String(identity.draft_revision));
		data.set("request_id", identity.request_id);
		if (submitter) {
			submitter.disabled = true;
			submitter.setAttribute("aria-disabled", "true");
			submitter.setAttribute("aria-busy", "true");
		}

		const pending = (async () => {
			try {
				const response = await request.post<DraftGenerationResponse>(
					ENDPOINTS.createSchema,
					data,
					{
						replaceErrorPage: false,
					},
				);
				if (this._destroyed) return false;
				if (this._generationIdentity !== identity) return false;
				if (
					identity.draft_revision !== builderDraft.revision ||
					response?.request_id !== identity.request_id ||
					response?.draft_revision !== identity.draft_revision
				) {
					if (response?.ok === true) {
						form.messages.submit = "Regenerate";
						form.showError(
							"Your draft changed while generation was running. Regenerate using your current draft.",
						);
						return false;
					}
				}
				const success = await this._updateSchema(response);
				if (this._destroyed) return false;
				if (success) {
					form.messages.submit = "Generate";
					form.success();
				}
				return success;
			} catch (error) {
				captureError(error, submitter, { context: "builder-generate-schema" });
				if (!this._destroyed) {
					form.showError("Could not generate this form. Try again.");
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

	async _updateSchema(
		response: RequestResult<DraftGenerationResponse> | null | undefined,
	) {
		if (this._destroyed || !this.generateForm) return false;

		if (response?.ok === true && response.operations) {
			try {
				const draft = this.builder.draft;
				if (!draft) return false;
				const revision = draft.revision;
				if (Object.keys(response.html_fields || {}).length)
					await this.builder.prepareGeneratedDocuments(response.html_fields);
				if (this._destroyed || this.builder._destroyed) return false;
				if (revision !== draft.revision) {
					this.generateForm.messages.submit = "Regenerate";
					this.generateForm.showError(
						"Your draft changed while generation was running. Regenerate using your current draft.",
					);
					return false;
				}
				if (draft.applyGeneration(response)) {
					this.builder.restoreDraft();
				}
			} catch (error) {
				this.generateForm.showError(
					error instanceof Error ? error.message : String(error),
				);
				return false;
			}
			return true;
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
		this.column?.removeEventListener("click", this._click);
		this.restrictions?.removeEventListener("submit", this._saveRestrictions);
		this.restrictionForm?.destroy();
		this.generateForm?.destroy();
	}
}
