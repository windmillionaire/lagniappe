/*! Third-party licenses: /third-party-licenses.txt */
import { S as ShellView, E as ENDPOINTS, r as request, w as withTransition } from '../foundation.js?v=b881d5e5';
import '../connectivity.js?v=b881d5e5';

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_manual_ajax_section_navigation_and_popstate
 * @tests tests_e2e/002_home/test_002m_home_manual_discovery.py::test_public_manual_search_metadata_and_navigation
 * @tests tests_js/test_038_startup_specializations.py::test_manual_dropdown_loads_only_in_mobile_mode
 * @matrix manual : popstate responsive-navigation section-navigation
 * @pair startup:mobile-only-dropdown
 */
class Manual extends ShellView {
	async init() {
		await super.init();
		this.endpoints = ENDPOINTS.manual;

		if (!this.elt) return;
		const sectionData =
			this.elt.querySelector("#manual-nav-button")?.dataset?.sections;
		this.sections = new Map(
			JSON.parse(sectionData || "[]").map((section) => [section.key, section]),
		);

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

	/**
	 * @testable false
	 * @covered-by src/script/views/manual.mjs::Manual.fetchSection
	 * @reason head metadata changes are part of the tested manual navigation commit
	 */
	_updateMetadata(key) {
		const metadata = this.sections.get(key)?.metadata;
		if (!metadata) return null;

		document.title = metadata.title;
		const description = document.querySelector("meta[name='description']");
		const robots = document.querySelector("meta[name='robots']");
		const canonical = document.querySelector("link[rel='canonical']");
		description?.setAttribute("content", metadata.description);
		robots?.setAttribute("content", metadata.robots);
		canonical?.setAttribute("href", metadata.canonical_url);
		return metadata;
	}

	async _ensureMobileDropdown() {
		if (this.mobileDropdown || this._mobileDropdownPromise) {
			return this.mobileDropdown || this._mobileDropdownPromise;
		}
		const mobileNavButton = this.elt.querySelector("#manual-nav-button");
		if (!mobileNavButton) return null;

		this._mobileDropdownPromise = import('../dropdown.js?v=b881d5e5')
			.then(({ Dropdown }) => {
				if (this._destroyed || !this.mobile) return null;
				const menu = {
					items: Array.from(this.sections.values()).map((section) => ({
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
	 * @tests tests_e2e/002_home/test_002m_home_manual_discovery.py::test_public_manual_search_metadata_and_navigation
	 * @matrix manual : canonical-url metadata popstate section-navigation
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
					const metadata = this._updateMetadata(key);
					if (pushState) {
						const url = metadata?.path || `/manual/${key}`;
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
