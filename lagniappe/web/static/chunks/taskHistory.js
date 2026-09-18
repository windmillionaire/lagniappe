/*! Third-party licenses: /third-party-licenses.txt */
import { E as EmbeddedTable } from './baseTable.js?v=bf6747aa';
import './foundation.js?v=bf6747aa';
import './upstreamUnavailable.js?v=bf6747aa';
import './connectivity.js?v=bf6747aa';
import './styles.js?v=bf6747aa';
import './icons.js?v=bf6747aa';
import './primitives.js?v=bf6747aa';
import './table.js?v=bf6747aa';
import './baseElement.js?v=bf6747aa';
import './checkbox.js?v=bf6747aa';
import './input.js?v=bf6747aa';
import './formatting.js?v=bf6747aa';
import './link.js?v=bf6747aa';
import './facets.js?v=bf6747aa';
import './remote.js?v=bf6747aa';
import './queryLifecycle.js?v=bf6747aa';
import './combobox.js?v=bf6747aa';
import './results.js?v=bf6747aa';
import './storage.js?v=bf6747aa';
import './submitter.js?v=bf6747aa';
import './loader.js?v=bf6747aa';

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
