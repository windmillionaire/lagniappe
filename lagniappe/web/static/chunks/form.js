/*! Third-party licenses: /third-party-licenses.txt */
import { InputElement } from './input.js?v=b43106f0';
import { RadioElement } from './radio.js?v=b43106f0';
import { F as FormWidget } from './formWidget.js?v=b43106f0';
import './styles.js?v=b43106f0';
import './baseElement.js?v=b43106f0';
import './icons.js?v=b43106f0';
import './primitives.js?v=b43106f0';
import './formatting.js?v=b43106f0';
import './controller.js?v=b43106f0';
import './foundation.js?v=b43106f0';
import './upstreamUnavailable.js?v=b43106f0';
import './connectivity.js?v=b43106f0';
import './loader.js?v=b43106f0';
import './modal.js?v=b43106f0';
import './representation.js?v=b43106f0';

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_page_form
 * @tests tests_e2e/003_forms/test_003a_forms.py::test_create_task_form
 * @matrix forms : create page-form task-form
 */
class CreateForm extends FormWidget {
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
