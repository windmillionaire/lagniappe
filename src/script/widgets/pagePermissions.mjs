import { FacetsBox } from "../elements/combobox";
import { FormElement } from "../elements/form";

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005d_page_permissions.py::test_owner_can_open_page_permissions_panel
 * @tests tests_e2e/005_pages/test_005e_page_access_restrictions.py::test_page_restrictions_save_drafts_and_show_each_source
 * @matrix pages : permission-gates permissions-panel access-restrictions explicit-submit group-restricted owner-restricted source-summary
 */
export class PagePermissions extends FormElement {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Save Restrictions",
			submitting: "Saving Restrictions",
			submitted: "Restrictions Saved",
		};
	}

	async _initForm(options) {
		await super._initForm(options);
		const restrictAccess = this.restrictAccess;
		if (!restrictAccess || this.readonly) return;

		const input = restrictAccess.querySelector(
			"[data-role='restrict-group-input']",
		);
		const select = new FacetsBox(input);
		await select.init();
		const addGroup = (event) => this._addGroup(event, select);
		const changeAdmin = (event) => {
			if (event.target.name !== "admin" || !event.target.checked) return;
			restrictAccess
				.querySelector("[data-role='restricted-group-list']")
				.replaceChildren();
			select.clear({ notify: false });
			this.markUnsavedState();
		};
		restrictAccess.addEventListener("updated", addGroup);
		restrictAccess.addEventListener("change", changeAdmin);
		this.destroyables.push(select, {
			destroy: () => {
				restrictAccess.removeEventListener("updated", addGroup);
				restrictAccess.removeEventListener("change", changeAdmin);
			},
		});
	}

	_click(event) {
		super._click(event);
		if (this.readonly) return;
		const button = event.target.closest("[data-role='remove-restriction']");
		if (!button) return;
		button.closest("li").remove();
		this.markUnsavedState();
	}

	_addGroup(event, select) {
		if (Object.keys(event.detail.options).length) {
			this.restrictAccess.querySelector("[name='admin']").checked = false;
		}
		const list = this.restrictAccess.querySelector(
			"[data-role='restricted-group-list']",
		);
		const template = this.restrictAccess.querySelector(
			"[data-role='restriction-template']",
		);
		const selected = new Set(
			Array.from(
				list.querySelectorAll("input[name='group-key']"),
				(input) => input.value,
			),
		);
		for (const [key, option] of Object.entries(event.detail.options)) {
			if (selected.has(key)) continue;
			const item = template.content.firstElementChild.cloneNode(true);
			item.querySelector("input[name='group-key']").value = key;
			item.querySelector("[data-role='group-name']").textContent = option.name;
			item.querySelector("button").dataset.key = key;
			list.append(item);
		}
		select.clear({ notify: false });
		this.markUnsavedState();
	}

	get formData() {
		const data = new FormData();
		const restrictions = this.restrictAccess;
		if (!restrictions) return data;
		data.set("restrictions", "true");
		const adminOnly = restrictions.querySelector("[name='admin']").checked;
		data.set("admin", adminOnly ? "true" : "false");
		if (adminOnly) return data;
		for (const input of restrictions.querySelectorAll(
			"input[name='group-key']",
		)) {
			data.append("group-key", input.value);
		}
		return data;
	}

	get visibleTo() {
		return this.target.querySelector("[data-role='visible-to']");
	}

	get restrictAccess() {
		return this.target.querySelector("[data-role='restrict-access']");
	}

	get html() {
		return [this.visibleTo, this.restrictAccess];
	}
}
