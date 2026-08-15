/*! Third-party licenses: /third-party-licenses.txt */
import { C as Combobox } from './combobox.js?v=bd5baecd';
import { R as Results } from './results.js?v=bd5baecd';
import { S as Submitter } from './submitter.js?v=bd5baecd';

/**
 * @testable infrastructure
 */
class SelectBox extends Submitter(Combobox) {
	constructor(element) {
		super(element);
		this.results = new Results();
		this.items = [];
	}

	init() {
		this.select = this.parent.querySelector("select");
		this.multiple = JSON.parse(this.select.dataset.multiple || "false");
		this.select.name = this.name;
		this.select.multiple = this.multiple;
		this.select.style.display = "none";

		this.element = document.createElement("input");
		this.select.after(this.element);

		this.element.className = `${this.select.className}`;
		this.element.dataset.mode = "select";
		this.element.readOnly = true;
		this.element.setAttribute("inputmode", "none");

		this._createItems();

		super.init();
	}

	updateSelect(preloading = false) {
		Array.from(this.select.options).forEach((option) => {
			option.selected = this.values.has(option.value);
		});

		if (this.values.size === 0) {
			this.select.selectedIndex = -1;
		}

		this.updatePlaceholder();

		if (!preloading) {
			this.dispatchChangeEvents();
		}
	}

	_createItems() {
		if (this.select.options.length === 0) return;

		this.items = Array.from(this.select.options)
			.filter((option) => option.value)
			.map((option) => ({
				id: option.value,
				name: option.textContent,
				kind: this.select.dataset.kind || "default",
				...JSON.parse(option.dataset.details || "{}"),
			}));
	}

	elementClick(event) {
		event.stopPropagation();

		this.panelOpen ? this.hidePanel() : void this.showPanel();
	}

	addOption(option) {
		if (!this.items) this._createItems();
		this.values.add(option.id);
	}

	hidePanel() {
		super.hidePanel();
		this.element.blur();
	}
}

export { SelectBox as S };
