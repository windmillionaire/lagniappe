/*! Third-party licenses: /third-party-licenses.txt */
import { InputElement } from './input.js?v=bf6747aa';
import { RadioElement } from './radio.js?v=bf6747aa';
import { F as FormWidget } from './formWidget.js?v=bf6747aa';
import './styles.js?v=bf6747aa';
import './baseElement.js?v=bf6747aa';
import './icons.js?v=bf6747aa';
import './primitives.js?v=bf6747aa';
import './formatting.js?v=bf6747aa';
import './controller.js?v=bf6747aa';
import './foundation.js?v=bf6747aa';
import './upstreamUnavailable.js?v=bf6747aa';
import './connectivity.js?v=bf6747aa';
import './loader.js?v=bf6747aa';
import './modal.js?v=bf6747aa';
import './formRepresentation.js?v=bf6747aa';

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
