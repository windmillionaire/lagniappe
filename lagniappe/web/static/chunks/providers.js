/*! Third-party licenses: /third-party-licenses.txt */
import { s as setIcon } from './icons.js?v=b55964c3';
import { S as SiteSetting } from './base.js?v=b55964c3';
import './styles.js?v=b55964c3';

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_sections_expand_help_and_configuration
 * @features admin
 * @dimensions service-providers external-links
 */
class SiteServiceProviders extends SiteSetting {
	updated(response) {
		this._links = response.service_providers;
	}

	postreconcile() {
		if (this._links) this._renderServiceProviders(this._links);
	}

	_renderServiceProviders(links) {
		const container = this.target.querySelector(
			"[data-role='service-providers']",
		);
		if (!container || !links?.length) return;

		const grid = document.createElement("div");
		grid.className = "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3";

		for (const link of links) {
			const card = document.createElement("a");
			card.href = link.url;
			card.target = "_blank";
			card.rel = "noopener noreferrer";
			card.className =
				"group/link flex flex-col gap-1 rounded-lg border border-base-light/50 bg-white px-4 py-3 shadow-sm hover:bg-base-bg transition-colors";

			const titleRow = document.createElement("div");
			titleRow.className = "flex flex-row items-center gap-1";

			const icon = document.createElement("span");
			setIcon(
				icon,
				link.icon,
				"text-base-dark text-lg group-hover/link:text-kind-default transition-colors text-sm",
			);

			const title = document.createElement("span");
			title.className =
				"text-sm font-semibold text-base-dark group-hover/link:text-kind-default transition-colors";
			title.textContent = link.title;

			const arrow = document.createElement("span");
			setIcon(arrow, "next", "icon-xs text-base-medium ml-auto");

			titleRow.append(icon, title, arrow);

			const description = document.createElement("span");
			description.className = "text-xs text-base-medium leading-snug";
			description.textContent = link.description;

			card.append(titleRow, description);
			grid.appendChild(card);
		}

		this.updateSummary(`${links.length} external links`);
		container.replaceChildren(grid);
	}
}

export { SiteServiceProviders };
