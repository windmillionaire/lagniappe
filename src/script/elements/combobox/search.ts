import { STYLES } from "../../generated/styles.mjs";
import { ENDPOINTS } from "../../shared/endpoints.ts";
import { request } from "../../shared/request.ts";
import type { ComboboxOptionElement } from "./combobox.ts";
import {
	type ComboboxQueryResponse,
	type RemoteInputEvent,
	RemoteQueryCombobox,
} from "./remote.ts";
import { Results } from "./results.ts";

export class SearchBox extends RemoteQueryCombobox {
	declare results: Results;
	declare endpoints: typeof ENDPOINTS.search;
	declare clearButton: HTMLButtonElement | null;
	declare _clearClick: (event: MouseEvent) => void;

	constructor(element: HTMLElement) {
		super(element);
		this.index = "search";
		this.results = new Results(this.index);
		this.placement = "bottom-end";
		this.endpoints = ENDPOINTS.search;
		this.clearButton =
			element.querySelector?.<HTMLButtonElement>(
				"[data-role='search-clear']",
			) ?? null;
		this._clearClick = (event: MouseEvent) => {
			event.preventDefault();
			event.stopPropagation();
			this.clearSearch();
		};
	}

	init() {
		this.styles.panel = `${STYLES.dropdown.panel} right-0 w-64 sm:w-96 mt-2`;
		super.init();
		this.clearButton?.addEventListener("click", this._clearClick);
		this._syncClearButton();
		this.updatePanel(this.results.create());
	}

	_syncClearButton() {
		if (!this.clearButton) return;
		this.clearButton.dataset.visible =
			this.element.value.length > 0 ? "true" : "false";
	}

	clearSearch() {
		this.element.value = "";
		this._syncClearButton();
		this.settleQueryInput();
		this.updatePanel(this.results.create());
		this.element.focus();
		return this.showPanel();
	}

	_input(event: RemoteInputEvent) {
		this._syncClearButton();
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

	destroy() {
		this.clearButton?.removeEventListener("click", this._clearClick);
		super.destroy();
	}

	elementClick(event: MouseEvent) {
		super.elementClick(event);
		this.showPanel();
	}

	_search(query: string) {
		const params = new URLSearchParams();
		params.set("q", query);
		return this.runQuery(
			query,
			(token) =>
				request.get<ComboboxQueryResponse>(this.endpoints.bar, params, {
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

	/**
	 * @template nav.html::search_results
	 */
	selectOption(option: ComboboxOptionElement) {
		const { url } = option.dataset;
		if (!url) return;
		this.results.save(option);
		this.hidePanel();
		window.location.href = url;
	}

	elementKeydown(event: KeyboardEvent) {
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
