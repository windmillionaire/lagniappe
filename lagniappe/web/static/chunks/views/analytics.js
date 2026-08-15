/*! Third-party licenses: /third-party-licenses.txt */
import { S as ShellView, w as withTransition, r as request } from '../foundation.js?v=b2884058';
import '../connectivity.js?v=b2884058';

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_analytics_dashboard_owner_filter_and_retention_clear
 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_ai_dashboard_diagnostics_and_clear_use_real_routes
 * @features analytics
 * @dimensions dashboard accordion retention-clear
 */
class Analytics extends ShellView {
	_click(event) {
		const retentionToggle = event.target.closest(
			"[data-role='analytics-retention-toggle']",
		);
		if (retentionToggle && this.elt.contains(retentionToggle)) {
			event.preventDefault();
			event.stopPropagation();
			this._toggleRetention(retentionToggle);
			return;
		}

		const clearButton = event.target.closest("[data-role='analytics-clear']");
		if (clearButton && this.elt.contains(clearButton)) {
			event.preventDefault();
			event.stopPropagation();
			this._clearRecords(clearButton);
			return;
		}

		const toggle = event.target.closest("[data-role='expand']");
		const group = toggle?.closest("[data-role='analytics-prefix']");
		if (group && this.elt.contains(group)) {
			event.preventDefault();
			event.stopPropagation();
			this._toggleGroup(group, toggle);
			return;
		}

		super._click(event);
	}

	async _toggleRetention(toggle) {
		const retention = toggle.closest("[data-role='analytics-retention']");
		const panel = retention?.querySelector(
			"[data-role='analytics-retention-panel']",
		);
		if (!panel) return;

		await withTransition(
			() => {
				const open = panel.dataset.visible !== "true";
				panel.dataset.visible = open ? "true" : "false";
				toggle.dataset.open = panel.dataset.visible;
				toggle.setAttribute("aria-expanded", open ? "true" : "false");
				if (retention) retention.dataset.open = panel.dataset.visible;
			},
			{ label: "analytics:toggle-retention" },
		);
	}

	async _toggleGroup(group, toggle) {
		const open = group.dataset.open !== "true";
		await withTransition(
			() => {
				group.dataset.open = open ? "true" : "false";
				toggle.dataset.open = group.dataset.open;
				toggle.setAttribute("aria-expanded", open ? "true" : "false");

				const target = group.querySelector("[data-role='analytics-events']");
				if (target) target.dataset.visible = group.dataset.open;
			},
			{ label: "analytics:toggle-group" },
		);

		if (open) this._loadGroup(group);
	}

	async _loadGroup(group) {
		if (group.dataset.loaded === "true") return;

		const target = group.querySelector("[data-role='analytics-events']");
		const route = group.dataset.route;
		if (!target || !route) return;

		group.dataset.loaded = "true";
		const response = await request.get(route);
		const html =
			response?.ok && response.html
				? response.html.body.innerHTML
				: '<div class="p-2 text-sm text-base-medium sm:px-6">Unable to load events.</div>';
		await withTransition(
			() => {
				target.innerHTML = html;
			},
			{ label: "analytics:load-group" },
		);
	}

	async _clearRecords(button) {
		if (button.disabled) return;

		const panel = button.closest("[data-role='analytics-retention-panel']");
		const dataset = panel?.dataset.dataset || "activity";
		const originalContent = button.innerHTML;
		button.disabled = true;
		button.setAttribute("aria-busy", "true");
		this._setRetentionStatus(panel, "Clearing records...");

		const response = await request.delete(button.dataset.route);
		if (!response?.ok) {
			button.disabled = false;
			button.removeAttribute("aria-busy");
			button.innerHTML = originalContent;
			this._setRetentionStatus(
				panel,
				response?.error || "Unable to clear analytics records.",
				"delete",
			);
			return;
		}

		const refreshedPanel = await this._refreshDashboard(dataset);
		const datasetLabel = dataset === "ai" ? "AI generation" : "analytics";
		this._setRetentionStatus(
			refreshedPanel,
			`Deleted ${response.deleted} ${datasetLabel} ${
				response.deleted === 1 ? "record" : "records"
			}.`,
			"success",
		);
	}

	_setRetentionStatus(panel, message, kind = "page") {
		const status = panel?.querySelector("[data-role='analytics-clear-status']");
		if (!status) return;

		status.dataset.kind = kind;
		status.dataset.visible = "true";
		status.textContent = message;
	}

	async _refreshDashboard(dataset) {
		const response = await request.get(
			`${window.location.pathname}${window.location.search}`,
		);
		const view = response?.html?.querySelector(
			"[lp-view][data-kind='analytics']",
		);
		if (!response?.ok || !view) return null;

		let panel = null;
		await withTransition(
			() => {
				this.elt.innerHTML = view.innerHTML;
				const retention = this.elt.querySelector(
					`[data-role='analytics-retention'][data-dataset='${dataset}']`,
				);
				panel = retention?.querySelector(
					"[data-role='analytics-retention-panel']",
				);
				const toggle = retention?.querySelector(
					"[data-role='analytics-retention-toggle']",
				);
				if (panel) panel.dataset.visible = "true";
				if (retention) retention.dataset.open = "true";
				if (toggle) {
					toggle.dataset.open = "true";
					toggle.setAttribute("aria-expanded", "true");
				}
			},
			{ label: "analytics:refresh-dashboard" },
		);
		return panel || null;
	}
}

export { Analytics as default };
