/*! Third-party licenses: /third-party-licenses.txt */
import { InputElement } from './input.js?v=bdc1ce7d';
import { RadioElement } from './radio.js?v=bdc1ce7d';
import { F as FormWidget } from './formWidget.js?v=bdc1ce7d';
import './styles.js?v=bdc1ce7d';
import './baseElement.js?v=bdc1ce7d';
import './icons.js?v=bdc1ce7d';
import './primitives.js?v=bdc1ce7d';
import './formatting.js?v=bdc1ce7d';
import './controller.js?v=bdc1ce7d';
import './foundation.js?v=bdc1ce7d';
import './upstreamUnavailable.js?v=bdc1ce7d';
import './connectivity.js?v=bdc1ce7d';
import './loader.js?v=bdc1ce7d';
import './modal.js?v=bdc1ce7d';
import './representation.js?v=bdc1ce7d';

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
