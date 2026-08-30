/*! Third-party licenses: /third-party-licenses.txt */
import { p as primitives } from './primitives.js?v=bdbb928b';
import { k as simpleHash } from './foundation.js?v=bdbb928b';
import './connectivity.js?v=bdbb928b';
import { C as Condition } from './base2.js?v=bdbb928b';
import './styles.js?v=bdbb928b';
import './icons.js?v=bdbb928b';
import './baseForm.js?v=bdbb928b';
import './loader.js?v=bdbb928b';
import './select2.js?v=bdbb928b';
import './combobox.js?v=bdbb928b';
import './results.js?v=bdbb928b';
import './storage.js?v=bdbb928b';
import './formatting.js?v=bdbb928b';
import './submitter.js?v=bdbb928b';

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_change_select_options
 * @pair forms:builder-select-options
 */
class Options extends Condition {
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

export { Options as default };
