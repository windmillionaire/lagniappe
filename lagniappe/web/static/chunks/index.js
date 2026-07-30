/*! Third-party licenses: /third-party-licenses.txt */
import { w as withTransition, S as STYLES } from './shared.js?v=bda9a134';
import { D as Dropdown } from './dropdown.js?v=bda9a134';
import { C as Core } from './core.js?v=bda9a134';
import './combobox.js?v=bda9a134';
import './primitives.js?v=bda9a134';
import './entityMenu.js?v=bda9a134';
import './results2.js?v=bda9a134';
import './formatting.js?v=bda9a134';

/**
 * @testable true
 * @tests tests_e2e/007_categories/test_007d_category_mobile_ui.py::test_category_mobile_controls_open_with_page_columns
 * @tests tests_e2e/006_tasks/test_006e_task_index_mobile_ui.py::test_task_index_mobile_controls_open_with_task_columns
 * @tests tests_e2e/003_forms/test_003e_form_index_mobile_ui.py::test_form_index_mobile_tools_and_column_controls_are_exclusive
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_user_index_initializes_mobile_tools_and_sorting_on_mobile_load
 * @features table-controls
 * @dimensions mobile-controls columns mobile-tools mutual-exclusion mobile-startup sorting
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

		if (this.mobile && tools) {
			this._createDropdown();
			const toolsNav = document.querySelector("nav[data-nav='tools']");
			if (toolsNav) toolsNav.style.display = "none";
		}

		await withTransition(async () => {
			if (!table.elt.hasAttribute("lp-prefetch")) {
				await table.loadWidget("IndexTable");
			}
			await table.loadWidget("TableVisibility");
			await table.render(true);
		});

		this.elt.addEventListener("mobile-resize", async () => {
			withTransition(async () => {
				const toolsNav = document.querySelector("nav[data-nav='tools']");
				if (!this.mobile) {
					if (mobileControls) mobileControls.dataset.visible = "false";
					this._setMobileControlsDropdownOpen(false);
					toolsNav?.removeAttribute("style");
				} else {
					if (tools) this.getComponent(tools).deactivate(false);
					this._createDropdown();
					if (toolsNav) toolsNav.style.display = "none";
				}
				table.widgets.TableSorting?.reset();
			});
		});

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
		await withTransition(async () => {
			await component.render(activated);
		});
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
	_createDropdown() {
		if (this.dropdown) return;

		const trigger = this.elt.querySelector("[data-role='tools-dropdown']");
		if (!trigger) return;

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
						const mobileControls = this.elt.querySelector("#mobile-controls");
						const table = this.getComponent(this.elt.querySelector("#table"));
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
	}

	destroy() {
		super.destroy();
		this._setMobileControlsDropdownOpen(false);
		this.dropdown?.destroy();
		this.dropdown = null;
		this.toolsObserver?.disconnect();
		this.toolsObserver = null;
	}
}

export { EntityIndex as default };
