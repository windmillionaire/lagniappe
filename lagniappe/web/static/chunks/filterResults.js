/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bc63f152';
import { E as EmbeddedTable } from './baseTable.js?v=bc63f152';
import './foundation.js?v=bc63f152';
import './upstreamUnavailable.js?v=bc63f152';
import './connectivity.js?v=bc63f152';
import './icons.js?v=bc63f152';
import './primitives.js?v=bc63f152';
import './table.js?v=bc63f152';
import './baseElement.js?v=bc63f152';
import './checkbox.js?v=bc63f152';
import './input.js?v=bc63f152';
import './formatting.js?v=bc63f152';
import './link.js?v=bc63f152';
import './facets.js?v=bc63f152';
import './remote.js?v=bc63f152';
import './queryLifecycle.js?v=bc63f152';
import './combobox.js?v=bc63f152';
import './results.js?v=bc63f152';
import './storage.js?v=bc63f152';
import './submitter.js?v=bc63f152';
import './loader.js?v=bc63f152';

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
