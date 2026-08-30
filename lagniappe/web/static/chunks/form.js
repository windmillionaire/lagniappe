/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=bb782d98';
import { InputElement } from './input.js?v=bb782d98';
import { RadioElement } from './radio.js?v=bb782d98';
import './foundation.js?v=bb782d98';
import './connectivity.js?v=bb782d98';
import './baseForm.js?v=bb782d98';
import './icons.js?v=bb782d98';
import './primitives.js?v=bb782d98';
import './styles.js?v=bb782d98';
import './loader.js?v=bb782d98';
import './baseElement.js?v=bb782d98';
import './formatting.js?v=bb782d98';

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_page_form
 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_task_form
 * @matrix forms : create page-form task-form
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
