import { buttons } from "../../elements/buttons.mjs";
import { SelectBox } from "../../elements/combobox/index.ts";
import type { ENDPOINTS } from "../../shared/endpoints.ts";
import { request } from "../../shared/index.ts";
import {
	type SiteActiveButton,
	type SiteSelectHost,
	SiteSetting,
	type SiteSettingAttributes,
} from "./base.ts";

const INSTANCE_CLASSES: Record<string, readonly string[] | undefined> & {
	basic: readonly string[];
} = {
	automatic: ["F1", "F2", "F4", "F4_1G"],
	basic: ["B1", "B2", "B4", "B4_1G", "B8"],
};
const DEFAULT_INSTANCE_CLASS: Record<string, string | undefined> = {
	automatic: "F2",
	basic: "B2",
};
const MEMORY_SAFE_WORKER_CLASSES = new Set(["F2", "B2"]);
const MEMORY_SAFE_WORKER_LIMIT = 3;

type DeploymentEndpoints = ReturnType<typeof ENDPOINTS.SiteDeployment>;

// Deployment controls also accept numeric defaults alongside count strings.
interface DeploymentSettings {
	DEPLOY_SCALING_TYPE?: string | null;
	DEPLOY_WORKER_COUNT?: string | number | null;
	DEPLOY_INSTANCE_CLASS?: string | null;
	DEPLOY_MAX_INSTANCES?: string | number | null;
	DEPLOY_MIN_IDLE_INSTANCES?: string | number | null;
	// The deployment endpoint passes this field through without normalizing it.
	DEPLOY_IDLE_TIMEOUT?: unknown;
}

interface DeploymentResponse {
	deployment?: DeploymentSettings | null;
}

interface DeploymentFields {
	scalingType: string;
	workerCount: string | number;
	instanceClass: string;
	maxInstances: string | number;
	minIdleInstances: string | number;
	idleTimeout: unknown;
}

export class SiteDeployment extends SiteSetting<DeploymentEndpoints> {
	declare _deployment: DeploymentResponse["deployment"];
	declare deploymentForm?: HTMLFormElement | null;
	declare deploymentButton?: SiteActiveButton;

	constructor(attributes: SiteSettingAttributes<DeploymentEndpoints>) {
		super(attributes);
		this._deployment = null;
		this._saveDeployment = this._saveDeployment.bind(this);
	}

	init() {
		this.deploymentForm = this.target.querySelector<HTMLFormElement>(
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
			.querySelectorAll<HTMLElement>("[data-role='deployment-select']")
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

	updated(response: DeploymentResponse) {
		this._deployment = response.deployment;
	}

	postreconcile() {
		if (this._deployment) this._renderDeployment(this._deployment);
	}

	_renderDeployment(deployment: DeploymentResponse["deployment"]) {
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
		this._setDeploymentField("DEPLOY_IDLE_TIMEOUT", String(data.idleTimeout));

		this._syncInstanceClassOptions({ preserveCurrent: true });
		this._syncInstanceControls();
		this._syncWorkerLimit();
		this._updateDeploymentSummary(data);
	}

	_updateDeploymentSummary(deployment: DeploymentFields) {
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

	_normalizeDeployment(deployment: DeploymentSettings): DeploymentFields {
		const first = <T>(value: T | null | undefined, fallback: T) =>
			value === undefined || value === null || value === "" ? fallback : value;
		return {
			scalingType: first(deployment.DEPLOY_SCALING_TYPE, "basic"),
			workerCount: first(deployment.DEPLOY_WORKER_COUNT, 3),
			instanceClass: first(deployment.DEPLOY_INSTANCE_CLASS, "B2"),
			maxInstances: first(deployment.DEPLOY_MAX_INSTANCES, 1),
			minIdleInstances: first(deployment.DEPLOY_MIN_IDLE_INSTANCES, 1),
			idleTimeout: first(deployment.DEPLOY_IDLE_TIMEOUT, "15m"),
		};
	}

	_setDeploymentField(
		name: keyof DeploymentSettings,
		value: string | number | undefined,
	) {
		this.deploymentForm
			?.querySelectorAll<HTMLInputElement | HTMLSelectElement>(
				`[name='${name}']`,
			)
			.forEach((field) => {
				field.value = String(value);
				if (field instanceof window.HTMLSelectElement) {
					this.syncSelectBox(field, value ? String(value) : undefined);
				}
			});
	}

	_syncInstanceClassOptions({ preserveCurrent = false } = {}) {
		if (!this.deploymentForm) return;
		const scaling = this.deploymentForm.querySelector<HTMLSelectElement>(
			"[name='DEPLOY_SCALING_TYPE']",
		);
		const instanceClass = this.deploymentForm.querySelector<HTMLSelectElement>(
			"[name='DEPLOY_INSTANCE_CLASS']",
		);
		if (!instanceClass) return;
		const scalingType = scaling?.value || "basic";
		const allowed = INSTANCE_CLASSES[scalingType] || INSTANCE_CLASSES.basic;

		const options = Array.from(instanceClass.querySelectorAll("option"));
		options.forEach((option) => {
			const visible = allowed.includes(option.value);
			option.disabled = !visible;
			option.hidden = !visible;
		});

		const combobox =
			instanceClass.closest<SiteSelectHost>("[lp-select]")?._lp_combobox;
		if (combobox) {
			combobox.items = options
				.filter((option) => allowed.includes(option.value))
				.map((option) => {
					const details: Record<string, unknown> = JSON.parse(
						option.dataset.details || "{}",
					);
					return {
						id: option.value,
						name: option.textContent,
						kind: instanceClass.dataset.kind || "default",
						...details,
					};
				});
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
		if (!this.deploymentForm) return;
		const scaling = this.deploymentForm.querySelector<HTMLSelectElement>(
			"[name='DEPLOY_SCALING_TYPE']",
		);
		const automatic = scaling?.value === "automatic";
		const basicGroup = this.deploymentForm.querySelector<HTMLElement>(
			"[data-role='basic-instance-count']",
		);
		const automaticGroup = this.deploymentForm.querySelector<HTMLElement>(
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

	_syncWorkerLimit() {
		if (!this.deploymentForm) return;
		const instanceClass = this.deploymentForm.querySelector<HTMLSelectElement>(
			"[name='DEPLOY_INSTANCE_CLASS']",
		)?.value;
		const workerInput = this.deploymentForm.querySelector<HTMLInputElement>(
			"[name='DEPLOY_WORKER_COUNT']",
		);
		if (!workerInput) return;

		const memoryLimited =
			instanceClass !== undefined &&
			MEMORY_SAFE_WORKER_CLASSES.has(instanceClass);
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

	_showDeploymentError(message: string) {
		const error = this.deploymentForm?.querySelector<HTMLElement>(
			"[data-role='deployment-error']",
		);
		if (!error) return;
		error.textContent = message || "";
		error.dataset.visible = message ? "true" : "false";
	}

	async _saveDeployment(event: SubmitEvent) {
		event.preventDefault();
		event.stopPropagation();
		if (!this.deploymentForm || !this.deploymentButton) return;

		this._showDeploymentError("");
		this.deploymentButton.activate();
		const response = await request.post<DeploymentResponse>(
			this.endpoints.setDeploymentSettings,
			new FormData(this.deploymentForm),
		);
		if (!response?.ok) {
			this._showDeploymentError(
				response?.error || "Unable to save deployment.",
			);
			this.deploymentButton.deactivate("Save Deployment Settings");
			return;
		}

		this._deployment = response.deployment;
		this._renderDeployment(response.deployment);
		this.deploymentButton.deactivate();
	}
}
