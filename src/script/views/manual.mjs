import { Dropdown } from "../elements/combobox";
import { ENDPOINTS, request } from "../shared";
import Core from "./base/core";

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_manual_ajax_section_navigation_and_popstate
 * @features manual
 * @dimensions section-navigation popstate
 */
export default class Manual extends Core {
	async init() {
		await super.init();
		this.endpoints = ENDPOINTS.manual;

		if (!this.elt) return;

		this.elt.addEventListener("click", (e) => {
			const button = e.target.closest("[data-section]");
			if (button) {
				e.preventDefault();
				this.fetchSection(button.dataset.section, true);
			}
		});

		this._onPopState = (e) => {
			if (e.state?.manualSection) {
				this.fetchSection(e.state.manualSection, false);
			}
		};
		window.addEventListener("popstate", this._onPopState);

		const mobileNavButton = this.elt.querySelector("#manual-nav-button");
		if (mobileNavButton) {
			const sections = JSON.parse(mobileNavButton.dataset.sections);
			const menu = {
				items: sections.map((section) => ({
					name: section.name,
					icon: section.icon,
					kind: section.kind,
					onClick: () => {
						this.fetchSection(section.key, true);
					},
				})),
			};
			this.mobileDropdown = new Dropdown(mobileNavButton).init(menu);
		}
	}

	initManual() {
		return { elt: this.elt };
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_manual_ajax_section_navigation_and_popstate
	 * @features manual
	 * @dimensions section-navigation popstate
	 */
	async fetchSection(key, pushState) {
		if (this.loading) return;
		this.loading = true;

		const response = await request.get(this.endpoints.section(key));
		if (response?.html) {
			const target = this.elt.querySelector("[data-role='manual-content']");
			const newTarget = response.html.querySelector("body");
			if (newTarget) target.replaceChildren(newTarget);

			if (pushState) {
				const url = `/manual/${key}`;
				history.pushState({ manualSection: key }, "", url);
			}
		}

		this.loading = false;
		window.scrollTo({ top: 0 });
	}

	destroy() {
		if (this._onPopState) {
			window.removeEventListener("popstate", this._onPopState);
		}
		if (this.mobileDropdown?.destroy) {
			this.mobileDropdown.destroy();
		}
		super.destroy();
	}
}
