import { STYLES } from "styles";
import { BaseUpload } from "../elements/base/baseUpload";
import { buttons } from "../elements/buttons";
import { SelectBox } from "../elements/combobox";
import { UploadMenu, uploadElement } from "../elements/upload";
import {
	clearRecentSearchResults,
	Modal,
	request,
	withTransition,
} from "../shared";
import { setIcon } from "../shared/icons";

const SPLASH_PREFIX = "splash-";
const SECTION_STORAGE_KEY = "lagniappe:site-settings-section";
const DEFAULT_SECTION = "maintenance";
const INSTANCE_CLASSES = {
	automatic: ["F1", "F2", "F4", "F4_1G"],
	basic: ["B1", "B2", "B4", "B4_1G", "B8"],
};
const DEFAULT_INSTANCE_CLASS = {
	automatic: "F2",
	basic: "B2",
};

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_is_owner_only
 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_sections_expand_help_and_configuration
 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_deployment_form_saves_and_updates_summary
 * @tests tests_js/test_019_form_sync_frontend.py::test_site_settings_initializes_ai_selects_before_syncing_saved_values
 * @features admin
 * @dimensions site-settings owner-only sections deployment-settings
 */
export class SiteSettings {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.destroyables = [];
		this.sections = new Map();
		this._aiSettings = null;
		this._aiModelOptions = null;
		this._deployment = null;
		this._siteImage = null;
		this._serviceProviders = null;
		this._migrationStatus = null;
		this._aiSelectsInitialized = false;
		this._uploadInitialized = false;
		this._saveAiSettings = this._saveAiSettings.bind(this);
		this._saveDeployment = this._saveDeployment.bind(this);
		this._uploadImage = this._uploadImage.bind(this);
	}

	async init() {
		this._initSections();
		this._initActions();
		this._initConfiguration();
		this._initDeploymentForm();
		this._initAiForm();
		this.target.setAttribute("initialized", "");
	}

	updated(response) {
		this._aiSettings = response.ai_settings;
		this._aiModelOptions = response.ai_model_options;
		this._deployment = response.deployment;
		this._siteImage = response.site_image;
		this._serviceProviders = response.service_providers;
		this._migrationStatus = response.migration_status || null;
		this.modified = true;
	}

	async postreconcile() {
		if (this._aiSettings) {
			this._renderAiSettings(this._aiSettings, this._aiModelOptions);
		}
		if (this._deployment) {
			this._renderDeployment(this._deployment);
		}
		if (this._serviceProviders) {
			this._renderServiceProviders(this._serviceProviders);
		}
		if (this._siteImage) {
			this._renderSiteImage(this._siteImage);
		}
		this._renderMigrationStatus(this._migrationStatus);
		if (this._isSectionOpen("site-image")) {
			await this._ensureUploadInitialized();
		}
	}

	_initSections() {
		this.target
			.querySelectorAll("[data-role='site-settings-section']")
			.forEach((section) => {
				const name = section.dataset.section;
				if (!name) return;
				this.sections.set(name, section);

				const toggle = section.querySelector("[data-role='expand']");
				toggle?.addEventListener("click", (event) => {
					event.preventDefault();
					event.stopPropagation();
					this._toggleSection(name);
				});

				const header = section.querySelector("header");
				header?.addEventListener("click", (event) => {
					if (event.target.closest("button, a, input, select, textarea")) {
						return;
					}
					this._toggleSection(name);
				});
			});

		const savedSection = localStorage.getItem(SECTION_STORAGE_KEY);
		const initialSection = this.sections.has(savedSection)
			? savedSection
			: DEFAULT_SECTION;
		this._setOpenSection(initialSection, { persist: false });
	}

	_initActions() {
		const cacheButton = this.target.querySelector(
			"[data-role='rebuild-cache']",
		);
		const updateButton = this.target.querySelector("[data-role='site-update']");
		if (!cacheButton || !updateButton) return;

		const rebuildCache = buttons.active({
			existingButton: cacheButton,
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
				rebuildCache.deactivate("Refresh Cache");
				this._renderMigrationStatus(this._migrationStatus);
				return;
			}
			rebuildCache.deactivate();
			clearRecentSearchResults();
		});

		const applyUpdates = buttons.active({
			existingButton: updateButton,
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
				applyUpdates.deactivate("Apply Updates");
				this._renderMigrationStatus(this._migrationStatus);
				return;
			}
			applyUpdates.deactivate();
			this._renderMigrationStatus(this._migrationStatus);
			clearRecentSearchResults();
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

	_initConfiguration() {
		const configurationButton = this.target.querySelector(
			"[data-role='configuration']",
		);
		configurationButton?.addEventListener("click", async () => {
			const modal = new Modal(this.view, configurationButton);
			await modal.load(this.endpoints.siteConfiguration);
		});
	}

	_initAiForm() {
		this.aiForm = this.target.querySelector("[data-role='ai-settings']");
		if (!this.aiForm) return;

		this.aiButton = buttons.active({
			existingButton: this.aiForm.querySelector("button[type='submit']"),
			text: "Save AI Model Settings",
			processingText: "Saving AI Model Settings",
			completedText: "AI Model Settings Saved",
			processingIcon: "spinner",
			completedIcon: "check",
		});

		this.aiForm.addEventListener("submit", this._saveAiSettings);
	}

	_initDeploymentForm() {
		this.deploymentForm = this.target.querySelector(
			"[data-role='deployment-settings']",
		);
		if (!this.deploymentForm) return;

		this.deploymentButton = buttons.active({
			existingButton: this.deploymentForm.querySelector(
				"button[type='submit']",
			),
			text: "Save Deployment Settings",
			processingText: "Saving Deployment Settings",
			completedText: "Deployment Settings Saved",
			processingIcon: "spinner",
			completedIcon: "check",
		});

		this.deploymentForm.addEventListener("submit", this._saveDeployment);
		this.deploymentForm
			.querySelectorAll("[data-role='deployment-select']")
			.forEach((element) => {
				const select = new SelectBox(element);
				select.init();
				this.destroyables.push(select);
			});
		this.deploymentForm
			.querySelector("[name='DEPLOY_SCALING_TYPE']")
			?.addEventListener("change", () => {
				this._syncInstanceClassOptions();
				this._syncInstanceControls();
			});
	}

	_toggleSection(name) {
		const nextOpen = !this._isSectionOpen(name);
		withTransition(() => {
			this._setOpenSection(nextOpen ? name : null);
		});
	}

	_setOpenSection(name, { persist = true } = {}) {
		this.sections.forEach((section, sectionName) => {
			const open = sectionName === name;
			section.dataset.open = open ? "true" : "false";

			const body = section.querySelector("[data-role='section-body']");
			if (body) body.dataset.visible = open ? "true" : "false";

			const toggle = section.querySelector("[data-role='expand']");
			if (toggle) {
				toggle.dataset.open = open ? "true" : "false";
				toggle.setAttribute("aria-expanded", open ? "true" : "false");
				toggle.setAttribute("aria-label", open ? "Collapse" : "Expand");
				toggle.title = open ? "Collapse" : "Expand";
			}
		});

		if (persist) {
			if (name) {
				localStorage.setItem(SECTION_STORAGE_KEY, name);
			} else {
				localStorage.removeItem(SECTION_STORAGE_KEY);
			}
		}
		if (name === "site-image") {
			this._ensureUploadInitialized();
		}
	}

	_isSectionOpen(name) {
		return this.sections.get(name)?.dataset.open === "true";
	}

	_updateSectionSummary(name, text) {
		const summary = this.sections
			.get(name)
			?.querySelector("[data-role='section-summary']");
		if (summary) summary.textContent = text || "";
	}

	async _ensureUploadInitialized() {
		if (this._uploadInitialized) return;
		this._uploadInitialized = true;
		await this._initUpload();
	}

	async _initUpload() {
		const uploadForm = this.target.querySelector(
			"[data-role='upload-site-image']",
		);
		if (!uploadForm) return;

		const dropzone = uploadElement.dropzone({
			text: "Drop image here, click to upload, or tap to choose camera/files",
		});

		this.upload = new BaseUpload({
			target: uploadForm,
			dropzone: dropzone,
			submitButton: uploadForm.querySelector("button[type='submit']"),
			inputName: "site-image",
			uploadType: "image",
			menuOptions: ["paste", "remove"],
			messages: {
				submit: "Update Site Image",
				submitting: "Processing Image",
				submitted: "Image Processed",
			},
			html: [dropzone.element],
		});

		this.upload.uploadMenu = new UploadMenu(this.upload);
		await this.upload.init();
		this.destroyables.push(this.upload);

		uploadForm.addEventListener("submit", this._uploadImage);
	}

	_renderAiSettings(settings, modelOptions) {
		if (!this.aiForm || !settings) return;

		this._initAiSelectBoxes();
		this._populateAiModelSelect("AI_MODEL", modelOptions?.text || []);
		this._populateAiModelSelect("AI_UTILITY_MODEL", modelOptions?.text || []);
		this._populateAiModelSelect("AI_IMAGE_MODEL", modelOptions?.image || []);

		this._setAiField("AI_MODEL", settings.AI_MODEL);
		this._setAiField("AI_UTILITY_MODEL", settings.AI_UTILITY_MODEL);
		this._setAiField("AI_IMAGE_MODEL", settings.AI_IMAGE_MODEL);
		this._setAiField("AI_LOCATION", settings.AI_LOCATION || "global");

		const pricing = this.aiForm.querySelector("[data-role='ai-pricing-link']");
		if (pricing && modelOptions?.pricing_url)
			pricing.href = modelOptions.pricing_url;

		this._updateAiSummary(settings);
	}

	_populateAiModelSelect(name, options) {
		const select = this.aiForm?.querySelector(`[name='${name}']`);
		if (!select) return;

		select.replaceChildren();
		for (const option of options) {
			const element = document.createElement("option");
			element.value = option.id;
			element.textContent = option.label || option.id;
			element.dataset.details = JSON.stringify({
				description: option.description,
				kind: option.kind,
				source: option.source,
			});
			select.appendChild(element);
		}

		this._refreshSelectBox(select);
	}

	_initAiSelectBoxes() {
		if (this._aiSelectsInitialized) {
			this.aiForm
				?.querySelectorAll("[data-role='ai-select'] select")
				.forEach((select) => {
					this._refreshSelectBox(select);
				});
			return;
		}

		this._aiSelectsInitialized = true;
		this.aiForm
			.querySelectorAll("[data-role='ai-select']")
			.forEach((element) => {
				const select = new SelectBox(element);
				select.init();
				this.destroyables.push(select);
			});
	}

	_refreshSelectBox(select) {
		const combobox = select.closest("[lp-select]")?._lp_combobox;
		if (!combobox) return;

		const options = Array.from(select.querySelectorAll("option"));
		combobox.items = options.map((option) => ({
			id: option.value,
			name: option.textContent,
			kind: option.dataset.kind || "default",
			...JSON.parse(option.dataset.details || "{}"),
		}));
		combobox.updatePanel(combobox.results.create(combobox.items));
		this._syncSelectBox(select, select.value);
	}

	_setAiField(name, value) {
		const field = this.aiForm?.querySelector(`[name='${name}']`);
		if (!field) return;
		field.value = value || "";
		if (field.matches("select")) this._syncSelectBox(field, value);
	}

	_updateAiSummary(settings) {
		this._updateSectionSummary(
			"ai-models",
			`${settings.AI_MODEL} · utility ${settings.AI_UTILITY_MODEL} · image ${settings.AI_IMAGE_MODEL}`,
		);
	}

	_showAiError(message) {
		const error = this.aiForm?.querySelector("[data-role='ai-error']");
		if (!error) return;
		error.textContent = message || "";
		error.dataset.visible = message ? "true" : "false";
	}

	async _saveAiSettings(e) {
		e.preventDefault();
		e.stopPropagation();

		this._showAiError("");
		this.aiButton.activate();
		const response = await request.post(
			this.endpoints.setAiSettings,
			new FormData(this.aiForm),
		);
		if (!response.ok) {
			this._showAiError(response.error || "Unable to save AI model settings.");
			this.aiButton.deactivate("Save AI Model Settings");
			return;
		}

		this._aiSettings = response.ai_settings;
		this._aiModelOptions = response.ai_model_options;
		this._renderAiSettings(response.ai_settings, response.ai_model_options);
		this.aiButton.deactivate();
	}

	_renderDeployment(deployment) {
		if (!this.deploymentForm || !deployment) return;

		const data = this._normalizeDeployment(deployment);

		this._setDeploymentField("DEPLOY_SCALING_TYPE", data.scalingType);
		this._setDeploymentField("DEPLOY_WORKER_COUNT", data.workerCount);
		this._setDeploymentField("DEPLOY_INSTANCE_CLASS", data.instanceClass);
		this._setDeploymentField("DEPLOY_MAX_INSTANCES", data.maxInstances);
		this._setDeploymentField(
			"DEPLOY_MIN_IDLE_INSTANCES",
			data.minIdleInstances,
		);
		this._setDeploymentField("DEPLOY_IDLE_TIMEOUT", data.idleTimeout);

		this._syncInstanceClassOptions({ preserveCurrent: true });
		this._syncInstanceControls();
		this._updateDeploymentSummary(data);
	}

	_updateDeploymentSummary(deployment) {
		const scaling =
			deployment.scalingType === "automatic" ? "Automatic" : "Basic";
		const workers = Number(deployment.workerCount) === 1 ? "worker" : "workers";
		const maxInstances =
			Number(deployment.maxInstances) === 1 ? "max instance" : "max instances";
		const instanceText =
			deployment.scalingType === "automatic"
				? `${deployment.minIdleInstances} min idle · ${deployment.maxInstances} ${maxInstances}`
				: `${deployment.maxInstances} ${maxInstances}`;
		this._updateSectionSummary(
			"deployment",
			`${scaling} · ${deployment.workerCount} ${workers} · ${deployment.instanceClass} · ${instanceText}`,
		);
	}

	_normalizeDeployment(deployment) {
		const first = (...values) =>
			values.find(
				(value) => value !== undefined && value !== null && value !== "",
			);
		return {
			scalingType: first(deployment.DEPLOY_SCALING_TYPE, "basic"),
			workerCount: first(deployment.DEPLOY_WORKER_COUNT, 3),
			instanceClass: first(deployment.DEPLOY_INSTANCE_CLASS, "B2"),
			maxInstances: first(deployment.DEPLOY_MAX_INSTANCES, 1),
			minIdleInstances: first(deployment.DEPLOY_MIN_IDLE_INSTANCES, 1),
			idleTimeout: first(deployment.DEPLOY_IDLE_TIMEOUT, "15m"),
		};
	}

	_setDeploymentField(name, value) {
		this.deploymentForm
			.querySelectorAll(`[name='${name}']`)
			.forEach((field) => {
				field.value = value;
				if (field.matches("select")) this._syncSelectBox(field, value);
			});
	}

	_syncSelectBox(select, value) {
		const combobox = select.closest("[lp-select]")?._lp_combobox;
		if (!combobox) return;

		combobox.values.clear();
		if (value) combobox.values.add(value);
		combobox.updateSelect(true);
	}

	_syncInstanceClassOptions({ preserveCurrent = false } = {}) {
		if (!this.deploymentForm) return;
		const scaling = this.deploymentForm.querySelector(
			"[name='DEPLOY_SCALING_TYPE']",
		);
		const instanceClass = this.deploymentForm.querySelector(
			"[name='DEPLOY_INSTANCE_CLASS']",
		);
		const scalingType = scaling?.value || "basic";
		const allowed = INSTANCE_CLASSES[scalingType] || INSTANCE_CLASSES.basic;

		const options = Array.from(instanceClass.querySelectorAll("option"));
		options.forEach((option) => {
			const visible = allowed.includes(option.value);
			option.disabled = !visible;
			option.hidden = !visible;
		});

		const combobox = instanceClass.closest("[lp-select]")?._lp_combobox;
		if (combobox) {
			combobox.items = options
				.filter((option) => allowed.includes(option.value))
				.map((option) => ({
					id: option.value,
					name: option.textContent,
					kind: instanceClass.dataset.kind || "default",
					...JSON.parse(option.dataset.details || "{}"),
				}));
			combobox.updatePanel(combobox.results.create(combobox.items));
		}

		if (!preserveCurrent || !allowed.includes(instanceClass.value)) {
			this._setDeploymentField(
				"DEPLOY_INSTANCE_CLASS",
				DEFAULT_INSTANCE_CLASS[scalingType],
			);
		} else {
			this._syncSelectBox(instanceClass, instanceClass.value);
		}
	}

	_syncInstanceControls() {
		const scaling = this.deploymentForm.querySelector(
			"[name='DEPLOY_SCALING_TYPE']",
		);
		const automatic = scaling?.value === "automatic";
		const basicGroup = this.deploymentForm.querySelector(
			"[data-role='basic-instance-count']",
		);
		const automaticGroup = this.deploymentForm.querySelector(
			"[data-role='automatic-instance-counts']",
		);
		if (!basicGroup || !automaticGroup) return;

		basicGroup.dataset.visible = automatic ? "false" : "true";
		automaticGroup.dataset.visible = automatic ? "true" : "false";
		basicGroup.querySelectorAll("input").forEach((input) => {
			input.disabled = automatic;
		});
		automaticGroup.querySelectorAll("input").forEach((input) => {
			input.disabled = !automatic;
		});
	}

	_showDeploymentError(message) {
		const error = this.deploymentForm?.querySelector(
			"[data-role='deployment-error']",
		);
		if (!error) return;
		error.textContent = message || "";
		error.dataset.visible = message ? "true" : "false";
	}

	async _saveDeployment(e) {
		e.preventDefault();
		e.stopPropagation();

		this._showDeploymentError("");
		this.deploymentButton.activate();
		const response = await request.post(
			this.endpoints.setDeploymentSettings,
			new FormData(this.deploymentForm),
		);
		if (!response.ok) {
			this._showDeploymentError(response.error || "Unable to save deployment.");
			this.deploymentButton.deactivate("Save Deployment Settings");
			return;
		}

		this._deployment = response.deployment;
		this._renderDeployment(response.deployment);
		this.deploymentButton.deactivate();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_image_upload_generates_and_persists_site_images
	 * @features admin
	 * @dimensions site-image-upload public-preview
	 */
	async _uploadImage(e) {
		e.preventDefault();
		e.stopPropagation();

		const prepared = await this.upload.prepareSubmit({
			route: this.endpoints.setSiteImage,
		});
		if (!prepared) return;

		const response = await request.post(
			this.endpoints.setSiteImage,
			this.upload.formData,
		);
		if (!response.ok) {
			if (response.error) this.upload.showError(response.error);
			this.upload.form?.resetSubmitButton();
			return;
		}

		this.upload.form?.success();
		if (response.site_image) {
			this._siteImage = response.site_image;
			withTransition(() => {
				this._renderSiteImage(response.site_image);
			});
		}
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

		this._updateSectionSummary(
			"service-providers",
			`${links.length} external links`,
		);
		container.replaceChildren(grid);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_image_upload_generates_and_persists_site_images
	 * @features admin
	 * @dimensions generated-images public-preview metadata
	 */
	_renderSiteImage(imageData) {
		const container = this.target.querySelector("[data-role='site-image']");
		if (!container || !imageData) return;

		const entries = Object.entries(imageData).filter(
			([name]) => !name.startsWith(SPLASH_PREFIX),
		);

		const fragment = document.createDocumentFragment();

		// Show main image preview
		const previewUrl =
			imageData["apple-touch-icon.png"] || imageData["logo-192x192.png"];
		if (previewUrl) {
			const preview = document.createElement("img");
			preview.src = `${previewUrl}?v=${Date.now()}`;
			preview.alt = "Site image";
			preview.className = "size-20 rounded-lg object-contain";
			fragment.appendChild(preview);
		}

		// Show grid of generated file links
		if (entries.length > 0) {
			const grid = document.createElement("div");
			grid.className = "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2";

			for (const [filename, url] of entries) {
				const link = document.createElement("a");
				link.href = url;
				link.target = "_blank";
				link.rel = "noopener noreferrer";
				link.className =
					"flex flex-row items-center gap-2 rounded-md border border-base-light/50 bg-white px-3 py-2 text-sm hover:bg-base-bg transition-colors";

				const icon = document.createElement("span");
				setIcon(icon, "image", "icon-xs text-base-medium");

				const name = document.createElement("span");
				name.className = "text-base-dark font-medium truncate grow text-xs";
				name.textContent = filename;

				const arrow = document.createElement("span");
				setIcon(arrow, "next", "icon-xs text-base-medium");

				link.append(icon, name, arrow);
				grid.appendChild(link);
			}

			fragment.appendChild(grid);
		}

		this._updateSectionSummary(
			"site-image",
			`${entries.length} generated files`,
		);
		container.replaceChildren(fragment);
	}

	destroy() {
		this.destroyables.forEach((d) => {
			d.destroy?.();
		});
		this.destroyables = [];
	}
}
