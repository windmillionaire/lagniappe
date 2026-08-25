/*! Third-party licenses: /third-party-licenses.txt */
import { w as withTransition } from './foundation.js?v=b66dffd0';
import { C as Core } from './core-foundation.js?v=b66dffd0';

/**
 * Lightweight persisted column-state owner. It applies visibility CSS before
 * an index table is shown; the checkbox controller remains in the lazy
 * TableVisibility widget.
 *
 * @testable true
 * @tests tests_js/test_038_startup_specializations.py::test_column_visibility_state_applies_before_lazy_panel
 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_column_visibility_persists_after_reload
 * @pairs table-controls:eager-column-state table-controls:lazy-checkbox-panel
 * @pairs table-controls:column-visibility table-controls:persistence
 */
class TableVisibilityState {
	constructor({ component, view, selected = [], columns = [] }) {
		this.component = component;
		this.view = view;
		this.selected = selected;
		this.columns = columns;
		this.columnIndexes = new Map();
		this.hiddenColumns = [];
		this.stylesheet = null;
		this.initialized = false;
		this._toggle = this._toggle.bind(this);
	}

	init() {
		if (this.initialized) return this;
		this.initialized = true;
		this.component.elt.querySelectorAll("th[data-column]").forEach((th, i) => {
			this.columnIndexes.set(th.dataset.column, i + 1);
		});

		const saved = localStorage.getItem(`columns-${this.view.hash}`);
		try {
			this.hiddenColumns = saved
				? JSON.parse(saved)
				: this.defaultHiddenColumns();
		} catch {
			this.hiddenColumns = this.defaultHiddenColumns();
		}
		this.apply();
		this.view.elt.addEventListener("toggle-column-visibility", this._toggle);
		return this;
	}

	get visibleColumns() {
		return this.columns
			.map((column) => column.field)
			.filter((field) => {
				const index = this.columnIndexes.get(field);
				return index && !this.hiddenColumns.includes(index);
			});
	}

	defaultHiddenColumns() {
		const hidden = this.selected.length
			? this.columns.filter((column) => !this.selected.includes(column.field))
			: this.columns.filter((column) => column.selected !== true);
		return hidden
			.map((column) => this.columnIndexes.get(column.field))
			.filter(Boolean);
	}

	_toggle(event) {
		this.toggle(event.detail.column, event.detail.active);
	}

	toggle(column, visible) {
		const index = this.columnIndexes.get(column);
		if (!index) return;
		this.hiddenColumns = visible
			? this.hiddenColumns.filter((value) => value !== index)
			: [...new Set([...this.hiddenColumns, index])];
		this.apply();
		void this.component.widgets.TableEditor?.refreshCheckboxes?.();
	}

	apply() {
		localStorage.setItem(
			`columns-${this.view.hash}`,
			JSON.stringify(this.hiddenColumns),
		);
		if (!this.stylesheet) {
			this.stylesheet = document.createElement("style");
			this.stylesheet.id = `column-visibility-${this.view.hash}`;
			document.head.appendChild(this.stylesheet);
		}

		const id = this.component.elt.id;
		const rowSelector = `#${id} tr:not([data-widget], [data-embedded], [data-role="empty"]) > td:not([data-column="delete"])`;
		const thSelector = `#${id} th:not([data-column="selector"], [data-embedded])`;
		this.stylesheet.textContent = this.hiddenColumns
			.map(
				(index) =>
					`${rowSelector}:nth-child(${index}), ${thSelector}:nth-child(${index}) { display: none; }`,
			)
			.join("\n");
	}

	destroy() {
		this.view?.elt?.removeEventListener(
			"toggle-column-visibility",
			this._toggle,
		);
		this.stylesheet?.remove();
		this.stylesheet = null;
		this.initialized = false;
	}
}

/**
 * @testable true
 * @tests tests_e2e/007_categories/test_007d_category_mobile_ui.py::test_category_mobile_controls_open_with_page_columns
 * @tests tests_e2e/006_tasks/test_006e_task_index_mobile_ui.py::test_task_index_mobile_controls_open_with_task_columns
 * @tests tests_e2e/003_forms/test_003e_form_index_mobile_ui.py::test_form_index_mobile_tools_and_column_controls_are_exclusive
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_user_index_initializes_mobile_tools_and_sorting_on_mobile_load
 * @tests tests_e2e/007_categories/test_007a_category_index.py::test_category_index_renders_first_batch_before_cursor_continuation
 * @features table-controls
 * @dimensions mobile-controls columns mobile-tools mutual-exclusion mobile-startup sorting cursor-continuation
 * @pair table-controls:mobile-controls
 * @pair table-controls:columns
 * @pair table-controls:mobile-tools
 * @pair table-controls:mutual-exclusion
 * @pair table-controls:mobile-startup
 * @pair table-controls:sorting
 * @pair table-controls:cursor-continuation
 */
class EntityIndex extends Core {
	constructor(node) {
		super(node);
		this.dropdown = null;
		this.nav = null;
		this.toolsObserver = null;
	}

	async init() {
		await super.init();

		const table = this.getComponent(this.elt.querySelector("#table"));
		const tools = this.elt.querySelector("#tools");
		const mobileControls = this.elt.querySelector("#mobile-controls");
		let indexTable = null;

		if (this.mobile && tools) {
			await this._createDropdown();
			const toolsNav = document.querySelector("nav[data-nav='tools']");
			if (toolsNav) toolsNav.style.display = "none";
		}

		this.TableVisibilityState = new TableVisibilityState({
			component: table,
			view: this,
			selected: table.preload("selected") || [],
			columns: table.preload("columns") || [],
		}).init();

		if (!table.elt.hasAttribute("lp-prefetch")) {
			indexTable = await table.loadWidget("IndexTable");
		}
		await table.prepareRender(true);
		await withTransition(
			() => {
				table.render(true);
			},
			{ label: "index:initial-table" },
		);

		const continuation = indexTable?.target.querySelector("tr[lp-load]");
		if (continuation) {
			const route = continuation.dataset.route;
			continuation.remove();
			indexTable.target.removeAttribute("loaded");
			indexTable.loaded = false;
			indexTable.loading = true;
			void table.load(indexTable, route);
		}

		this._indexMobileResize = async () => {
			const toolsNav = document.querySelector("nav[data-nav='tools']");
			if (this.mobile) await this._createDropdown();
			await withTransition(
				() => {
					if (!this.mobile) {
						if (mobileControls) mobileControls.dataset.visible = "false";
						this._setMobileControlsDropdownOpen(false);
						toolsNav?.removeAttribute("style");
					} else {
						if (tools) this.getComponent(tools).deactivate(false);
						if (toolsNav) toolsNav.style.display = "none";
					}
					table.widgets.TableSorting?.reset();
				},
				{ label: "index:mobile-resize" },
			);
		};
		this.elt.addEventListener("mobile-resize", this._indexMobileResize);

		if (!tools) {
			return;
		}

		const thead = table.elt.querySelector("thead");
		this.toolsObserver = new MutationObserver((mutations) => {
			for (const mutation of mutations) {
				if (mutation.attributeName === "data-visible") {
					const visible = tools?.dataset.visible === "true";
					thead?.classList.toggle("sticky", !visible);
				}
			}
		});
		this.toolsObserver.observe(tools, { attributes: true });
		await this._renderDefaultTool(tools);
	}

	_click(e) {
		const toolsTrigger = e.target.closest("[data-role='tools-dropdown']");
		if (this.mobile && toolsTrigger && !this.dropdown) {
			e.preventDefault();
			e.stopPropagation();
			void this.runColdAction(
				toolsTrigger,
				() => this._createDropdown(),
				(dropdown) => dropdown?.showPanel?.(),
				toolsTrigger,
			);
			return;
		}

		const tableControls = e.target.closest(
			"button[lp-show='table:MobileTableControls']",
		);
		if (this.mobile && tableControls) {
			this.dropdown?.hidePanel();
			this._setMobileControlsDropdownOpen(false);

			const tools = this.elt.querySelector("#tools");
			if (tools?.dataset.visible === "true") {
				this.getComponent(tools)?.deactivate(false);
			}
		}

		super._click(e);
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/index.mjs::EntityIndex._defaultToolTarget
	 * @reason query parsing is owned by the target resolver
	 */
	_defaultToolSlug() {
		return this.querySlug(this.queryParam("tool"));
	}

	/**
	 * @testable true
	 * @tests tests_e2e/007_categories/test_007b_category_filters.py::test_category_url_tool_opens_saved_filters
	 * @features filters
	 * @dimensions saved-filters query-tool
	 */
	_defaultToolTarget(tools) {
		const tool = this._defaultToolSlug();
		if (!tool) return null;

		const buttons = tools.querySelectorAll(
			"nav[data-nav='tools'] button[lp-show]",
		);
		for (const button of buttons) {
			const attribute = button.getAttribute("lp-show");
			const [componentId, widgetName] = attribute.split(":");
			const candidates = [
				componentId,
				widgetName,
				attribute.replace(":", "-"),
				button.textContent,
			];

			if (candidates.some((candidate) => this.querySlug(candidate) === tool)) {
				return { componentId, widgetName };
			}
		}

		const widget = Array.from(tools.querySelectorAll("[data-widget]")).find(
			(elt) => this.querySlug(elt.dataset.widget) === tool,
		);
		if (!widget) return null;

		return {
			componentId: widget.closest("[lp-component]")?.id || tools.id,
			widgetName: widget.dataset.widget,
		};
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/index.mjs::EntityIndex._defaultToolTarget
	 * @reason render helper is driven by the resolved query target
	 */
	async _renderDefaultTool(tools) {
		const target = this._defaultToolTarget(tools);
		if (!target) return;

		const component = this.getComponent(
			document.getElementById(target.componentId),
		);
		if (!component) return;

		const activated = await component.activate(target.widgetName || "default");
		await component.prepareRender(activated);
		await withTransition(
			() => {
				component.render(activated);
			},
			{ label: "index:default-tool" },
		);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003e_form_index_mobile_ui.py::test_form_index_mobile_tools_and_column_controls_are_exclusive
	 * @features table-controls
	 * @dimensions mobile-controls mobile-tools mutual-exclusion
	 */
	_setMobileControlsDropdownOpen(open) {
		const mobileControls = this.elt.querySelector("#mobile-controls");
		if (!mobileControls) return;

		mobileControls.classList.toggle("opacity-50", open);
		mobileControls.classList.toggle("pointer-events-none", open);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/007_categories/test_007d_category_mobile_ui.py::test_category_mobile_tools_dropdown_opens_new_page_form
	 * @tests tests_e2e/003_forms/test_003e_form_index_mobile_ui.py::test_form_index_mobile_tools_and_column_controls_are_exclusive
	 * @pairs pages:create pages:category-index pages:mobile-tools
	 * @pairs table-controls:mobile-controls table-controls:mobile-tools table-controls:mutual-exclusion
	 */
	async _createDropdown() {
		if (this.dropdown) return;
		if (this._dropdownPromise) return this._dropdownPromise;

		const trigger = this.elt.querySelector("[data-role='tools-dropdown']");
		if (!trigger) return;
		this._dropdownPromise = Promise.all([
			import('./dropdown.js?v=b66dffd0'),
			import('./styles.js?v=b66dffd0'),
		])
			.then(([{ Dropdown }, { STYLES }]) => {
				if (this._destroyed || !this.mobile) return null;

				const items = [];

				const createOption = (button) => {
					const option = button.cloneNode(true);
					option.setAttribute("role", "option");
					option.removeAttribute("data-selected");
					option.className = STYLES.index.tools.dropdown.toggle;
					return option.outerHTML;
				};

				document
					.querySelectorAll("nav[data-nav='tools'] button")
					.forEach((button) => {
						if (button.dataset.visible === "false") return;
						items.push({
							html: createOption(button),
							onClick: () => {
								const mobileControls =
									this.elt.querySelector("#mobile-controls");
								const table = this.getComponent(
									this.elt.querySelector("#table"),
								);
								if (table?.active?.name === "MobileTableControls") {
									table.deactivate(false);
								} else if (mobileControls) {
									mobileControls.dataset.visible = "false";
								}
								this._setMobileControlsDropdownOpen(false);
								this.renderComponent(button);
							},
						});
					});

				this.dropdown = new Dropdown(trigger);

				this.dropdown.init({
					items,
					placement: "bottom-end",
					styles: {
						panel: STYLES.index.tools.dropdown.panel,
					},
					onShow: () => this._setMobileControlsDropdownOpen(true),
					onHide: () => this._setMobileControlsDropdownOpen(false),
				});
				return this.dropdown;
			})
			.catch((error) => {
				this.reportStartupError(error, trigger, "index-tools-dropdown");
				return null;
			})
			.finally(() => {
				this._dropdownPromise = null;
			});
		return this._dropdownPromise;
	}

	destroy() {
		this.elt.removeEventListener("mobile-resize", this._indexMobileResize);
		super.destroy();
		this._setMobileControlsDropdownOpen(false);
		this.dropdown?.destroy();
		this.dropdown = null;
		this.toolsObserver?.disconnect();
		this.toolsObserver = null;
		this.TableVisibilityState?.destroy();
		this.TableVisibilityState = null;
	}
}

export { EntityIndex as E, TableVisibilityState as T };
