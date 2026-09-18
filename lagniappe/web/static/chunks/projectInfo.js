/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=baf2edcb';
import { InputElement } from './input.js?v=baf2edcb';
import { s as sections } from './sections.js?v=baf2edcb';
import { TextareaElement } from './textarea.js?v=baf2edcb';
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
import './baseUpload.js?v=baf2edcb';
import './directUpload.js?v=baf2edcb';
import './buttons.js?v=baf2edcb';
import './dropdown.js?v=baf2edcb';
import './combobox.js?v=baf2edcb';

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
