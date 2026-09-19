/*! Third-party licenses: /third-party-licenses.txt */
import { E as EmbeddedTable } from './baseTable.js?v=b1aeef6f';
import { STYLES } from './styles.js?v=b1aeef6f';
import './foundation.js?v=b1aeef6f';
import './upstreamUnavailable.js?v=b1aeef6f';
import './connectivity.js?v=b1aeef6f';
import './icons.js?v=b1aeef6f';
import './primitives.js?v=b1aeef6f';
import './table.js?v=b1aeef6f';
import './baseElement.js?v=b1aeef6f';
import './checkbox.js?v=b1aeef6f';
import './input.js?v=b1aeef6f';
import './formatting.js?v=b1aeef6f';
import './link.js?v=b1aeef6f';
import './facets.js?v=b1aeef6f';
import './remote.js?v=b1aeef6f';
import './queryLifecycle.js?v=b1aeef6f';
import './combobox.js?v=b1aeef6f';
import './results.js?v=b1aeef6f';
import './storage.js?v=b1aeef6f';
import './submitter.js?v=b1aeef6f';
import './loader.js?v=b1aeef6f';

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
