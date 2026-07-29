import { FacetedSearchElement } from "../elements/facetedSearch";
import { FormElement } from "../elements/form";
import { InputElement } from "../elements/input";
import { PermissionsForm } from "../elements/permissions";

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_create_user_from_index
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_create_user_attached_to_existing_page_preserves_page_info_form
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_create_user_group_selector_accepts_multiple_groups
 * @features users
 * @dimensions create-form create-submit created-row attach-existing-page page-form-preserved
 * @pairs users:group-selector users:multiple
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

		return [details, page.edit, group.edit];
	}

	postreconcile() {
		const created = this._created;
		super.postreconcile();

		if (created) {
			this.nameElement.clear();
			this.success();
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
		if (this._newGroupSelector) {
			this.selectors.appendChild(this._newGroupSelector);
			this._newGroupSelector = null;
			this.component.nav = null;
		}

		this._newGroupForm = response.html?.body.querySelector("form");
		if (this._newGroupForm) {
			this.component.elt.appendChild(this._newGroupForm);
			const newGroupWidget = this._newGroupForm.dataset.widget;
			await this.component.activate(newGroupWidget);
		}
	}

	async postreconcile() {
		if (this._newGroupSelector) {
			await this.reset();
			this.target.dataset.visible = "false";
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
 * @features user-groups
 * @dimensions permission-update general-permissions entity-permissions
 */
export class GroupPermissions extends PermissionsForm {
	init() {
		this.messages = {
			submit: "Update Group Permissions",
			submitting: "Updating Group Permissions",
			submitted: "Group Permissions Updated",
		};
		super.init();
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
