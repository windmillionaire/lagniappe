/*! Third-party licenses: /third-party-licenses.txt */
import { r as request } from './request.js?v=b3f50eb1';
import './connectivity.js?v=b3f50eb1';
import './utilities.js?v=b3f50eb1';
import { p as primitives } from './primitives.js?v=b3f50eb1';
import { F as FacetsBox } from './facets.js?v=b3f50eb1';
import { F as FormElement } from './form2.js?v=b3f50eb1';
import './errors.js?v=b3f50eb1';
import './styles.js?v=b3f50eb1';
import './icons.js?v=b3f50eb1';
import './endpoints.js?v=b3f50eb1';
import './combobox.js?v=b3f50eb1';
import './results.js?v=b3f50eb1';
import './formatting.js?v=b3f50eb1';
import './submitter.js?v=b3f50eb1';
import './baseForm.js?v=b3f50eb1';
import './loader.js?v=b3f50eb1';

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005d_page_permissions.py::test_owner_can_open_page_permissions_panel
 * @features pages
 * @dimensions permissions-panel permission-gates
 */
class PagePermissions extends FormElement {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Update Page Permissions",
			submitting: "Updating Page Permissions",
			submitted: "Page Permissions Updated",
		};
		this.restrictAccessSelect = null;

		this._input = this._input.bind(this);
		this._click = this._click.bind(this);
		this._addGroup = this._addGroup.bind(this);
	}

	async init() {
		await super.init();
		const restrictAccess = this.restrictAccess;

		if (restrictAccess) {
			const input = this.target.querySelector(
				"[data-role='restrict-group-input']",
			);
			this.restrictAccessSelect = new FacetsBox(input);
			this.restrictAccessSelect.init();

			if (!this.revisionPreview) {
				const response = await request.get(this.endpoints.viewAccess);
				this._replaceBadges(response.viewers);
			}
			restrictAccess.addEventListener("input", this._input);
			restrictAccess.addEventListener("updated", this._addGroup);
			restrictAccess.addEventListener("click", this._click);
		}
	}

	get revisionEntries() {
		const owner = this.target.querySelector("[name='owner']")?.checked
			? "true"
			: "false";
		const groups = Array.from(
			this.target.querySelectorAll(
				"[data-role='remove-restriction'][data-key]",
			),
			(button) => ["__revision-restricted-group", button.dataset.key],
		);
		return [["__revision-owner", owner], ...groups];
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005e_page_access_restrictions.py::test_owner_restricted_page_is_hidden_from_model_viewer
	 * @features pages
	 * @dimensions access-restrictions owner-restricted
	 */
	_input(event) {
		if (event.target.name === "owner") {
			const data = new FormData();
			data.set("owner", event.target.checked ? "add" : "remove");
			this._addRestriction(data);
		}
	}

	_click(event) {
		const button = event.target.closest("[data-role='remove-restriction']");
		if (!button) return;

		const data = new FormData();
		data.set("group", "remove");
		data.set("group-key", button.dataset.key);
		this._addRestriction(data);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005e_page_access_restrictions.py::test_group_restricted_page_opens_for_member_only
	 * @features pages
	 * @dimensions access-restrictions group-restricted
	 */
	_addGroup(event) {
		const data = new FormData();
		data.set("group", "add");
		Object.keys(event.detail.options).forEach((key) => {
			data.append("group-key", key);
		});
		this._addRestriction(data);
		this.restrictAccessSelect.clear();
	}

	async _addRestriction(data) {
		const route = this.endpoints.viewAccess;
		const response = await request.put(route, data);
		if (response.ok) {
			this._replaceBadges(response.viewers);
			this._replaceGroupList(response.group_list);
		}
	}

	_replaceBadges(badges) {
		if (!badges) return;

		const badgeContainer = this.badgeContainer;
		const newBadges = badges.map((badge) => primitives.badge(badge));
		badgeContainer.replaceChildren(...newBadges);
	}

	_replaceGroupList(newGroupList) {
		const groupList = this.target.querySelector(
			"[data-role='restricted-group-list']",
		);
		groupList.innerHTML = newGroupList;
	}

	get badgeContainer() {
		return this.target.querySelector("[data-role='badges']");
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

export { PagePermissions };
