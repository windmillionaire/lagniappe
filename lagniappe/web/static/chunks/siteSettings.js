/*! Third-party licenses: /third-party-licenses.txt */
import { w as withTransition } from './foundation.js?v=bfd37afb';
import './connectivity.js?v=bfd37afb';
import './notificationState.js?v=bfd37afb';

const SECTION_STORAGE_KEY = "lagniappe:site-settings-section";
const DEFAULT_SECTION = "maintenance";
const SETTING_WIDGETS = {
	maintenance: "SiteMaintenance",
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
 * @tests tests_js/test_019_form_sync_frontend.py::test_site_settings_coordinates_section_widgets
 * @features admin
 * @dimensions site-settings sections composite-widgets persistence
 */
class SiteSettings {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.sections = new Map();
		this.settingWidgets = new Map();
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
		await this._setOpenSection(initialSection, { persist: false });
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

	_toggleSection(name) {
		const nextOpen = !this._isSectionOpen(name);
		return withTransition(() => {
			return this._setOpenSection(nextOpen ? name : null);
		});
	}

	async _setOpenSection(name, { persist = true } = {}) {
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

		await this.settingWidgets.get(name)?.opened?.();
	}

	_isSectionOpen(name) {
		return this.sections.get(name)?.dataset.open === "true";
	}

	destroy() {
		this.target.removeEventListener("click", this._click);
	}
}

export { SiteSettings };
