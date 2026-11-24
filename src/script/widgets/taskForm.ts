import { sections } from "../elements/sections.ts";
import { FormController } from "../forms/controller.ts";
import type { ENDPOINTS } from "../shared/endpoints.ts";
import { captureError, request } from "../shared/index.ts";
import type { RequestResult } from "../types/api";
import type { FormRevisionFields, FormSubmission } from "../types/forms";
import {
	type FormResetOptions,
	FormWidget,
	type FormWidgetSettings,
} from "./base/formWidget.ts";

interface OriginalSubmissionFields
	extends Pick<FormRevisionFields, "schema" | "submission"> {
	html_fields: Record<string, string>;
	schema_error: string;
	content_error: string;
	raw_submission: unknown;
}

interface HistorySubmissionFields {
	history_fields: string[];
	latest_submission: FormSubmission;
}

type OfflineContext = Parameters<NonNullable<FormWidget["offline"]>>[0];
type QueueContext = Parameters<
	NonNullable<FormWidget["handleOfflineQueue"]>
>[0];

async function renderOriginalSubmission(
	response: RequestResult<OriginalSubmissionFields>,
	key?: string | null,
) {
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
	declare endpoints?: ReturnType<typeof ENDPOINTS.TaskForm>;
	declare _historyFillRequest: Promise<string[]> | null;
	declare _historyFillSubmission: string[] | null;
	declare _historyFillGeneration: number;
	declare _originalCompletionForm: FormController | null;
	declare _archivedSubmissionForm: FormController | null;
	declare _originalCompletionGeneration: number;

	constructor(attributes: FormWidgetSettings) {
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
				this.component?.elt?.querySelector("[data-widget='TaskHistory']"),
		);
	}

	get prepend() {
		const archived = this.target.querySelector(
			"[data-role='archived-submission-controls']",
		);
		archived
			?.querySelector("[data-role='load-archived-submission']")
			?.addEventListener("click", this._showArchivedSubmission);
		const original = this.target.querySelector<HTMLElement>(
			"[data-role='original-completion-controls']",
		);
		original
			?.querySelector("[data-role='view-original-completion']")
			?.addEventListener("click", this._showOriginalCompletion);
		original
			?.querySelector<HTMLElement>(
				"[data-role='completion-submission-options']",
			)
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
			notice.textContent = error ?? null;
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

	_setCompletionView(showOriginal: boolean) {
		const controls = this.target.querySelector<HTMLElement>(
			"[data-role='original-completion-controls']",
		);
		if (!controls) return;
		let current = this.target.querySelector<HTMLElement>(
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
		const original = controls.querySelector<HTMLElement>(
			"[data-role='original-completion-detail']",
		);
		if (original) original.hidden = !showOriginal;
	}

	_selectCompletionSubmission(event: Event) {
		event.stopPropagation();
		if (event.target instanceof HTMLInputElement)
			this._setCompletionView(event.target.value === "original");
	}

	async _showOriginalCompletion(event: Event) {
		event.preventDefault();
		event.stopPropagation();
		const button = event.currentTarget as HTMLButtonElement | null;
		if (!button) return;
		const controls = button.closest(
			"[data-role='original-completion-controls']",
		);
		const target = controls?.querySelector<HTMLElement>(
			"[data-role='original-completion-detail']",
		);
		if (!controls || !target) return;
		if (button.disabled || !button.dataset.route) return;
		const generation = this._originalCompletionGeneration;
		button.disabled = true;
		try {
			if (!this._originalCompletionForm) {
				const response = await request.get<OriginalSubmissionFields>(
					button.dataset.route,
				);
				if (!response) throw new Error("Submission response is unavailable.");
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
			const options = controls.querySelector<HTMLElement>(
				"[data-role='completion-submission-options']",
			);
			if (!options) return;
			for (const radio of options.querySelectorAll("input")) {
				radio.disabled = false;
				radio.checked = radio.value === "original";
			}
			options.hidden = false;
			options.querySelector<HTMLInputElement>("input:checked")?.focus();
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

	async _showArchivedSubmission(event: Event) {
		event.preventDefault();
		event.stopPropagation();
		const button = event.currentTarget as HTMLButtonElement | null;
		if (!button) return;
		if (button.disabled || !button.dataset.route) return;
		const generation = this._originalCompletionGeneration;
		const target = button
			.closest("[data-role='archived-submission-controls']")
			?.querySelector<HTMLElement>("[data-role='archived-submission-detail']");
		if (!target) return;
		button.disabled = true;
		try {
			if (!this._archivedSubmissionForm) {
				const response = await request.get<OriginalSubmissionFields>(
					button.dataset.route,
				);
				if (!response) throw new Error("Submission response is unavailable.");
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
			const original = this.target.querySelector<HTMLElement>(
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

	offline({ data, method, route }: OfflineContext) {
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

	handleOfflineQueue({ phase, record }: QueueContext) {
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

	async prepareReset(options: FormResetOptions<this> = {}) {
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
			const route = this.historyFillRoute;
			if (!route) return [];
			const pending = request
				.get<HistorySubmissionFields>(route)
				.then((response) => response?.history_fields || [])
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

	async historyValue(fieldId: string) {
		const form = this.form;
		const generation = this._historyFillGeneration;
		const route = this.historyFillRoute;
		if (!form || !route) return null;
		const response = await request.get<HistorySubmissionFields>(
			route,
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
		const form = this.form;
		const renderer = form?.renderer;
		if (!this.historyFillEnabled || !renderer) return;
		const generation = this._historyFillGeneration;
		const fields = await this.latestHistorySubmission();
		if (this.form !== form || this._historyFillGeneration !== generation)
			return;
		renderer.addHistoryFillButtons(
			Object.fromEntries(fields.map((id) => [id, () => this.historyValue(id)])),
		);
	}
}
