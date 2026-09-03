/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=b3952f7d';
import { InputElement } from './input.js?v=b3952f7d';
import { RadioElement } from './radio.js?v=b3952f7d';
import './foundation.js?v=b3952f7d';
import './upstreamUnavailable.js?v=b3952f7d';
import './connectivity.js?v=b3952f7d';
import './baseForm.js?v=b3952f7d';
import './icons.js?v=b3952f7d';
import './primitives.js?v=b3952f7d';
import './styles.js?v=b3952f7d';
import './loader.js?v=b3952f7d';
import './baseElement.js?v=b3952f7d';
import './formatting.js?v=b3952f7d';

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
