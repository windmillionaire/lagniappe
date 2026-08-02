/*! Third-party licenses: /third-party-licenses.txt */
import { BaseList } from './baseList.js?v=b549327e';
import { F as FormElement } from './form2.js?v=b549327e';
import { InputElement } from './input.js?v=b549327e';
import { S as SectionToggle } from './sectionToggle.js?v=b549327e';
import './baseForm.js?v=b549327e';
import './request.js?v=b549327e';
import './errors.js?v=b549327e';
import './connectivity.js?v=b549327e';
import './icons.js?v=b549327e';
import './styles.js?v=b549327e';
import './utilities.js?v=b549327e';
import './primitives.js?v=b549327e';
import './loader.js?v=b549327e';
import './baseElement.js?v=b549327e';
import './formatting.js?v=b549327e';
import './facets.js?v=b549327e';
import './endpoints.js?v=b549327e';
import './combobox.js?v=b549327e';
import './results.js?v=b549327e';
import './submitter.js?v=b549327e';
import './buttons.js?v=b549327e';
import './baseUpload.js?v=b549327e';
import './dropdown.js?v=b549327e';

/**
 * @testable infrastructure
 */
class ModelTask extends FormElement {
	get formSelectElement() {
		const target = this.target.querySelector('[data-action="select-form"]');
		if (!target) return null;

		const control = SectionToggle.facet(this, target);
		control.init();
		this.destroyables.push(control);
		return control.elt;
	}

	get html() {
		this.nameElement = new InputElement(
			{
				kind: "task",
				readonly: this.readonly,
			},
			{
				id: "name",
				name: "name",
				title: "Name",
				input: "text",
				required: true,
				label: "Name",
			},
			this.target.dataset.name || "",
		);
		return [this.nameElement.elt, this.formSelectElement];
	}
}

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004a_project.py::test_create_model_task
 * @tests tests_e2e/004_projects/test_004a_project.py::test_create_model_task_with_form
 * @tests tests_e2e/004_projects/test_004g_project_mobile_ui.py::test_mobile_create_model_form_opens_from_model_tasks_section
 * @tests tests_e2e/004_projects/test_004i_project_permissions.py::test_project_editor_can_open_model_task_creation
 * @features model-tasks
 * @dimensions create attach-form permission-gates
 */
class CreateModelTask extends ModelTask {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Create Model Task",
			submitting: "Creating Model Task",
			submitted: "Model Task Created",
		};
	}

	postreconcile() {
		const created = this._created;
		super.postreconcile();

		if (created) {
			this.nameElement.clear();
			if (this.visible) this.form?.success();
			this.form?.resetSubmitButton();
		}
		if (this.visible) this.nameElement.focus();
	}
}

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004c_model_tasks.py::test_click_model_opens_info
 * @tests tests_e2e/004_projects/test_004c_model_tasks.py::test_edit_model_task_name
 * @tests tests_e2e/004_projects/test_004c_model_tasks.py::test_change_model_task_form
 * @tests tests_e2e/004_projects/test_004c_model_tasks.py::test_delete_model_task_form
 * @features model-tasks
 * @dimensions info-form update name form-change form-clear
 */
class ModelTaskInfo extends ModelTask {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Update Model Task",
			submitting: "Updating Model Task",
			submitted: "Model Task Updated",
		};
	}

	async postreconcile() {
		await super.postreconcile();
		const name =
			this.nameElement?.value ||
			this.target.dataset.name ||
			this.component.elt.dataset.title ||
			"";
		if (!name) return;

		this.component.elt.dataset.title = name;
		const title = this.component.elt.querySelector("span[data-role='title']");
		if (title && name !== title.textContent) {
			title.textContent = name;
		}
	}
}

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004c_model_tasks.py::test_delete_model_task
 * @features model-tasks
 * @dimensions delete
 */
class ModelTaskList extends BaseList {
	postreconcile() {
		super.postreconcile();
		this.target.setAttribute("loaded", "");
	}
}

export { CreateModelTask, ModelTaskInfo, ModelTaskList };
