import { FormRenderer } from "../../../forms/renderer.ts";
import { areEqual, captureError, request } from "../../../shared/index.ts";
import { withTransition } from "../../../shared/transitions.ts";
import type { RequestResult } from "../../../types/api.d.ts";
import type FormBuilder from "../builder.ts";
import { builderControl } from "../controls.ts";
import type {
	DraftAttempt,
	DraftChangeResponse,
	DraftPublication,
	DraftState,
} from "../types.ts";

export class Header {
	declare builder: FormBuilder;
	declare _destroyed: boolean;
	declare _previewGeneration: number;
	declare _messageTimer: number | null;
	declare _savePromise: Promise<boolean> | null;
	declare _saveAttempt?: (DraftAttempt & { baseline: string | null }) | null;
	declare _originalName: string;
	declare nameDisplay: HTMLElement;
	declare nameInput: HTMLInputElement;
	declare nameHidden: HTMLInputElement;
	declare saveButton: HTMLButtonElement | null;
	declare schemaForm: HTMLFormElement | null;
	declare notification: HTMLElement;
	declare previewToggle: HTMLElement;
	declare previewPanel: HTMLElement;
	declare draftControls: HTMLElement | null;
	declare renderer: FormRenderer | null;

	constructor(builder: FormBuilder) {
		this._destroyed = false;
		this._previewGeneration = 0;
		this._messageTimer = null;
		this._savePromise = null;
		this.builder = builder;
		this.nameDisplay = builderControl("form-name-display");
		this.nameInput = document.getElementById(
			"form-name-input",
		) as HTMLInputElement;
		this.nameHidden = document.getElementById(
			"form-name-hidden",
		) as HTMLInputElement;
		this.saveButton = document.querySelector<HTMLButtonElement>("[data-saved]");
		this.schemaForm = document.getElementById(
			"schema-form",
		) as HTMLFormElement | null;
		this.notification = builderControl("notification");
		this.previewToggle = builderControl("preview-toggle");
		this.previewPanel = builderControl("preview-panel");
		this.draftControls = document.querySelector<HTMLElement>(
			"[data-role='draft-history']",
		);
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
			String(
				Boolean(
					this._savePromise ||
						this.builder.pendingChange ||
						this.builder.online === false,
				),
			),
		);
	}

	clearMessage() {
		clearTimeout(this._messageTimer ?? undefined);
		this._messageTimer = null;
		if (!this.notification) return;
		this.notification.textContent = "";
		this.notification.dataset.visible = "false";
	}

	message(text: string, { persistent = false } = {}) {
		if (this._destroyed) return;
		clearTimeout(this._messageTimer ?? undefined);
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

	showConflict(
		response: RequestResult<{ saved_url?: string }> | null | undefined,
	) {
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

	acknowledge(state: DraftState) {
		const current = this.persistenceState;
		if (current.name === state.name && areEqual(current.schema, state.schema)) {
			this.saved();
			return true;
		}
		this.unsaved();
		return false;
	}

	closePreview() {
		this._previewGeneration += 1;
		this.renderer?.destroy();
		this.renderer = null;
		this.previewToggle.dataset.active = "false";
		this.previewToggle.setAttribute("aria-checked", "false");
		this.previewPanel.dataset.visible = "false";
		if (this.draftControls) this.draftControls.dataset.visible = "true";
	}

	async togglePreviewPanel() {
		if (this._destroyed) return;
		const generation = ++this._previewGeneration;
		const active = this.previewToggle.dataset.active === "true";
		this.previewToggle.dataset.active = active ? "false" : "true";
		this.previewToggle.setAttribute("aria-checked", active ? "false" : "true");

		let renderer: FormRenderer | null = null;
		if (!active) {
			renderer = new FormRenderer({
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

	saveForm() {
		if (this.builder.pendingChange) return Promise.resolve(false);
		if (this._savePromise) return this._savePromise;
		if (this.builder.online === false) return Promise.resolve(false);
		const route = this.schemaForm?.dataset.route;
		const draft = this.builder.draft;
		if (this._destroyed || !this.saveButton || !route || !draft) {
			return Promise.resolve(false);
		}

		const button = this.saveButton;
		const hadFocus = document.activeElement === button;
		this.builder.updateSchema();
		if (!draft.dirty) return Promise.resolve(true);
		draft.group = null;
		const state = this.persistenceState;
		if (
			!this._saveAttempt ||
			!draft.equal(this._saveAttempt.state, state) ||
			this._saveAttempt.baseline !== draft.baseline
		) {
			this._saveAttempt = {
				state,
				baseline: draft.baseline,
				id: crypto.randomUUID(),
			};
		}
		const attempt = this._saveAttempt;
		this.unsaved();
		this.clearMessage();
		// Keep keyboard focus; clean and in-flight saves are guarded above.
		button.setAttribute("aria-disabled", "true");
		button.setAttribute("aria-busy", "true");

		const pending = (async () => {
			try {
				const payload = await this.builder.draftPayload(
					state,
					route,
					attempt.id,
				);
				if (this._destroyed) return false;
				const response = await request.put<DraftChangeResponse>(
					route,
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
					draft.acknowledge(state, response as DraftPublication);
					this._saveAttempt = null;
					this.builder.setPendingChange?.(response.pending_change || null);
					if (draft.equal(this.persistenceState, draft.state)) {
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
					this.builder.offline?.(!this.builder.online);
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
		this._originalName = this.nameDisplay.textContent ?? "";
		this.nameDisplay.dataset.visible = "false";
		this.nameInput.dataset.visible = "true";
		this.nameInput.focus();
		this.nameInput.select();
	}

	_nameBlur() {
		const newName = this.nameInput.value.trim();
		this.nameDisplay.textContent = newName;
		this.nameHidden.value = newName;
		this.builder.updateSchema(false, "form-name");
		if (this.builder.draft) this.builder.draft.group = null;
		this.nameInput.dataset.visible = "false";
		this.nameDisplay.dataset.visible = "true";
	}

	_nameInput() {
		this.nameHidden.value = this.nameInput.value.trim();
		this.builder.updateSchema(false, "form-name");
	}

	_nameKeyDown(e: KeyboardEvent) {
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
		clearTimeout(this._messageTimer ?? undefined);
		this._messageTimer = null;
		this.nameInput.removeEventListener("blur", this._nameBlur);
		this.nameInput.removeEventListener("keydown", this._nameKeyDown);
		this.nameInput.removeEventListener("input", this._nameInput);
		this.renderer?.destroy();
		this.renderer = null;
	}
}
