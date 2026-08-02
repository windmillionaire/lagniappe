/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=be0d9638';
import { InputElement } from './input.js?v=be0d9638';
import { RadioElement } from './radio.js?v=be0d9638';
import './baseForm.js?v=be0d9638';
import './request.js?v=be0d9638';
import './errors.js?v=be0d9638';
import './connectivity.js?v=be0d9638';
import './icons.js?v=be0d9638';
import './styles.js?v=be0d9638';
import './utilities.js?v=be0d9638';
import './primitives.js?v=be0d9638';
import './loader.js?v=be0d9638';
import './baseElement.js?v=be0d9638';
import './formatting.js?v=be0d9638';

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_page_form
 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_task_form
 * @features forms
 * @dimensions create page-form task-form
 */
class CreateForm extends FormElement {
	init() {
		this.messages = {
			submit: "Create Form",
			submitting: "Creating Form",
			submitted: "Form Created",
		};

		super.init();
	}

	get html() {
		this.nameElement = new InputElement(this, {
			name: "name",
			required: true,
			type: "text",
			label: "Name",
		});

		const formType = new RadioElement(this, {
			name: "form-type",
			required: true,
			layout: "row",
			options: [
				{ label: "Page", value: "page" },
				{ label: "Task", value: "task" },
			],
		});

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

export { CreateForm };
