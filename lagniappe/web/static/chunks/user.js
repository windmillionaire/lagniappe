/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bd5baecd';
import { w as withTransition } from './foundation.js?v=bd5baecd';
import './connectivity.js?v=bd5baecd';
import { p as primitives } from './primitives.js?v=bd5baecd';
import { F as FacetsBox } from './facets.js?v=bd5baecd';
import { f as formatting } from './formatting.js?v=bd5baecd';
import { B as BaseElement } from './baseElement.js?v=bd5baecd';
import { F as FormElement } from './form2.js?v=bd5baecd';
import { InputElement } from './input.js?v=bd5baecd';
import { B as BaseForm } from './baseForm.js?v=bd5baecd';
import { RadioElement } from './radio.js?v=bd5baecd';
import './icons.js?v=bd5baecd';
import './combobox.js?v=bd5baecd';
import './results.js?v=bd5baecd';
import './submitter.js?v=bd5baecd';
import './loader.js?v=bd5baecd';

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

const SECTION_ORDER = [
	"public",
	"models",
	"forms",
	"users",
	"groups",
	"categories",
	"projects",
	"pages",
];

/**
 * @testable false
 * @covered-by src/script/elements/permissions.mjs::PermissionsForm
 * @reason permission-section container is private permissions form rendering
 */
const container = (name, config) => {
	const container = document.createElement("div");
	container.dataset.kind = config.kind || "default";
	container.className =
		"w-full rounded-md pt-2 pb-3 px-3 outline-1 bg-slate-100 outline-user-default";
	container.setAttribute("data-section", name);

	const header = container.appendChild(document.createElement("h3"));
	header.className = "text-lg font-bold text-base-dark mb-3";
	header.textContent = config.title;

	return container;
};

/**
 * @testable false
 * @covered-by src/script/elements/permissions.mjs::PermissionsForm
 * @reason permission-level row is private permissions form rendering
 */
const row = (config, entry = {}) => {
	// permission contains the current level, or use first available level as fallback
	const level = entry.level || config.levels?.[0];
	const setLevel = level === "RESTRICTED" ? "NONE" : level;

	const options = config.levels.map((level) => ({
		label: level,
		value: level,
		name: entry.id || entry.name,
		checked: setLevel === level,
	}));

	const permissionRow = document.createElement("fieldset");
	permissionRow.className = `${STYLES.radio.fieldset.row} min-w-0 flex-1 flex-wrap`;

	options.forEach((option) => {
		permissionRow.appendChild(primitives.radio(option));
	});

	return permissionRow;
};

/**
 * @testable false
 * @covered-by src/script/elements/permissions.mjs::PermissionsForm
 * @reason specific-permission row is private permissions form rendering
 */
const addSpecificPermission = (config, entry = {}) => {
	const permission = document.createElement("li");
	permission.className = "flex flex-row flex-wrap items-center gap-x-4 gap-y-2";
	permission.appendChild(
		primitives.checkbox({
			label: entry.label || entry.name,
			checked: true,
		}),
	);
	permission.appendChild(row(config, entry));
	return permission;
};

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_general_permissions
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_entity_specific_permissions
 * @tests tests_js/test_028_form_state_split.py::test_permissions_form_does_not_rebuild_for_visibility_only_reconciliation
 * @tests tests_js/test_028_form_state_split.py::test_permissions_form_serializes_overlapping_section_rebuilds
 * @tests tests_js/test_028_form_state_split.py::test_permissions_form_preserves_unsaved_values_during_background_update
 * @features user-groups
 * @dimensions permission-update general-permissions entity-permissions selection-render responsive-layout single-reconciliation unsaved-preservation background-update rebuild-serialization
 */
class PermissionsForm extends FormElement {
	constructor(attributes) {
		super(attributes);
		this.sections = new Map();
		this._rebuildSections = false;
		this._sectionReconcile = null;
		this._update = this._update.bind(this);
		this._change = this._change.bind(this);
		this.target.addEventListener("updated", this._update);
		this.target.addEventListener("change", this._change);
	}

	get html() {
		return [...this.sections.values()]
			.map((section) => section.container)
			.filter(Boolean);
	}

	async init() {
		if (this.html.length === 0) return;
		this.form = new BaseForm(this);
		await this.form.init();
		this.setVisibility();
		this.commitRevisionBaseline();
	}

	async updated(response) {
		// A polling/revision response may finish after the user has started
		// editing. The edit watcher owns presenting that conflict; rebuilding here
		// would silently replace the live controls before they can be submitted.
		if (this.unsavedState) return;
		if (this.target) this.target.inert = true;

		SECTION_ORDER.forEach((name) => {
			if (response.sections[name]) {
				this.sections.set(name, { config: response.sections[name] });
			}
		});

		this._rebuildSections = true;

		if (this.form) this._success = true;
	}

	async prereconcile() {
		if (this._sectionReconcile) return this._sectionReconcile;
		if (!this._rebuildSections) return;

		this._sectionReconcile = (async () => {
			// Drain updates which arrive during init before making the controls
			// interactive. This keeps a late authoritative response from replacing
			// the first user input on a newly activated form.
			while (this._rebuildSections) {
				this._rebuildSections = false;
				this.discardPreparedReset();
				const sections = new Map(
					Array.from(this.sections, ([name, section]) => [
						name,
						{ config: section.config },
					]),
				);
				await this.prepareReset({
					nextTarget: this.target.cloneNode(true),
					staged: { sections },
					beforeInit: (widget) => {
						widget.setSections();
					},
					afterInit: (widget) => {
						widget.setVisibility();
						widget.target.addEventListener("updated", widget._update);
						widget.target.addEventListener("change", widget._change);
					},
				});
			}
		})();

		try {
			await this._sectionReconcile;
		} finally {
			this._sectionReconcile = null;
			if (!this._preparedReset && this.target) this.target.inert = false;
		}
	}

	postreconcile() {
		if (!this._preparedReset) return;
		this.commitReset();
		if (this.target) this.target.inert = false;
		if (this._success) this.form.success();
		this._success = false;
	}

	_update(event) {
		const section = this.sections.get(event.detail.name);
		const newEntry = Object.values(event.detail.options)[0];
		if (!section || !newEntry?.id) return;

		void withTransition(
			() => {
				if (!section.list.querySelector(`[name="${newEntry.id}"]`)) {
					section.list.appendChild(
						addSpecificPermission(section.config, newEntry),
					);
				}
				section.select.clear();
			},
			{ label: "permissions:add-entry" },
		);
	}

	_change(event) {
		const sectionContainer = event.target.closest("[data-section]");
		if (!sectionContainer) return;
		void withTransition(
			() => {
				const section = sectionContainer.dataset.section;
				if (event.target.type === "checkbox" && !event.target.checked) {
					const permission = event.target.closest("li");
					permission.remove();
				}

				const changed = this.sections.get(section);
				if (["public"].includes(section)) {
					changed.set = event.target.value === "TRUE";
				} else if ("list" in this.sections.get(section)) {
					changed.set = this.sections.get(section).list.children.length > 0;
				} else if (section === "users") {
					changed.set = !["NONE", "VIEW"].includes(event.target.value);
				} else {
					changed.set = event.target.value !== "NONE";
				}

				this.setVisibility();
			},
			{ label: "permissions:change" },
		);
	}

	setSections() {
		this.sections.entries().forEach(([name, section]) => {
			const config = section.config;
			section.container = container(name, config);

			if (config.select) {
				const selectElt = section.container.appendChild(
					primitives.input(config.select),
				);

				section.list = section.container.appendChild(
					document.createElement("ul"),
				);
				section.list.className = "flex flex-col gap-2 empty:hidden gap-2 mt-4";
				config.permissions.forEach((perm) => {
					section.list.appendChild(addSpecificPermission(config, perm));
				});
				section.set = config.permissions.length > 0;

				section.select =
					name === "projects"
						? new FacetsBox(selectElt, { models: false })
						: new FacetsBox(selectElt);
				section.select.init();
				this.destroyables.push(section.select);
			} else {
				const entry = config.permission ?? { name: name };
				section.container.appendChild(row(config, entry));

				const level = config.permission?.level;
				if (["public"].includes(name)) {
					section.set = level === "TRUE";
				} else if (["forms", "models"].includes(name)) {
					section.set = level !== "NONE";
				} else if (name === "users") {
					section.set = !["NONE", "VIEW"].includes(level);
				}
			}
		});
	}

	setVisibility() {
		const publicNotAllowed = this.sections.get("public")?.set === false;
		const hasModelPermissions = this.sections.get("models")?.set === true;

		this.sections.forEach((section, name) => {
			if (publicNotAllowed && name !== "public") {
				section.container.dataset.visible = "false";
			} else if (
				hasModelPermissions &&
				["categories", "projects", "pages"].includes(name)
			) {
				section.container.dataset.visible = "false";
			} else if (name === "groups" && this.sections.get("users")?.set) {
				section.container.dataset.visible = "false";
			} else if (name === "users" && this.sections.get("groups")?.set) {
				section.container.dataset.visible = "false";
			} else {
				section.container.dataset.visible = "true";
			}
		});
	}
}

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_create_user_from_index
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_owner_create_adopts_public_user_and_resets_form
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_create_user_attached_to_existing_page_preserves_page_info_form
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_create_user_group_selector_accepts_multiple_groups
 * @tests tests_js/test_044_user_widget_frontend.py::test_create_user_focuses_on_open_and_reset_without_stealing_live_field_focus
 * @features users
 * @dimensions create-form create-submit created-row attach-existing-page page-form-preserved create-form-reset submitted-form-data focus-preservation
 * @pairs users:group-selector users:multiple
 * @pairs users:create-form-reset users:submitted-form-data
 */
class CreateUser extends FormElement {
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
class CreateUserGroup extends FormElement {
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
class PublicPermissions extends PermissionsForm {
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
class GroupPermissions extends PermissionsForm {
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
class UserPermissions extends PermissionsForm {
	init() {
		this.messages = {
			submit: "Update User Permissions",
			submitting: "Updating User Permissions",
			submitted: "User Permissions Updated",
		};
		super.init();
	}
}

export { CreateUser, CreateUserGroup, GroupPermissions, PublicPermissions, UserPermissions };
