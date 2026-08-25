import { STYLES } from "styles";
import { ENDPOINTS, request, updateUserLocation } from "../../shared";
import { setIcon } from "../../shared/icons";
import { RemoteQueryCombobox } from "./remote";

/**
 * @testable true
 * @tests tests_js/test_016_combobox_frontend.py::test_location_combobox_starts_location_sync_on_init
 * @tests tests_js/test_016_combobox_frontend.py::test_location_combobox_waits_for_session_sync_before_search
 * @matrix location : initialization on-demand request-ordering session-update
 */
export class LocationBox extends RemoteQueryCombobox {
	constructor(element, { name = null, onSelect = null } = {}) {
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
		this.element.autocomplete = "bork";
		void updateUserLocation();
	}

	_input(event) {
		const query = event.target.value.trim();
		if (query.length > 2) {
			return this._search(query);
		}
		this.settleQueryInput({ clear: true });
	}

	elementClick(event) {
		void updateUserLocation();
		super.elementClick(event, false);
	}

	_search(query) {
		const params = new URLSearchParams();
		params.set("q", query);
		return this.runQuery(
			query,
			async (token) => {
				await updateUserLocation();
				if (token.signal?.aborted) return null;
				return request.get(this.endpoint, params, { signal: token.signal });
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

	_setManualAddress(text, notify = true) {
		const address = this._cleanText(text);
		if (!address) return;

		this._selectLocation({ address, name: address }, { notify });
		this.element.value = "";
		this.hidePanel();
	}

	selectOption(option) {
		if (option.dataset.manual === "true") {
			this._setManualAddress(option.dataset.address);
			return;
		}

		if (!option.dataset.details) return;

		const details = JSON.parse(option.dataset.details);
		this._selectLocation(details);
		this.element.value = "";
		this.hidePanel();
	}

	elementKeydown(event) {
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

	addOption(option = {}, notify = true) {
		if (Object.keys(option).length === 0) return;

		this._selectLocation(option, { notify });
	}

	clear({ notify = true } = {}) {
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

	_appendManualOption(query) {
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
		option.dataset.index = this.options.length;
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

	_selectLocation(location, { notify = true } = {}) {
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

	_cleanText(value) {
		if (value === null || value === undefined) return null;
		const text = String(value).trim();
		return text || null;
	}

	_normalizeLocation(location) {
		if (!location || typeof location !== "object") return null;

		const id = this._cleanText(location.id || location.place_id);
		const address = this._cleanText(location.address);
		const name = this._cleanText(location.name) || address;
		const address2 = this._cleanText(location.address2);

		const normalized = {};
		if (id) normalized.id = id;
		if (name) normalized.name = name;
		if (address) normalized.address = address;
		if (address2) normalized.address2 = address2;

		return Object.keys(normalized).length > 0 ? normalized : null;
	}

	_displayText(location) {
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
