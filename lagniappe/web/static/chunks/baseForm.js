/*! Third-party licenses: /third-party-licenses.txt */
import { g as generateElementId, w as withTransition, c as captureError, s as showBriefly } from './foundation.js?v=b4b0f2eb';
import './connectivity.js?v=b4b0f2eb';
import { c as createIcon } from './icons.js?v=b4b0f2eb';
import { p as primitives } from './primitives.js?v=b4b0f2eb';
import { g as getFormElement } from './loader.js?v=b4b0f2eb';

/**
 * @testable infrastructure
 */
class Renderer {
	constructor(form) {
		this.id = generateElementId("renderer");
		this.form = form;
		this.kind = form.kind || form.target.dataset.kind || "form";
		this.elements = new Map();
		this.visibilityTriggers = new Map();
		this.visibilityConditions = new Map();
		this.statusTriggers = new Set();
		this.status = null;

		this._onChange = this._onChange.bind(this);
	}

	get target() {
		return this.form.target;
	}

	get readonly() {
		return this.form.readonly;
	}

	get showEmptyFields() {
		return this.form.showEmptyFields;
	}

	get historyFillEnabled() {
		return this.form.historyFillEnabled;
	}

	async render() {
		await this._createElements();

		const html = Array.from(this.elements.values())
			.map((element) => element.elt)
			.filter(Boolean);
		this.form.target.replaceChildren(...html);

		this._initStatusTriggers();

		this._initVisibilityTriggers();
		if (!this.readonly) {
			this.target.addEventListener("change", this._onChange);
		}

		this._updateDerivedState();
		this.target.setAttribute("rendered", "");
	}

	destroy() {
		this.elements.forEach((element) => {
			if (element.destroy) element.destroy();
		});
		this.target.removeAttribute("rendered");
		this.target.removeEventListener("change", this._onChange);
		this.visibilityTriggers.clear();
		this.visibilityConditions.clear();
		this.statusTriggers.clear();
	}

	_packageSubmission() {
		const result = Object.fromEntries(
			Array.from(this.elements.values()).map((element) => [
				element.schema.id,
				element.value,
			]),
		);

		return result;
	}

	_onChange(event) {
		const trigger = event.target.closest(".form-element");
		if (!trigger) return;

		const element = this.elements.get(trigger.id);
		if (!element) return;

		if (this.statusTriggers.has(element)) {
			this.status.update();
		}
		if (this.visibilityTriggers.has(element)) {
			this._updateVisibility(element);
		}
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_form_field_fills_from_latest_history
	 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_fill_controls_cover_submission_elements
	 * @features tasks
	 * @dimensions history-fill latest-submission element-matrix
	 */
	addHistoryFillButtons(submission, onFill = null) {
		if (!this.historyFillEnabled || !submission) return;

		for (const [fieldId, value] of Object.entries(submission)) {
			const element = this.elements.get(`${fieldId}-${this.id}`);
			element?.addHistoryFill?.(value, onFill);
		}
	}

	async _initStatusTriggers() {
		this.statusTriggers.clear();
		this.status = Array.from(this.elements.values()).find(
			(element) => element.schema.type === "status",
		);
		if (!this.status) return;

		const messages = Array.isArray(this.status.schema.status)
			? this.status.schema.status
			: [];
		for (const message of messages) {
			if (!message?.id) continue;

			const trigger = this.elements.get(`${message.id}-${this.id}`);
			if (!trigger) continue;

			this.statusTriggers.add(trigger);
		}
	}

	/**
	 * @testable true
	 * @tests tests_js/test_019_form_sync_frontend.py::test_renderer_visibility_requires_canonical_condition_lists
	 * @features forms form-schema
	 * @dimensions visibility canonical-list legacy-object-rejected
	 */
	async _initVisibilityTriggers() {
		this.visibilityTriggers = new Map();
		this.visibilityConditions.clear();

		const targets = Array.from(this.elements.values()).filter(
			(element) => element.schema.visibility && element.elt,
		);

		for (const target of targets) {
			const conditions = target.schema.visibility.filter(
				(trigger) => trigger?.id,
			);
			if (conditions.length === 0) continue;
			this.visibilityConditions.set(target, conditions);

			for (const trigger of conditions) {
				const element = this.elements.get(`${trigger.id}-${this.id}`);
				if (!element?.elt) continue;

				const values = this.visibilityTriggers.get(element) || new Set();
				values.add(target);
				this.visibilityTriggers.set(element, values);
			}
		}
	}

	_updateDerivedState() {
		this.status?.update();
		this.visibilityConditions.forEach((_conditions, target) => {
			this._updateVisibilityTarget(target);
		});
	}

	_updateVisibility(trigger) {
		const targets = this.visibilityTriggers.get(trigger);
		if (!targets) return;

		const changes = Array.from(targets, (target) => ({
			target,
			visible: this._visibilityConditionsMatch(target),
		})).filter(
			({ target, visible }) =>
				target.elt.dataset.visible !== (visible ? "true" : "false"),
		);
		if (!changes.length) return;

		void withTransition(
			() => {
				changes.forEach(({ target, visible }) => {
					target.elt.dataset.visible = visible ? "true" : "false";
				});
			},
			{ label: "form:conditional-visibility" },
		);
	}

	_updateVisibilityTarget(target) {
		const visible = this._visibilityConditionsMatch(target);
		target.elt.dataset.visible = visible ? "true" : "false";
	}

	_visibilityConditionsMatch(target) {
		const conditions = (this.visibilityConditions.get(target) || []).filter(
			(condition) => condition?.id,
		);
		if (conditions.length === 0) return true;

		const groups = new Map();

		for (const condition of conditions) {
			const group = groups.get(condition.id) || [];
			group.push(condition);
			groups.set(condition.id, group);
		}

		return Array.from(groups.entries()).every(([triggerId, group]) => {
			const element = this.elements.get(`${triggerId}-${this.id}`);
			if (!element) return false;
			return group.some((condition) => element.active(condition.value));
		});
	}

	async _createElements() {
		for (const eltSchema of this.form.schema) {
			const eltSubmission = this.form.submission?.[eltSchema.id];
			try {
				const element = await getFormElement(this, eltSchema, eltSubmission);
				this.elements.set(element.id, element);
			} catch (error) {
				captureError(error, this.target, {
					schema: eltSchema,
					submission: eltSubmission,
				});
			}
		}
	}
}

/**
 * @testable infrastructure
 */
class BaseForm {
	constructor(widget) {
		this._widget = widget;

		this._submitGroup = widget.submitGroup ?? null;
		this._submitButton = widget.submitButton ?? null;
		this._header = widget.header ?? null;
		this._messages = widget.messages ?? {};
		this._icon = widget.icon ?? null;
		this._error = widget.error ?? null;
		this._editedMarker =
			widget.target?.querySelector("[lp-edited-marker]") ?? null;
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
			return this.target.querySelector("[data-role='submit-group']");
		}
	}

	get submitButton() {
		if (this.readonly) {
			return null;
		} else if (this._subForm) {
			return this._subForm.submitButton;
		} else if (this._submitButton) {
			return this._submitButton;
		} else if (this.submitGroup) {
			return this.submitGroup.querySelector("button[type='submit']");
		} else {
			return this.target.querySelector("button[type='submit']");
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
			this.target.querySelector("[data-role='error']") ??
			primitives.error();

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
		const prepend = this._widget.prepend;
		const append = this._widget.append;
		const html = this.html ?? [];
		const schema = this.schema ?? [];

		if (schema.length > 0) {
			this.renderer = new Renderer(this);
			await this.renderer.render();
		} else if (html.length > 0) {
			this.target.replaceChildren(...html.filter(Boolean));
		}

		this.target.setAttribute("autocomplete", "off");

		if (this._header && !this.target.contains(this._header)) {
			this.target.prepend(this._header);
		}

		if (Array.isArray(prepend)) {
			this.target.prepend(...prepend.filter(Boolean));
		}

		const submitGroup = this.submitGroup ?? this.submitButton;
		if (Array.isArray(append)) {
			this.target.append(...append.filter(Boolean));
			if (submitGroup) this.target.append(submitGroup);
		} else if (submitGroup && !this.target.contains(submitGroup)) {
			this.target.append(submitGroup);
		}

		if (this._editedMarker && !this.target.contains(this._editedMarker)) {
			const markerAnchor = this.submitGroup ?? this.submitButton;
			if (markerAnchor) {
				markerAnchor.before(this._editedMarker);
			} else {
				this.target.append(this._editedMarker);
			}
		}

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

	markUnsavedState(event = null) {
		const control = event?.target;
		if (
			control &&
			(typeof control.matches !== "function" ||
				!control.matches("input, select, textarea, [contenteditable='true']") ||
				control.disabled)
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

	setSubmitButton(attributes) {
		const { submitButton, submitGroup } = this;
		const { message, icon, disabled, fade = false } = attributes;
		if (!submitButton) return;
		let textElement = submitButton.querySelector("span[data-role='text']");
		if (!textElement) {
			textElement = document.createElement("span");
			textElement.dataset.role = "text";
			submitButton.replaceChildren(textElement);
		}
		textElement.textContent = this.messages[message] ?? message ?? "";

		let iconWrapper = submitButton.querySelector("span[data-role='icon']");
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

	toggleSubForm(form) {
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

	showError(error) {
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
		this.submitButton.disabled = true;
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

var baseForm = /*#__PURE__*/Object.freeze({
	__proto__: null,
	BaseForm: BaseForm
});

export { BaseForm as B, Renderer as R, baseForm as b };
