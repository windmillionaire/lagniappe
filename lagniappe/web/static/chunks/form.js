/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=be396a6a';
import { InputElement } from './input.js?v=be396a6a';
import { RadioElement } from './radio.js?v=be396a6a';
import './foundation.js?v=be396a6a';
import './upstreamUnavailable.js?v=be396a6a';
import './connectivity.js?v=be396a6a';
import './baseForm.js?v=be396a6a';
import './icons.js?v=be396a6a';
import './primitives.js?v=be396a6a';
import './styles.js?v=be396a6a';
import './loader.js?v=be396a6a';
import './baseElement.js?v=be396a6a';
import './formatting.js?v=be396a6a';

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
