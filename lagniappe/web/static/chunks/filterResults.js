/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=b158c05a';
import { E as EmbeddedTable } from './baseTable.js?v=b158c05a';
import './foundation.js?v=b158c05a';
import './upstreamUnavailable.js?v=b158c05a';
import './connectivity.js?v=b158c05a';
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
 * @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_results_expands_table_submission_cell
 * @matrix embedded-table : horizontal-scroll run-results table-cell-expand
 */
class FilterResults extends EmbeddedTable {
	constructor(attributes) {
		super(attributes);
		this.badges = null;
		this.table = null;
		this.tableContainer = null;
		this.container = null;
		this.filtering = this.target.dataset.kind;
	}

	async updated(response) {
		this.table =
			response.html.querySelector("#embedded-table") ||
			response.html.querySelector("table");
		if (this.filtering === "page") {
			this.badges = this.component.widgets.Filters.filters.cloneNode(true);
		}
	}

	get tbody() {
		return this.table.querySelector("tbody");
	}

	get rows() {
		return this.tbody.querySelectorAll("tr:not([data-role='empty'])");
	}

	get empty() {
		return this.tbody.querySelector("tr[data-role='empty']");
	}

	/**
	 * @testable true
	 * @tests tests_e2e/004_projects/test_004f_project_filters.py::test_project_filter_results_respect_task_permissions
	 * @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_by_task_name
	 * @matrix filters : run-results results-layout
	 */
	postreconcile() {
		if (!this.table || this.target.contains(this.table)) return;

		this.container = document.createElement("div");
		this.container.dataset.role = "results-table";
		this.container.className = STYLES.table.container;
		this.tableContainer = document.createElement("div");
		this.tableContainer.className = "table-container px-4";
		this.tableContainer.dataset.role = "table";
		this.tableContainer.dataset.embedded = "true";
		this.tableContainer.appendChild(this.table);
		this.container.appendChild(this.tableContainer);
		this.table.dataset.visible = "true";
		this.initVisibility(this.table);
		if (this.filtering === "page") {
			this.target.replaceChildren(this.badges, this.container);
		} else {
			this.target.replaceChildren(this.container);
		}
	}

	reset() {
		if (this.badges) {
			this.badges.remove();
			this.badges = null;
		}
		if (this.container) {
			this.container.remove();
			this.container = null;
		}
		if (this.tableContainer) {
			this.tableContainer = null;
		}
		if (this.table) {
			this.table = null;
		}
	}
}

export { FilterResults };
