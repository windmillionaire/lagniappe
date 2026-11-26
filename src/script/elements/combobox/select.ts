import {
	Combobox,
	type ComboboxOption,
	type ComboboxOptionElement,
} from "./combobox.ts";
import { type ResultDetails, Results } from "./results.ts";
import { Submitter } from "./submitter.ts";

export class SelectBox extends Submitter(Combobox) {
	declare select: HTMLSelectElement;
	declare items: ResultDetails[];

	constructor(element: HTMLElement) {
		super(element);
		this.results = new Results();
		this.items = [];
	}

	init() {
		const select = this.parent.querySelector("select");
		if (!select) throw new Error("SelectBox requires a native select element");
		this.select = select;
		const multiple: boolean = JSON.parse(
			this.select.dataset.multiple || "false",
		);
		this.multiple = multiple;
		this.select.name = String(this.name);
		this.select.multiple = multiple;
		this.select.style.display = "none";
		this.select.setAttribute("aria-hidden", "true");
		this.select.tabIndex = -1;

		const input = document.createElement("input");
		this.element = input;
		this.select.after(input);

		input.className = `${this.select.className}`;
		input.dataset.mode = "select";
		input.readOnly = true;
		input.setAttribute("inputmode", "none");

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
			.map((option) => {
				const details: ResultDetails = JSON.parse(
					option.dataset.details || "{}",
				);
				return {
					id: option.value,
					name: option.textContent ?? "",
					kind: this.select.dataset.kind || "default",
					...details,
					disabled:
						option.disabled ||
						(option.parentElement?.hasAttribute("disabled") ?? false),
				};
			});
	}

	selectOption(option: ComboboxOptionElement) {
		if (option.getAttribute("aria-disabled") === "true") return;
		super.selectOption(option);
	}

	elementClick(event: MouseEvent) {
		event.stopPropagation();

		this.panelOpen ? this.hidePanel() : void this.showPanel();
	}

	addOption(option: ComboboxOption) {
		if (!this.items) this._createItems();
		if (option.id !== undefined) this.values.add(option.id);
	}

	hidePanel(): undefined {
		super.hidePanel();
		this.element.blur();
	}
}
