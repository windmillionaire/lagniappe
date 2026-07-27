import { primitives } from "../../../elements/primitives";
import { simpleHash } from "../../../shared";
import { Condition } from "./base";

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_change_select_options
 * @features forms
 * @dimensions builder-select-options
 */
export default class Options extends Condition {
	constructor(builder) {
		super(builder);
		this.key = "options";
		this.messages = {
			submit: "Add Option",
		};
	}

	init() {
		this.element.schema.options ??= [];

		if (this.index !== -1) {
			this.setTitle("Edit Option");
			this.messages.submit = "Update Option";
			this.setting = { ...this.element.schema.options[this.index] };
		} else {
			this.setTitle("Create Option");
			this.messages.submit = "Add Option";
			this.setting = {};
		}

		super.init();

		this.showProgress();
	}

	showProgress() {
		this.addOptionName();
		if (this.setting.label) {
			this.complete = true;
		}
		super.showProgress();
	}

	addOptionName() {
		if (this.options.has("name")) return;
		delete this.setting.value;

		const optionName = primitives.input({
			label: "Option Name",
			placeholder: "enter option name...",
			name: "option-name",
			type: "text",
			value: this.setting.label || null,
		});

		this.options.set("name", optionName);
		this.focusTarget = optionName;

		optionName.addEventListener("input", (e) => {
			this.setting.label = e.target.value;
			this.showProgress();
		});
	}

	validate() {
		if (!this.setting.label) {
			this.form.showError("Please enter an option name.");
			return false;
		}
		if (!this.setting.value) {
			this.setting.value = `o${simpleHash(this.setting.label)}`;
		}
		return true;
	}
}
