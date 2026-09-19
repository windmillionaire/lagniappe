/*! Third-party licenses: /third-party-licenses.txt */
import { F as FacetsBox } from './facets.js?v=bdc1ce7d';
import { w as withTransition } from './foundation.js?v=bdc1ce7d';
import './remote.js?v=bdc1ce7d';
import './queryLifecycle.js?v=bdc1ce7d';
import './combobox.js?v=bdc1ce7d';
import './styles.js?v=bdc1ce7d';
import './primitives.js?v=bdc1ce7d';
import './icons.js?v=bdc1ce7d';
import './results.js?v=bdc1ce7d';
import './storage.js?v=bdc1ce7d';
import './formatting.js?v=bdc1ce7d';
import './submitter.js?v=bdc1ce7d';
import './upstreamUnavailable.js?v=bdc1ce7d';
import './connectivity.js?v=bdc1ce7d';

/**
 * Enhances server-rendered permission fields without owning a form lifecycle.
 * @testable true
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_general_permissions
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_entity_specific_permissions
 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_set_public_permissions
 * @matrix user-groups public-groups : general-permissions entity-permissions permission-update
 */
class PermissionSections {
	constructor(root, { readonly = false, onChange = () => {} } = {}) {
		this.root = root;
		this.readonly = readonly;
		this.onChange = onChange;
		this.selects = new Map();
		this._destroyed = false;
		this._updated = this._updated.bind(this);
		this._change = this._change.bind(this);
	}

	async init() {
		this.setVisibility();
		if (this.readonly) return;
		for (const section of this.root.querySelectorAll("[data-section]")) {
			const input = section.querySelector("[data-role='permission-picker']");
			if (!input) continue;
			const select = new FacetsBox(
				input,
				section.dataset.section === "projects" ? { models: false } : {},
			);
			this.selects.set(section, select);
			await select.init();
			if (this._destroyed) return;
		}
		this.root.addEventListener("updated", this._updated);
		this.root.addEventListener("change", this._change);
	}

	_updated(event) {
		const section = event.target.closest("[data-section]");
		const select = this.selects.get(section);
		const entry = Object.values(event.detail.options)[0];
		if (!select || event.target !== select.element || !entry?.id) return;
		void withTransition(
			() => {
				if (this._destroyed) return;
				const list = section.querySelector("[data-role='permission-list']");
				const exists = Array.from(
					list.querySelectorAll("input[type='radio']"),
				).some((input) => input.name === entry.id);
				if (!exists) {
					const item = section
						.querySelector("template")
						.content.firstElementChild.cloneNode(true);
					item.querySelector("[data-role='permission-name']").textContent =
						entry.label || entry.name;
					for (const input of item.querySelectorAll("input[type='radio']"))
						input.name = entry.id;
					list.append(item);
					this.onChange();
				}
				select.clear({ notify: false });
				this.setVisibility();
			},
			{ label: "permissions:add-entry" },
		);
	}

	_change(event) {
		if (!event.target.closest("[data-section]")) return;
		void withTransition(
			() => {
				if (this._destroyed) return;
				if (
					event.target.matches("[data-role='remove-permission']") &&
					!event.target.checked
				) {
					event.target.closest("li").remove();
					this.onChange();
				}
				this.setVisibility();
			},
			{ label: "permissions:change" },
		);
	}

	setVisibility() {
		const sections = new Map(
			Array.from(this.root.querySelectorAll("[data-section]"), (section) => [
				section.dataset.section,
				section,
			]),
		);
		const level = (name) =>
			sections.get(name)?.querySelector("input[type='radio']:checked")?.value;
		const publicOff = level("public") === "FALSE";
		const models = level("models") && level("models") !== "NONE";
		const users = level("users") && !["NONE", "VIEW"].includes(level("users"));
		const groups = !!sections
			.get("groups")
			?.querySelector("[data-role='permission-list'] li");
		for (const [name, section] of sections) {
			section.dataset.visible = String(
				!(
					(publicOff && name !== "public") ||
					(models && ["categories", "projects", "pages"].includes(name)) ||
					(name === "groups" && users) ||
					(name === "users" && groups)
				),
			);
		}
	}

	destroy() {
		if (this._destroyed) return;
		this._destroyed = true;
		this.root.removeEventListener("updated", this._updated);
		this.root.removeEventListener("change", this._change);
		for (const select of this.selects.values()) select.destroy();
		this.selects.clear();
	}
}

export { PermissionSections as default };
