/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bdc368f0';
import { b as buttons } from './buttons.js?v=bdc368f0';
import { r as request, w as withTransition, a as clearRecentSearchResults } from './foundation.js?v=bdc368f0';
import './connectivity.js?v=bdc368f0';
import { Modal } from './modal.js?v=bdc368f0';
import { S as SiteSetting } from './base.js?v=bdc368f0';
import './icons.js?v=bdc368f0';
import './formatting.js?v=bdc368f0';

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_sections_expand_help_and_configuration
 * @features admin
 * @dimensions configuration-modal
 */
class SiteMaintenance extends SiteSetting {
	constructor(attributes) {
		super(attributes);
		this._migrationStatus = null;
	}

	init() {
		this._initActions();
		this._initConfiguration();
	}

	updated(response) {
		this._migrationStatus = response.migration_status || null;
	}

	postreconcile() {
		this._renderMigrationStatus(this._migrationStatus);
	}

	_initActions() {
		const cacheButton = this.target.querySelector(
			"[data-role='rebuild-cache']",
		);
		const updateButton = this.target.querySelector("[data-role='site-update']");
		if (!cacheButton || !updateButton) return;

		const rebuildCache = buttons.active({
			existingButton: cacheButton,
			icon: "database",
			text: "Refresh Cache",
			processingText: "Refreshing Cache",
			completedText: "Cache Refreshed",
			processingIcon: "spinner",
			completedIcon: "check",
		});

		rebuildCache.element.addEventListener("click", async () => {
			rebuildCache.activate();
			const response = await request.post(this.endpoints.rebuildCache);
			if (response?.migration_status) {
				this._migrationStatus = response.migration_status;
			}
			if (!response.ok) {
				await withTransition(
					() => {
						rebuildCache.deactivate("Refresh Cache");
						this._renderMigrationStatus(this._migrationStatus);
					},
					{ label: "site-settings:cache-error" },
				);
				return;
			}
			rebuildCache.deactivate();
			clearRecentSearchResults();
		});

		const applyUpdates = buttons.active({
			existingButton: updateButton,
			icon: "installation",
			text: "Apply Updates",
			processingText: "Applying Site Updates",
			completedText: "Updates Applied",
			processingIcon: "spinner",
			completedIcon: "check",
		});

		applyUpdates.element.addEventListener("click", async () => {
			applyUpdates.activate();
			const response = await request.post(this.endpoints.siteUpdate);
			if (response?.migration_status) {
				this._migrationStatus = response.migration_status;
			}
			if (!response.ok) {
				await withTransition(
					() => {
						applyUpdates.deactivate("Apply Updates");
						this._renderMigrationStatus(this._migrationStatus);
					},
					{ label: "site-settings:update-error" },
				);
				return;
			}
			await withTransition(
				() => {
					applyUpdates.deactivate();
					this._renderMigrationStatus(this._migrationStatus);
				},
				{ label: "site-settings:update-complete" },
			);
			clearRecentSearchResults();
		});
	}

	_initConfiguration() {
		const configurationButton = this.target.querySelector(
			"[data-role='configuration']",
		);
		const configuration = configurationButton
			? buttons.active({
					existingButton: configurationButton,
					icon: "configuration",
					text: "Configuration",
					processingText: "Loading Configuration",
					completedText: "Configuration",
					completedIcon: "configuration",
				})
			: null;
		configurationButton?.addEventListener("click", async () => {
			configuration.activate();
			const modal = new Modal(this.view, configurationButton);
			try {
				await modal.load(this.endpoints.siteConfiguration);
			} finally {
				configuration.deactivate();
			}
		});
	}

	/**
	 * @testable true
	 * @tests tests_js/test_019_form_sync_frontend.py::test_site_settings_migration_status_uses_generic_release_states
	 * @features admin database-migrations
	 * @dimensions current pending running failed audit-error version-history repairs actionable-links cache-gate
	 */
	_renderMigrationStatus(status) {
		const panel = this.target.querySelector("[data-role='migration-status']");
		if (!panel) return;

		const title = panel.querySelector("[data-role='migration-status-title']");
		const summary = panel.querySelector(
			"[data-role='migration-status-summary']",
		);
		const results = panel.querySelector(
			"[data-role='migration-status-results']",
		);
		const repairs = panel.querySelector(
			"[data-role='migration-status-repairs']",
		);
		const errors = panel.querySelector("[data-role='migration-status-errors']");
		const updateButton = this.target.querySelector("[data-role='site-update']");
		const cacheButton = this.target.querySelector(
			"[data-role='rebuild-cache']",
		);

		results.replaceChildren();
		repairs?.replaceChildren();
		errors.replaceChildren();
		panel.dataset.visible = "true";

		const state = status?.status || "current";
		const counts = status?.counts || {};
		const pendingCount =
			(counts.pending || 0) +
			(counts.failed || 0) +
			(counts.interrupted || 0) +
			(counts.blocked || 0);
		if (updateButton) {
			updateButton.disabled = !["pending", "failed"].includes(state);
			updateButton.title = pendingCount
				? `Apply ${pendingCount} pending site ${pendingCount === 1 ? "update" : "updates"}`
				: "All site updates are complete";
		}
		if (cacheButton) {
			cacheButton.disabled = !status?.cache_refresh_allowed;
			cacheButton.title = status?.cache_refresh_allowed
				? "Refresh cached and search data"
				: "Apply all site updates before refreshing the cache";
		}

		const version = status?.current_version
			? `Version ${status.current_version}. `
			: "";
		switch (state) {
			case "pending":
				title.textContent = "Site updates are ready";
				summary.textContent = `${version}${pendingCount} pending, ${counts.complete || 0} previously completed.`;
				break;
			case "running":
				title.textContent = "Site updates are running";
				summary.textContent = `${version}Another update request is currently working through the migration catalog.`;
				break;
			case "failed":
				title.textContent = "Site updates need attention";
				summary.textContent = `${version}Fix or retry the first incomplete update; later updates remain blocked.`;
				break;
			case "audit-error":
				title.textContent = "Site update history needs repair";
				summary.textContent = `${version}Stored migration identity or history does not match this build.`;
				break;
			default:
				title.textContent = "Site updates are current";
				summary.textContent = `${version}${counts.complete || 0} ${counts.complete === 1 ? "update" : "updates"} completed.`;
		}

		const appendDetail = (list, migrationId, detail) => {
			if (!list) return;
			const item = document.createElement("li");
			item.textContent = detail.url
				? `${migrationId}: ${detail.message} `
				: `${migrationId} ${detail.key}: ${detail.message}`;
			if (detail.url) {
				const link = document.createElement("a");
				link.href = detail.url;
				link.textContent = detail.link_label || "Open record";
				link.className = STYLES.link.emphasized;
				item.appendChild(link);
			}
			list.appendChild(item);
		};

		const stateLabels = {
			complete: "Completed",
			pending: "Pending",
			running: "Running",
			failed: "Failed",
			interrupted: "Interrupted — retry available",
			blocked: "Blocked by an earlier update",
			"audit-error": "Audit error",
		};
		const releases = new Map();
		for (const migration of status?.migrations || []) {
			const release = migration.introduced_in || "Unknown";
			if (!releases.has(release)) releases.set(release, []);
			releases.get(release).push(migration);
		}

		for (const [release, migrations] of releases) {
			const releaseItem = document.createElement("li");
			const releaseDetails = document.createElement("details");
			releaseDetails.open = migrations.some(
				(migration) => migration.state !== "complete",
			);
			const releaseSummary = document.createElement("summary");
			const completed = migrations.filter(
				(migration) => migration.state === "complete",
			).length;
			releaseSummary.textContent = `Version ${release} — ${completed}/${migrations.length} completed`;
			releaseSummary.className = STYLES.siteSettings.migration.releaseSummary;
			releaseDetails.appendChild(releaseSummary);
			const migrationList = document.createElement("ul");
			migrationList.className = STYLES.siteSettings.migration.migrationList;

			for (const migration of migrations) {
				const migrationItem = document.createElement("li");
				const attempts = migration.attempts || [];
				const attemptCount = attempts.length;
				const detailAttempt =
					migration.state === "complete"
						? [...attempts]
								.reverse()
								.find((attempt) => attempt.status === "complete")
						: attempts.at(-1);
				migrationItem.textContent = `${migration.id} — ${migration.label}: ${stateLabels[migration.state] || migration.state}`;
				if (migration.completed_at) {
					const completion = document.createElement("div");
					const completedVersion = migration.completed_version
						? `version ${migration.completed_version}`
						: "an earlier version";
					const completedBuild = migration.completed_build_id
						? `, build ${migration.completed_build_id}`
						: "";
					completion.textContent = `Completed on ${completedVersion}${completedBuild} · ${attemptCount} recorded ${attemptCount === 1 ? "attempt" : "attempts"}`;
					completion.className = STYLES.siteSettings.migration.completion;
					migrationItem.appendChild(completion);
				}
				if (migration.audit_error) {
					appendDetail(errors, migration.id, {
						key: "audit",
						message: migration.audit_error,
					});
				}
				if (attempts.length) {
					const history = document.createElement("ul");
					history.className = STYLES.siteSettings.migration.attemptList;
					for (const attempt of attempts) {
						const attemptItem = document.createElement("li");
						const totals = attempt.totals || {};
						attemptItem.textContent = `${attempt.status}: ${totals.changed || 0} changed, ${totals.repaired || 0} repaired, ${totals.failed || 0} failed`;
						history.appendChild(attemptItem);
					}
					migrationItem.appendChild(history);
				}
				for (const repair of detailAttempt?.repairs || []) {
					appendDetail(repairs, migration.id, repair);
				}
				for (const failure of detailAttempt?.errors || []) {
					appendDetail(errors, migration.id, failure);
				}
				migrationList.appendChild(migrationItem);
			}
			releaseDetails.appendChild(migrationList);
			releaseItem.appendChild(releaseDetails);
			results.appendChild(releaseItem);
		}
		if (repairs) {
			repairs.dataset.visible = repairs.childElementCount ? "true" : "false";
		}
		errors.dataset.visible = errors.childElementCount ? "true" : "false";
	}
}

export { SiteMaintenance };
