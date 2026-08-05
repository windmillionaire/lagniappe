/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=bb7cd952';
import { InputElement } from './input.js?v=bb7cd952';
import { RadioElement } from './radio.js?v=bb7cd952';
import './baseForm.js?v=bb7cd952';
import './foundation.js?v=bb7cd952';
import './notificationState.js?v=bb7cd952';
import './connectivity.js?v=bb7cd952';
import './icons.js?v=bb7cd952';
import './primitives.js?v=bb7cd952';
import './styles.js?v=bb7cd952';
import './loader.js?v=bb7cd952';
import './baseElement.js?v=bb7cd952';
import './formatting.js?v=bb7cd952';

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
