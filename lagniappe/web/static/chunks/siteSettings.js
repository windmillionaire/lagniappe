/*! Third-party licenses: /third-party-licenses.txt */
import { r as request, w as withTransition } from './foundation.js?v=bb55a6e4';
import './connectivity.js?v=bb55a6e4';
import { b as buttons } from './buttons.js?v=bb55a6e4';
import { S as SiteSetting } from './base.js?v=bb55a6e4';
import './styles.js?v=bb55a6e4';
import './icons.js?v=bb55a6e4';
import './formatting.js?v=bb55a6e4';

const PUBLIC_PAGE_SETTINGS_ENDPOINT = "/l/site-settings/public-pages";

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_public_page_indexing_saves_live_setting
 * @matrix admin public-pages : live-settings sitemap-invalidation
 */
class SitePublicPages extends SiteSetting {
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

const SECTION_STORAGE_KEY = "lagniappe:site-settings-section";
const DEFAULT_SECTION = "maintenance";
const SETTING_WIDGETS = {
	maintenance: "SiteMaintenance",
	administrators: "SiteAdministrators",
	"installation-access": "SiteInstallationAccess",
	deployment: "SiteDeployment",
	"ai-models": "SiteAiModels",
	"service-providers": "SiteServiceProviders",
	"site-image": "SiteImage",
};

/**
 * Coordinates the shared site-settings section chrome while each section body
 * is owned by a focused persistent widget.
 *
 * @testable true
 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_sections_expand_help_and_configuration
 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_public_page_indexing_saves_live_setting
 * @tests tests_js/test_019_form_sync_frontend.py::test_site_settings_coordinates_section_widgets
 * @matrix admin : composite-widgets persistence sections site-settings
 * @matrix public-pages : live-settings
 */
class SiteSettings {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.sections = new Map();
		this.settingWidgets = new Map();
		this._sectionRequest = 0;
		this._click = this._click.bind(this);
	}

	async init() {
		this._collectSections();
		await this._loadSettingWidgets();
		this.target.addEventListener("click", this._click);

		const savedSection = localStorage.getItem(SECTION_STORAGE_KEY);
		const initialSection = this.sections.has(savedSection)
			? savedSection
			: DEFAULT_SECTION;
		await this.settingWidgets.get(initialSection)?.opened?.();
		this._setOpenSection(initialSection, { persist: false });
		this.target.setAttribute("initialized", "");
	}

	_collectSections() {
		this.target
			.querySelectorAll("[data-role='site-settings-section']")
			.forEach((section) => {
				const name = section.dataset.section;
				if (name) this.sections.set(name, section);
			});
	}

	async _loadSettingWidgets() {
		await Promise.all(
			Object.entries(SETTING_WIDGETS).map(async ([section, widgetName]) => {
				const widget = await this.component.loadWidget(widgetName);
				if (widget) this.settingWidgets.set(section, widget);
			}),
		);
		const target = this.sections
			.get("public-pages")
			?.querySelector("[data-widget='SitePublicPages']");
		if (target) {
			const widget = new SitePublicPages({ target, kind: "page" });
			await widget.init();
			this.settingWidgets.set("public-pages", widget);
		}
	}

	updated(response) {
		this.settingWidgets.forEach((widget) => {
			widget.updated?.(response);
			widget.modified = true;
		});
		this.modified = true;
	}

	// ViewComponent.load() reconciles a loaded inactive widget before activate()
	// assigns it as current. Child widgets do the actual response rendering.
	postreconcile() {}

	_click(event) {
		const section = event.target.closest("[data-role='site-settings-section']");
		if (!section || !this.target.contains(section)) return;

		const toggle = event.target.closest("[data-role='expand']");
		if (toggle) {
			event.preventDefault();
			event.stopPropagation();
			void this._toggleSection(section.dataset.section);
			return;
		}

		const header = event.target.closest("header");
		if (!header || !section.contains(header)) return;
		if (event.target.closest("button, a, input, select, textarea")) return;
		void this._toggleSection(section.dataset.section);
	}

	async _toggleSection(name) {
		const nextOpen = !this._isSectionOpen(name);
		const nextSection = nextOpen ? name : null;
		const request = ++this._sectionRequest;
		await this.settingWidgets.get(nextSection)?.opened?.();
		if (request !== this._sectionRequest) return;

		return withTransition(() => this._setOpenSection(nextSection), {
			label: "site-settings:toggle-section",
		});
	}

	_setOpenSection(name, { persist = true } = {}) {
		this.sections.forEach((section, sectionName) => {
			const open = sectionName === name;
			section.dataset.open = open ? "true" : "false";

			const body = section.querySelector("[data-role='section-body']");
			if (body) body.dataset.visible = open ? "true" : "false";

			const toggle = section.querySelector("[data-role='expand']");
			if (toggle) {
				toggle.dataset.open = open ? "true" : "false";
				toggle.setAttribute("aria-expanded", open ? "true" : "false");
				toggle.setAttribute("aria-label", open ? "Collapse" : "Expand");
				toggle.title = open ? "Collapse" : "Expand";
			}
		});

		if (persist) {
			if (name) {
				localStorage.setItem(SECTION_STORAGE_KEY, name);
			} else {
				localStorage.removeItem(SECTION_STORAGE_KEY);
			}
		}
	}

	_isSectionOpen(name) {
		return this.sections.get(name)?.dataset.open === "true";
	}

	destroy() {
		this.target.removeEventListener("click", this._click);
		this.settingWidgets.get("public-pages")?.destroy?.();
	}
}

export { SiteSettings };
