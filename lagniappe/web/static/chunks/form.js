/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=b052d07c';
import { InputElement } from './input.js?v=b052d07c';
import { RadioElement } from './radio.js?v=b052d07c';
import './foundation.js?v=b052d07c';
import './upstreamUnavailable.js?v=b052d07c';
import './connectivity.js?v=b052d07c';
import './baseForm.js?v=b052d07c';
import './icons.js?v=b052d07c';
import './primitives.js?v=b052d07c';
import './styles.js?v=b052d07c';
import './loader.js?v=b052d07c';
import './baseElement.js?v=b052d07c';
import './formatting.js?v=b052d07c';

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
