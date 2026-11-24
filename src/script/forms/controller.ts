import { primitives } from "../elements/primitives.mjs";
import { createIcon } from "../shared/icons.ts";
import { withTransition } from "../shared/transitions.ts";
import { showBriefly } from "../shared/utilities.ts";
import type { FormSchema, FormSubmission } from "../types/forms.d.ts";
import { initFormControls } from "./controls/loader.ts";
import { FormRenderer } from "./renderer.ts";

type FormFragment = Node | string | false | null | undefined;
type FormMessages = Record<string, string>;
type SubmitButton = HTMLButtonElement & { __initialized?: boolean };

export interface FormSubmitOptions {
	route?: string | null;
	submitter?: HTMLElement | null;
}

interface FormControllerWidget {
	target: HTMLElement;
	key?: string | null;
	readonly?: boolean;
	showEmptyFields?: boolean;
	historyFillEnabled?: boolean;
	schema?: FormSchema | null;
	submission?: FormSubmission | null;
	htmlFields?: Record<string, string> | null;
	html?: FormFragment[] | null;
	prepend?: FormFragment[] | null;
	append?: FormFragment[] | null;
	submitGroup?: HTMLElement | null;
	submitButton?: HTMLButtonElement | null;
	header?: HTMLElement | null;
	messages?: FormMessages | null;
	icon?: string | null;
	error?: HTMLElement | null;
	view?: { elt?: EventTarget | null; offline?: boolean } | null;
	offline?: unknown;
	unsavedState?: boolean;
	markUnsavedState?(): void;
	clearUnsavedState?(): void;
}

interface FormControllerSubForm {
	submitGroup: HTMLElement | null;
	submitButton: HTMLButtonElement | null;
	messages: FormMessages;
	icon?: string | null;
	deferred?: boolean;
	applyDirectUploads?(data: FormData): FormData;
	prepareSubmit?(options?: FormSubmitOptions): boolean | Promise<boolean>;
}

interface SubmitButtonAttributes {
	message: string;
	icon?: string | null;
	disabled?: boolean;
	fade?: boolean;
}

const presentFragment = (fragment: FormFragment): fragment is Node | string =>
	Boolean(fragment);

export class FormController {
	declare private _widget: FormControllerWidget;
	declare _destroyed: boolean;
	declare private _submitGroup: HTMLElement | null;
	declare private _submitButton: HTMLButtonElement | null;
	declare private _header: HTMLElement | null;
	declare private _messages: FormMessages;
	declare private _icon: string | null;
	declare private _error: HTMLElement | null;
	declare private _editedMarker: HTMLElement | null;
	declare _subForm: FormControllerSubForm | null;
	declare renderer: FormRenderer | null;
	declare destroyables: { destroy?(): void }[];
	declare private _offlineBlocked: boolean;
	declare private _offlineListener: EventListener | null;
	declare private _unsavedStateListener: EventListener | null;
	declare private _resetListener: EventListener | null;
	declare _queued: boolean;

	constructor(widget: FormControllerWidget) {
		this._widget = widget;
		this._destroyed = false;

		this._submitGroup = widget.submitGroup ?? null;
		this._submitButton = widget.submitButton ?? null;
		this._header = widget.header ?? null;
		this._messages = widget.messages ?? {};
		this._icon = widget.icon ?? null;
		this._error = widget.error ?? null;
		this._editedMarker =
			widget.target?.querySelector<HTMLElement>("[lp-edited-marker]") ?? null;
		this._subForm = null;

		this.renderer = null;
		this.destroyables = [];
		this._offlineBlocked = false;
		this._offlineListener = null;
		this._unsavedStateListener = null;
		this._resetListener = null;
		this._queued = false;

		this.markUnsavedState = this.markUnsavedState.bind(this);
		this.clearUnsavedState = this.clearUnsavedState.bind(this);
		this.submitting = this.submitting.bind(this);
		this.syncOfflineState = this.syncOfflineState.bind(this);
	}

	get target() {
		return this._widget.target;
	}

	get key() {
		return this._widget.key;
	}

	get html() {
		return this._widget.html;
	}

	get readonly() {
		return this._widget.readonly;
	}

	get showEmptyFields() {
		return this._widget.showEmptyFields;
	}

	get historyFillEnabled() {
		return this._widget.historyFillEnabled ?? false;
	}

	get submitGroup() {
		if (this.readonly) {
			return null;
		} else if (this._subForm) {
			return this._subForm.submitGroup;
		} else if (this._submitGroup) {
			return this._submitGroup;
		} else {
			return this.target.querySelector<HTMLElement>(
				"[data-role='submit-group']",
			);
		}
	}

	get submitButton(): SubmitButton | null {
		if (this.readonly) {
			return null;
		} else if (this._subForm) {
			return this._subForm.submitButton;
		} else if (this._submitButton) {
			return this._submitButton;
		} else if (this.submitGroup) {
			return this.submitGroup.querySelector<HTMLButtonElement>(
				"button[type='submit']",
			);
		} else {
			return this.target.querySelector<HTMLButtonElement>(
				"button[type='submit']",
			);
		}
	}

	get schema() {
		return this._widget.schema ?? [];
	}

	get submission() {
		return this._widget.submission ?? {};
	}

	get htmlFields() {
		return this._widget.htmlFields ?? {};
	}

	get messages() {
		if (this._subForm) {
			return this._subForm.messages;
		} else {
			return this._messages ?? {};
		}
	}

	get icon() {
		if (this._subForm) {
			return this._subForm.icon;
		} else {
			return this._icon ?? null;
		}
	}

	get error() {
		const error =
			this._error ??
			this.target.querySelector<HTMLElement>("[data-role='error']") ??
			primitives.error(undefined);

		if (!this.target.contains(error)) {
			const anchor = this.submitGroup || this.submitButton;
			anchor ? anchor.before(error) : this.target.prepend(error);
		}
		return error;
	}

	get canSubmitOffline() {
		if (this._subForm?.deferred) return false;
		return (
			this.target?.hasAttribute("lp-offline") &&
			typeof this._widget.offline === "function"
		);
	}

	async init() {
		try {
			await this._initialize();
		} catch (error) {
			this.destroy();
			throw error;
		}
	}

	async _initialize() {
		const prepend = this._widget.prepend;
		const append = this._widget.append;
		const html = this.html ?? [];
		const schema = this.schema ?? [];

		if (schema.length > 0) {
			this.renderer = new FormRenderer(this);
			await this.renderer.render();
		} else if (html.length > 0) {
			this.target.replaceChildren(...html.filter(presentFragment));
		}

		this.target.setAttribute("autocomplete", "off");

		if (this._header && !this.target.contains(this._header)) {
			this.target.prepend(this._header);
		}

		if (Array.isArray(prepend)) {
			this.target.prepend(...prepend.filter(presentFragment));
		}

		const submitGroup = this.submitGroup ?? this.submitButton;
		if (Array.isArray(append)) {
			this.target.append(...append.filter(presentFragment));
			if (submitGroup) this.target.append(submitGroup);
		} else if (submitGroup && !this.target.contains(submitGroup)) {
			this.target.append(submitGroup);
		}

		if (this._editedMarker) {
			const autofillPanel = this.target.querySelector("[data-role='autofill']");
			if (autofillPanel) {
				autofillPanel.before(this._editedMarker);
			} else if (!this.target.contains(this._editedMarker)) {
				const markerAnchor = this.submitGroup ?? this.submitButton;
				if (markerAnchor) {
					markerAnchor.before(this._editedMarker);
				} else {
					this.target.append(this._editedMarker);
				}
			}
		}

		await initFormControls(this);
		if (this._destroyed) return;
		this._initSubmitButton();
		this._initOfflineState();
		this._initUnsavedState();

		this.target.setAttribute("rendered", "");
	}

	_initOfflineState() {
		const viewElt = this._widget.view?.elt;
		if (viewElt && !this._offlineListener) {
			this._offlineListener = () => this.syncOfflineState();
			viewElt.addEventListener("offline-status", this._offlineListener);
		}

		this.syncOfflineState();
	}

	_initUnsavedState() {
		if (this.readonly || !this.submitButton || this._unsavedStateListener)
			return;

		this._unsavedStateListener = this.markUnsavedState;
		this._resetListener = () => queueMicrotask(this.clearUnsavedState);
		this.target.addEventListener("input", this._unsavedStateListener);
		this.target.addEventListener("change", this._unsavedStateListener);
		this.target.addEventListener("reset", this._resetListener);
		this.syncOfflineState();
	}

	markUnsavedState(event: Event | null = null) {
		const control = event?.target;
		if (
			control &&
			(!("matches" in control) ||
				typeof control.matches !== "function" ||
				!control.matches("input, select, textarea, [contenteditable='true']") ||
				("disabled" in control && control.disabled))
		) {
			return;
		}

		if (this._widget.markUnsavedState) {
			this._widget.markUnsavedState();
		} else {
			this._widget.unsavedState = true;
			this.syncOfflineState();
		}
	}

	clearUnsavedState() {
		if (this._widget.clearUnsavedState) {
			this._widget.clearUnsavedState();
		} else {
			this._widget.unsavedState = false;
		}
		if (!this._queued && !this._offlineBlocked && this.submitButton) {
			this.setSubmitButton({
				message: "submit",
				icon: this.icon,
				disabled: false,
			});
		}
	}

	success() {
		if (!this.submitButton) return;

		this._queued = false;
		this.clearUnsavedState();
		this.hideError();
		this.setSubmitButton({
			message: "submitted",
			icon: "check",
			fade: true,
			disabled: false,
		});
	}

	submitting() {
		if (!this.submitButton) return;
		if (this.syncOfflineState()) return;

		this._queued = false;
		this.setSubmitButton({
			message: "submitting",
			icon: "spinner",
		});
		this.hideError();
	}

	setSubmitButton(attributes: SubmitButtonAttributes) {
		const { submitButton, submitGroup } = this;
		const { message, icon, disabled, fade = false } = attributes;
		if (!submitButton) return;
		let textElement = submitButton.querySelector<HTMLSpanElement>(
			"span[data-role='text']",
		);
		if (!textElement) {
			textElement = document.createElement("span");
			textElement.dataset.role = "text";
			submitButton.replaceChildren(textElement);
		}
		textElement.textContent = this.messages[message] ?? message ?? "";

		let iconWrapper = submitButton.querySelector<HTMLSpanElement>(
			"span[data-role='icon']",
		);
		if (icon) {
			if (!iconWrapper) {
				iconWrapper = document.createElement("span");
				iconWrapper.dataset.role = "icon";
				submitButton.prepend(iconWrapper);
			}
			const iconElement = createIcon(icon);
			iconWrapper.dataset.visible = "true";
			if (fade) {
				showBriefly(iconWrapper, iconElement);
			} else {
				iconWrapper.replaceChildren(iconElement);
			}
		} else if (iconWrapper) {
			iconWrapper.replaceChildren();
			iconWrapper.dataset.visible = "false";
		}

		submitButton.dataset.visible = "true";
		submitButton.classList.remove("hidden");
		submitButton.disabled = Boolean(disabled);
		submitButton.setAttribute("aria-disabled", disabled ? "true" : "false");
		submitButton.classList.toggle("opacity-75", Boolean(disabled));
		submitButton.classList.toggle("cursor-not-allowed", Boolean(disabled));
		submitButton.classList.toggle("pointer-events-none", Boolean(disabled));
		if (submitGroup) submitGroup.dataset.visible = "true";
	}

	queued() {
		if (!this.submitButton) return;

		this._queued = true;
		this.hideError();
		this.setSubmitButton({
			message: "queued",
			icon: "offline",
			disabled: false,
		});
	}

	toggleSubForm(form?: FormControllerSubForm | null) {
		if (form) {
			this.hideSubmitGroup();
			this._subForm = form;
		} else {
			this._subForm = null;
			this.showSubmitGroup();
		}
		this._initSubmitButton();
	}

	_initSubmitButton() {
		const submitButton = this.submitButton;
		if (!this.messages?.submit || !submitButton) return;

		this.setSubmitButton({ message: "submit", icon: this.icon });
		if (submitButton.__initialized || !this.messages?.submitting) return;
		submitButton.__initialized = true;

		submitButton.addEventListener("click", this.submitting);
	}

	syncOfflineState() {
		if (!this.submitButton) return false;

		const blocked = Boolean(
			this._widget.view?.offline && !this.canSubmitOffline,
		);
		const wasBlocked = this._offlineBlocked;
		if (blocked) {
			this._offlineBlocked = true;
			this.hideError();
			this.setSubmitButton({
				message: "Server Offline",
				icon: "offline",
				disabled: true,
			});
			return true;
		}

		this._offlineBlocked = false;
		if (this._queued) return false;
		if (this.submitButton.disabled && !wasBlocked) return false;

		if (this._widget.unsavedState) {
			this.setSubmitButton({
				message: "submit",
				icon: "builder.unsaved",
				disabled: false,
			});
			return false;
		}

		if (wasBlocked) {
			this.setSubmitButton({
				message: "submit",
				icon: this.icon,
				disabled: false,
			});
		}
		return false;
	}

	showError(error: string) {
		const errorElement = this.error;
		if (!errorElement) return;

		withTransition(() => {
			errorElement.textContent = error;
			errorElement.dataset.visible = "true";
			this.setSubmitButton({
				message: "submit",
				icon: this.icon,
				disabled: false,
			});
			this.syncOfflineState();
		});
	}

	hideError() {
		if (!this.error) return;

		this.error.textContent = "";
		this.error.dataset.visible = "false";
	}

	showSubmitButton() {
		if (!this.submitButton) return;

		this.hideError();
		this.setSubmitButton({
			message: "submit",
			icon: this.icon,
			disabled: false,
		});
		this.syncOfflineState();
	}

	showSubmitGroup() {
		if (!this.submitGroup) return;

		this.hideError();
		this.setSubmitButton({
			message: "submit",
			icon: this.icon,
			disabled: false,
		});
		this.syncOfflineState();
	}

	hideSubmitGroup() {
		if (!this.submitGroup) return;

		this.hideError();
		this.submitGroup.dataset.visible = "false";
		const submitButton = this.submitButton;
		if (!submitButton) throw new TypeError("Submit group has no submit button");
		submitButton.disabled = true;
	}

	hideSubmitButton() {
		if (!this.submitButton) return;

		this.hideError();
		this.submitButton.dataset.visible = "false";
		this.submitButton.disabled = true;
	}

	resetSubmitButton() {
		this._queued = false;
		this.setSubmitButton({
			message: "submit",
			icon: this.icon,
			disabled: false,
		});
		this.hideError();
		this.syncOfflineState();
	}

	destroy() {
		if (this._destroyed) return;
		this._destroyed = true;
		const submitButton = this.submitButton;
		if (submitButton?.__initialized) {
			submitButton.removeEventListener("click", this.submitting);
			delete submitButton.__initialized;
		}
		if (this._offlineListener) {
			this._widget.view?.elt?.removeEventListener(
				"offline-status",
				this._offlineListener,
			);
			this._offlineListener = null;
		}
		if (this._unsavedStateListener) {
			this.target?.removeEventListener("input", this._unsavedStateListener);
			this.target?.removeEventListener("change", this._unsavedStateListener);
			this._unsavedStateListener = null;
		}
		if (this._resetListener) {
			this.target?.removeEventListener("reset", this._resetListener);
			this._resetListener = null;
		}
		if (this.renderer) this.renderer.destroy();
		this.destroyables.forEach((destroyable) => {
			if (destroyable.destroy) destroyable.destroy();
		});
		this.destroyables = [];
	}
}
