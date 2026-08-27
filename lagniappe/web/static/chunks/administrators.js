/*! Third-party licenses: /third-party-licenses.txt */
import { r as request } from './foundation.js?v=b687b680';
import './connectivity.js?v=b687b680';
import { Modal } from './modal.js?v=b687b680';
import { F as FacetsBox } from './facets.js?v=b687b680';
import { S as SiteSetting } from './base.js?v=b687b680';
import './styles.js?v=b687b680';
import './remote.js?v=b687b680';
import './queryLifecycle.js?v=b687b680';
import './combobox.js?v=b687b680';
import './primitives.js?v=b687b680';
import './icons.js?v=b687b680';
import './results.js?v=b687b680';
import './storage.js?v=b687b680';
import './formatting.js?v=b687b680';
import './submitter.js?v=b687b680';

/**
 * Renders the primary Owner and additional-Administrator roster.
 *
 * @testable true
 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_administrator_roster_and_owner_controls
 * @matrix admin : confirmation-modal demotion failure-state promotion read-only responsive roster
 * @pair owner:role-controls
 */
class SiteAdministrators extends SiteSetting {
	constructor(attributes) {
		super(attributes);
		this._administrators = [];
		this._candidates = [];
		this._canManage = false;
		this._demotionModal = null;
		this._submit = this._submit.bind(this);
		this._click = this._click.bind(this);
	}

	init() {
		this.form = this.target.querySelector("[data-role='administrator-form']");
		this.list = this.target.querySelector("[data-role='administrator-list']");
		this.error = this.target.querySelector("[data-role='administrator-error']");
		this.selector = new FacetsBox(
			this.form.querySelector("input[name='user_key']"),
		);
		this.selector.init();
		this.form?.addEventListener("submit", this._submit);
		this.list?.addEventListener("click", this._click);
	}

	updated(response) {
		this._administrators = response.administrators || [];
		this._candidates = response.administrator_candidates || [];
		this._canManage = response.can_manage_administrators === true;
	}

	postreconcile() {
		this._render();
	}

	_render() {
		if (!this.list || !this.form) return;
		this.list.replaceChildren(
			...this._administrators.map((administrator) =>
				this._administratorRow(administrator),
			),
		);

		this.selector.clear({ notify: false });
		this.selector.updatePanel("");
		this.form.dataset.visible = this._canManage ? "true" : "false";
		this.form.querySelector("button").disabled = !this._candidates.length;
		this.updateSummary(
			`${this._administrators.length} ${this._administrators.length === 1 ? "administrator" : "administrators"}`,
		);
	}

	_administratorRow(administrator) {
		const item = document.createElement("li");
		item.dataset.role = "administrator";
		item.dataset.owner = administrator.is_owner ? "true" : "false";
		item.className =
			"flex flex-col gap-2 rounded-md border border-base-light/70 bg-white/80 p-3 sm:flex-row sm:items-center sm:justify-between";

		const details = document.createElement("div");
		const name = document.createElement("strong");
		name.className = "block text-sm text-base-dark";
		name.textContent = `${administrator.name}${administrator.is_owner ? " — Primary Owner" : ""}`;
		const email = document.createElement("span");
		email.className = "block text-xs text-base-medium";
		email.textContent = administrator.email;
		const status = document.createElement("span");
		status.className = "block text-xs text-base-medium";
		status.dataset.role = "administrator-last-login";
		status.textContent = administrator.awaiting_first_sign_in
			? "Awaiting first sign-in"
			: administrator.last_login
				? `Last signed in ${new Date(administrator.last_login).toLocaleString()}`
				: "Never signed in";
		details.append(name, email, status);
		item.append(details);

		if (this._canManage && !administrator.is_owner) {
			const button = document.createElement("button");
			button.type = "button";
			button.dataset.role = "demote-administrator";
			button.dataset.key = administrator.key;
			button.dataset.name = administrator.name;
			button.dataset.kind = "delete";
			button.className =
				"action-button shrink-0 rounded-md px-3 py-1.5 text-sm font-semibold";
			button.textContent = "Remove Administrator";
			item.append(button);
		}
		return item;
	}

	async _submit(event) {
		event.preventDefault();
		const select = this.form.querySelector("select[name='user_key']");
		if (!select.value) return;
		this._showError();
		const response = await request.post(this.endpoints.promote, {
			user_key: select.value,
		});
		if (!response.ok) return this._showError(response.error);
		this.updated(response);
		this._render();
	}

	async _click(event) {
		const button = event.target.closest("[data-role='demote-administrator']");
		if (!button || !this.list.contains(button)) return;
		this._showError();
		this._demotionModal?.destroy();
		const modal = new Modal(this.view, button);
		this._demotionModal = modal;
		await modal.load(this.endpoints.demote(button.dataset.key));
		if (this._demotionModal !== modal || !modal.modal) return;

		const confirm = modal.modal.querySelector("[data-role='delete']");
		if (!confirm) return;
		let submitting = false;
		confirm.addEventListener("click", async () => {
			if (submitting) return;
			submitting = true;
			confirm.disabled = true;
			const spinner = confirm.querySelector("#spinner");
			if (spinner) spinner.dataset.visible = "true";

			const response = await request.delete(
				this.endpoints.demote(button.dataset.key),
			);
			if (!response.ok) {
				submitting = false;
				confirm.disabled = false;
				if (spinner) spinner.dataset.visible = "false";
				this._showError(response.error);
				return;
			}

			await modal.remove();
			if (this._demotionModal === modal) this._demotionModal = null;
			this.updated(response);
			this._render();
		});
	}

	_showError(message = "") {
		if (!this.error) return;
		this.error.textContent = message;
		this.error.dataset.visible = message ? "true" : "false";
	}

	destroy() {
		this._demotionModal?.destroy();
		this._demotionModal = null;
		this.form?.removeEventListener("submit", this._submit);
		this.list?.removeEventListener("click", this._click);
		this.selector?.destroy();
		super.destroy();
	}
}

export { SiteAdministrators };
