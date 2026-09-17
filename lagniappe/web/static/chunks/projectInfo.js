/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=b24ca4c6';
import { InputElement } from './input.js?v=b24ca4c6';
import { s as sections } from './sections.js?v=b24ca4c6';
import { TextareaElement } from './textarea.js?v=b24ca4c6';
import './foundation.js?v=b24ca4c6';
import './upstreamUnavailable.js?v=b24ca4c6';
import './connectivity.js?v=b24ca4c6';
import './formRepresentation.js?v=b24ca4c6';
import './styles.js?v=b24ca4c6';
import './modal.js?v=b24ca4c6';
import './baseForm.js?v=b24ca4c6';
import './icons.js?v=b24ca4c6';
import './primitives.js?v=b24ca4c6';
import './loader.js?v=b24ca4c6';
import './baseElement.js?v=b24ca4c6';
import './formatting.js?v=b24ca4c6';
import './baseUpload.js?v=b24ca4c6';
import './upload.js?v=b24ca4c6';
import './buttons.js?v=b24ca4c6';
import './dropdown.js?v=b24ca4c6';
import './combobox.js?v=b24ca4c6';

/**
 * @testable false
 * @covered-by src/script/widgets/projectInfo.mjs::CreateProject
 * @covered-by src/script/widgets/projectInfo.mjs::ProjectInfo
 * @reason shared field construction is exercised through concrete project widgets
 */
class ProjectForm extends FormElement {
	get nameElement() {
		return new InputElement(
			{
				kind: "project",
				readonly: this.readonly,
			},
			{
				id: "name",
				label: "Project Name",
				input: "text",
				placeholder: "name this project...",
			},
			this.target.dataset.name || "",
		).elt;
	}

	get descriptionElement() {
		return new TextareaElement(
			{
				kind: "project",
				readonly: this.readonly,
			},
			{
				id: "description",
				label: "Project Description",
				input: "textarea",
				placeholder: "describe this project...",
			},
			this.target.dataset.description || "",
		).elt;
	}
}

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004b_info.py::test_project_info_form
 * @tests tests_e2e/004_projects/test_004i_project_permissions.py::test_project_viewer_reads_project_without_editing_controls
 * @matrix projects : info-form metadata-sync readonly
 */
class ProjectInfo extends ProjectForm {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Update Project",
			submitting: "Updating Project",
			submitted: "Project Updated",
		};
	}

	get html() {
		return [this.nameElement, this.descriptionElement];
	}

	postreconcile() {
		super.postreconcile();
		this.setEntityMetadata();
	}
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002b_home_projects.py::test_create_project_form
 * @tests tests_e2e/002_home/test_002b_home_projects.py::test_create_project_ai_mode
 * @matrix projects : ai-form manual-form
 */
class CreateProject extends ProjectForm {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Create Project",
			submitting: "Creating Project",
			submitted: "Project Created",
		};
		this.target.dataset.mode = "manual";
		this.target.dataset.role = "generate";
	}

	get html() {
		const name = this.nameElement;
		const description = this.descriptionElement;
		name.dataset.role = "manual";
		description.dataset.role = "manual";

		return [sections.generateEntityForm(this), name, description];
	}

	postreconcile() {
		this.target.querySelectorAll("input, textarea").forEach((element) => {
			if (element.type !== "checkbox") {
				element.value = "";
			}
		});
		this.target.dataset.mode = "manual";
		this.form.resetSubmitButton();
	}
}

export { CreateProject, ProjectInfo };
