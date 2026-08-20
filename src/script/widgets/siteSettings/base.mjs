/**
 * Shared lifecycle and section helpers for site-settings child widgets.
 *
 * @testable infrastructure
 * @covered-by src/script/widgets/siteSettings.mjs::SiteSettings
 */
export class SiteSetting {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.destroyables = [];
	}

	updateSummary(text) {
		const summary = this.target
			.closest("[data-role='site-settings-section']")
			?.querySelector("[data-role='section-summary']");
		if (summary) summary.textContent = text || "";
	}

	syncSelectBox(select, value) {
		const combobox = select.closest("[lp-select]")?._lp_combobox;
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
