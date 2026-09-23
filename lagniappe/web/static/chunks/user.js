/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=b6b75cd2';
import { B as BaseElement } from './baseElement.js?v=b6b75cd2';
import './foundation.js?v=b6b75cd2';
import { p as primitives } from './primitives.js?v=b6b75cd2';
import { F as FacetsBox } from './facets.js?v=b6b75cd2';
import { f as formatting } from './formatting.js?v=b6b75cd2';
import { InputElement } from './input.js?v=b6b75cd2';
import { RadioElement } from './radio.js?v=b6b75cd2';
import { F as FormWidget } from './formWidget.js?v=b6b75cd2';
import './icons.js?v=b6b75cd2';
import './upstreamUnavailable.js?v=b6b75cd2';
import './connectivity.js?v=b6b75cd2';
import './remote.js?v=b6b75cd2';
import './queryLifecycle.js?v=b6b75cd2';
import './combobox.js?v=b6b75cd2';
import './results.js?v=b6b75cd2';
import './storage.js?v=b6b75cd2';
import './submitter.js?v=b6b75cd2';
import './controller.js?v=b6b75cd2';
import './loader.js?v=b6b75cd2';
import './modal.js?v=b6b75cd2';
import './reviewBar.js?v=b6b75cd2';
import './representation.js?v=b6b75cd2';

/**
 * @testable infrastructure
 */
class FacetedSearchElement extends BaseElement {
	active(value) {
		return (
			this.combobox?.values.has(value) ??
			this.values.some((v) => v?.id === value || v === value)
		);
	}

	get values() {
		let submission = this.submission;
		if (typeof this.submission === "string") {
			submission = JSON.parse(this.submission);
			return Array.isArray(submission) ? submission : [submission];
		} else if (submission && typeof submission === "object") {
			return [submission];
		}
		return [];
	}

	get read() {
		if (this._read) return this._read;

		this._read = document.createElement("div");
		this._read.className = "flex flex-row flex-wrap gap-2";
		this._read.dataset.kind = this.renderer.kind;

		this.values.forEach((item) => {
			const container = this._read.appendChild(document.createElement("div"));
			container.className = STYLES.form.submission.default;
			container.appendChild(formatting.name(item));
			this._read.appendChild(container);
		});

		this._read.classList.add("group-data-[mode=edit]/element:hidden");
		return this._read;
	}

	get edit() {
		if (this._edit) return this._edit;

		this._edit = primitives.input({
			label: this.schema.title || this.schema.label,
			name: this.schema.id || this.schema.name,
			data: {
				placeholder: this.schema.placeholder || "search...",
				multiple: this.schema.multiple,
				kind: this.renderer.kind,
				index: this.schema.index,
				creatable: this.schema.creatable,
			},
		});
		this._edit.querySelector("input").setAttribute("lp-select", "");

		this.combobox = new FacetsBox(this._edit);

		this.values.forEach((value) => {
			this.combobox.addOption(value);
		});
		this.combobox.init();
		this.destroyables.push(this.combobox);

		this._edit
			.querySelector("[lp-select]")
			.classList.add("group-data-[mode=read]/element:hidden");

		return this._edit;
	}

	clear() {
		this.combobox?.clear();
		this.submission = null;
	}

	destroy() {
		this.combobox?.destroy();
	}
}

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_create_user_from_index
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_owner_create_adopts_public_user_and_resets_form
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_create_user_attached_to_existing_page_preserves_page_info_form
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_create_user_group_selector_accepts_multiple_groups
 * @tests tests_js/test_044_user_widget_frontend.mjs::test_create_user_focuses_on_open_and_reset_without_stealing_live_field_focus
 * @matrix users : create-form create-form-reset focus-preservation group-selector multiple submitted-form-data visibility-isolation
 * @pair users:page-form-preserved
 */
class CreateUser extends FormWidget {
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

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_general_permissions
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_entity_specific_permissions
 * @matrix user-groups : group-create nav
 */
class CreateUserGroup extends FormWidget {
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

export { CreateUser, CreateUserGroup };
