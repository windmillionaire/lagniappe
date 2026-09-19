/*! Third-party licenses: /third-party-licenses.txt */
import { InputElement } from './input.js?v=bdc1ce7d';
import { s as sections } from './sections.js?v=bdc1ce7d';
import { TextareaElement } from './textarea.js?v=bdc1ce7d';
import { F as FormWidget } from './formWidget.js?v=bdc1ce7d';
import './styles.js?v=bdc1ce7d';
import './baseElement.js?v=bdc1ce7d';
import './icons.js?v=bdc1ce7d';
import './primitives.js?v=bdc1ce7d';
import './formatting.js?v=bdc1ce7d';
import './foundation.js?v=bdc1ce7d';
import './upstreamUnavailable.js?v=bdc1ce7d';
import './connectivity.js?v=bdc1ce7d';
import './baseUpload.js?v=bdc1ce7d';
import './controller.js?v=bdc1ce7d';
import './loader.js?v=bdc1ce7d';
import './directUpload.js?v=bdc1ce7d';
import './buttons.js?v=bdc1ce7d';
import './dropdown.js?v=bdc1ce7d';
import './combobox.js?v=bdc1ce7d';
import './modal.js?v=bdc1ce7d';
import './representation.js?v=bdc1ce7d';

/**
 * @testable false
 * @covered-by src/script/widgets/projectInfo.mjs::CreateProject
 * @covered-by src/script/widgets/projectInfo.mjs::ProjectInfo
 * @reason shared field construction is exercised through concrete project widgets
 */
class ProjectForm extends FormWidget {
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
