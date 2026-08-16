/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=ba9311bf';
import { s as sections } from './sections.js?v=ba9311bf';
import { r as request, c as captureError } from './foundation.js?v=ba9311bf';
import './connectivity.js?v=ba9311bf';
import './baseForm.js?v=ba9311bf';
import './icons.js?v=ba9311bf';
import './primitives.js?v=ba9311bf';
import './styles.js?v=ba9311bf';
import './loader.js?v=ba9311bf';
import './baseUpload.js?v=ba9311bf';
import './buttons.js?v=ba9311bf';
import './formatting.js?v=ba9311bf';
import './dropdown.js?v=ba9311bf';
import './combobox.js?v=ba9311bf';

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

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_form_field_fills_from_latest_history
	 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_fill_controls_cover_submission_elements
	 * @features tasks
	 * @dimensions history-fill live-update
	 */
	get hasHistory() {
		return Boolean(
			this.target?.dataset.history ||
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

	/**
	 * @testable false
	 * @covered-by src/script/widgets/taskForm.mjs::TaskForm
	 * @reason detached task-form resets preserve history-fill initialization
	 */
	async prepareReset(options = {}) {
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
