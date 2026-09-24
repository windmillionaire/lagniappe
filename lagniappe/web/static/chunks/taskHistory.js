/*! Third-party licenses: /third-party-licenses.txt */
import { E as EmbeddedTable } from './baseTable.js?v=b518b165';
import './foundation.js?v=b518b165';
import './upstreamUnavailable.js?v=b518b165';
import './connectivity.js?v=b518b165';
import './styles.js?v=b518b165';
import './icons.js?v=b518b165';
import './primitives.js?v=b518b165';
import './table.js?v=b518b165';
import './baseElement.js?v=b518b165';
import './checkbox.js?v=b518b165';
import './input.js?v=b518b165';
import './formatting.js?v=b518b165';
import './link.js?v=b518b165';
import './facets.js?v=b518b165';
import './remote.js?v=b518b165';
import './queryLifecycle.js?v=b518b165';
import './combobox.js?v=b518b165';
import './results.js?v=b518b165';
import './storage.js?v=b518b165';
import './submitter.js?v=b518b165';
import './loader.js?v=b518b165';

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
