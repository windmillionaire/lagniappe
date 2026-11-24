import { InputElement } from "../elements/input.mjs";
import { SectionToggle } from "../elements/sectionToggle.mjs";
import { TextareaElement } from "../elements/textarea.mjs";
import { withTransition } from "../shared/transitions.ts";
import { FormWidget } from "./base/formWidget.ts";

const TASK_BUTTONS = {
	selectUser: "facet",
	selectForm: "facet",
	selectProject: "facet",
	selectCategory: "facet",
	schedule: "date",
	uploadFile: "upload",
};

export class BaseTaskSettings extends FormWidget {
	constructor(attributes) {
		super(attributes);
		this.buttons = {};
		this._actions = null;
		this._formUpdatedListener = this._formUpdatedListener.bind(this);
	}

	_formUpdatedListener(e) {
		const project = e.detail.options
			? Object.values(e.detail.options)[0]
			: null;
		const formControl = this.buttons.selectForm;
		if (
			e.detail.name === "project" &&
			project?.form &&
			formControl &&
			!formControl.readonly
		) {
			if (formControl.details?.id !== project.form.id) {
				formControl.clear();
				formControl.addOption(project.form);
			}
		} else if (e.detail.name === "form") {
			const options = Object.keys(e.detail.options);
			if (options.length === 0) return;

			const formKey = Object.keys(e.detail.options)[0];
			const existingForm = this.component.elt.querySelector(
				`[data-widget="TaskForm"]`,
			)?.dataset.formKey;
			if (!existingForm || existingForm === formKey) return;

			const form = this.component.widgets.TaskForm;
			void withTransition(
				() => {
					form.destroy();
					delete this.component.widgets.TaskForm;
					this.component.elt.querySelector(`[data-widget="TaskForm"]`).remove();
					this.component.elt.querySelector('[lp-control="form"]').remove();
				},
				{ label: "task-settings:replace-attached-form" },
			);
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

export class TaskSettings extends BaseTaskSettings {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Update Task",
			submitting: "Updating",
			submitted: "Task Updated",
		};
	}
}

export class TaskMove extends BaseTaskSettings {
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

export class TaskCombine extends FormWidget {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Combine Tasks",
			submitting: "Combining",
			submitted: "Tasks Combined",
		};
	}
}

export class CreateUserTask extends BaseTaskSettings {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Create Personal Task",
			submitting: "Creating",
			submitted: "Task Created",
		};
	}

	postreconcile() {
		if (this._resetAfterCreate) {
			this.commitReset();
			this._resetAfterCreate = false;
		}
		super.postreconcile();
		if (this.target.dataset.visible === "true") {
			this.target.querySelector("input[name='name']")?.focus();
		}
	}

	async created() {
		await this.prepareReset();
		this._resetAfterCreate = true;
	}

	offline() {
		return {
			action: "create",
			kind: "task",
		};
	}
}

export class CreateTask extends BaseTaskSettings {
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

	postreconcile() {
		if (this._resetAfterCreate) {
			this.commitReset();
			this._resetAfterCreate = false;
		}
		if (this._closeAfterCreate) {
			this.target.dataset.close = this._closeAfterCreate;
			this._closeAfterCreate = null;
		}
		super.postreconcile();
		if (this.target.dataset.visible === "true") {
			this.target.querySelector("input[name='name']").focus();
		}
	}

	async created() {
		await this.prepareReset();
		this._resetAfterCreate = true;
		if (this.component.widgets.PageTaskList?.itemCount > 0) {
			this._closeAfterCreate = "tasks:PageTaskList";
		}
	}
}
