import { buttons } from "../../elements/buttons.mjs";
import { STYLES } from "../../generated/styles.mjs";
import type { ENDPOINTS } from "../../shared/endpoints.ts";
import { Modal, request } from "../../shared/index.ts";
import { clearRecentSearchResults } from "../../shared/storage.ts";
import { withTransition } from "../../shared/transitions.ts";
import {
	type SiteActiveButton,
	SiteSetting,
	type SiteSettingAttributes,
} from "./base.ts";

type MaintenanceEndpoints = ReturnType<typeof ENDPOINTS.SiteMaintenance>;

interface RecordDetail {
	message: string;
	key?: string;
	url?: string;
	link_label?: string;
}

interface CacheStatus {
	processed: number;
	failed: number;
	errors?: RecordDetail[];
}

interface MigrationAttempt {
	status: string;
	totals?: Partial<Record<"changed" | "repaired" | "failed", number>>;
	repairs?: RecordDetail[];
	errors?: RecordDetail[];
}

interface Migration {
	id: string;
	label: string;
	state: string;
	source?: string | null;
	introduced_in?: string | null;
	completed_at?: string | null;
	completed_version?: string | null;
	completed_build_id?: string | null;
	audit_error?: string | null;
	attempts?: MigrationAttempt[];
}

interface MigrationStatus {
	status: string;
	current_version: string | null;
	cache_refresh_allowed: boolean;
	counts: Partial<
		Record<"pending" | "failed" | "interrupted" | "blocked", number>
	>;
	migrations: Migration[];
}

interface MigrationResponse {
	migration_status?: MigrationStatus | null;
}

interface CacheResponse extends MigrationResponse {
	cache_status?: CacheStatus | null;
}

export class SiteMaintenance extends SiteSetting<MaintenanceEndpoints> {
	declare _migrationStatus: MigrationStatus | null;
	declare _cacheStatus: CacheStatus | null;

	constructor(attributes: SiteSettingAttributes<MaintenanceEndpoints>) {
		super(attributes);
		this._migrationStatus = null;
		this._cacheStatus = null;
	}

	init() {
		this._initActions();
		this._initConfiguration();
	}

	updated(response: MigrationResponse) {
		this._migrationStatus = response.migration_status || null;
	}

	postreconcile() {
		this._renderMigrationStatus(this._migrationStatus);
		this._renderCacheStatus(this._cacheStatus);
	}

	_initActions() {
		const cacheButton = this.target.querySelector<HTMLButtonElement>(
			"[data-role='rebuild-cache']",
		);
		const updateButton = this.target.querySelector<HTMLButtonElement>(
			"[data-role='site-update']",
		);
		if (!cacheButton || !updateButton) return;

		const rebuildCache: SiteActiveButton = buttons.active({
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
			this._cacheStatus = null;
			this._renderCacheStatus(null);
			const response = await request.post<CacheResponse>(
				this.endpoints.rebuildCache,
			);
			if (response?.migration_status) {
				this._migrationStatus = response.migration_status;
			}
			if (!response?.ok) {
				await withTransition(
					() => {
						rebuildCache.deactivate("Refresh Cache");
						this._renderMigrationStatus(this._migrationStatus);
					},
					{ label: "site-settings:cache-error" },
				);
				return;
			}
			this._cacheStatus = response.cache_status || null;
			this._renderCacheStatus(this._cacheStatus);
			rebuildCache.deactivate(
				this._cacheStatus?.failed
					? "Cache Refreshed — Review Errors"
					: undefined,
			);
			clearRecentSearchResults();
		});

		const applyUpdates: SiteActiveButton = buttons.active({
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
			const response = await request.post<MigrationResponse>(
				this.endpoints.siteUpdate,
			);
			if (response?.migration_status) {
				this._migrationStatus = response.migration_status;
			}
			if (!response?.ok) {
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

	_renderCacheStatus(status: CacheStatus | null) {
		const panel = this.target.querySelector<HTMLElement>(
			"[data-role='cache-status']",
		);
		if (!panel) return;
		panel.dataset.visible = status ? "true" : "false";
		if (!status) return;
		const title = panel.querySelector("[data-role='cache-status-title']");
		const summary = panel.querySelector("[data-role='cache-status-summary']");
		const list = panel.querySelector("[data-role='cache-status-errors']");
		if (!title || !summary || !list) return;
		title.textContent = status.failed
			? "Cache refreshed with errors"
			: "Cache refreshed";
		const errors = status.errors || [];
		summary.textContent =
			`${status.processed} records processed; ${status.failed} skipped.` +
			(status.failed
				? " Skipped records could not be safely cached. Review them, then refresh again."
				: "") +
			(status.failed > errors.length
				? ` Showing ${errors.length} errors.`
				: "");
		list.replaceChildren();
		for (const error of errors) {
			const item = document.createElement("li");
			item.textContent = `${error.message} `;
			if (error.url) {
				const link = document.createElement("a");
				link.href = error.url;
				link.textContent = error.link_label || "Open record";
				link.className = STYLES.link.emphasized;
				item.appendChild(link);
			} else {
				item.textContent += error.key || "";
			}
			list.appendChild(item);
		}
	}

	_initConfiguration() {
		const configurationButton = this.target.querySelector<HTMLButtonElement>(
			"[data-role='configuration']",
		);
		if (!configurationButton) return;
		const configuration = buttons.active({
			existingButton: configurationButton,
			icon: "configuration",
			text: "Configuration",
			processingText: "Loading Configuration",
			completedText: "Configuration",
			completedIcon: "configuration",
		});
		configurationButton.addEventListener("click", async () => {
			configuration.activate();
			const modal = new Modal(this.view, configurationButton);
			try {
				await modal.load(this.endpoints.siteConfiguration);
			} finally {
				configuration.deactivate();
			}
		});
	}

	_renderMigrationStatus(status: MigrationStatus | null) {
		const panel = this.target.querySelector<HTMLElement>(
			"[data-role='migration-status']",
		);
		if (!panel) return;

		const title = panel.querySelector("[data-role='migration-status-title']");
		const summary = panel.querySelector(
			"[data-role='migration-status-summary']",
		);
		const results = panel.querySelector(
			"[data-role='migration-status-results']",
		);
		const errors = panel.querySelector<HTMLElement>(
			"[data-role='migration-status-errors']",
		);
		if (!title || !summary || !results || !errors) return;
		const updateButton = this.target.querySelector<HTMLButtonElement>(
			"[data-role='site-update']",
		);
		const cacheButton = this.target.querySelector<HTMLButtonElement>(
			"[data-role='rebuild-cache']",
		);

		results.replaceChildren();
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
		const visibleMigrations = (status?.migrations || []).filter(
			(migration) => migration.source !== "fresh-install",
		);
		const visibleCompleted = visibleMigrations.filter(
			(migration) => migration.state === "complete",
		).length;
		switch (state) {
			case "pending":
				title.textContent = "Site updates are ready";
				summary.textContent = `${version}${pendingCount} pending site ${pendingCount === 1 ? "update" : "updates"}.`;
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
				summary.textContent = visibleCompleted
					? `${version}${visibleCompleted} site ${visibleCompleted === 1 ? "update" : "updates"} completed.`
					: `${version}No site updates are required.`;
		}

		const appendDetail = (list: Element, detail: RecordDetail, label = "") => {
			const item = document.createElement("li");
			item.textContent = `${label ? `${label}: ` : ""}${detail.message}${detail.url ? " " : ""}`;
			if (detail.url) {
				const link = document.createElement("a");
				link.href = detail.url;
				link.textContent = detail.link_label || "Open record";
				link.className = STYLES.link.emphasized;
				item.appendChild(link);
			}
			list.appendChild(item);
		};

		const stateLabels: Record<string, string | undefined> = {
			complete: "Completed",
			pending: "Pending",
			running: "Running",
			failed: "Failed",
			interrupted: "Interrupted — retry available",
			blocked: "Blocked by an earlier update",
			"audit-error": "Audit error",
		};
		const releases = new Map<string, Migration[]>();
		for (const migration of visibleMigrations) {
			const release = migration.introduced_in || "Unknown";
			const migrations = releases.get(release);
			if (migrations) migrations.push(migration);
			else releases.set(release, [migration]);
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
					appendDetail(
						errors,
						{ message: migration.audit_error },
						`${migration.id} audit`,
					);
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
				const repairDetails =
					migration.id === "MSG-001" ? [] : detailAttempt?.repairs || [];
				if (repairDetails.length) {
					const notes = document.createElement("ul");
					notes.className = STYLES.siteSettings.migration.attemptList;
					for (const repair of repairDetails) {
						appendDetail(notes, repair, repair.url ? "" : repair.key);
					}
					migrationItem.appendChild(notes);
				}
				for (const failure of detailAttempt?.errors || []) {
					appendDetail(
						errors,
						failure,
						failure.url ? migration.id : `${migration.id} ${failure.key}`,
					);
				}
				migrationList.appendChild(migrationItem);
			}
			releaseDetails.appendChild(migrationList);
			releaseItem.appendChild(releaseDetails);
			results.appendChild(releaseItem);
		}
		errors.dataset.visible = errors.childElementCount ? "true" : "false";
	}
}
