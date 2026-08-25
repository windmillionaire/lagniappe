/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=b4b0f2eb';
import { InputElement } from './input.js?v=b4b0f2eb';
import { s as sections } from './sections.js?v=b4b0f2eb';
import { TextareaElement } from './textarea.js?v=b4b0f2eb';
import './foundation.js?v=b4b0f2eb';
import './connectivity.js?v=b4b0f2eb';
import './baseForm.js?v=b4b0f2eb';
import './icons.js?v=b4b0f2eb';
import './primitives.js?v=b4b0f2eb';
import './styles.js?v=b4b0f2eb';
import './loader.js?v=b4b0f2eb';
import './baseElement.js?v=b4b0f2eb';
import './formatting.js?v=b4b0f2eb';
import './baseUpload.js?v=b4b0f2eb';
import './buttons.js?v=b4b0f2eb';
import './dropdown.js?v=b4b0f2eb';
import './combobox.js?v=b4b0f2eb';

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
 * @features projects
 * @dimensions info-form metadata-sync readonly
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
		return [
			this.nameElement,
			this.descriptionElement,
			this.readonly ? null : sections.attributes(this),
		];
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
 * @features projects
 * @dimensions manual-form ai-form
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

		return [
			sections.generateEntityForm(this),
			name,
			description,
			sections.attributes(this),
		];
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
