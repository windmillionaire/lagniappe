/*! Third-party licenses: /third-party-licenses.txt */
import { BaseList } from './baseList.js?v=bdbb928b';
import { F as FormElement } from './form2.js?v=bdbb928b';
import { InputElement } from './input.js?v=bdbb928b';
import { S as SectionToggle } from './sectionToggle.js?v=bdbb928b';
import './foundation.js?v=bdbb928b';
import './connectivity.js?v=bdbb928b';
import './baseForm.js?v=bdbb928b';
import './icons.js?v=bdbb928b';
import './primitives.js?v=bdbb928b';
import './styles.js?v=bdbb928b';
import './loader.js?v=bdbb928b';
import './baseElement.js?v=bdbb928b';
import './formatting.js?v=bdbb928b';
import './facets.js?v=bdbb928b';
import './remote.js?v=bdbb928b';
import './queryLifecycle.js?v=bdbb928b';
import './combobox.js?v=bdbb928b';
import './results.js?v=bdbb928b';
import './storage.js?v=bdbb928b';
import './submitter.js?v=bdbb928b';
import './buttons.js?v=bdbb928b';
import './baseUpload.js?v=bdbb928b';
import './dropdown.js?v=bdbb928b';

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
 * @matrix model-tasks : attach-form create permission-gates
 * @pair entity-layout:project-mobile
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
 * @matrix model-tasks : form-change form-clear info-form name update
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

	postreconcile() {
		super.postreconcile();
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
 * @pair model-tasks:delete
 */
class ModelTaskList extends BaseList {
	postreconcile() {
		super.postreconcile();
		this.target.setAttribute("loaded", "");
	}
}

export { CreateModelTask, ModelTaskInfo, ModelTaskList };
