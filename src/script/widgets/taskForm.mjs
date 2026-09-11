import { FormElement } from "../elements/form";
import { sections } from "../elements/sections";
import { captureError, request } from "../shared";

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_submit_attached_task_form
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_task_update_preserves_open_widget_and_completed_readonly_state
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_completed_task_with_empty_form_is_readonly
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_completed_task_with_partial_submission_omits_empty_fields
 * @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_page_task_viewer_sees_empty_form_structure_without_edit_controls
 * @matrix tasks : attached-form autofill complete empty-fields partial-submission permission-gates readonly submission
 */
export class TaskForm extends FormElement {
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
		this._historyFillError = null;
		this._historyFillGeneration = 0;
		this._defaultFieldSave = Promise.resolve();
		this._originalCompletionForm = null;
		this._originalCompletionGeneration = 0;
		this._showOriginalCompletion = this._showOriginalCompletion.bind(this);
	}

	get autofillElement() {
		if (this.readonly) return null;
		return sections.autofill(this);
	}

	get historyFillRoute() {
		return this.endpoints?.latestHistorySubmission;
	}

	get saveDefaultFieldRoute() {
		return this.endpoints?.saveDefaultField;
	}

	get historyFillEnabled() {
		return Boolean(!this.readonly && this.hasHistory && this.historyFillRoute);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_form_field_fills_from_latest_history
	 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_fill_controls_cover_submission_elements
	 * @matrix tasks : history-fill live-update
	 */
	get hasHistory() {
		return Boolean(
			this.target?.dataset.history ||
				this.component?.elt.querySelector("[data-widget='TaskHistory']"),
		);
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
			raw.textContent = JSON.stringify(JSON.parse(this.target.dataset.rawSubmission), null, 2);
		}
		const original = this.target.querySelector("[data-role='original-completion-controls']");
		original?.querySelector("[data-role='view-original-completion']")
			?.addEventListener("click", this._showOriginalCompletion);
		return [this.autofillElement, notice, raw, original];
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_completion_views_follow_generation_and_archive_original_answers
	 * @matrix task-completion : original-view readonly archive uncomplete
	 */
	async _showOriginalCompletion(event) {
		event.preventDefault();
		event.stopPropagation();
		const button = event.currentTarget;
		const target = button.parentElement.querySelector("[data-role='original-completion-detail']");
		if (button.disabled) return;
		if (this._originalCompletionForm) {
			target.hidden = !target.hidden;
			button.setAttribute("aria-expanded", String(!target.hidden));
			return;
		}
		const generation = this._originalCompletionGeneration;
		button.disabled = true;
		try {
			const response = await request.get(button.dataset.route);
			const { renderCompletionForm } = await import("./tables");
			const { form, host } = await renderCompletionForm(response, this.key);
			if (generation !== this._originalCompletionGeneration || !this.target.contains(button)) {
				form.destroy();
				return;
			}
			if (response.can_uncomplete) {
				const archive = document.createElement("button");
				archive.type = "button";
				archive.dataset.role = "archive-completion";
				archive.className = button.className;
				archive.textContent = "Archive completion and uncomplete";
				archive.addEventListener("click", (click) => {
					click.preventDefault();
					click.stopPropagation();
					const data = new FormData();
					data.append("role", "archive-completion");
					this.component.disable();
					void this.view.update(this.component, data, this.component.elt.dataset.route);
				});
				host.append(archive);
			}
			target.replaceChildren(host);
			target.hidden = false;
			button.setAttribute("aria-expanded", "true");
			this._originalCompletionForm = form;
		} catch (error) {
			if (generation !== this._originalCompletionGeneration) return;
			target.textContent = "Could not load the original completion. Please try again.";
			target.hidden = false;
			captureError(error, this.target, { route: button.dataset.route });
		} finally {
			button.disabled = false;
		}
	}

	/**
	 * @testable false
	 * @covered-by src/script/widgets/taskForm.mjs::TaskForm._showOriginalCompletion
	 * @reason the requested readonly form shares the Task form lifetime
	 */
	_clearOriginalCompletion() {
		this._originalCompletionGeneration += 1;
		this._originalCompletionForm?.destroy();
		this._originalCompletionForm = null;
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
		this._historyFillError = null;
		this._historyFillGeneration += 1;
	}

	async init() {
		await super.init();
		await this.loadHistoryFill();
	}

	/**
	 * @testable false
	 * @covered-by src/script/widgets/taskForm.mjs::TaskForm
	 * @reason detached task-form resets preserve history-fill initialization
	 */
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
				.then((response) => {
					if (this._historyFillRequest === pending)
						this._historyFillError = response.history_error || null;
					return response.latest_submission || {};
				})
				.catch((error) => {
					if (this._historyFillRequest === pending) {
						this._historyFillRequest = null;
						captureError(error, this.target, { route: this.historyFillRoute });
					}
					return {};
				});
			this._historyFillRequest = pending;
		}

		const pending = this._historyFillRequest;
		const submission = await pending;
		if (this._historyFillRequest === pending)
			this._historyFillSubmission = submission;
		return submission;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_form_field_fills_from_latest_history
	 * @matrix tasks : history-fill patch repeating-default
	 */
	async saveDefaultField(fieldId) {
		if (!this.saveDefaultFieldRoute || !fieldId) return;

		this._defaultFieldSave = this._defaultFieldSave.then(() =>
			request.patch(this.saveDefaultFieldRoute, { field_id: fieldId }),
		);
		const response = await this._defaultFieldSave;
		if (!response?.ok) {
			captureError(
				new Error(response?.error || "Failed to save repeating task value"),
				this.target,
				{ fieldId, route: this.saveDefaultFieldRoute },
			);
		}
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_form_field_fills_from_latest_history
	 * @tests tests_js/test_032_task_settings_lifecycle.py::test_task_history_fill_reports_incompatible_values_and_ignores_stale_responses
	 * @matrix tasks : history-fill latest-submission incompatible-value stale-response
	 */
	async loadHistoryFill() {
		if (!this.historyFillEnabled || !this.form?.renderer) return;

		const form = this.form;
		const generation = this._historyFillGeneration;
		const submission = await this.latestHistorySubmission();
		if (this.form !== form || this._historyFillGeneration !== generation) return;
		this.target.querySelector("[data-role='history-fill-error']")?.remove();
		if (this._historyFillError) {
			const notice = document.createElement("p");
			notice.dataset.role = "history-fill-error";
			notice.setAttribute("role", "status");
			notice.textContent = this._historyFillError;
			this.target.append(notice);
			return;
		}
		form.renderer.addHistoryFillButtons(submission, (fieldId) =>
			this.saveDefaultField(fieldId),
		);
	}
}
