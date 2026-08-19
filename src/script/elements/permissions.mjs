import { STYLES } from "styles";
import { withTransition } from "../shared";
import { BaseForm } from "./base/baseForm";
import { FacetsBox } from "./combobox";
import { FormElement } from "./form";
import { primitives } from "./primitives";

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
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_rename_group
 * @tests tests_js/test_028_form_state_split.py::test_permissions_form_does_not_rebuild_for_visibility_only_reconciliation
 * @tests tests_js/test_028_form_state_split.py::test_permissions_form_serializes_overlapping_section_rebuilds
 * @tests tests_js/test_028_form_state_split.py::test_permissions_form_preserves_unsaved_values_during_background_update
 * @features user-groups
 * @dimensions permission-update general-permissions entity-permissions selection-render responsive-layout single-reconciliation unsaved-preservation background-update rebuild-serialization
 */
export class PermissionsForm extends FormElement {
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
		this.initialized = true;
		this.target.setAttribute("initialized", "");
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
