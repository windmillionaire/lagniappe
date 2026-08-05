/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bfd37afb';
import { s as setIcon } from './icons.js?v=bfd37afb';
import { d as debounce, E as ENDPOINTS, r as request } from './foundation.js?v=bfd37afb';
import './connectivity.js?v=bfd37afb';
import { p as primitives } from './primitives.js?v=bfd37afb';
import { updateUserLocation } from './user2.js?v=bfd37afb';
import { C as Combobox } from './combobox.js?v=bfd37afb';
import { B as BaseElement } from './baseElement.js?v=bfd37afb';
import './notificationState.js?v=bfd37afb';

/**
 * @testable infrastructure
 */
class LocationBox extends Combobox {
	constructor(element, { name = null, onSelect = null } = {}) {
		super(element);
		this.index = "location";
		this.currentQuery = "";
		this.fieldName = name || this.name;
		this.location = null;
		this.onSelect = onSelect;

		this._input = this._input.bind(this);
		this._debouncedInput = debounce(this._input, 200);

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
		this.element.addEventListener("input", this._debouncedInput);
	}

	_input(event) {
		const query = event.target.value.trim();
		this.currentQuery = query;
		if (query.length > 2) {
			this._search(query);
		} else if (this.panelOpen) {
			this.hidePanel();
		}
	}

	elementClick(event) {
		updateUserLocation();
		super.elementClick(event, false);
	}

	async _search(query) {
		const params = new URLSearchParams();
		params.set("q", query);
		const response = await request.get(this.endpoint, params);
		if (query !== this.currentQuery) return;

		if (!this.panel) this._createPanel();
		this.panel.innerHTML = "";
		this.options = [];
		this.focusedIndex = -1;

		if (response.ok) this.updatePanel(response.results || null);
		this._appendManualOption(query);
		this.showPanel();
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

	destroy() {
		this.element.removeEventListener("input", this._debouncedInput);
		super.destroy();
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

const MAPS_SEARCH = "https://www.google.com/maps/search/";

/**
 * @testable false
 * @covered-by src/script/elements/location.mjs::LocationElement
 * @reason text cleanup is private location value normalization
 */
function cleanText(value) {
	if (value === null || value === undefined) return "";
	return String(value).trim();
}

/**
 * @testable false
 * @covered-by src/script/elements/location.mjs::LocationElement
 * @reason address/unit display is private location value normalization
 */
function addressWithUnit(location = {}) {
	const address = cleanText(location.address);
	const address2 = cleanText(location.address2);
	if (!address || !address2) return address || "";
	if (address.toLowerCase().includes(address2.toLowerCase())) return address;

	const index = address.indexOf(",");
	if (index < 0) return `${address}, ${address2}`;
	return `${address.slice(0, index)}, ${address2}${address.slice(index)}`;
}

/**
 * @testable false
 * @covered-by src/script/elements/location.mjs::LocationElement
 * @reason display text is private location value normalization
 */
function displayText(location = {}) {
	const name = cleanText(location.name);
	const address = addressWithUnit(location);
	if (name && address && name !== cleanText(location.address)) {
		return `${name}, ${address}`;
	}
	return address || name;
}

/**
 * @testable true
 * @tests tests_js/test_026_location_urls.py::test_location_maps_url_uses_search_contract_and_place_id
 * @features location
 * @dimensions maps-url place-id encoding
 */
function mapsUrl(location = {}) {
	const query = displayText(location);
	if (!query) return "#";

	const url = new URL(MAPS_SEARCH);
	url.searchParams.set("api", "1");
	url.searchParams.set("query", query);
	const placeId = cleanText(location.id || location.place_id);
	if (placeId) url.searchParams.set("query_place_id", placeId);
	return url.toString();
}

/**
 * @testable infrastructure
 */
class LocationElement extends BaseElement {
	constructor(renderer, schema, submission) {
		super(renderer, schema, submission);

		this.location = null;

		this._handleLocationSelect = this._handleLocationSelect.bind(this);
		this._unitInput = this._unitInput.bind(this);
		this._unitChange = this._unitChange.bind(this);
	}

	get value() {
		return this._payload() || this.submission || null;
	}

	changed(value) {
		if (!value && !this.submission) return false;
		if (!value || !this.submission) return true;
		const pid = (v) => cleanText(v.id || v.place_id);
		const a = pid(value);
		const b = pid(this.submission);
		const address2 = (v) => cleanText(v.address2);
		if (a && b && a === b && address2(value) === address2(this.submission)) {
			return false;
		}
		const addr = (v) => cleanText(v.address || v.name);
		if (
			!a &&
			!b &&
			addr(value) &&
			addr(value) === addr(this.submission) &&
			address2(value) === address2(this.submission)
		) {
			return false;
		}
		return true;
	}

	get read() {
		if (this._read) return this._read;

		this._read = document.createElement("div");
		this._read.className = STYLES.form.submission.grows;

		const container = this._read.appendChild(document.createElement("div"));
		container.className = `flex flex-row items-start gap-2`;

		const out = container.appendChild(document.createElement("span"));
		setIcon(out, "map", "mt-1");

		const text = container.appendChild(document.createElement("div"));
		text.className = "flex flex-col";

		const link = text.appendChild(document.createElement("a"));
		link.dataset.kind = "page";
		link.className = STYLES.link.default;
		link.target = "_blank";
		const sub = this.submission;
		link.href = mapsUrl(sub);

		link.textContent = sub.name || addressWithUnit(sub);

		const details = sub.name ? addressWithUnit(sub) : null;
		if (details) {
			const detail = text.appendChild(document.createElement("span"));
			detail.className = "text-xs font-normal text-base-medium";
			detail.textContent = details;
		}

		this._read.classList.add("group-data-[mode=edit]/element:hidden");

		return this._read;
	}

	get edit() {
		if (this._edit) return this._edit;

		this.location = null;

		this._edit = document.createElement("div");
		this._edit.className = "flex flex-col gap-2";

		if (this.label) {
			const label = primitives.label({
				label: this.label,
				tag: "h3",
			});
			this._edit.appendChild(label);
		}

		const controls = this._edit.appendChild(document.createElement("div"));
		controls.className =
			"flex flex-col gap-2 group-data-[mode=read]/element:hidden";

		this.searchInput = primitives.input({
			type: "text",
			kind: this.renderer.kind,
			placeholder: "search for a location...",
		});
		controls.appendChild(this.searchInput);

		this.unitInput = this._createUnitInput();
		controls.appendChild(this.unitInput);

		this.nameInput = this._createDetailInput("name");
		this.addressInput = this._createDetailInput("address");
		controls.append(this.nameInput, this.addressInput);

		this.unitInput.addEventListener("input", this._unitInput);
		this.unitInput.addEventListener("change", this._unitChange);

		this.combobox = new LocationBox(controls, {
			name: this.schema.id,
			onSelect: this._handleLocationSelect,
		});
		this.combobox.init();
		this.idInput = this.combobox.hiddenInput;
		this.destroyables.push(this.combobox);

		if (this.submission) {
			this.combobox.addOption(this.submission, false);
		} else {
			this._syncHidden({ notify: false });
		}

		return this._edit;
	}

	clear() {
		if (this.combobox) {
			this.combobox.clear({ notify: false });
		}
		this.location = null;
		if (this.searchInput) this.searchInput.value = "";
		if (this.unitInput) this.unitInput.value = "";
		if (this.nameInput) this.nameInput.value = "";
		if (this.addressInput) this.addressInput.value = "";
		this.submission = null;
		this._syncHidden();
	}

	destroy() {
		this.unitInput?.removeEventListener("input", this._unitInput);
		this.unitInput?.removeEventListener("change", this._unitChange);

		super.destroy();

		this.location = null;
		this.searchInput = null;
		this.unitInput = null;
		this.idInput = null;
		this.nameInput = null;
		this.addressInput = null;
	}

	_handleLocationSelect(location, { notify = true } = {}) {
		this._setLocation(location, { notify });
		if (this.searchInput) this.searchInput.value = "";
	}

	_createDetailInput(part) {
		const input = document.createElement("input");
		input.type = "hidden";
		input.name = `${this.schema.id}:${part}`;
		input.value = "";
		return input;
	}

	_createUnitInput() {
		const input = document.createElement("input");
		input.type = "text";
		input.name = `${this.schema.id}:address2`;
		input.autocomplete = "off";
		input.placeholder = "Apt, suite, unit";
		input.setAttribute("aria-label", "Apt, suite, unit");
		input.setAttribute("data-1p-ignore", "");
		input.className = STYLES.input;
		input.pattern = ".*";
		return input;
	}

	_setLocation(details, { notify = true } = {}) {
		if (!details) {
			this.location = null;
			if (this.unitInput) this.unitInput.value = "";
			this._syncHidden({ notify });
			return;
		}

		const address2 = cleanText(details.address2) || this._unitValue();
		const id = cleanText(details.id || details.place_id);
		const address = cleanText(details.address);
		const name = cleanText(details.name) || address;

		this.location = {};
		if (id) this.location.id = id;
		if (name) this.location.name = name;
		if (address) this.location.address = address;
		if (address2) this.location.address2 = address2;

		if (!this.location.name && !this.location.address && !this.location.id) {
			this.location = null;
		}

		if (this.unitInput) this.unitInput.value = address2 || "";
		this._syncHidden({ notify });
	}

	_payload() {
		if (!this.location) return null;

		const payload = { ...this.location };
		const address2 = this._unitValue();
		if (address2) {
			payload.address2 = address2;
		} else {
			delete payload.address2;
		}

		return Object.keys(payload).length > 0 ? payload : null;
	}

	_syncHidden({ notify = true } = {}) {
		const payload = this._payload();

		if (this.idInput) this.idInput.value = payload?.id || "";
		if (this.nameInput) this.nameInput.value = payload?.name || "";
		if (this.addressInput) this.addressInput.value = payload?.address || "";
		if (this.searchInput) {
			this.searchInput.dataset.values = payload ? "true" : "false";
			this.searchInput.placeholder = payload
				? this._selectedPlaceholder(payload)
				: this.searchInput.dataset.placeholder || "search for a location...";
		}

		if (notify && this.idInput) {
			this.idInput.dispatchEvent(new Event("change", { bubbles: true }));
		}
	}

	_unitInput() {
		this._syncHidden({ notify: false });
	}

	_unitChange() {
		this._syncHidden();
	}

	_unitValue() {
		return cleanText(this.unitInput?.value);
	}

	_selectedPlaceholder(payload) {
		return displayText(payload) || "search for a location...";
	}
}

export { LocationElement };
