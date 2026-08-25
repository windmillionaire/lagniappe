/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bdc368f0';
import { E as ENDPOINTS, r as request } from './foundation.js?v=bdc368f0';
import './connectivity.js?v=bdc368f0';
import { R as RemoteQueryCombobox } from './remote.js?v=bdc368f0';
import { R as Results } from './results.js?v=bdc368f0';
import './queryLifecycle.js?v=bdc368f0';
import './combobox.js?v=bdc368f0';
import './primitives.js?v=bdc368f0';
import './icons.js?v=bdc368f0';
import './storage.js?v=bdc368f0';
import './formatting.js?v=bdc368f0';

/**
 * @testable true
 * @tests tests_e2e/009_search/test_009a_search_page.py::test_search_from_navbar
 * @tests tests_js/test_046_async_query_lifecycle.py::test_search_threshold_settles_stale_work_and_restores_recent_results
 * @features search
 * @dimensions navbar-submit page-navigation
 * @pairs search:threshold search:recent-results search:stale-publication
 */
class SearchBox extends RemoteQueryCombobox {
	constructor(element) {
		super(element);
		this.index = "search";
		this.results = new Results(this.index);
		this.placement = "bottom-end";
		this.endpoints = ENDPOINTS.search;
	}

	init() {
		this.styles.panel = `${STYLES.dropdown.panel} right-0 w-64 sm:w-96 mt-2`;
		super.init();
		this.updatePanel(this.results.create());
	}

	_input(event) {
		const query = event.target.value.trim();
		if (query.length > 1) {
			return this._search(query);
		} else if (query.length === 0) {
			this.settleQueryInput();
			this.updatePanel(this.results.create());
			return this.showPanel();
		}
		this.settleQueryInput({ clear: true });
	}

	elementClick(event) {
		super.elementClick(event);
		this.showPanel();
	}

	_search(query) {
		const params = new URLSearchParams();
		params.set("q", query);
		return this.runQuery(
			query,
			(token) =>
				request.get(this.endpoints.bar, params, { signal: token.signal }),
			(response) => {
				if (response?.ok) {
					this.updatePanel(response.results || null);
				} else {
					this.clearQueryResults();
				}
				return this.showPanel();
			},
		);
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
			event.preventDefault();
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
