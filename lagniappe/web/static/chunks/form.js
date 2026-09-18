/*! Third-party licenses: /third-party-licenses.txt */
import { InputElement } from './input.js?v=bc80da50';
import { RadioElement } from './radio.js?v=bc80da50';
import { F as FormWidget } from './formWidget.js?v=bc80da50';
import './styles.js?v=bc80da50';
import './baseElement.js?v=bc80da50';
import './icons.js?v=bc80da50';
import './primitives.js?v=bc80da50';
import './formatting.js?v=bc80da50';
import './controller.js?v=bc80da50';
import './foundation.js?v=bc80da50';
import './upstreamUnavailable.js?v=bc80da50';
import './connectivity.js?v=bc80da50';
import './loader.js?v=bc80da50';
import './modal.js?v=bc80da50';
import './formRepresentation.js?v=bc80da50';

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
