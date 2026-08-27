import { buttons } from "../../elements/buttons";
import { request } from "../../shared";
import { SiteSetting } from "./base";

const PUBLIC_PAGE_SETTINGS_ENDPOINT = "/l/site-settings/public-pages";

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_public_page_indexing_saves_live_setting
 * @matrix admin public-pages : live-settings sitemap-invalidation
 */
export class SitePublicPages extends SiteSetting {
	constructor(attributes) {
		super(attributes);
		this._settings = null;
		this._save = this._save.bind(this);
	}

	async init() {
		this.form = this.target.querySelector("[data-role='public-page-settings']");
		if (!this.form) return;
		this.button = buttons.active({
			existingButton: this.form.querySelector("button[type='submit']"),
			text: "Save Public Page Settings",
			processingText: "Saving Public Page Settings",
			completedText: "Public Page Settings Saved",
			processingIcon: "spinner",
			completedIcon: "check",
		});
		this.form.addEventListener("submit", this._save);
		const response = await request.get(PUBLIC_PAGE_SETTINGS_ENDPOINT);
		if (response.ok) {
			this._settings = response.public_pages;
			this._render(response.public_pages);
		} else {
			this._showError(response.error || "Unable to load public page settings.");
		}
	}

	updated(response) {
		if (response.public_pages) this._settings = response.public_pages;
	}

	postreconcile() {
		if (this._settings) this._render(this._settings);
	}

	_render(settings) {
		const enabled = settings.PUBLIC_PAGE_INDEXING === true;
		const field = this.form?.querySelector("[name='PUBLIC_PAGE_INDEXING']");
		if (field) field.checked = enabled;
		this.updateSummary(
			enabled ? "Search discovery is on" : "Search discovery is off",
		);
	}

	_showError(message) {
		const error = this.form?.querySelector("[data-role='public-pages-error']");
		if (!error) return;
		error.textContent = message || "";
		error.dataset.visible = message ? "true" : "false";
	}

	async _save(event) {
		event.preventDefault();
		event.stopPropagation();
		this._showError("");
		this.button.activate();
		const data = new FormData();
		data.set(
			"PUBLIC_PAGE_INDEXING",
			this.form.querySelector("[name='PUBLIC_PAGE_INDEXING']")?.checked
				? "true"
				: "false",
		);
		const response = await request.post(PUBLIC_PAGE_SETTINGS_ENDPOINT, data);
		if (!response.ok) {
			this._showError(response.error || "Unable to save public page settings.");
			this.button.deactivate("Save Public Page Settings");
			return;
		}
		this._settings = response.public_pages;
		this._render(response.public_pages);
		this.button.deactivate();
	}

	destroy() {
		this.form?.removeEventListener("submit", this._save);
		super.destroy();
	}
}
