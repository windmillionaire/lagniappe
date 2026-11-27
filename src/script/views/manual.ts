import type { Dropdown } from "../elements/combobox/dropdown.ts";
import { ENDPOINTS } from "../shared/endpoints.ts";
import { request } from "../shared/request.ts";
import { withTransition } from "../shared/transitions.ts";
import ShellView from "./base/shell.ts";

interface ManualSection {
	key: string;
	name: string;
	icon: string;
	kind: string;
	metadata?: {
		title: string;
		description: string;
		robots: string;
		canonical_url: string;
		path: string;
	};
}

export default class Manual extends ShellView {
	declare endpoints: typeof ENDPOINTS.manual;
	declare sections: Map<string, ManualSection>;
	declare mobileDropdown?: Dropdown | null;
	declare _mobileDropdownPromise?: Promise<Dropdown | null> | null;
	declare _manualClick?: (event: MouseEvent) => void;
	declare _onPopState?: (event: PopStateEvent) => void;
	declare _manualMobileResize?: EventListener;
	declare loading?: boolean;

	async init() {
		await super.init();
		this.endpoints = ENDPOINTS.manual;

		if (!this.elt) return;
		const sectionData =
			this.elt.querySelector<HTMLButtonElement>("#manual-nav-button")?.dataset
				?.sections;
		const sections: ManualSection[] = JSON.parse(sectionData || "[]");
		this.sections = new Map(sections.map((section) => [section.key, section]));

		this._manualClick = (e) => {
			const target = e.target as Element | null;
			const mobileNavButton = target?.closest?.("#manual-nav-button");
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

			const button = target?.closest?.<HTMLButtonElement>("[data-section]");
			if (button?.dataset.section) {
				e.preventDefault();
				this.fetchSection(button.dataset.section, true);
			}
		};
		this.elt.addEventListener("click", this._manualClick);

		this._onPopState = (e) => {
			const state: { manualSection?: string } | null = e.state;
			if (state?.manualSection) this.fetchSection(state.manualSection, false);
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

	_updateMetadata(key: string) {
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

	async _ensureMobileDropdown(): Promise<Dropdown | null> {
		if (this.mobileDropdown || this._mobileDropdownPromise) {
			return this.mobileDropdown ?? this._mobileDropdownPromise ?? null;
		}
		const mobileNavButton =
			this.elt.querySelector<HTMLButtonElement>("#manual-nav-button");
		if (!mobileNavButton) return null;

		this._mobileDropdownPromise = import("../elements/combobox/dropdown.ts")
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

	async fetchSection(key: string, pushState: boolean) {
		if (this.loading) return;
		this.loading = true;

		const response = await request.get(this.endpoints.section(key));
		if (response?.html) {
			const target = this.elt.querySelector("[data-role='manual-content']");
			const newTarget = response.html.querySelector("body");
			await withTransition(
				() => {
					if (newTarget) target?.replaceChildren(...newTarget.childNodes);
					this.elt
						.querySelectorAll<HTMLButtonElement>("[data-section]")
						.forEach((button) => {
							const active = button.dataset.section === key;
							button.dataset.active = active ? "true" : "false";
							if (active) button.setAttribute("aria-current", "page");
							else button.removeAttribute("aria-current");
						});
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
		if (this._manualClick)
			this.elt.removeEventListener("click", this._manualClick);
		if (this._manualMobileResize)
			this.elt.removeEventListener("mobile-resize", this._manualMobileResize);
		this._destroyMobileDropdown();
		super.destroy();
	}
}
