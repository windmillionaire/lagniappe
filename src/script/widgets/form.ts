import { InputElement } from "../elements/input.ts";
import { RadioElement } from "../elements/radio.ts";
import type { FormSubmitOptions } from "../forms/controller.ts";
import { FormWidget } from "./base/formWidget.ts";

export class CreateForm extends FormWidget {
	declare nameElement: InputElement;

	init() {
		this.messages = {
			submit: "Create Form",
			submitting: "Creating Form",
			submitted: "Form Created",
		};

		void super.init();
	}

	async prepareSubmit(options?: FormSubmitOptions) {
		const nameInput =
			this.target.querySelector<HTMLInputElement>("input[name='name']");
		if (!nameInput?.value.trim()) {
			this.form?.showError("Please enter a form name.");
			nameInput?.focus();
			return false;
		}

		const formType = this.target.querySelector<HTMLInputElement>(
			"input[name='form-type']:checked",
		);
		if (!formType) {
			this.form?.showError(
				"Please choose whether this is a Page or Task form.",
			);
			this.target
				.querySelector<HTMLInputElement>("input[name='form-type']")
				?.focus();
			return false;
		}

		this.form?.hideError();
		return super.prepareSubmit(options);
	}

	get html() {
		this.nameElement = new InputElement(
			this,
			{
				id: "name",
				required: true,
				input: "text",
				label: "Name",
			},
			undefined,
		);

		const formType = new RadioElement(
			this,
			{
				id: "form-type",
				label: "Form Type",
				required: true,
				layout: "row",
				options: [
					{ label: "Page", value: "page" },
					{ label: "Task", value: "task" },
				],
			},
			undefined,
		);

		return [this.nameElement.edit, formType.edit];
	}

	postreconcile() {
		const created = this._created;
		super.postreconcile();

		if (created) {
			this.nameElement.clear();
			this.success();
			this.form?.resetSubmitButton();
		}
		this.nameElement.focus();
		this.target.dataset.visible = "true";
	}
}
