import { Renderer } from "../../../elements/renderer";
import {
	areEqual,
	captureError,
	request,
	withTransition,
} from "../../../shared";

/**
 * @testable infrastructure
 */
export class Header {
	constructor(builder) {
		this._destroyed = false;
		this._previewGeneration = 0;
		this._messageTimer = null;
		this._savePromise = null;
		this.builder = builder;
		this.nameDisplay = document.getElementById("form-name-display");
		this.nameInput = document.getElementById("form-name-input");
		this.nameHidden = document.getElementById("form-name-hidden");
		this.saveButton = document.querySelector("[data-saved]");
		this.schemaForm = document.getElementById("schema-form");
		this.notification = document.getElementById("notification");
		this.previewToggle = document.getElementById("preview-toggle");
		this.previewPanel = document.getElementById("preview-panel");
		this.draftControls = document.querySelector("[data-role='draft-history']");
		this.saveButton?.setAttribute("aria-describedby", "notification");
		this.notification?.setAttribute("role", "status");
		this.notification?.setAttribute("aria-live", "polite");
		this.notification?.setAttribute("aria-atomic", "true");

		this.togglePreviewPanel = this.togglePreviewPanel.bind(this);
		this.saveForm = this.saveForm.bind(this);
		this.editFormName = this.editFormName.bind(this);
		this._nameBlur = this._nameBlur.bind(this);
		this._nameKeyDown = this._nameKeyDown.bind(this);
		this._nameInput = this._nameInput.bind(this);

		this.renderer = null;

		this.init();
	}

	init() {
		this.nameInput.addEventListener("blur", this._nameBlur);
		this.nameInput.addEventListener("keydown", this._nameKeyDown);
		this.nameInput.addEventListener("input", this._nameInput);
	}

	saved() {
		if (!this.saveButton) return;
		this.saveButton.dataset.saved = "true";
		this.saveButton.dataset.kind = "saved";
		this.saveButton.setAttribute("aria-disabled", "true");
		if (!this.builder.pendingChange) this.clearMessage();
	}

	unsaved() {
		if (!this.saveButton) return;
		this.saveButton.dataset.saved = "false";
		this.saveButton.dataset.kind = "unsaved";
		this.saveButton.setAttribute(
			"aria-disabled",
			String(Boolean(this._savePromise || this.builder.pendingChange)),
		);
	}

	clearMessage() {
		clearTimeout(this._messageTimer);
		this._messageTimer = null;
		if (!this.notification) return;
		this.notification.textContent = "";
		this.notification.dataset.visible = "false";
	}

	message(text, { persistent = false } = {}) {
		if (this._destroyed) return;
		clearTimeout(this._messageTimer);
		this._messageTimer = null;
		this.notification.textContent = text;
		this.notification.dataset.visible = "true";
		if (!persistent) {
			this._messageTimer = setTimeout(() => {
				if (this._destroyed) return;
				this.notification.dataset.visible = "false";
			}, 3000);
		}
	}

	showConflict(response) {
		if (response?.code !== "stale_form_draft" || !response.saved_url)
			return false;
		this.message(
			`${response.error || "The saved form changed. Your draft is preserved."} `,
			{ persistent: true },
		);
		const link = document.createElement("a");
		link.href = response.saved_url;
		link.target = "_blank";
		link.rel = "noopener";
		link.dataset.role = "open-saved-form";
		link.className = "underline";
		link.textContent = "Open saved form";
		this.notification.append(link);
		return true;
	}

	get persistenceState() {
		return this.builder.captureDraft();
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/builder/panels/header.mjs::Header.saveForm
	 * @reason acknowledgements are only valid when the live state matches the submitted snapshot
	 */
	acknowledge(state) {
		const current = this.persistenceState;
		if (current.name === state.name && areEqual(current.schema, state.schema)) {
			this.saved();
			return true;
		}
		this.unsaved();
		return false;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_preview_panel
	 * @pair forms:builder-preview
	 */
	closePreview() {
		this._previewGeneration += 1;
		this.renderer?.destroy();
		this.renderer = null;
		this.previewToggle.dataset.active = "false";
		this.previewToggle.setAttribute("aria-checked", "false");
		this.previewPanel.dataset.visible = "false";
		if (this.draftControls) this.draftControls.dataset.visible = "true";
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_preview_panel
	 * @pair forms:builder-preview
	 */
	async togglePreviewPanel() {
		if (this._destroyed) return;
		const generation = ++this._previewGeneration;
		const active = this.previewToggle.dataset.active === "true";
		this.previewToggle.dataset.active = active ? "false" : "true";
		this.previewToggle.setAttribute("aria-checked", active ? "false" : "true");

		let renderer = null;
		if (!active) {
			renderer = new Renderer({
				target: this.previewPanel,
				schema: this.builder.schema,
				kind: "form",
				key: this.builder.key,
				submission: {},
				htmlFields: Object.fromEntries(
					Object.entries(this.builder.htmlFields).map(([id, html]) => [
						id,
						this.builder.previewHtml(html),
					]),
				),
			});
			await renderer.render();
			if (this._destroyed || generation !== this._previewGeneration) {
				renderer.destroy();
				return;
			}
		}

		await withTransition(
			() => {
				if (this._destroyed || generation !== this._previewGeneration) {
					renderer?.destroy();
					return;
				}
				if (this.draftControls)
					this.draftControls.dataset.visible = active ? "true" : "false";
				if (!active) {
					this.renderer = renderer;
					this.builder.elt.dataset.expanded = "true";
					this.previewPanel.dataset.visible = "true";
					this.builder.conditions.hide();
					this.builder.model.hide();
				} else {
					this.renderer?.destroy();
					this.renderer = null;
					this.builder.elt.dataset.expanded = "false";
					this.previewPanel.dataset.visible = "false";
					this.builder.model.show();
				}
			},
			{ label: "builder:toggle-preview" },
		);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_add_inputs_to_form
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_add_fields_to_form
	 * @tests tests_e2e/003_forms/test_003e_retryable_builder_actions.py::test_builder_save_failure_releases_control_for_retry
	 * @tests tests_e2e/003_forms/test_003f_builder_drafts.py::test_save_feedback_retains_keyboard_focus
	 * @tests tests_e2e/003_forms/test_003f_builder_drafts.py::test_generation_is_one_undoable_unsaved_command
	 * @tests tests_e2e/003_forms/test_003f_builder_drafts.py::test_saved_relabels_preserve_active_task_answers_and_conditions
	 * @tests tests_js/test_036_form_builder_frontend.py::test_builder_save_releases_for_retry_and_only_acknowledges_submitted_state
	 * @matrix forms : builder-reload builder-save focus-recovery persistent-error retryable-action single-flight stale-acknowledgement
	 */
	saveForm() {
		if (this.builder.pendingChange) return Promise.resolve(false);
		if (this._savePromise) return this._savePromise;
		if (this._destroyed || !this.saveButton || !this.schemaForm) {
			return Promise.resolve(false);
		}

		const button = this.saveButton;
		const hadFocus = document.activeElement === button;
		this.builder.updateSchema();
		if (!this.builder.draft.dirty) return Promise.resolve(true);
		this.builder.draft.group = null;
		const state = this.persistenceState;
		if (
			!this._saveAttempt ||
			!this.builder.draft.equal(this._saveAttempt.state, state) ||
			this._saveAttempt.baseline !== this.builder.draft.baseline
		) {
			this._saveAttempt = {
				state,
				baseline: this.builder.draft.baseline,
				id: crypto.randomUUID(),
			};
		}
		this.unsaved();
		this.clearMessage();
		// Keep keyboard focus; clean and in-flight saves are guarded above.
		button.setAttribute("aria-disabled", "true");
		button.setAttribute("aria-busy", "true");

		const pending = (async () => {
			try {
				const payload = await this.builder.draftPayload(
					state,
					this.schemaForm.dataset.route,
					this._saveAttempt.id,
				);
				if (this._destroyed) return false;
				const response = await request.put(
					this.schemaForm.dataset.route,
					payload,
					{ replaceErrorPage: false },
				);
				if (this._destroyed) return false;
				if (response?.rejected_change) {
					this._saveAttempt = null;
					this.message(response.rejected_change.error, { persistent: true });
					return false;
				}
				if (response?.ok === true && response.draft && response.baseline) {
					this.builder.draft.acknowledge(state, response);
					this._saveAttempt = null;
					this.builder.setPendingChange?.(response.pending_change || null);
					if (
						this.builder.draft.equal(
							this.persistenceState,
							this.builder.draft.state,
						)
					) {
						this.builder.settings.refreshSavedState();
						this.builder.conditions.condition?.refreshSavedState?.();
						this.builder.refreshDraftControls();
					} else {
						await this.builder.restoreDraft({ preserveFocus: true });
					}
					return true;
				}
				if (!this.showConflict(response))
					this.message(
						response?.error || "Could not save this form. Try again.",
						{ persistent: true },
					);
				return false;
			} catch (error) {
				captureError(error, button, { context: "builder-save" });
				this.message("Could not save this form. Try again.", {
					persistent: true,
				});
				return false;
			} finally {
				if (!this._destroyed && button.isConnected !== false) {
					button.setAttribute(
						"aria-disabled",
						String(
							Boolean(
								this.builder.pendingChange || button.dataset.saved === "true",
							),
						),
					);
					button.removeAttribute("aria-busy");
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
		})();
		this._savePromise = pending;
		const clearPending = () => {
			if (this._savePromise === pending) this._savePromise = null;
		};
		pending.then(clearPending, clearPending);
		return pending;
	}

	editFormName() {
		if (this.builder.pendingChange) return;
		this._originalName = this.nameDisplay.textContent;
		this.nameDisplay.dataset.visible = "false";
		this.nameInput.dataset.visible = "true";
		this.nameInput.focus();
		this.nameInput.select();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_copy_form_from_builder_title_menu
	 * @pairs entity-menu:title-menu forms:builder-form-name frontend-icons:material-icon-preservation
	 */
	_nameBlur() {
		const newName = this.nameInput.value.trim();
		this.nameDisplay.textContent = newName;
		this.nameHidden.value = newName;
		this.builder.updateSchema(false, "form-name");
		this.builder.draft.group = null;
		this.nameInput.dataset.visible = "false";
		this.nameDisplay.dataset.visible = "true";
	}

	_nameInput() {
		this.nameHidden.value = this.nameInput.value.trim();
		this.builder.updateSchema(false, "form-name");
	}

	_nameKeyDown(e) {
		if (e.key === "Enter") {
			e.preventDefault();
			this.nameInput.blur();
		} else if (e.key === "Escape") {
			this.nameInput.value = this._originalName;
			this.nameInput.blur();
		}
	}

	destroy() {
		if (this._destroyed) return;
		this._destroyed = true;
		this._previewGeneration += 1;
		clearTimeout(this._messageTimer);
		this._messageTimer = null;
		this.nameInput.removeEventListener("blur", this._nameBlur);
		this.nameInput.removeEventListener("keydown", this._nameKeyDown);
		this.nameInput.removeEventListener("input", this._nameInput);
		this.renderer?.destroy();
		this.renderer = null;
	}
}
