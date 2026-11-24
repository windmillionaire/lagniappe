import { buttons } from "../../elements/buttons.ts";
import { request } from "../../shared/index.ts";
import { type SiteActiveButton, SiteSetting } from "./base.ts";

const PUBLIC_PAGE_SETTINGS_ENDPOINT = "/l/site-settings/public-pages";

type PublicPageSettings = { PUBLIC_PAGE_INDEXING: boolean };
type PublicPagesResponse = { public_pages?: PublicPageSettings };

export class SitePublicPages extends SiteSetting {
	declare _settings: PublicPageSettings | null;
	declare form?: HTMLFormElement | null;
	declare button?: SiteActiveButton;

	constructor(attributes: { target: HTMLElement; kind?: string }) {
		super({ ...attributes, endpoints: {} });
		this._settings = null;
		this._save = this._save.bind(this);
	}

	async init() {
		this.form = this.target.querySelector<HTMLFormElement>(
			"[data-role='public-page-settings']",
		);
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
		const response = await request.get<PublicPagesResponse>(
			PUBLIC_PAGE_SETTINGS_ENDPOINT,
		);
		if (response?.ok && response.public_pages) {
			this._settings = response.public_pages;
			this._render(response.public_pages);
		} else {
			this._showError(
				response?.error || "Unable to load public page settings.",
			);
		}
	}

	updated(response: PublicPagesResponse) {
		if (response.public_pages) this._settings = response.public_pages;
	}

	postreconcile() {
		if (this._settings) this._render(this._settings);
	}

	_render(settings: PublicPageSettings) {
		const enabled = settings.PUBLIC_PAGE_INDEXING === true;
		const field = this.form?.querySelector<HTMLInputElement>(
			"[name='PUBLIC_PAGE_INDEXING']",
		);
		if (field) field.checked = enabled;
		this.updateSummary(
			enabled ? "Search discovery is on" : "Search discovery is off",
		);
	}

	_showError(message: string) {
		const error = this.form?.querySelector<HTMLElement>(
			"[data-role='public-pages-error']",
		);
		if (!error) return;
		error.textContent = message || "";
		error.dataset.visible = message ? "true" : "false";
	}

	async _save(event: SubmitEvent) {
		event.preventDefault();
		event.stopPropagation();
		const { form, button } = this;
		if (!form || !button) return;
		this._showError("");
		button.activate();
		const data = new FormData();
		data.set(
			"PUBLIC_PAGE_INDEXING",
			form.querySelector<HTMLInputElement>("[name='PUBLIC_PAGE_INDEXING']")
				?.checked
				? "true"
				: "false",
		);
		const response = await request.post<PublicPagesResponse>(
			PUBLIC_PAGE_SETTINGS_ENDPOINT,
			data,
		);
		if (!response?.ok || !response.public_pages) {
			this._showError(
				response?.error || "Unable to save public page settings.",
			);
			button.deactivate("Save Public Page Settings");
			return;
		}
		this._settings = response.public_pages;
		this._render(response.public_pages);
		button.deactivate();
	}

	destroy() {
		this.form?.removeEventListener("submit", this._save);
		super.destroy();
	}
}
