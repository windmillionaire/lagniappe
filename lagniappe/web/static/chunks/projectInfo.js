/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=be1b1fb2';
import { InputElement } from './input.js?v=be1b1fb2';
import { s as sections } from './sections.js?v=be1b1fb2';
import { TextareaElement } from './textarea.js?v=be1b1fb2';
import './baseForm.js?v=be1b1fb2';
import './request.js?v=be1b1fb2';
import './errors.js?v=be1b1fb2';
import './connectivity.js?v=be1b1fb2';
import './icons.js?v=be1b1fb2';
import './styles.js?v=be1b1fb2';
import './utilities.js?v=be1b1fb2';
import './primitives.js?v=be1b1fb2';
import './loader.js?v=be1b1fb2';
import './baseElement.js?v=be1b1fb2';
import './formatting.js?v=be1b1fb2';
import './baseUpload.js?v=be1b1fb2';
import './buttons.js?v=be1b1fb2';
import './dropdown.js?v=be1b1fb2';
import './combobox.js?v=be1b1fb2';

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

	async postreconcile() {
		await super.postreconcile();
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
