/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=b32ad33a';
import { s as sections } from './sections.js?v=b32ad33a';
import { r as request } from './request.js?v=b32ad33a';
import './connectivity.js?v=b32ad33a';
import { captureError } from './errors.js?v=b32ad33a';
import './utilities.js?v=b32ad33a';
import './baseForm.js?v=b32ad33a';
import './icons.js?v=b32ad33a';
import './styles.js?v=b32ad33a';
import './primitives.js?v=b32ad33a';
import './loader.js?v=b32ad33a';
import './baseUpload.js?v=b32ad33a';
import './buttons.js?v=b32ad33a';
import './formatting.js?v=b32ad33a';
import './dropdown.js?v=b32ad33a';
import './combobox.js?v=b32ad33a';

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_submit_attached_task_form
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_task_update_preserves_open_widget_and_completed_readonly_state
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_completed_task_with_empty_form_is_readonly
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_completed_task_with_partial_submission_omits_empty_fields
 * @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_page_task_viewer_sees_empty_form_structure_without_edit_controls
 * @features tasks
 * @dimensions attached-form submission autofill readonly complete empty-fields partial-submission permission-gates
 */
class TaskForm extends FormElement {
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
		this._defaultFieldSave = Promise.resolve();
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

	get hasHistory() {
		return Boolean(
			this.component?.elt.querySelector("[data-widget='TaskHistory']"),
		);
	}

	get append() {
		return [this.autofillElement];
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
	}

	async init() {
		await super.init();
		await this.loadHistoryFill();
	}

	async reset() {
		this._resetHistoryFillCache();
		await super.reset();
		await this.loadHistoryFill();
	}

	async latestHistorySubmission() {
		if (this._historyFillSubmission) return this._historyFillSubmission;

		if (!this._historyFillRequest) {
			this._historyFillRequest = request
				.get(this.historyFillRoute)
				.then((response) => response.latest_submission || {})
				.catch((error) => {
					this._historyFillRequest = null;
					captureError(error, this.target, { route: this.historyFillRoute });
					return {};
				});
		}

		this._historyFillSubmission = await this._historyFillRequest;
		return this._historyFillSubmission;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_form_field_fills_from_latest_history
	 * @features tasks
	 * @dimensions history-fill repeating-default patch
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
	 * @features tasks
	 * @dimensions history-fill latest-submission
	 */
	async loadHistoryFill() {
		if (!this.historyFillEnabled || !this.form?.renderer) return;

		const submission = await this.latestHistorySubmission();
		this.form.renderer.addHistoryFillButtons(submission, (fieldId) =>
			this.saveDefaultField(fieldId),
		);
	}
}

export { TaskForm };
