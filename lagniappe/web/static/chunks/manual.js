/*! Third-party licenses: /third-party-licenses.txt */
import { D as Dropdown } from './dropdown.js?v=bda9a134';
import { E as ENDPOINTS, r as request } from './shared.js?v=bda9a134';
import { C as Core } from './core.js?v=bda9a134';
import './combobox.js?v=bda9a134';
import './primitives.js?v=bda9a134';
import './entityMenu.js?v=bda9a134';
import './results2.js?v=bda9a134';
import './formatting.js?v=bda9a134';

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_manual_ajax_section_navigation_and_popstate
 * @features manual
 * @dimensions section-navigation popstate
 */
class Manual extends Core {
	async init() {
		await super.init();
		this.endpoints = ENDPOINTS.manual;
		this.copyResetTimers = new Map();

		if (!this.elt) return;

		this.elt.addEventListener("click", (e) => {
			const copyButton = e.target.closest(
				"[data-role='manual-command-copy']",
			);
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
		if (this.mobileDropdown?.destroy) {
			this.mobileDropdown.destroy();
		}
		super.destroy();
	}
}

export { Manual as default };
