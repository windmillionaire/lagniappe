import { sections } from "../elements/sections.mjs";
import { FormController } from "../forms/controller.mjs";
import { captureError, request } from "../shared/index.ts";
import { FormWidget } from "./base/formWidget.mjs";

async function renderOriginalSubmission(response, key) {
	const host = document.createElement("div");
	host.dataset.kind = "task";
	const form = new FormController({
		target: host,
		key,
		readonly: true,
		schema: response.schema || [],
		submission: response.submission || {},
		htmlFields: response.html_fields || {},
		showEmptyFields: false,
	});
	await form.init();
	const error = response.schema_error || response.content_error;
	if (error) {
		const message = document.createElement("p");
		message.setAttribute("role", "status");
		message.textContent = error;
		host.prepend(message);
	}
	if (response.raw_submission) {
		const raw = document.createElement("pre");
		raw.dataset.role = "original-raw-answers";
		raw.className = "whitespace-pre-wrap break-words";
		raw.textContent = JSON.stringify(response.raw_submission, null, 2);
		host.append(raw);
	}
	return { form, host };
}

export class TaskForm extends FormWidget {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Update",
			submitting: "Updating",
			submitted: "Updated",
			queued: "Queued Sync",
		};
		this._historyFillRequest = null;
		this._historyFillSubmission = null;
		this._historyFillGeneration = 0;
		this._originalCompletionForm = null;
		this._archivedSubmissionForm = null;
		this._originalCompletionGeneration = 0;
		this._showOriginalCompletion = this._showOriginalCompletion.bind(this);
		this._showArchivedSubmission = this._showArchivedSubmission.bind(this);
		this._selectCompletionSubmission =
			this._selectCompletionSubmission.bind(this);
	}

	get autofillElement() {
		if (this.readonly) return null;
		return sections.autofill(this);
	}

	get historyFillRoute() {
		return this.endpoints?.latestHistorySubmission;
	}

	get historyFillEnabled() {
		return Boolean(
			!this.revisionPreview &&
				!this.readonly &&
				this.hasHistory &&
				this.historyFillRoute,
		);
	}

	get hasHistory() {
		return Boolean(
			this.target?.dataset.history ||
				this.component?.elt.querySelector("[data-widget='TaskHistory']"),
		);
	}

	get prepend() {
		const archived = this.target.querySelector(
			"[data-role='archived-submission-controls']",
		);
		archived
			?.querySelector("[data-role='load-archived-submission']")
			?.addEventListener("click", this._showArchivedSubmission);
		const original = this.target.querySelector(
			"[data-role='original-completion-controls']",
		);
		original
			?.querySelector("[data-role='view-original-completion']")
			?.addEventListener("click", this._showOriginalCompletion);
		original
			?.querySelector("[data-role='completion-submission-options']")
			?.addEventListener("change", this._selectCompletionSubmission);
		return [
			archived,
			original,
			this.target.querySelector("[data-role='empty-completed-submission']"),
		];
	}

	get append() {
		const error = this.target?.dataset.schemaError;
		const notice = error ? document.createElement("p") : null;
		if (notice) {
			notice.textContent = error;
			notice.setAttribute("role", "status");
		}
		let raw = null;
		if (error && this.target?.dataset.rawSubmission) {
			raw = document.createElement("pre");
			raw.dataset.role = "original-raw-answers";
			raw.className = "whitespace-pre-wrap break-words";
			raw.textContent = JSON.stringify(
				JSON.parse(this.target.dataset.rawSubmission),
				null,
				2,
			);
		}
		return [this.autofillElement, notice, raw];
	}

	_setCompletionView(showOriginal) {
		const controls = this.target.querySelector(
			"[data-role='original-completion-controls']",
		);
		let current = this.target.querySelector(
			"[data-role='current-completion-detail']",
		);
		if (!current) {
			current = document.createElement("div");
			current.dataset.role = "current-completion-detail";
			current.className = "flex flex-col gap-6";
			// Group the current fields only when an original is first requested.
			current.append(
				...Array.from(this.target.children).filter(
					(child) => child !== controls && !child.matches("[lp-edited-marker]"),
				),
			);
			controls.after(current);
		}
		current.hidden = showOriginal;
		controls.querySelector("[data-role='original-completion-detail']").hidden =
			!showOriginal;
	}

	_selectCompletionSubmission(event) {
		event.stopPropagation();
		this._setCompletionView(event.target.value === "original");
	}

	async _showOriginalCompletion(event) {
		event.preventDefault();
		event.stopPropagation();
		const button = event.currentTarget;
		const controls = button.closest(
			"[data-role='original-completion-controls']",
		);
		const target = controls.querySelector(
			"[data-role='original-completion-detail']",
		);
		if (button.disabled) return;
		const generation = this._originalCompletionGeneration;
		button.disabled = true;
		try {
			if (!this._originalCompletionForm) {
				const response = await request.get(button.dataset.route);
				const { form, host } = await renderOriginalSubmission(
					response,
					this.key,
				);
				host.className = "flex flex-col gap-6";
				if (
					generation !== this._originalCompletionGeneration ||
					!this.target.contains(button)
				) {
					form.destroy();
					return;
				}
				target.replaceChildren(host);
				this._originalCompletionForm = form;
			}
			this._setCompletionView(true);
			const options = controls.querySelector(
				"[data-role='completion-submission-options']",
			);
			for (const radio of options.querySelectorAll("input")) {
				radio.disabled = false;
				radio.checked = radio.value === "original";
			}
			options.hidden = false;
			options.querySelector("input:checked").focus();
		} catch (error) {
			if (generation !== this._originalCompletionGeneration) return;
			target.textContent =
				"Could not load the original submission. Please try again.";
			target.hidden = false;
			captureError(error, this.target, { route: button.dataset.route });
		} finally {
			button.disabled = false;
		}
	}

	async _showArchivedSubmission(event) {
		event.preventDefault();
		event.stopPropagation();
		const button = event.currentTarget;
		if (button.disabled) return;
		const generation = this._originalCompletionGeneration;
		const target = button
			.closest("[data-role='archived-submission-controls']")
			.querySelector("[data-role='archived-submission-detail']");
		button.disabled = true;
		try {
			if (!this._archivedSubmissionForm) {
				const response = await request.get(button.dataset.route);
				const { form, host } = await renderOriginalSubmission(
					response,
					this.key,
				);
				if (
					generation !== this._originalCompletionGeneration ||
					!this.target.contains(button)
				) {
					form.destroy();
					return;
				}
				host.className = "flex flex-col gap-6";
				target.replaceChildren(host);
				this._archivedSubmissionForm = form;
			}
			target.hidden = false;
			const original = this.target.querySelector(
				"[data-role='original-completion-controls']",
			);
			if (original) original.hidden = false;
		} catch (error) {
			if (generation !== this._originalCompletionGeneration) return;
			target.textContent =
				"Could not load the archived version. Please try again.";
			target.hidden = false;
			captureError(error, this.target, { route: button.dataset.route });
		} finally {
			button.disabled = false;
		}
	}

	_clearOriginalCompletion() {
		this._originalCompletionGeneration += 1;
		this._originalCompletionForm?.destroy();
		this._originalCompletionForm = null;
		this._archivedSubmissionForm?.destroy();
		this._archivedSubmissionForm = null;
	}

	destroy() {
		this._clearOriginalCompletion();
		super.destroy();
	}

	offline({ data, method, route }) {
		return {
			id: `update:task:${this.key}`,
			action: "update",
			kind: "task",
			method,
			route,
			target_key: this.key,
			data,
		};
	}

	handleOfflineQueue({ phase, record }) {
		if (record?.kind !== "task" || record.target_key !== this.key) return;
		if (phase === "queued") this.form?.queued();
		if (phase === "conflict") {
			this._offlineConflict = {
				record,
				response: record.conflictResponse,
			};
			return this.stageOfflineConflict();
		}
		if (phase === "replayed") this.form?.success();
	}

	_resetHistoryFillCache() {
		this._historyFillRequest = null;
		this._historyFillSubmission = null;
		this._historyFillGeneration += 1;
	}

	async init() {
		await super.init();
		await this.loadHistoryFill();
	}

	async prepareReset(options = {}) {
		this._clearOriginalCompletion();
		this._resetHistoryFillCache();
		const afterInit = options.afterInit;
		await super.prepareReset({
			...options,
			afterInit: async (widget) => {
				await afterInit?.(widget);
				await widget.loadHistoryFill();
			},
		});
	}

	async reset() {
		await this.prepareReset();
		this.commitReset();
	}

	async latestHistorySubmission() {
		if (this._historyFillSubmission) return this._historyFillSubmission;

		if (!this._historyFillRequest) {
			const pending = request
				.get(this.historyFillRoute)
				.then((response) => response.history_fields || [])
				.catch((error) => {
					if (this._historyFillRequest === pending) {
						this._historyFillRequest = null;
						captureError(error, this.target, { route: this.historyFillRoute });
					}
					return [];
				});
			this._historyFillRequest = pending;
		}

		const pending = this._historyFillRequest;
		const submission = await pending;
		if (this._historyFillRequest === pending)
			this._historyFillSubmission = submission;
		return submission;
	}

	async historyValue(fieldId) {
		const form = this.form;
		const generation = this._historyFillGeneration;
		const response = await request.get(
			this.historyFillRoute,
			{ field: fieldId },
			{ replaceErrorPage: false },
		);
		if (this.form !== form || this._historyFillGeneration !== generation)
			return null;
		if (!response?.ok) {
			form.showError(
				response?.error || "Could not fill this value from history. Try again.",
			);
			return null;
		}
		form.hideError();
		return response.latest_submission?.[fieldId];
	}

	async loadHistoryFill() {
		if (!this.historyFillEnabled || !this.form?.renderer) return;

		const form = this.form;
		const generation = this._historyFillGeneration;
		const fields = await this.latestHistorySubmission();
		if (this.form !== form || this._historyFillGeneration !== generation)
			return;
		form.renderer.addHistoryFillButtons(
			Object.fromEntries(fields.map((id) => [id, () => this.historyValue(id)])),
		);
	}
}
