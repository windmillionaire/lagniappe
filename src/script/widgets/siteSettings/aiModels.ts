import { buttons } from "../../elements/buttons.mjs";
import { SelectBox } from "../../elements/combobox/index.ts";
import type { ENDPOINTS } from "../../shared/endpoints.ts";
import { request } from "../../shared/index.ts";
import { withTransition } from "../../shared/transitions.ts";
import {
	type SiteActiveButton,
	type SiteSelectHost,
	SiteSetting,
	type SiteSettingAttributes,
} from "./base.ts";

type AiEndpoints = ReturnType<typeof ENDPOINTS.SiteAiModels>;
type AiModelField = "AI_MODEL" | "AI_UTILITY_MODEL" | "AI_IMAGE_MODEL";

type AiSettings = Partial<Record<AiModelField | "AI_LOCATION", string>> & {
	AI_AUTO_EXECUTE?: boolean;
};

interface AiModelDetails {
	description?: string;
	kind?: string;
	source?: string;
}

interface AiModel extends AiModelDetails {
	id: string;
	label: string;
}

interface AiModelOptions {
	text?: AiModel[];
	image?: AiModel[];
	pricing_url?: string;
}

interface AiSettingsResponse {
	ai_settings?: AiSettings;
	ai_model_options?: AiModelOptions;
}

export class SiteAiModels extends SiteSetting<AiEndpoints> {
	declare _aiSettings: AiSettings | null | undefined;
	declare _aiModelOptions: AiModelOptions | null | undefined;
	declare _aiSelectsInitialized: boolean;
	declare aiForm: HTMLFormElement | null;
	declare aiButton?: SiteActiveButton;

	constructor(attributes: SiteSettingAttributes<AiEndpoints>) {
		super(attributes);
		this._aiSettings = null;
		this._aiModelOptions = null;
		this._aiSelectsInitialized = false;
		this._saveAiSettings = this._saveAiSettings.bind(this);
	}

	init() {
		this.aiForm = this.target.querySelector<HTMLFormElement>(
			"[data-role='ai-settings']",
		);
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

	updated(response: AiSettingsResponse) {
		this._aiSettings = response.ai_settings;
		this._aiModelOptions = response.ai_model_options;
	}

	postreconcile() {
		if (this._aiSettings) {
			this._renderAiSettings(this._aiSettings, this._aiModelOptions);
		}
	}

	_renderAiSettings(
		settings: AiSettings | null | undefined,
		modelOptions: AiModelOptions | null | undefined,
	) {
		if (!this.aiForm || !settings) return;

		this._initAiSelectBoxes();
		this._populateAiModelSelect("AI_MODEL", modelOptions?.text || []);
		this._populateAiModelSelect("AI_UTILITY_MODEL", modelOptions?.text || []);
		this._populateAiModelSelect("AI_IMAGE_MODEL", modelOptions?.image || []);

		this._setAiField("AI_MODEL", settings.AI_MODEL);
		this._setAiField("AI_UTILITY_MODEL", settings.AI_UTILITY_MODEL);
		this._setAiField("AI_IMAGE_MODEL", settings.AI_IMAGE_MODEL);
		this._setAiField("AI_LOCATION", settings.AI_LOCATION || "global");
		const autoExecute = this.aiForm.querySelector<HTMLInputElement>(
			"[name='AI_AUTO_EXECUTE']",
		);
		if (autoExecute) {
			autoExecute.checked = settings.AI_AUTO_EXECUTE === true;
		}

		const pricing = this.aiForm.querySelector<HTMLAnchorElement>(
			"[data-role='ai-pricing-link']",
		);
		if (pricing && modelOptions?.pricing_url) {
			pricing.href = modelOptions.pricing_url;
		}

		const autoSuffix =
			settings.AI_AUTO_EXECUTE === true ? " · auto-execute on" : "";
		this.updateSummary(
			`${settings.AI_MODEL} · utility ${settings.AI_UTILITY_MODEL} · image ${settings.AI_IMAGE_MODEL}${autoSuffix}`,
		);
	}

	_populateAiModelSelect(name: AiModelField, options: AiModel[]) {
		const select = this.aiForm?.querySelector<HTMLSelectElement>(
			`[name='${name}']`,
		);
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
		if (!this.aiForm) return;
		if (this._aiSelectsInitialized) {
			this.aiForm
				.querySelectorAll<HTMLSelectElement>("[data-role='ai-select'] select")
				.forEach((select) => {
					this._refreshSelectBox(select);
				});
			return;
		}

		this._aiSelectsInitialized = true;
		this.aiForm
			.querySelectorAll<HTMLElement>("[data-role='ai-select']")
			.forEach((element) => {
				const select = new SelectBox(element);
				select.init();
				this.destroyables.push(select);
			});
	}

	_refreshSelectBox(select: HTMLSelectElement) {
		const combobox =
			select.closest<SiteSelectHost>("[lp-select]")?._lp_combobox;
		if (!combobox) return;

		const options = Array.from(select.querySelectorAll("option"));
		combobox.items = options.map((option) => ({
			id: option.value,
			name: option.textContent ?? "",
			kind: option.dataset.kind || "default",
			...(JSON.parse(option.dataset.details || "{}") as AiModelDetails),
		}));
		combobox.updatePanel(combobox.results.create(combobox.items));
		this.syncSelectBox(select, select.value);
	}

	_setAiField(name: AiModelField | "AI_LOCATION", value?: string) {
		const field = this.aiForm?.querySelector<
			HTMLInputElement | HTMLSelectElement
		>(`[name='${name}']`);
		if (!field) return;
		field.value = value || "";
		if (field instanceof HTMLSelectElement) this.syncSelectBox(field, value);
	}

	_showAiError(message: string) {
		const error = this.aiForm?.querySelector<HTMLElement>(
			"[data-role='ai-error']",
		);
		if (!error) return;
		error.textContent = message || "";
		error.dataset.visible = message ? "true" : "false";
	}

	_aiSettingsFormData() {
		const form = this.aiForm;
		const data = new FormData(form ?? undefined);
		if (!form) return data;
		form
			.querySelectorAll<HTMLSelectElement>("[data-role='ai-select'] select")
			.forEach((select) => {
				const combobox =
					select.closest<SiteSelectHost>("[lp-select]")?._lp_combobox;
				const selected = combobox?.values?.values().next().value;
				data.set(select.name, selected ?? select.value ?? "");
			});
		const autoExecute = form.querySelector<HTMLInputElement>(
			"[name='AI_AUTO_EXECUTE']",
		);
		if (autoExecute) {
			data.set("AI_AUTO_EXECUTE", autoExecute.checked ? "true" : "false");
		}
		return data;
	}

	async _saveAiSettings(event: SubmitEvent) {
		event.preventDefault();
		event.stopPropagation();
		const button = this.aiButton;
		if (!button) return;

		this._showAiError("");
		button.activate();
		const response = await request.post<AiSettingsResponse>(
			this.endpoints.setAiSettings,
			this._aiSettingsFormData(),
		);
		if (!response?.ok) {
			this._showAiError(response?.error || "Unable to save AI model settings.");
			button.deactivate("Save AI Model Settings");
			return;
		}

		this._aiSettings = response.ai_settings;
		this._aiModelOptions = response.ai_model_options;
		await withTransition(
			() => {
				this._renderAiSettings(response.ai_settings, response.ai_model_options);
				button.deactivate();
			},
			{ label: "site-settings:save-ai-models" },
		);
	}
}
