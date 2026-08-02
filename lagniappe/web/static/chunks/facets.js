/*! Third-party licenses: /third-party-licenses.txt */
import { r as request } from './request.js?v=be1b1fb2';
import './connectivity.js?v=be1b1fb2';
import { E as ENDPOINTS } from './endpoints.js?v=be1b1fb2';
import { debounce } from './utilities.js?v=be1b1fb2';
import { C as Combobox } from './combobox.js?v=be1b1fb2';
import { R as Results } from './results.js?v=be1b1fb2';
import { S as Submitter } from './submitter.js?v=be1b1fb2';

/**
 * @testable infrastructure
 */
class FacetsBox extends Submitter(Combobox) {
	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002k_home_pages.py::test_home_page_create_visible_for_category_editor
	 * @tests tests_e2e/009_search/test_009b_facet_quick_create.py::test_user_assign_search_permission_filter_returns_assignable_users
	 * @features combobox
	 * @dimensions permission-filter
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
		this._searchSequence = 0;

		this._input = this._input.bind(this);
	}

	init() {
		this.element.addEventListener("input", debounce(this._input, 200));

		super.init();
	}

	_input(event) {
		this._search(event.target.value.trim());
	}

	elementClick(event) {
		super.elementClick(event);
		this.showPanel();
	}

	selectOption(option) {
		if (option.dataset.command === "create") {
			this._createOption(option);
			return;
		}
		if (!option.dataset.id) return;

		super.selectOption(option);
		this.results.save(option);
	}

	get selectedOptions() {
		return this.options.filter((o) => this.values.has(o.id));
	}

	async _search(query) {
		const searchSequence = ++this._searchSequence;
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

		const response = await request.get(this.endpoint, params);
		if (
			searchSequence !== this._searchSequence ||
			query !== this.element.value.trim()
		) {
			return;
		}
		if (response.ok) {
			const html = response.results || null;
			this.updatePanel(html);
		}
		this.showPanel();
	}

	async _createOption(option) {
		this._searchSequence++;
		const selectedOptions = this.selectedOptions;
		const data = new FormData();
		data.set("name", option.dataset.name || this.element.value.trim());
		Object.entries(this.indexArgs).forEach(([key, value]) => {
			data.set(key, value);
		});

		const response = await request.post(`${this.endpoint}/create`, data);
		if (!response.ok) return;

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
	}
}

export { FacetsBox as F };
