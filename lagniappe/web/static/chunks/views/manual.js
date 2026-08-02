/*! Third-party licenses: /third-party-licenses.txt */
import { E as ENDPOINTS } from '../endpoints.js?v=b55964c3';
import { r as request } from '../request.js?v=b55964c3';
import { S as ShellView } from '../shell.js?v=b55964c3';
import '../errors.js?v=b55964c3';
import '../connectivity.js?v=b55964c3';

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_manual_ajax_section_navigation_and_popstate
 * @features manual
 * @dimensions section-navigation popstate
 */
class Manual extends ShellView {
	async init() {
		await super.init();
		this.endpoints = ENDPOINTS.manual;
		this.copyResetTimers = new Map();

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

			const copyButton = e.target.closest("[data-role='manual-command-copy']");
			if (copyButton) {
				e.preventDefault();
				this.copyCommand(copyButton);
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

		this._mobileDropdownPromise = import('../dropdown.js?v=b55964c3')
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
	 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_manual_installation_commands_are_copyable_and_scroll_on_mobile
	 * @features manual
	 * @dimensions command-copy clipboard-fallback
	 */
	async copyCommand(button) {
		const command = button
			.closest("[data-role='manual-command-shell']")
			?.querySelector("[data-role='manual-command'] code")?.textContent;
		if (!command) return;

		let copied = false;
		try {
			if (navigator.clipboard?.writeText) {
				await navigator.clipboard.writeText(command);
				copied = true;
			}
		} catch {
			copied = false;
		}

		if (!copied) {
			const textarea = document.createElement("textarea");
			textarea.value = command;
			textarea.setAttribute("readonly", "");
			textarea.style.position = "fixed";
			textarea.style.opacity = "0";
			document.body.append(textarea);
			textarea.select();
			try {
				copied = document.execCommand("copy");
			} catch {
				copied = false;
			}
			textarea.remove();
			button.focus();
		}

		const resetTimer = this.copyResetTimers.get(button);
		if (resetTimer) clearTimeout(resetTimer);
		button.textContent = copied ? "Copied!" : "Copy failed";
		button.setAttribute(
			"aria-label",
			copied ? "Command copied" : "Command could not be copied",
		);
		this.copyResetTimers.set(
			button,
			setTimeout(() => {
				if (button.isConnected) {
					button.textContent = "Copy";
					button.setAttribute("aria-label", "Copy command");
				}
				this.copyResetTimers.delete(button);
			}, 2000),
		);
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
		for (const timer of this.copyResetTimers?.values() || []) {
			clearTimeout(timer);
		}
		this.copyResetTimers?.clear();
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
