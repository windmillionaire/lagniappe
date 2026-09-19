/*! Third-party licenses: /third-party-licenses.txt */
import { InputElement } from './input.js?v=b1aeef6f';
import { RadioElement } from './radio.js?v=b1aeef6f';
import { F as FormWidget } from './formWidget.js?v=b1aeef6f';
import './styles.js?v=b1aeef6f';
import './baseElement.js?v=b1aeef6f';
import './icons.js?v=b1aeef6f';
import './primitives.js?v=b1aeef6f';
import './formatting.js?v=b1aeef6f';
import './controller.js?v=b1aeef6f';
import './foundation.js?v=b1aeef6f';
import './upstreamUnavailable.js?v=b1aeef6f';
import './connectivity.js?v=b1aeef6f';
import './loader.js?v=b1aeef6f';
import './modal.js?v=b1aeef6f';
import './representation.js?v=b1aeef6f';

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
