/*! Third-party licenses: /third-party-licenses.txt */
import { E as ENDPOINTS, r as request } from './foundation.js?v=b506293e';
import './connectivity.js?v=b506293e';
import { R as RemoteQueryCombobox } from './remote.js?v=b506293e';
import { R as Results } from './results.js?v=b506293e';
import { S as Submitter } from './submitter.js?v=b506293e';

/**
 * @testable infrastructure
 */
class FacetsBox extends Submitter(RemoteQueryCombobox) {
	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002k_home_pages.py::test_home_page_create_visible_for_category_editor
	 * @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_user_assign_search_permission_filter_returns_assignable_users
	 * @pair combobox:permission-filter
	 */
	constructor(element, args = {}) {
		super(element);
		this.endpoint = ENDPOINTS.facet(this.index);
		this.indexArgs = args;

		const formType = this.formType;
		if (formType) {
			this.indexArgs["form-type"] = formType;
		}
		if (this.includeUsers === "false") {
			this.indexArgs["include-users"] = "false";
		}
		if (this.permission) {
			this.indexArgs.permission = this.permission;
		}

		let index = this.index;
		if (formType) {
			index = `${this.index}-${formType}`;
		} else if (this.indexArgs.models === false) {
			index = `${this.index}-no-models`;
		}
		this.results = new Results(index);
	}

	_input(event) {
		const query = event.target.value.trim();
		if (query) return this._search(query);

		this.settleQueryInput();
		this.updatePanel(this.results.create());
		return this.showPanel();
	}

	elementClick(event) {
		super.elementClick(event);
		this.showPanel();
	}

	selectOption(option) {
		if (option.dataset.command === "create") {
			return this._createOption(option);
		}
		if (!option.dataset.id) return;

		this.invalidateQuery();
		super.selectOption(option);
		this.results.save(option);
	}

	get selectedOptions() {
		return this.options.filter((o) => this.values.has(o.id));
	}

	_search(query) {
		const selectedHashes = this.options
			.filter((o) => this.values.has(o.id))
			.map((o) => o.hash);

		const params = new URLSearchParams();
		params.set("q", query);
		if (this.creatable === "true") {
			params.set("creatable", "true");
		}
		Object.entries(this.indexArgs).forEach(([key, value]) => {
			params.set(key, value);
		});
		selectedHashes.forEach((hash) => {
			params.append("preload", hash);
		});

		return this.runQuery(
			query,
			(token) => request.get(this.endpoint, params, { signal: token.signal }),
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

	_createOption(option) {
		const selectedOptions = this.selectedOptions;
		const query = this.element.value.trim();
		this.hidePanel();
		const data = new FormData();
		data.set("name", option.dataset.name || query);
		Object.entries(this.indexArgs).forEach(([key, value]) => {
			data.set(key, value);
		});

		const key = `create:${query}`;
		return this.runQuery(
			key,
			() => request.post(`${this.endpoint}/create`, data),
			(response) => {
				if (!response?.ok) return;

				let html = response.results || null;
				if (this.multiple && response.option) {
					html = this.results.create(
						[...selectedOptions, response.option].filter(
							(item, index, items) =>
								item?.id && items.findIndex((i) => i?.id === item.id) === index,
						),
					);
				}

				this.updatePanel(html);
				const created = [
					...(this.panel?.querySelectorAll("[role='option'][data-id]") || []),
				].find((item) => item.dataset.id === response.option?.id);
				if (!created) return;

				super.selectOption(created);
				this.results.save(created);
			},
			{
				cancelTransport: false,
				getCurrentKey: () => `create:${this.element.value.trim()}`,
			},
		);
	}
}

export { FacetsBox as F };
