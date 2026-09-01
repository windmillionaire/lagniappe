/*! Third-party licenses: /third-party-licenses.txt */
import { b as buttons } from './buttons.js?v=b8995073';
import { r as request } from './foundation.js?v=b8995073';
import './connectivity.js?v=b8995073';
import { S as SelectBox } from './select2.js?v=b8995073';
import { S as SiteSetting } from './base.js?v=b8995073';
import './styles.js?v=b8995073';
import './icons.js?v=b8995073';
import './formatting.js?v=b8995073';
import './upstreamUnavailable.js?v=b8995073';
import './combobox.js?v=b8995073';
import './primitives.js?v=b8995073';
import './results.js?v=b8995073';
import './storage.js?v=b8995073';
import './submitter.js?v=b8995073';

const INSTANCE_CLASSES = {
	automatic: ["F1", "F2", "F4", "F4_1G"],
	basic: ["B1", "B2", "B4", "B4_1G", "B8"],
};
const DEFAULT_INSTANCE_CLASS = {
	automatic: "F2",
	basic: "B2",
};
const MEMORY_SAFE_WORKER_CLASSES = new Set(["F2", "B2"]);
const MEMORY_SAFE_WORKER_LIMIT = 3;

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008g_site_settings.py::test_site_settings_deployment_form_saves_and_updates_summary
 * @matrix admin : deployment-settings metadata scaling-controls
 */
class SiteDeployment extends SiteSetting {
	constructor(attributes) {
		super(attributes);
		this._deployment = null;
		this._saveDeployment = this._saveDeployment.bind(this);
	}

	init() {
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
				this._syncWorkerLimit();
			});
		this.deploymentForm
			.querySelector("[name='DEPLOY_INSTANCE_CLASS']")
			?.addEventListener("change", () => this._syncWorkerLimit());
		this._syncWorkerLimit();
	}

	updated(response) {
		this._deployment = response.deployment;
	}

	postreconcile() {
		if (this._deployment) this._renderDeployment(this._deployment);
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
		this._syncWorkerLimit();
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
		this.updateSummary(
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
				if (field.matches("select")) this.syncSelectBox(field, value);
			});
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
			this.syncSelectBox(instanceClass, instanceClass.value);
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

	/**
	 * @testable true
	 * @tests tests_js/test_019_form_sync_frontend.py::test_site_deployment_caps_workers_only_for_f2_and_b2
	 * @matrix admin : deployment-settings memory-pressure scaling-controls
	 */
	_syncWorkerLimit() {
		if (!this.deploymentForm) return;
		const instanceClass = this.deploymentForm.querySelector(
			"[name='DEPLOY_INSTANCE_CLASS']",
		)?.value;
		const workerInput = this.deploymentForm.querySelector(
			"[name='DEPLOY_WORKER_COUNT']",
		);
		if (!workerInput) return;

		const memoryLimited = MEMORY_SAFE_WORKER_CLASSES.has(instanceClass);
		workerInput.max = memoryLimited ? String(MEMORY_SAFE_WORKER_LIMIT) : "20";
		if (memoryLimited && Number(workerInput.value) > MEMORY_SAFE_WORKER_LIMIT) {
			workerInput.value = String(MEMORY_SAFE_WORKER_LIMIT);
		}
		const guidance = this.deploymentForm.querySelector(
			"[data-role='deployment-worker-guidance']",
		);
		if (guidance) {
			guidance.textContent = memoryLimited
				? `${instanceClass} supports at most three workers; each worker adds application memory use.`
				: "Workers multiply application memory use; monitor memory after increasing them.";
		}
	}

	_showDeploymentError(message) {
		const error = this.deploymentForm?.querySelector(
			"[data-role='deployment-error']",
		);
		if (!error) return;
		error.textContent = message || "";
		error.dataset.visible = message ? "true" : "false";
	}

	async _saveDeployment(event) {
		event.preventDefault();
		event.stopPropagation();

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
}

export { SiteDeployment };
