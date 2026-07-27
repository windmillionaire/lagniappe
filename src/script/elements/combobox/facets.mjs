import { debounce, ENDPOINTS, request } from "../../shared";
import { Combobox } from "./combobox";
import { Results } from "./results";
import { Submitter } from "./submitter";

/**
 * @testable infrastructure
 */
export class FacetsBox extends Submitter(Combobox) {
	constructor(element, args = {}) {
		super(element);
		this.endpoint = ENDPOINTS.facet(this.index);
		this.indexArgs = args;

		const formType = element.dataset.formType;
		if (formType) {
			this.indexArgs["form-type"] = formType;
		}
		if (element.dataset.includeUsers === "false") {
			this.indexArgs["include-users"] = "false";
		}
		if (element.dataset.permission) {
			this.indexArgs.permission = element.dataset.permission;
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
