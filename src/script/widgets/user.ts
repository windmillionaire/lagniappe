import { FacetedSearchElement } from "../elements/facetedSearch.ts";
import { InputElement } from "../elements/input.ts";
import { RadioElement } from "../elements/radio.ts";
import type { RequestResult } from "../types/api";
import type ViewComponent from "../views/base/component.ts";
import { FormWidget, type FormWidgetSettings } from "./base/formWidget.ts";

export class CreateUser extends FormWidget {
	declare nameElement: InputElement;
	declare _focusNameAfterReconcile?: boolean;

	init() {
		this.messages = {
			submit: "Create User",
			submitting: "Creating",
			submitted: "User Created",
		};

		void super.init();
	}

	get html() {
		const details = document.createElement("div");
		details.className = "flex flex-col gap-4 sm:flex-row";

		this.nameElement = new InputElement(this, {
			id: "name",
			required: true,
			input: "text",
			label: "Name",
		});
		this.nameElement.edit.classList.add("w-full", "sm:basis-1/2");
		details.appendChild(this.nameElement.edit);

		const email = new InputElement(this, {
			id: "email",
			required: true,
			input: "email",
			label: "Email",
		});
		email.edit.classList.add("w-full", "sm:basis-1/2");
		details.appendChild(email.edit);

		const pageOptions = {
			id: "page",
			kind: "page",
			label: "Attach to Existing Page",
			placeholder: "select a page...",
			index: "page",
			creatable: true,
		};
		const page = new FacetedSearchElement(this, pageOptions);

		const groupOptions = {
			id: "group",
			kind: "user",
			label: "User Group(s)",
			placeholder: "select user group(s)...",
			index: "group",
			multiple: true,
		};
		const group = new FacetedSearchElement(this, groupOptions);

		this.destroyables.push(page, group);

		const aiAccess =
			this.target.dataset.canEditAi === "true"
				? new RadioElement(
						this,
						{
							id: "ai_access",
							label: "AI Access",
							required: true,
							layout: "row",
							options: [
								{ label: "None", value: "NONE" },
								{ label: "Ask", value: "ASK" },
								{ label: "Create", value: "CREATE" },
							],
						},
						"NONE",
					).edit
				: null;

		return [details, aiAccess, page.edit, group.edit];
	}

	async prereconcile() {
		this._focusNameAfterReconcile =
			this._created || this.target?.dataset.visible !== "true";
		await super.prereconcile();
		if (this._created) await this.prepareReset();
	}

	postreconcile() {
		const created = this._created;
		const focusName = this._focusNameAfterReconcile || created;
		this._focusNameAfterReconcile = false;
		if (created) this.commitReset();
		super.postreconcile();

		if (created) {
			this.form?.resetSubmitButton();
		}
		if (focusName && !this.target?.contains(document.activeElement)) {
			this.nameElement.focus();
		}
	}
}

export class CreateUserGroup extends FormWidget {
	declare component: ViewComponent | null | undefined;
	declare _newGroupSelector: HTMLButtonElement | null | undefined;
	declare _newGroupForm: HTMLFormElement | null | undefined;

	constructor(attributes: FormWidgetSettings) {
		super(attributes);
		this.messages = {
			submit: "Create User Group",
			submitting: "Creating",
			submitted: "User Group Created",
		};
		this._newGroupSelector = null;
		this._newGroupForm = null;
	}

	get html() {
		const name = new InputElement(this, {
			id: "name",
			required: true,
			input: "text",
			label: "Group Name",
		});

		return [name.edit];
	}

	get selectors() {
		return this.component?.elt.querySelector("[data-role='group-selectors']");
	}

	async created(response?: RequestResult) {
		const html = response?.html || null;
		this._newGroupSelector = html?.body.querySelector<HTMLButtonElement>(
			"button[lp-show]:not([lp-control])",
		);

		this._newGroupForm = html?.body.querySelector("form");
		if (this._newGroupForm && this.component) {
			this._newGroupForm.dataset.visible = "false";
			this.component.elt.appendChild(this._newGroupForm);
			const newGroupWidget = this._newGroupForm.dataset.widget;
			await this.component.activate(newGroupWidget);
		}
	}

	async prereconcile() {
		await super.prereconcile();
		if (this._newGroupSelector) await this.prepareReset();
	}

	postreconcile() {
		if (this._newGroupSelector) {
			this.commitReset();
			this.target.dataset.visible = "false";
			this.selectors?.appendChild(this._newGroupSelector);
			this._newGroupSelector = null;
			if (this.component) this.component.nav = null;
		}
	}
}
