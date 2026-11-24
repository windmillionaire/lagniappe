import { primitives } from "../../../elements/primitives.ts";
import { generateElementId } from "../../../shared/utilities.ts";
import type { FieldOption } from "../../../types/forms.d.ts";
import type FormBuilder from "../builder.ts";
import { Condition } from "./base.ts";

export default class Options extends Condition<Partial<FieldOption>> {
	declare setting: Partial<FieldOption>;
	declare key: "options";
	constructor(builder: FormBuilder) {
		super(builder);
		this.key = "options";
		this.messages = {
			submit: "Add Option",
		};
	}

	init(): undefined {
		if (this.index !== -1) {
			this.setTitle("Edit Option");
			this.messages.submit = "Update Option";
			this.setting = { ...this.element.schema.options?.[this.index] };
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
			this.setting.label = (e.target as HTMLInputElement).value;
			this.showProgress();
		});
	}

	validate() {
		if (!this.setting.label) {
			this.form?.showError("Please enter an option name.");
			return false;
		}
		if (!this.setting.value) {
			do {
				this.setting.value = generateElementId("option");
			} while (
				this.element.schema.options?.some(
					(option) => option.value === this.setting.value,
				)
			);
		}
		return true;
	}
}
