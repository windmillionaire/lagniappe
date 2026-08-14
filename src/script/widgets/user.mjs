import { FacetedSearchElement } from "../elements/facetedSearch";
import { FormElement } from "../elements/form";
import { InputElement } from "../elements/input";
import { PermissionsForm } from "../elements/permissions";
import { RadioElement } from "../elements/radio";

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_create_user_from_index
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_owner_create_adopts_public_user_and_resets_form
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_create_user_attached_to_existing_page_preserves_page_info_form
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_create_user_group_selector_accepts_multiple_groups
 * @features users
 * @dimensions create-form create-submit created-row attach-existing-page page-form-preserved create-form-reset submitted-form-data
 * @pairs users:group-selector users:multiple
 * @pairs users:create-form-reset users:submitted-form-data
 */
export class CreateUser extends FormElement {
	init() {
		this.messages = {
			submit: "Create User",
			submitting: "Creating",
			submitted: "User Created",
		};

		super.init();
	}

	get html() {
		const details = document.createElement("div");
		details.className = "flex flex-col gap-4 sm:flex-row";

		this.nameElement = new InputElement(this, {
			name: "name",
			required: true,
			type: "text",
			label: "Name",
		});
		this.nameElement.edit.classList.add("w-full", "sm:basis-1/2");
		details.appendChild(this.nameElement.edit);

		const email = new InputElement(this, {
			name: "email",
			required: true,
			input: "email",
			label: "Email",
		});
		email.edit.classList.add("w-full", "sm:basis-1/2");
		details.appendChild(email.edit);

		const page = new FacetedSearchElement(this, {
			name: "page",
			kind: "page",
			label: "Attach to Existing Page",
			placeholder: "select a page...",
			index: "page",
			creatable: true,
		});

		const group = new FacetedSearchElement(this, {
			name: "group",
			kind: "user",
			label: "User Group(s)",
			placeholder: "select user group(s)...",
			index: "group",
			multiple: true,
		});

		this.destroyables.push(page, group);

		const aiAccess =
			this.target.dataset.canEditAi === "true"
				? new RadioElement(
						this,
						{
							name: "ai_access",
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

		return [details, aiAccess, page.edit, group.edit].filter(Boolean);
	}

	async prereconcile() {
		await super.prereconcile();
		if (this._created) await this.prepareReset();
	}

	postreconcile() {
		const created = this._created;
		if (created) this.commitReset();
		super.postreconcile();

		if (created) {
			this.form?.resetSubmitButton();
		}
		this.nameElement.focus();
		this.target.dataset.visible = "true";
	}
}

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_general_permissions
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_entity_specific_permissions
 * @features user-groups
 * @dimensions group-create nav
 */
export class CreateUserGroup extends FormElement {
	constructor(attributes) {
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
			name: "name",
			required: true,
			type: "text",
			label: "Group Name",
		});

		return [name.edit];
	}

	get selectors() {
		return this.component.elt.querySelector("[data-role='group-selectors']");
	}

	async created(response) {
		this._newGroupSelector = response.html?.body.querySelector(
			"button[lp-show]:not([lp-control])",
		);

		this._newGroupForm = response.html?.body.querySelector("form");
		if (this._newGroupForm) {
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
			this.selectors.appendChild(this._newGroupSelector);
			this._newGroupSelector = null;
			this.component.nav = null;
		}
	}
}

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_public_permissions
 * @features public-groups permissions
 * @dimensions public active permission-update
 */
export class PublicPermissions extends PermissionsForm {
	init() {
		this.messages = {
			submit: "Update Public Permissions",
			submitting: "Updating Public Permissions",
			submitted: "Public Permissions Updated",
		};
		super.init();
	}
}

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_general_permissions
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_entity_specific_permissions
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_rename_group
 * @features user-groups
 * @dimensions permission-update general-permissions entity-permissions rename
 */
export class GroupPermissions extends PermissionsForm {
	constructor(attributes) {
		super(attributes);
		this._draftName = null;
		this.target.addEventListener("input", (event) => {
			if (event.target.matches("input[name='name']")) {
				this._draftName = event.target.value;
				this.target.dataset.name = event.target.value;
			}
		});
	}

	get formData() {
		const data = super.formData;
		if (this._draftName !== null) data.set("name", this._draftName);
		return data;
	}

	get html() {
		const name = new InputElement(
			this,
			{
				id: "name",
				name: "name",
				title: "Group Name",
				input: "text",
			},
			this.target.dataset.name || "",
		);

		return [name.edit, ...super.html];
	}

	init() {
		this.messages = {
			submit: "Update User Group",
			submitting: "Updating User Group",
			submitted: "User Group Updated",
		};
		super.init();
	}

	updated(response) {
		if (response.name) {
			if (
				this._draftName !== null &&
				response.name !== this._draftName.trim()
			) {
				return super.updated(response);
			}

			this._draftName = null;
			this.target.dataset.name = response.name;
			this.target.dataset.title = `${response.name} Permissions`;

			const selector = Array.from(
				this.component.elt.querySelectorAll(
					"[data-role='group-selectors'] button[data-key]",
				),
			).find((button) => button.dataset.key === this.key);
			const label = selector?.querySelector("[data-role='group-name']");
			if (label) label.textContent = response.name;
		}

		return super.updated(response);
	}
}

/**
 * @testable false
 * @covered-by lagniappe/core/properties/user_permissions.py::UserPermissions.create
 * @reason user permission persistence is owned by the backend property; this wrapper is not currently rendered by an E2E flow
 */
export class UserPermissions extends PermissionsForm {
	init() {
		this.messages = {
			submit: "Update User Permissions",
			submitting: "Updating User Permissions",
			submitted: "User Permissions Updated",
		};
		super.init();
	}
}
