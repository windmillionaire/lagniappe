/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=bedf900f';
import { InputElement } from './input.js?v=bedf900f';
import { RadioElement } from './radio.js?v=bedf900f';
import './foundation.js?v=bedf900f';
import './upstreamUnavailable.js?v=bedf900f';
import './connectivity.js?v=bedf900f';
import './formRepresentation.js?v=bedf900f';
import './styles.js?v=bedf900f';
import './modal.js?v=bedf900f';
import './baseForm.js?v=bedf900f';
import './icons.js?v=bedf900f';
import './primitives.js?v=bedf900f';
import './loader.js?v=bedf900f';
import './baseElement.js?v=bedf900f';
import './formatting.js?v=bedf900f';

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
