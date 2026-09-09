/*! Third-party licenses: /third-party-licenses.txt */
import { BaseList } from './baseList.js?v=be396a6a';
import { l as localStore } from './storage.js?v=be396a6a';
import { w as withTransition } from './foundation.js?v=be396a6a';
import './upstreamUnavailable.js?v=be396a6a';
import './connectivity.js?v=be396a6a';

const REPORT_FILTERS = ["active", "executed", "ask"];

/**
 * @testable true
 * @tests tests_js/test_047_home_report_filters.py::test_report_categories_and_saved_filter_selection
 * @matrix ai-report : filter-categories
 */
function reportCategory(report) {
	if (report.tool === "ask") return "ask";
	return ["create", "organize"].includes(report.tool) &&
		report.status === "complete"
		? "executed"
		: "active";
}

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
class HomeProjectList extends LoadedHomeList {
	static disableToggleWhenUnavailable = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002c_home_categories.py::test_create_category_manual_mode
 * @tests tests_e2e/002_home/test_002c_home_categories.py::test_navigate_to_category
 * @matrix categories : create-manual navigate
 */
class HomeCategoryList extends LoadedHomeList {
	static disableToggleWhenUnavailable = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002k_home_pages.py::test_home_page_list_loads_recent_pages
 * @matrix home pages : list load
 */
class HomePageList extends LoadedHomeList {
	static unlockToggleWhenPopulated = true;
	static disableToggleWhenUnavailable = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002a_home.py::test_directory_list
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_directory_links_present
 * @pair home:directory-list
 */
class DirectoryList extends LoadedHomeList {
	static unlockToggleWhenPopulated = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_file_input
 * @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_drag_drop
 * @matrix ingress : delete upload-counts
 */
class IngressList extends LoadedHomeList {
	static unlockToggleWhenPopulated = true;
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_list_item_refreshes_stage_labels
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_report_list_item_delete_removes_report_only_file
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_lazy_report_list_reconciles_active_job_status
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_ai_access_tiers_gate_tool_routes
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_saved_report_controls_do_not_require_provider_access
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_create_tool_starts_pending_report
 * @tests tests_e2e/002_home/test_002n_home_report_filters.py::test_report_filters_persist_and_follow_live_status
 * @matrix ai-report : deferred-refresh delete-modal empty-count lazy-load list operation-poll stage-labels status-reconciliation toggle
 * @matrix ai-report : filter-create filter-persistence
 */
class ToolReportList extends BaseList {
	constructor(attributes) {
		super(attributes);
		this._listToggle = _listToggle(this.component, this.name);
		this.storageKey = `home-report-filters:${this.component.elt.dataset.reportUser}`;
		const saved = localStore.getJSON(this.storageKey);
		this.filters = new Set(
			Array.isArray(saved) &&
				saved.every((value) => REPORT_FILTERS.includes(value))
				? saved
				: ["active", "ask"],
		);
		this._click = this._click.bind(this);
		this._deleteMessage = "";
	}

	init() {
		this.component.elt.addEventListener("click", this._click);
	}

	get reportItems() {
		return Array.from(
			this.target.querySelectorAll("li[lp-entity][data-kind='report']"),
		);
	}

	get itemCount() {
		return this.reportItems.length;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_create_tool_starts_pending_report
	 * @tests tests_js/test_047_home_report_filters.py::test_report_filters_count_hidden_categories_and_empty_selections
	 * @matrix ai-report : filter-create filter-persistence
	 */
	created(response) {
		super.created(response);
		const items =
			response.html?.querySelectorAll("li[lp-entity][data-kind='report']") ||
			[];
		for (const item of items) this.filters.add(reportCategory(item.dataset));
		if (items.length) localStore.setJSON(this.storageKey, [...this.filters]);
	}

	_click(event) {
		const filter = event.target.closest("[data-role='report-filter']");
		if (filter && this.target.contains(filter)) {
			const value = filter.dataset.filter;
			if (this.filters.has(value)) this.filters.delete(value);
			else this.filters.add(value);
			localStore.setJSON(this.storageKey, [...this.filters]);
			void withTransition(() => this._renderFilters(), {
				label: "reports:filter",
			});
		}
		const clear = event.target.closest("[data-role='delete-executed-reports']");
		if (clear && this.target.contains(clear)) void this._openDelete(clear);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002n_home_report_filters.py::test_report_filters_persist_and_follow_live_status
	 * @tests tests_js/test_047_home_report_filters.py::test_report_filters_count_hidden_categories_and_empty_selections
	 * @matrix ai-report : filter-categories filter-counts filter-empty
	 */
	_renderFilters() {
		const counts = { active: 0, executed: 0, ask: 0 };
		let visible = 0;
		for (const item of this.reportItems) {
			const category = reportCategory(item.dataset);
			counts[category]++;
			item.hidden = !this.filters.has(category);
			if (!item.hidden) visible++;
		}
		for (const button of this.target.querySelectorAll(
			"[data-role='report-filter']",
		)) {
			const selected = this.filters.has(button.dataset.filter).toString();
			button.dataset.active = selected;
			button.setAttribute("aria-pressed", selected);
			button.querySelector("[data-role='report-count']").textContent =
				counts[button.dataset.filter];
		}
		const empty = this.target.querySelector("[data-role='report-empty']");
		if (empty) {
			empty.hidden = visible > 0;
			empty.textContent = !this.filters.size
				? "Select a report type to show."
				: this.filters.size === 1
					? {
							active: "No active proposals.",
							executed: "No executed proposals.",
							ask: "No Ask reports.",
						}[[...this.filters][0]]
					: "No reports match the selected types.";
		}
		const clear = this.target.querySelector(
			"[data-role='delete-executed-reports']",
		);
		if (clear) {
			clear.hidden = !(
				this.filters.size === 1 &&
				this.filters.has("executed") &&
				counts.executed > 0
			);
			clear.disabled = Boolean(this._deleting);
		}
		const result = this.target.querySelector(
			"[data-role='report-delete-result']",
		);
		if (result) {
			result.textContent = this._deleteMessage;
			result.hidden = !this._deleteMessage;
		}
	}

	postreconcile() {
		const created = this._created;
		this._created = [];
		super.postreconcile();
		if (created.length) {
			this.target
				.querySelector("[data-role='report-items']")
				?.prepend(...created);
			this.view.addFlash(...created);
		}
		this.target.dataset.visible = Boolean(
			this.visible || this.component.active === this,
		).toString();
		this._renderFilters();
		void this.view
			.ensureDeferredOperations?.()
			.then((manager) => manager?.scan(this.target));
		_syncEmptyCount(this._listToggle, this.name, this.itemCount === 0);
		if (this.itemCount > 0 && this._listToggle) {
			this._listToggle.classList.remove("opacity-50", "pointer-events-none");
		}
		this.target.setAttribute("loaded", "");
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002n_home_report_filters.py::test_delete_executed_reports_confirms_snapshot_and_preserves_workspace
	 * @matrix ai-report : bulk-delete confirmation delete-snapshot
	 */
	async _openDelete(trigger) {
		if (this._openingDelete || this._deleting || this._deleteModal?.modal)
			return;
		if (this.filters.size !== 1 || !this.filters.has("executed")) return;
		if (!this.view.online) {
			this._deleteMessage = "Connect to the server to delete reports.";
			this._renderFilters();
			return;
		}
		const keys = this.reportItems
			.filter((item) => reportCategory(item.dataset) === "executed")
			.map((item) => item.dataset.key);
		if (!keys.length) return;
		const element = this.target
			.querySelector("[data-role='report-delete-template']")
			?.content.querySelector("#modal")
			?.cloneNode(true);
		if (!element) return;
		this._openingDelete = true;
		try {
			const { Modal } = await import('./modal.js?v=be396a6a');
			if (this._destroyed) return;
			this._deleteModal?.destroy();
			const modal = new Modal(this.view, trigger);
			this._deleteModal = modal;
			const content = element.querySelector("#modal-content");
			content.setAttribute("role", "dialog");
			content.setAttribute("aria-modal", "true");
			content.setAttribute("aria-labelledby", "report-delete-title");
			const noun = keys.length === 1 ? "proposal" : "proposals";
			element.querySelector(
				"[data-role='report-delete-description']",
			).textContent =
				`Delete ${keys.length} executed ${noun}? Their reports, undo history, and report-only uploads will be deleted. Pages, tasks, and other workspace changes will remain.`;
			const confirm = element.querySelector(
				"[data-role='confirm-delete-reports']",
			);
			confirm.querySelector("[data-role='text']").textContent =
				`Delete ${keys.length} ${noun}`;
			confirm.addEventListener("click", () => {
				void this._deleteExecuted(keys, trigger.dataset.route, modal);
			});
			await modal.attach(element);
			confirm.focus();
		} finally {
			this._openingDelete = false;
		}
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002n_home_report_filters.py::test_delete_executed_reports_confirms_snapshot_and_preserves_workspace
	 * @tests tests_js/test_047_home_report_filters.py::test_bulk_delete_recovers_from_partial_and_network_failures
	 * @matrix ai-report : bulk-delete delete-failure delete-snapshot loading-indicator
	 */
	async _deleteExecuted(keys, route, modal) {
		if (this._deleting) return;
		this._deleting = true;
		const confirm = modal.modal.querySelector(
			"[data-role='confirm-delete-reports']",
		);
		const error = modal.modal.querySelector(
			"[data-role='report-delete-error']",
		);
		const spinner = confirm.querySelector("#spinner");
		confirm.disabled = true;
		spinner.dataset.visible = "true";
		error.hidden = true;
		this._renderFilters();
		try {
			const { request } = await import('./foundation.js?v=be396a6a').then(function (n) { return n.o; });
			const response = await request.delete(route, { keys });
			if (!response?.ok)
				throw new Error("Reports could not be deleted. Please try again.");
			const deleted = new Set(response.deleted || []);
			const skipped = response.skipped?.length || 0;
			const failed = response.failed?.length || 0;
			this._deleteMessage = [
				skipped ? `${skipped} no longer eligible or already deleted.` : "",
				failed ? `${failed} could not be deleted. Please try again.` : "",
			]
				.filter(Boolean)
				.join(" ");
			await modal.remove();
			if (this._destroyed) return;
			await withTransition(
				() => {
					for (const item of this.reportItems)
						if (deleted.has(item.dataset.key)) item.remove();
					this.postreconcile();
				},
				{ label: "reports:delete-executed" },
			);
			await this.view._refreshHomeWidget(this.component, this);
		} catch {
			this._deleteMessage = "Reports could not be deleted. Please try again.";
			if (modal.modal) {
				error.textContent = this._deleteMessage;
				error.hidden = false;
				confirm.disabled = false;
			}
		} finally {
			spinner.dataset.visible = "false";
			this._deleting = false;
			if (!this._destroyed) this._renderFilters();
		}
	}

	destroy() {
		this._destroyed = true;
		this.component.elt.removeEventListener("click", this._click);
		this._deleteModal?.destroy();
	}
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_category
 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_project
 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_page
 * @matrix starred : category page project
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
