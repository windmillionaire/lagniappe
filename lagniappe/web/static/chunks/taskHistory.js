/*! Third-party licenses: /third-party-licenses.txt */
import { E as EmbeddedTable } from './baseTable.js?v=b158c05a';
import './foundation.js?v=b158c05a';
import './upstreamUnavailable.js?v=b158c05a';
import './connectivity.js?v=b158c05a';
import './styles.js?v=b158c05a';
import './icons.js?v=b158c05a';
import './primitives.js?v=b158c05a';
import './table.js?v=b158c05a';
import './baseElement.js?v=b158c05a';
import './checkbox.js?v=b158c05a';
import './input.js?v=b158c05a';
import './formatting.js?v=b158c05a';
import './link.js?v=b158c05a';
import './facets.js?v=b158c05a';
import './remote.js?v=b158c05a';
import './queryLifecycle.js?v=b158c05a';
import './combobox.js?v=b158c05a';
import './results.js?v=b158c05a';
import './storage.js?v=b158c05a';
import './submitter.js?v=b158c05a';
import './loader.js?v=b158c05a';

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
