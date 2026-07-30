/*! Third-party licenses: /third-party-licenses.txt */
import { E as ENDPOINTS, S as STYLES, k as debounce, r as request } from './shared.js?v=b30f3f24';
import { C as Combobox } from './combobox.js?v=b30f3f24';
import { R as Results } from './results2.js?v=b30f3f24';
import { D as Dropdown } from './dropdown.js?v=b30f3f24';

/**
 * @testable true
 * @tests tests_e2e/009_search/test_009a_search_page.py::test_search_from_navbar
 * @features search
 * @dimensions navbar-submit page-navigation
 */
class SearchBox extends Combobox {
	constructor(element) {
		super(element);
		this.index = "search";
		this.results = new Results(this.index);
		this.input = this._input.bind(this);
		this.placement = "bottom-end";
		this.endpoints = ENDPOINTS.search;
	}

	init() {
		this.styles.panel = `${STYLES.dropdown.panel} right-0 w-64 sm:w-96 mt-2`;
		this.element.addEventListener("input", debounce(this.input, 200));

		super.init();
	}

	_input(event) {
		const query = event.target.value.trim();
		if (query.length > 1) {
			this._search(query);
		} else if (query.length === 0) {
			this.updatePanel(this.results.create());
		}
	}

	elementClick(event) {
		super.elementClick(event);
		this.showPanel();
	}

	async _search(query) {
		const params = new URLSearchParams();
		params.set("q", query);
		const response = await request.get(this.endpoints.bar, params);
		if (response?.ok) {
			const html = response?.results || null;
			this.updatePanel(html);
		}
		this.showPanel();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/009_search/test_009a_search_page.py::test_click_result_navigates
	 * @tests tests_e2e/009_search/test_009a_search_page.py::test_result_links_correct
	 * @features search
	 * @dimensions result-navigation result-links
	 * @template nav.html::search_results
	 */
	selectOption(option) {
		this.results.save(option);
		this.hidePanel();
		window.location.href = option.dataset.url;
	}

	elementKeydown(event) {
		super.elementKeydown(event);
		if (event.defaultPrevented) return;

		if (event.key === "Enter") {
			event.stopPropagation();
			const params = new URLSearchParams();
			params.set("q", this.element.value);
			if (this.element.value) {
				window.location.href = `${this.endpoints.page}?${params.toString()}`;
			}
		}
	}
}

/**
 * Adapts template-defined entity actions to the shared Dropdown primitive.
 *
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_completed_task_can_move_to_another_page
 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_delete_page_from_title_menu
 * @tests tests_e2e/003_forms/test_003a_forms.py::test_copy_form_from_builder_title_menu
 * @tests tests_js/test_016_combobox_frontend.py::test_entity_title_menu_anchors_to_the_title_bottom_left
 * @pairs entity-menu:title-menu entity-menu:title-positioning entity-menu:state-linking entity-menu:builder-copy
 */
class EntityMenu {
	constructor(view) {
		this.view = view;
		this.dropdowns = new Set();
	}

	_items(container) {
		const entityKey = container.closest("[data-key]")?.dataset.key;
		return Array.from(
			container.querySelectorAll(
				":scope > [data-role='menu-items'] > [data-menu-item]",
			),
		)
			.filter((item) => !item.disabled && item.dataset.visible !== "false")
			.map((source) => {
				const option = source.cloneNode(true);
				option.hidden = false;
				option.removeAttribute("id");
				option.setAttribute("role", "menuitem");
				option.querySelectorAll("[id]").forEach((element) => {
					element.removeAttribute("id");
				});
				if (entityKey) option.dataset.entityKey = entityKey;

				return {
					html: option.outerHTML,
					onClick: () => source.isConnected && source.click(),
				};
			});
	}

	toggle(container) {
		if (!container) return;
		this._prune();

		const trigger = container.querySelector(
			":scope > [data-role='menu-trigger']",
		);
		const items = this._items(container);
		if (!trigger || items.length === 0) return;
		const title = container
			.closest("[data-menu-anchor]")
			?.querySelector("[data-role='title']");

		const dropdown = new Dropdown(trigger).init({
			items,
			loadOptions: async () => this._items(container),
			placement: "bottom-start",
			positionReference: title || trigger,
			matchReferenceWidth: true,
			styles: { panel: STYLES.dropdown.menu },
			popupRole: "menu",
			optionRole: "menuitem",
			triggerRole: null,
		});
		this.dropdowns.add(dropdown);

		// The first click reached the delegated Core handler before Dropdown was
		// attached to the trigger, so open it explicitly. Later clicks are owned
		// directly by Dropdown.
		dropdown.showPanel();
	}

	_prune() {
		for (const dropdown of this.dropdowns) {
			if (dropdown.element.isConnected) continue;
			dropdown.destroy();
			this.dropdowns.delete(dropdown);
		}
	}

	destroy() {
		this.dropdowns.forEach((dropdown) => {
			dropdown.destroy();
		});
		this.dropdowns.clear();
		this.view = null;
	}
}

export { EntityMenu as E, SearchBox as S };
