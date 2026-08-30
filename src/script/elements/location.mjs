import { STYLES } from "styles";
import { LocationBox } from "../elements/combobox";
import { setIcon } from "../shared/icons";
import { BaseElement } from "./base/baseElement";
import { primitives } from "./primitives";

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
 * @matrix location : encoding maps-url place-id
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
export class LocationElement extends BaseElement {
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

	/**
	 * @testable true
	 * @pair location:read-layout
	 */
	get read() {
		if (this._read) return this._read;

		this._read = document.createElement("div");
		const sub = this.submission;
		const name = cleanText(sub.name);
		const address = addressWithUnit(sub);
		const details =
			name &&
			address &&
			name.toLowerCase() !== cleanText(sub.address).toLowerCase()
				? address
				: null;
		this._read.className = details
			? STYLES.form.submission.grows
			: STYLES.form.submission.default;

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
		link.href = mapsUrl(sub);

		link.textContent = details ? name : address || name;

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
