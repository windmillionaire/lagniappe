/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=b19dd33c';
import { InputElement } from './input.js?v=b19dd33c';
import { RadioElement } from './radio.js?v=b19dd33c';
import './baseForm.js?v=b19dd33c';
import './request.js?v=b19dd33c';
import './errors.js?v=b19dd33c';
import './connectivity.js?v=b19dd33c';
import './icons.js?v=b19dd33c';
import './styles.js?v=b19dd33c';
import './utilities.js?v=b19dd33c';
import './primitives.js?v=b19dd33c';
import './loader.js?v=b19dd33c';
import './baseElement.js?v=b19dd33c';
import './formatting.js?v=b19dd33c';

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
