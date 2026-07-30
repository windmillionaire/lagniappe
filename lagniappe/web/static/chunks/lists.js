/*! Third-party licenses: /third-party-licenses.txt */
import { BaseList } from './baseList.js?v=bda9a134';

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
	static disableToggleWhenUnavailable = false;

	constructor(attributes) {
		super(attributes);
		this._listToggle = _listToggle(this.component, this.name);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002h_home_permissions.py::test_empty_home_model_lists_settle_to_disabled_zero_state
	 * @pairs home:lazy-empty-list home:unavailable-toggle
	 */
	_syncUnavailableToggle() {
		if (!this.constructor.disableToggleWhenUnavailable || !this._listToggle) {
			return;
		}

		const unavailable = this.itemCount === 0 && !this.target.dataset.ifEmpty;
		this._listToggle.disabled = unavailable;
		this._listToggle.classList.toggle("opacity-50", unavailable);

		const indicator = this._listToggle.querySelector(
			`[data-indicator='${this.name}']`,
		);
		if (!indicator) return;

		const wasUnavailable = indicator.dataset.empty === "true";
		indicator.dataset.empty = unavailable ? "true" : "false";
		indicator.classList.toggle("hidden", !unavailable);
		indicator.classList.toggle("font-bold", unavailable);
		if (unavailable) {
			indicator.textContent = "0";
		} else if (wasUnavailable) {
			indicator.textContent = "";
		}
	}

	postreconcile() {
		super.postreconcile();
		this._syncUnavailableToggle();
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
class HomeProjectList extends LoadedHomeList {
	static disableToggleWhenUnavailable = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002c_home_categories.py::test_create_category_manual_mode
 * @tests tests_e2e/002_home/test_002c_home_categories.py::test_navigate_to_category
 * @features categories
 * @dimensions create-manual navigate
 */
class HomeCategoryList extends LoadedHomeList {
	static disableToggleWhenUnavailable = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002k_home_pages.py::test_home_page_list_loads_recent_pages
 * @features home pages
 * @dimensions list load
 */
class HomePageList extends LoadedHomeList {
	static unlockToggleWhenPopulated = true;
	static disableToggleWhenUnavailable = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002a_home.py::test_directory_list
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_directory_links_present
 * @features home
 * @dimensions directory-list
 */
class DirectoryList extends LoadedHomeList {
	static unlockToggleWhenPopulated = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_file_input
 * @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_drag_drop
 * @features ingress
 * @dimensions upload-counts delete
 */
class IngressList extends LoadedHomeList {
	static unlockToggleWhenPopulated = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_list_item_refreshes_stage_labels
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_list_item_delete_removes_report_only_file
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_lazy_report_list_reconciles_active_job_status
 * @features ai-report
 * @dimensions list delete-modal deferred-refresh operation-poll stage-labels lazy-load status-reconciliation
 */
class ToolReportList extends BaseList {
	constructor(attributes) {
		super(attributes);
		this._listToggle = _listToggle(this.component, this.name);
	}

	postreconcile() {
		super.postreconcile();
		this.view.DeferredOperations?.scan(this.target);
		if (this.itemCount > 0 && this._listToggle) {
			this._listToggle.classList.remove("opacity-50", "pointer-events-none");
		}
		this.target.setAttribute("loaded", "");
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
class StarredList extends BaseList {
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

export { DirectoryList, HomeCategoryList, HomePageList, HomeProjectList, IngressList, StarredList, ToolReportList };
