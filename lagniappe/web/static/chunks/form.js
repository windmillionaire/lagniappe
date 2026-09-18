/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=baf2edcb';
import { InputElement } from './input.js?v=baf2edcb';
import { RadioElement } from './radio.js?v=baf2edcb';
import './foundation.js?v=baf2edcb';
import './upstreamUnavailable.js?v=baf2edcb';
import './connectivity.js?v=baf2edcb';
import './formRepresentation.js?v=baf2edcb';
import './styles.js?v=baf2edcb';
import './modal.js?v=baf2edcb';
import './baseForm.js?v=baf2edcb';
import './icons.js?v=baf2edcb';
import './primitives.js?v=baf2edcb';
import './loader.js?v=baf2edcb';
import './baseElement.js?v=baf2edcb';
import './formatting.js?v=baf2edcb';

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
