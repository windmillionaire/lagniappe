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
 * @testable false
 * @covered-by src/script/widgets/home/lists.mjs::LoadedHomeList._syncUnavailableToggle
 * @covered-by src/script/widgets/home/lists.mjs::ToolReportList
 * @reason shared zero-count presentation is exercised through home list E2E flows
 */
function _syncEmptyCount(toggle, widgetName, empty) {
	const indicator = toggle?.querySelector(`[data-indicator='${widgetName}']`);
	if (!indicator) return;

	const wasEmpty = indicator.dataset.empty === "true";
	indicator.dataset.empty = empty ? "true" : "false";
	indicator.classList.toggle("hidden", !empty);
	indicator.classList.toggle("font-bold", empty);
	if (empty) {
		indicator.textContent = "0";
	} else if (wasEmpty) {
		indicator.textContent = "";
	}
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
	 * @matrix home : lazy-empty-list unavailable-toggle
	 */
	_syncUnavailableToggle() {
		if (!this.constructor.disableToggleWhenUnavailable || !this._listToggle) {
			return;
		}

		const unavailable = this.itemCount === 0 && !this.target.dataset.ifEmpty;
		this._listToggle.disabled = unavailable;
		this._listToggle.classList.toggle("opacity-50", unavailable);
		_syncEmptyCount(this._listToggle, this.name, unavailable);
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
 * @matrix projects : ai-create create-manual
 */
export class HomeProjectList extends LoadedHomeList {
	static disableToggleWhenUnavailable = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002c_home_categories.py::test_create_category_manual_mode
 * @tests tests_e2e/002_home/test_002c_home_categories.py::test_navigate_to_category
 * @matrix categories : create-manual navigate
 */
export class HomeCategoryList extends LoadedHomeList {
	static disableToggleWhenUnavailable = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002k_home_pages.py::test_home_page_list_loads_recent_pages
 * @matrix home pages : list load
 */
export class HomePageList extends LoadedHomeList {
	static unlockToggleWhenPopulated = true;
	static disableToggleWhenUnavailable = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002a_home.py::test_directory_list
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_directory_links_present
 * @pair home:directory-list
 */
export class DirectoryList extends LoadedHomeList {
	static unlockToggleWhenPopulated = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_file_input
 * @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_drag_drop
 * @matrix ingress : delete upload-counts
 */
export class IngressList extends LoadedHomeList {
	static unlockToggleWhenPopulated = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_list_item_refreshes_stage_labels
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_list_item_delete_removes_report_only_file
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_lazy_report_list_reconciles_active_job_status
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_ai_access_tiers_gate_tool_routes
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_saved_report_controls_do_not_require_provider_access
 * @matrix ai-report : deferred-refresh delete-modal empty-count lazy-load list operation-poll stage-labels status-reconciliation toggle
 */
export class ToolReportList extends BaseList {
	constructor(attributes) {
		super(attributes);
		this._listToggle = _listToggle(this.component, this.name);
	}

	postreconcile() {
		super.postreconcile();
		void this.view
			.ensureDeferredOperations?.()
			.then((manager) => manager?.scan(this.target));
		_syncEmptyCount(this._listToggle, this.name, this.itemCount === 0);
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
 * @matrix starred : category page project
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
