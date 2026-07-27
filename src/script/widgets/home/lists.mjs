import { BaseList } from "../../elements/base/baseList";

/**
 * @testable false
 * @covered-by src/script/widgets/home/lists.mjs::HomeProjectList
 * @reason selector helper for home list loading affordances
 */
function _listToggle(component, widgetName) {
	return component.elt.querySelector(
		`[lp-show='${component.name}:${widgetName}'][data-toggle]`,
	);
}
/**
 * Shared loading lifecycle for simple home collection lists.
 *
 * @testable false
 * @covered-by src/script/widgets/home/lists.mjs::HomePageList
 * @reason internal adapter exercised through the semantic list subclasses
 */
class LoadedHomeList extends BaseList {
	static unlockToggleWhenPopulated = false;

	constructor(attributes) {
		super(attributes);
		this._listToggle = _listToggle(this.component, this.name);
	}

	postreconcile() {
		super.postreconcile();
		if (
			this.constructor.unlockToggleWhenPopulated &&
			this.itemCount > 0 &&
			this._listToggle
		) {
			this._listToggle.classList.remove("opacity-50", "pointer-events-none");
		}
		this.target.setAttribute("loaded", "");
	}
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002b_home_projects.py::test_create_project_manual_mode
 * @tests tests_e2e/002_home/test_002b_home_projects.py::test_create_project_ai_mode
 * @features projects
 * @dimensions create-manual ai-create
 */
export class HomeProjectList extends LoadedHomeList {}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002c_home_categories.py::test_create_category_manual_mode
 * @tests tests_e2e/002_home/test_002c_home_categories.py::test_navigate_to_category
 * @features categories
 * @dimensions create-manual navigate
 */
export class HomeCategoryList extends LoadedHomeList {}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002k_home_pages.py::test_home_page_list_loads_recent_pages
 * @features home pages
 * @dimensions list load
 */
export class HomePageList extends LoadedHomeList {
	static unlockToggleWhenPopulated = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002a_home.py::test_directory_list
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_directory_links_present
 * @features home
 * @dimensions directory-list
 */
export class DirectoryList extends LoadedHomeList {
	static unlockToggleWhenPopulated = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_file_input
 * @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_drag_drop
 * @features ingress
 * @dimensions upload-counts delete
 */
export class IngressList extends LoadedHomeList {
	static unlockToggleWhenPopulated = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_list_item_refreshes_stage_labels
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_list_item_delete_removes_report_only_file
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_lazy_report_list_reconciles_active_job_status
 * @features ai-report
 * @dimensions list delete-modal deferred-refresh pending-poll stage-labels lazy-load status-reconciliation
 */
export class ToolReportList extends BaseList {
	constructor(attributes) {
		super(attributes);
		this._listToggle = _listToggle(this.component, this.name);
		this._pendingRefresh = null;
	}

	get hasPendingReports() {
		return Boolean(this.target.querySelector("[data-pending='true']"));
	}

	_schedulePendingRefresh() {
		if (this._pendingRefresh || !this.hasPendingReports) return;

		this._pendingRefresh = setTimeout(async () => {
			this._pendingRefresh = null;
			if (!this.hasPendingReports) return;
			if (document.hidden) {
				this._schedulePendingRefresh();
				return;
			}

			const response = await this.view.load(this.component, this.route);
			if (response && response.updated !== false) {
				this.refresh(response);
			} else {
				this._schedulePendingRefresh();
			}
		}, 5000);
	}

	postreconcile() {
		super.postreconcile();
		this.view.DeferredOperations?.scan(this.target);
		if (this.itemCount > 0 && this._listToggle) {
			this._listToggle.classList.remove("opacity-50", "pointer-events-none");
		}
		this.target.setAttribute("loaded", "");
		this._schedulePendingRefresh();
	}

	destroy() {
		if (this._pendingRefresh) clearTimeout(this._pendingRefresh);
		this._pendingRefresh = null;
	}
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_category
 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_project
 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_page
 * @features starred
 * @dimensions category project page
 */
export class StarredList extends BaseList {
	constructor(attributes) {
		super(attributes);
		this._listToggle = _listToggle(this.component, this.name);
	}

	get countElt() {
		return this.component.elt.querySelector("[data-role='starred-count']");
	}

	postreconcile() {
		super.postreconcile();
		this.countElt.textContent = this.itemCount;
		this._listToggle.classList.toggle("opacity-50", this.itemCount === 0);
		this._listToggle.classList.toggle(
			"pointer-events-none",
			this.itemCount === 0,
		);
		this.target.setAttribute("loaded", "");
	}
}
