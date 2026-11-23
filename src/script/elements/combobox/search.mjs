import { STYLES } from "../../generated/styles.mjs";
import { ENDPOINTS } from "../../shared/endpoints.mjs";
import { request } from "../../shared/request.mjs";
import { RemoteQueryCombobox } from "./remote.mjs";
import { Results } from "./results.mjs";

export class SearchBox extends RemoteQueryCombobox {
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
