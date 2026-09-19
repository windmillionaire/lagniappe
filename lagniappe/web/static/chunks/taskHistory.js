/*! Third-party licenses: /third-party-licenses.txt */
import { E as EmbeddedTable } from './baseTable.js?v=bdc1ce7d';
import './foundation.js?v=bdc1ce7d';
import './upstreamUnavailable.js?v=bdc1ce7d';
import './connectivity.js?v=bdc1ce7d';
import './styles.js?v=bdc1ce7d';
import './icons.js?v=bdc1ce7d';
import './primitives.js?v=bdc1ce7d';
import './table.js?v=bdc1ce7d';
import './baseElement.js?v=bdc1ce7d';
import './checkbox.js?v=bdc1ce7d';
import './input.js?v=bdc1ce7d';
import './formatting.js?v=bdc1ce7d';
import './link.js?v=bdc1ce7d';
import './facets.js?v=bdc1ce7d';
import './remote.js?v=bdc1ce7d';
import './queryLifecycle.js?v=bdc1ce7d';
import './combobox.js?v=bdc1ce7d';
import './results.js?v=bdc1ce7d';
import './storage.js?v=bdc1ce7d';
import './submitter.js?v=bdc1ce7d';
import './loader.js?v=bdc1ce7d';

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_appears_after_completion_cycle
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_visibility_persists_after_reload
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_expands_table_submission_cell
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_completion_views_follow_generation_and_archive_original_answers
 * @matrix tasks : completion-cycle history reload
 * @matrix task-completion : history readonly generation
 * @pair embedded-table:table-cell-expand
 */
class TaskHistory extends EmbeddedTable {
	constructor(attributes) {
		super(attributes);
		this._updated = null;
	}

	get table() {
		return this.target.querySelector("[data-role='table']");
	}

	async updated(response) {
		this._updated = response.html.querySelector(
			"[data-role='completion-history']",
		);
	}

	postreconcile() {
		if (!this._updated) return;

		this.visible = true;
		this.target.dataset.visible = "true";
		this.table.replaceChildren(this._updated);
		this._updated.dataset.visible = "true";
		for (const table of this._updated.querySelectorAll("table")) {
			table.dataset.visible = "true";
			this.initVisibility(table, `columns-${this.component.name}-history`);
		}
		this._updated = null;
	}
}

export { TaskHistory };
