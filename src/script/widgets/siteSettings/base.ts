import type { SelectBox } from "../../elements/combobox/index.ts";
import type { Modal } from "../../shared/index.ts";

export interface SiteSettingAttributes<Endpoints extends object = object> {
	target: HTMLElement;
	view?: ConstructorParameters<typeof Modal>[0];
	endpoints: Endpoints;
}

export type SiteSelectHost = HTMLElement & { _lp_combobox?: SelectBox };

export interface SiteActiveButton {
	element: HTMLButtonElement;
	activate(text?: string | null, kind?: string | null): void;
	deactivate(text?: string | null, kind?: string | null): void;
}

/**
 * Shared lifecycle and section helpers for site-settings child widgets.
 */
export class SiteSetting<Endpoints extends object = object> {
	declare target: HTMLElement;
	declare view: SiteSettingAttributes<Endpoints>["view"];
	declare endpoints: Endpoints;
	declare destroyables: { destroy?(): void }[];

	constructor(attributes: SiteSettingAttributes<Endpoints>) {
		Object.assign(this, attributes);
		this.destroyables = [];
	}

	updateSummary(text?: string | null) {
		const summary = this.target
			.closest("[data-role='site-settings-section']")
			?.querySelector("[data-role='section-summary']");
		if (summary) summary.textContent = text || "";
	}

	syncSelectBox(select: HTMLSelectElement, value?: string | null) {
		const combobox =
			select.closest<SiteSelectHost>("[lp-select]")?._lp_combobox;
		if (!combobox) return;

		combobox.values.clear();
		if (value) combobox.values.add(value);
		combobox.updateSelect(true);
	}

	destroy() {
		this.destroyables.forEach((destroyable) => {
			destroyable.destroy?.();
		});
		this.destroyables = [];
	}
}
