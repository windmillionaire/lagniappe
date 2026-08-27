/*! Third-party licenses: /third-party-licenses.txt */
import { S as ShellView, E as ENDPOINTS, r as request, w as withTransition } from '../foundation.js?v=b687b680';
import '../connectivity.js?v=b687b680';

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_manual_ajax_section_navigation_and_popstate
 * @tests tests_js/test_038_startup_specializations.py::test_manual_dropdown_loads_only_in_mobile_mode
 * @matrix manual : popstate responsive-navigation section-navigation
 * @pair startup:mobile-only-dropdown
 */
class Manual extends ShellView {
	async init() {
		await super.init();
		this.endpoints = ENDPOINTS.manual;

		if (!this.elt) return;

		this._manualClick = (e) => {
			const mobileNavButton = e.target.closest("#manual-nav-button");
			if (mobileNavButton && this.mobile && !this.mobileDropdown) {
				e.preventDefault();
				e.stopPropagation();
				void this.runColdAction(
					mobileNavButton,
					() => this._ensureMobileDropdown(),
					(dropdown) => dropdown?.showPanel?.(),
					mobileNavButton,
				);
				return;
			}

			const button = e.target.closest("[data-section]");
			if (button) {
				e.preventDefault();
				this.fetchSection(button.dataset.section, true);
			}
		};
		this.elt.addEventListener("click", this._manualClick);

		this._onPopState = (e) => {
			if (e.state?.manualSection) {
				this.fetchSection(e.state.manualSection, false);
			}
		};
		window.addEventListener("popstate", this._onPopState);

		this._manualMobileResize = () => {
			if (this.mobile) void this._ensureMobileDropdown();
			else this._destroyMobileDropdown();
		};
		this.elt.addEventListener("mobile-resize", this._manualMobileResize);
		if (this.mobile) await this._ensureMobileDropdown();
		return this;
	}

	async _ensureMobileDropdown() {
		if (this.mobileDropdown || this._mobileDropdownPromise) {
			return this.mobileDropdown || this._mobileDropdownPromise;
		}
		const mobileNavButton = this.elt.querySelector("#manual-nav-button");
		if (!mobileNavButton) return null;

		this._mobileDropdownPromise = import('../dropdown.js?v=b687b680')
			.then(({ Dropdown }) => {
				if (this._destroyed || !this.mobile) return null;
				const sections = JSON.parse(mobileNavButton.dataset.sections);
				const menu = {
					items: sections.map((section) => ({
						name: section.name,
						icon: section.icon,
						kind: section.kind,
						onClick: () => this.fetchSection(section.key, true),
					})),
				};
				this.mobileDropdown = new Dropdown(mobileNavButton).init(menu);
				return this.mobileDropdown;
			})
			.catch((error) => {
				this.reportStartupError(error, mobileNavButton, "manual-dropdown");
				return null;
			})
			.finally(() => {
				this._mobileDropdownPromise = null;
			});
		return this._mobileDropdownPromise;
	}

	_destroyMobileDropdown() {
		this.mobileDropdown?.destroy?.();
		this.mobileDropdown = null;
	}

	initManual() {
		return { elt: this.elt };
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_manual_ajax_section_navigation_and_popstate
	 * @matrix manual : popstate section-navigation
	 */
	async fetchSection(key, pushState) {
		if (this.loading) return;
		this.loading = true;

		const response = await request.get(this.endpoints.section(key));
		if (response?.html) {
			const target = this.elt.querySelector("[data-role='manual-content']");
			const newTarget = response.html.querySelector("body");
			await withTransition(
				() => {
					if (newTarget) target.replaceChildren(newTarget);
					if (pushState) {
						const url = `/manual/${key}`;
						history.pushState({ manualSection: key }, "", url);
					}
				},
				{ label: "manual:change-section" },
			);
		}

		this.loading = false;
		window.scrollTo({ top: 0, behavior: "auto" });
	}

	destroy() {
		if (this._onPopState) {
			window.removeEventListener("popstate", this._onPopState);
		}
		this.elt.removeEventListener("click", this._manualClick);
		this.elt.removeEventListener("mobile-resize", this._manualMobileResize);
		this._destroyMobileDropdown();
		super.destroy();
	}
}

export { Manual as default };
