import { STYLES } from "../../generated/styles.mjs";
import { ENDPOINTS } from "../../shared/endpoints.ts";
import { setIcon } from "../../shared/icons.ts";
import { request } from "../../shared/request.ts";
import { updateUserLocation } from "../../shared/user.ts";
import type { ComboboxOptionElement } from "./combobox.ts";
import {
	type ComboboxQueryResponse,
	type RemoteInputEvent,
	RemoteQueryCombobox,
} from "./remote.ts";

type LocationSelection = {
	id?: string;
	name?: string;
	address?: string;
	address2?: string;
};

type LocationSource = {
	[Field in keyof LocationSelection | "place_id"]?: unknown;
};

type SelectionOptions = { notify?: boolean };

type LocationBoxOptions = {
	name?: string | null;
	onSelect?:
		| ((
				location: LocationSelection | null,
				options: { notify: boolean },
		  ) => void)
		| null;
};

export class LocationBox extends RemoteQueryCombobox {
	declare element: HTMLInputElement;
	declare fieldName: string | undefined;
	declare location: LocationSelection | null;
	declare onSelect: LocationBoxOptions["onSelect"];
	declare endpoint: string;
	declare basePlaceholder?: string;
	declare hiddenInput?: HTMLInputElement;

	constructor(
		element: HTMLElement,
		{ name = null, onSelect = null }: LocationBoxOptions = {},
	) {
		super(element);
		this.index = "location";
		this.fieldName = name || this.name;
		this.location = null;
		this.onSelect = onSelect;

		this.endpoint = ENDPOINTS.location;
	}

	init() {
		if (this.element.name) {
			this.fieldName = this.element.name;
		}
		super.init();

		this.element.removeAttribute("name");
		this.basePlaceholder = this.element.placeholder;
		this._createHiddenInput();
		this.element.setAttribute("autocomplete", "bork");
		void updateUserLocation();
	}

	_input(event: RemoteInputEvent) {
		const query = event.target.value.trim();
		if (query.length > 2) {
			return this._search(query);
		}
		this.settleQueryInput({ clear: true });
	}

	elementClick(event: MouseEvent) {
		void updateUserLocation();
		super.elementClick(event, false);
	}

	_search(query: string) {
		const params = new URLSearchParams();
		params.set("q", query);
		return this.runQuery(
			query,
			async (token) => {
				await updateUserLocation();
				if (token.signal?.aborted) return null;
				return request.get<ComboboxQueryResponse>(this.endpoint, params, {
					signal: token.signal,
				});
			},
			(response) => {
				this.clearQueryResults();
				if (response?.ok) this.updatePanel(response.results || null);
				if (!this.panel) this._createPanel();
				this._appendManualOption(query);
				return this.showPanel();
			},
		);
	}

	_setManualAddress(text: string | undefined, notify = true) {
		const address = this._cleanText(text);
		if (!address) return;

		this._selectLocation({ address, name: address }, { notify });
		this.element.value = "";
		this.hidePanel();
	}

	selectOption(option: ComboboxOptionElement) {
		if (option.dataset.manual === "true") {
			this._setManualAddress(option.dataset.address);
			return;
		}

		if (!option.dataset.details) return;

		const details: unknown = JSON.parse(option.dataset.details);
		this._selectLocation(details);
		this.element.value = "";
		this.hidePanel();
	}

	elementKeydown(event: KeyboardEvent) {
		super.elementKeydown(event);
		if (event.defaultPrevented) return;

		if (event.key === "Enter") {
			const text = this.element.value.trim();
			if (!text) return;

			event.stopPropagation();
			event.preventDefault();
			this._setManualAddress(text);
		} else if (
			this.location &&
			!this.element.value &&
			(event.key === "Backspace" || event.key === "Delete")
		) {
			event.stopPropagation();
			event.preventDefault();
			this.clear();
		}
	}

	addOption(option: LocationSource = {}, notify = true) {
		if (Object.keys(option).length === 0) return;

		this._selectLocation(option, { notify });
	}

	clear({ notify = true }: SelectionOptions = {}) {
		this.values.clear();
		this.location = null;
		this.focusedIndex = -1;
		this.element.value = "";
		this.element.placeholder = this.basePlaceholder || this.placeholder || "";
		this.element.dataset.values = "false";
		if (this.hiddenInput) this.hiddenInput.value = "";
		this.hidePanel();
		if (this.onSelect) this.onSelect(null, { notify });
		if (notify && !this.onSelect) this._dispatchChange();
	}

	_appendManualOption(query: string) {
		const address = this._cleanText(query);
		if (!this.panel || !address) return;

		const option = document.createElement("div");
		option.setAttribute("role", "option");
		option.className = STYLES.dropdown.search.result;
		option.dataset.manual = "true";
		option.dataset.address = address;
		option.dataset.id = `manual:${address}`;
		option.dataset.name = `Use "${address}"`;
		option.dataset.details = JSON.stringify({ address, name: address });
		option.dataset.index = String(this.options.length);
		option.id = `${this.panel.id}-manual`;

		const row = option.appendChild(document.createElement("p"));

		const icon = row.appendChild(document.createElement("span"));
		icon.className = "text-base-default";
		const iconElt = icon.appendChild(document.createElement("span"));
		setIcon(iconElt, "location", STYLES.dropdown.icon);

		const label = row.appendChild(document.createElement("span"));
		label.className = "font-medium text-base-default";
		label.textContent = `Use "${address}"`;

		this.panel.appendChild(option);
		this.options.push({
			id: option.dataset.id,
			name: option.dataset.name,
			address,
		});
	}

	_selectLocation(location: unknown, { notify = true }: SelectionOptions = {}) {
		const selected = this._normalizeLocation(location);
		if (!selected) return;

		this.location = selected;
		this.values.clear();
		if (selected.id) this.values.add(selected.id);

		if (this.hiddenInput) this.hiddenInput.value = selected.id || "";
		this.element.value = "";
		this.element.placeholder = this._displayText(selected);
		this.element.dataset.values = "true";

		if (this.onSelect) {
			this.onSelect(selected, { notify });
		}
		if (notify && !this.onSelect) this._dispatchChange();
	}

	_createHiddenInput() {
		if (this.hiddenInput || !this.fieldName) return;

		this.hiddenInput = document.createElement("input");
		this.hiddenInput.type = "hidden";
		this.hiddenInput.name = `${this.fieldName}:id`;
		this.element.after(this.hiddenInput);
	}

	_cleanText(value: unknown) {
		if (value === null || value === undefined) return null;
		const text = String(value).trim();
		return text || null;
	}

	_normalizeLocation(location: unknown) {
		if (!location || typeof location !== "object") return null;

		const details = location as LocationSource;
		const id = this._cleanText(details.id || details.place_id);
		const address = this._cleanText(details.address);
		const name = this._cleanText(details.name) || address;
		const address2 = this._cleanText(details.address2);

		const normalized: LocationSelection = {};
		if (id) normalized.id = id;
		if (name) normalized.name = name;
		if (address) normalized.address = address;
		if (address2) normalized.address2 = address2;

		return Object.keys(normalized).length > 0 ? normalized : null;
	}

	_displayText(location: LocationSelection) {
		return (
			this._cleanText(location?.name) ||
			this._cleanText(location?.address) ||
			this.basePlaceholder ||
			this.placeholder ||
			""
		);
	}

	_dispatchChange() {
		const target = this.hiddenInput || this.element;
		target.dispatchEvent(new Event("change", { bubbles: true }));
	}
}
