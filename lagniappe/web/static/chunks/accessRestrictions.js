/*! Third-party licenses: /third-party-licenses.txt */
import { F as FacetsBox } from './facets.js?v=bf6747aa';
import './foundation.js?v=bf6747aa';
import './upstreamUnavailable.js?v=bf6747aa';
import './connectivity.js?v=bf6747aa';
import './remote.js?v=bf6747aa';
import './queryLifecycle.js?v=bf6747aa';
import './combobox.js?v=bf6747aa';
import './styles.js?v=bf6747aa';
import './primitives.js?v=bf6747aa';
import './icons.js?v=bf6747aa';
import './results.js?v=bf6747aa';
import './storage.js?v=bf6747aa';
import './formatting.js?v=bf6747aa';
import './submitter.js?v=bf6747aa';

/**
 * Local administrator/group choices shared by Page, User Settings and Builder.
 * @testable true
 * @tests tests_e2e/005_pages/test_005e_page_access_restrictions.py::test_page_restrictions_save_drafts_and_show_each_source
 * @tests tests_e2e/003_forms/test_003c_access_restrictions.py::test_form_admin_only_replaces_groups_until_explicitly_selected_again
 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_user_settings_submit_preserves_attached_form_and_categories
 * @matrix pages forms : access-restrictions explicit-submit group-restricted owner-restricted
 * @pair user-settings:restrictions
 */
class AccessRestrictions {
	constructor(root, { readonly = false, onChange = () => {} } = {}) {
		this.root = root;
		this.readonly = readonly;
		this.onChange = onChange;
		this.select = null;
		this._destroyed = false;
		this._updated = this._updated.bind(this);
		this._change = this._change.bind(this);
		this._click = this._click.bind(this);
	}

	async init() {
		if (this.readonly) return;
		this.select = new FacetsBox(
			this.root.querySelector("[data-role='restrict-group-input']"),
		);
		await this.select.init();
		if (this._destroyed) return;
		this.root.addEventListener("updated", this._updated);
		this.root.addEventListener("change", this._change);
		this.root.addEventListener("click", this._click);
	}

	get list() {
		return this.root.querySelector("[data-role='restricted-group-list']");
	}

	_updated(event) {
		if (event.target !== this.select.element) return;
		const options = Object.entries(event.detail.options);
		if (!options.length) return;
		const list = this.list;
		const template = this.root.querySelector(
			"[data-role='restriction-template']",
		);
		const selected = new Set(
			Array.from(
				list.querySelectorAll("[name='group-key']"),
				(input) => input.value,
			),
		);
		this.root.querySelector("[name='admin']").checked = false;
		for (const [key, option] of options) {
			if (selected.has(key)) continue;
			const item = template.content.firstElementChild.cloneNode(true);
			item.querySelector("[name='group-key']").value = key;
			item.querySelector("[data-role='group-name']").textContent = option.name;
			item.querySelector("button").dataset.key = key;
			list.append(item);
			selected.add(key);
		}
		this.select.clear({ notify: false });
		this.onChange();
	}

	_change(event) {
		if (event.target.name !== "admin" || !event.target.checked) return;
		this.list.replaceChildren();
		this.select.clear({ notify: false });
		this.onChange();
	}

	_click(event) {
		const button = event.target.closest("[data-role='remove-restriction']");
		if (!button || !this.root.contains(button)) return;
		event.preventDefault();
		button.closest("li").remove();
		this.onChange();
	}

	destroy() {
		if (this._destroyed) return;
		this._destroyed = true;
		this.root.removeEventListener("updated", this._updated);
		this.root.removeEventListener("change", this._change);
		this.root.removeEventListener("click", this._click);
		this.select?.destroy();
	}
}

export { AccessRestrictions as default };
