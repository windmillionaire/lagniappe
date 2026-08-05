/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bb7cd952';
import { E as ENDPOINTS, d as debounce, r as request } from './foundation.js?v=bb7cd952';
import './connectivity.js?v=bb7cd952';
import { C as Combobox } from './combobox.js?v=bb7cd952';
import { R as Results } from './results.js?v=bb7cd952';
import './notificationState.js?v=bb7cd952';
import './primitives.js?v=bb7cd952';
import './icons.js?v=bb7cd952';
import './formatting.js?v=bb7cd952';

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

export { SearchBox };
