/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormElement } from './form2.js?v=b19dd33c';
import { InputElement } from './input.js?v=b19dd33c';
import { S as SectionToggle } from './sectionToggle.js?v=b19dd33c';
import { TextareaElement } from './textarea.js?v=b19dd33c';
import './baseForm.js?v=b19dd33c';
import './request.js?v=b19dd33c';
import './errors.js?v=b19dd33c';
import './connectivity.js?v=b19dd33c';
import './icons.js?v=b19dd33c';
import './styles.js?v=b19dd33c';
import './utilities.js?v=b19dd33c';
import './primitives.js?v=b19dd33c';
import './loader.js?v=b19dd33c';
import './baseElement.js?v=b19dd33c';
import './formatting.js?v=b19dd33c';
import './facets.js?v=b19dd33c';
import './endpoints.js?v=b19dd33c';
import './combobox.js?v=b19dd33c';
import './results.js?v=b19dd33c';
import './submitter.js?v=b19dd33c';
import './buttons.js?v=b19dd33c';
import './baseUpload.js?v=b19dd33c';
import './dropdown.js?v=b19dd33c';

const TASK_BUTTONS = {
	selectUser: "facet",
	selectForm: "facet",
	selectProject: "facet",
	selectCategory: "facet",
	schedule: "date",
	uploadFile: "upload",
};

/**
 * @testable infrastructure
 */
class BaseTaskSettings extends FormElement {
	constructor(attributes) {
		super(attributes);
		this.buttons = {};
		this._actions = null;
		this._formUpdatedListener = this._formUpdatedListener.bind(this);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_model_task
	 * @features tasks
	 * @dimensions create model-task-link attach-form
	 */
	_formUpdatedListener(e) {
		const project = e.detail.options
			? Object.values(e.detail.options)[0]
			: null;
		const formSelected = this.buttons.selectForm?.active;
		if (project?.form && !formSelected) {
			this.buttons.selectForm.addOption(project.form);
		} else if (e.detail.name === "form") {
			const options = Object.keys(e.detail.options);
			if (options.length === 0) return;

			const formKey = Object.keys(e.detail.options)[0];
			const existingForm = this.component.elt.querySelector(
				`[data-widget="TaskForm"]`,
			)?.dataset.formKey;
			if (!existingForm || existingForm === formKey) return;

			const form = this.component.widgets.TaskForm;
			form.destroy();
			delete this.component.widgets.TaskForm;
			this.component.elt.querySelector(`[data-widget="TaskForm"]`).remove();
			this.component.elt.querySelector('[lp-control="form"]').remove();
		}
	}

	get html() {
		return [this.nameElement, this.descriptionElement, this.actions];
	}

	get actions() {
		return this.target.querySelector("[data-role='action-buttons']");
	}

	async _initForm() {
		await super._initForm();
		await this._initActions();
	}

	/**
	 * @testable true
	 * @tests tests_js/test_032_task_settings_lifecycle.py::test_task_settings_awaits_action_controls_and_cleans_up
	 * @features tasks
	 * @dimensions action-control-lifecycle teardown
	 */
	async _initActions() {
		const actions = this.actions;
		if (!actions) return;

		const buttons = Array.from(actions.querySelectorAll("button[data-action]"));
		if (buttons.length === 0) return;

		this.buttons = {};

		for (const button of buttons) {
			const action = button.dataset.action;
			const factory = TASK_BUTTONS[action];
			const control =
				factory && SectionToggle[factory]
					? SectionToggle[factory](this, button)
					: null;
			if (!control) continue;

			await control.init();
			this.buttons[action] = control;
			this.destroyables.push(control);
		}

		actions.addEventListener("updated", this._formUpdatedListener);
		this._actions = actions;
	}

	get pageElement() {
		return this._facetElement('[data-role="page-select"]');
	}

	get nameElement() {
		const nameElement = new InputElement(
			{
				kind: "task",
				readonly: this.readonly,
			},
			{
				id: "name",
				title: "Name",
				input: "text",
				placeholder: "name this task...",
			},
			this.target.dataset.name,
		).elt;

		return nameElement;
	}

	get descriptionElement() {
		return new TextareaElement(
			{
				kind: "task",
				readonly: this.readonly,
			},
			{
				id: "description",
				title: "Description",
				input: "textarea",
				placeholder: "describe this task...",
			},
			this.target.dataset.description,
		).elt;
	}

	get formData() {
		const data = super.formData;
		["task-file", "mimetype"].forEach((name) => {
			data.delete(name);
		});
		return data;
	}

	_facetElement(selector) {
		const target = this.target.querySelector(selector);
		if (!target) return null;

		const control = SectionToggle.facet(this, target);
		control.init();
		this.destroyables.push(control);
		return control.elt;
	}

	destroy() {
		this._actions?.removeEventListener("updated", this._formUpdatedListener);
		this._actions = null;
		super.destroy();
		this.buttons = {};
	}
}

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_update_page_task_settings_from_row
 * @features tasks
 * @dimensions update settings-form
 */
class TaskSettings extends BaseTaskSettings {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Update Task",
			submitting: "Updating",
			submitted: "Task Updated",
		};
	}
}

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_completed_task_can_move_to_another_page
 * @features tasks
 * @dimensions move completed title-menu
 */
class TaskMove extends BaseTaskSettings {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Move Task",
			submitting: "Moving",
			submitted: "Task Moved",
		};
	}

	get html() {
		return [this.pageElement];
	}
}

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_task_form_filters_compatible_tasks
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_tasks_migrates_history_and_reconciles_task_delta
 * @pairs task-combine:lazy-form task-combine:checkbox-submit task-combine:delta
 */
class TaskCombine extends FormElement {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Combine Tasks",
			submitting: "Combining",
			submitted: "Tasks Combined",
		};
	}
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002d_home_tasks.py::test_create_task_form
 * @tests tests_e2e/002_home/test_002d_home_tasks.py::test_create_personal_task_due_today
 * @tests tests_e2e/002_home/test_002d_home_tasks.py::test_create_personal_task_due_in_four_days
 * @features tasks
 * @dimensions create-form create-personal due-date
 */
class CreateUserTask extends BaseTaskSettings {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Create Personal Task",
			submitting: "Creating",
			submitted: "Task Created",
		};
	}

	async postreconcile() {
		await super.postreconcile();
		if (this.target.dataset.visible === "true") {
			this.target.querySelector("input[name='name']")?.focus();
		}
	}

	async created() {
		await this.reset();
	}

	offline() {
		return {
			action: "create",
			kind: "task",
		};
	}
}

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_basic_page_task
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_while_another_task_is_open_keeps_rows_clear
 * @features tasks
 * @dimensions create basic while-open list-state
 */
class CreateTask extends BaseTaskSettings {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Create Task",
			submitting: "Creating",
			submitted: "Task Created",
		};

		if (this.component.widgets.PageTaskList?.itemCount === 0) {
			delete this.target.dataset.close;
		}
	}

	async postreconcile() {
		await super.postreconcile();
		if (this.target.dataset.visible === "true") {
			this.target.querySelector("input[name='name']").focus();
		}
	}

	async created() {
		await this.reset();
		if (this.component.widgets.PageTaskList?.itemCount > 0) {
			this.target.dataset.close = "tasks:PageTaskList";
		}
	}
}

export { BaseTaskSettings, CreateTask, CreateUserTask, TaskCombine, TaskMove, TaskSettings };
