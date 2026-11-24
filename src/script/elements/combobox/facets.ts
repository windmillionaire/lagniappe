import { ENDPOINTS } from "../../shared/endpoints.ts";
import { request } from "../../shared/request.ts";
import type { ComboboxOption, ComboboxOptionElement } from "./combobox.ts";
import {
	type ComboboxQueryResponse,
	type RemoteInputEvent,
	RemoteQueryCombobox,
} from "./remote.ts";
import { Results } from "./results.ts";
import { Submitter } from "./submitter.ts";

type FacetIndexArgs = Record<string, string | boolean>;

type CreatedFacetResponse = ComboboxQueryResponse & {
	option?: ComboboxOption & { id: string; name: string; kind: string };
};

export function isFacetOption(value: unknown): value is ComboboxOption {
	if (!value || typeof value !== "object" || Array.isArray(value)) return false;
	const data: Record<string, unknown> = { ...value };
	return ["id", "name", "kind", "hash"].every(
		(key) => data[key] === undefined || typeof data[key] === "string",
	);
}

export class FacetsBox extends Submitter(RemoteQueryCombobox) {
	declare endpoint: string;
	declare indexArgs: FacetIndexArgs;

	constructor(element: HTMLElement, args: FacetIndexArgs = {}) {
		super(element);
		this.endpoint = ENDPOINTS.facet(String(this.index));
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

	_input(event: RemoteInputEvent) {
		const query = event.target.value.trim();
		if (query) return this._search(query);

		this.settleQueryInput();
		this.updatePanel(this.results.create());
		return this.showPanel();
	}

	elementClick(event: MouseEvent) {
		super.elementClick(event);
		this.showPanel();
	}

	selectOption(option: ComboboxOptionElement) {
		if (option.dataset.command === "create") {
			return this._createOption(option);
		}
		if (!option.dataset.id) return;

		this.invalidateQuery();
		super.selectOption(option);
		this.results.save(option);
	}

	get selectedOptions() {
		return this.options.filter(
			(o) => o.id !== undefined && this.values.has(o.id),
		);
	}

	_search(query: string) {
		const params = new URLSearchParams();
		params.set("q", query);
		if (this.creatable === "true") {
			params.set("creatable", "true");
		}
		Object.entries(this.indexArgs).forEach(([key, value]) => {
			params.set(key, String(value));
		});
		this.selectedOptions.forEach(({ hash }) => {
			params.append("preload", String(hash));
		});

		return this.runQuery(
			query,
			(token) =>
				request.get<ComboboxQueryResponse>(this.endpoint, params, {
					signal: token.signal,
				}),
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

	_createOption(option: ComboboxOptionElement) {
		const selectedOptions = this.selectedOptions;
		const query = this.element.value.trim();
		this.hidePanel();
		const data = new FormData();
		data.set("name", option.dataset.name || query);
		Object.entries(this.indexArgs).forEach(([key, value]) => {
			data.set(key, String(value));
		});

		const key = `create:${query}`;
		return this.runQuery(
			key,
			() => request.post<CreatedFacetResponse>(`${this.endpoint}/create`, data),
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
					...(this.panel?.querySelectorAll<ComboboxOptionElement>(
						"[role='option'][data-id]",
					) || []),
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
