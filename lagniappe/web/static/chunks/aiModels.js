/*! Third-party licenses: /third-party-licenses.txt */
import { b as buttons } from './buttons.js?v=bd5baecd';
import { r as request, w as withTransition } from './foundation.js?v=bd5baecd';
import './connectivity.js?v=bd5baecd';
import { S as SelectBox } from './select2.js?v=bd5baecd';
import { S as SiteSetting } from './base.js?v=bd5baecd';
import './styles.js?v=bd5baecd';
import './icons.js?v=bd5baecd';
import './formatting.js?v=bd5baecd';
import './combobox.js?v=bd5baecd';
import './primitives.js?v=bd5baecd';
import './results.js?v=bd5baecd';
import './submitter.js?v=bd5baecd';

/**
 * @testable true
 * @tests tests_js/test_019_form_sync_frontend.py::test_site_settings_initializes_ai_selects_before_syncing_saved_values
 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_ai_form_saves_current_models_through_route
 * @features admin
 * @dimensions ai-settings model-options saved-values model-selection
 */
class SiteAiModels extends SiteSetting {
	constructor(attributes) {
		super(attributes);
		this._aiSettings = null;
		this._aiModelOptions = null;
		this._aiSelectsInitialized = false;
		this._saveAiSettings = this._saveAiSettings.bind(this);
	}

	init() {
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

	updated(response) {
		this._aiSettings = response.ai_settings;
		this._aiModelOptions = response.ai_model_options;
	}

	postreconcile() {
		if (this._aiSettings) {
			this._renderAiSettings(this._aiSettings, this._aiModelOptions);
		}
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
		if (pricing && modelOptions?.pricing_url) {
			pricing.href = modelOptions.pricing_url;
		}

		this.updateSummary(
			`${settings.AI_MODEL} · utility ${settings.AI_UTILITY_MODEL} · image ${settings.AI_IMAGE_MODEL}`,
		);
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
		this.syncSelectBox(select, select.value);
	}

	_setAiField(name, value) {
		const field = this.aiForm?.querySelector(`[name='${name}']`);
		if (!field) return;
		field.value = value || "";
		if (field.matches("select")) this.syncSelectBox(field, value);
	}

	_showAiError(message) {
		const error = this.aiForm?.querySelector("[data-role='ai-error']");
		if (!error) return;
		error.textContent = message || "";
		error.dataset.visible = message ? "true" : "false";
	}

	/**
	 * @testable true
	 * @tests tests_js/test_019_form_sync_frontend.py::test_site_settings_ai_submission_uses_visible_combobox_values
	 * @tests tests_e2e/008_users/test_008c_user_settings.py::test_site_settings_ai_form_saves_current_models_through_route
	 * @features admin
	 * @dimensions ai-settings model-selection submission
	 */
	_aiSettingsFormData() {
		const data = new FormData(this.aiForm);
		this.aiForm
			.querySelectorAll("[data-role='ai-select'] select")
			.forEach((select) => {
				const combobox = select.closest("[lp-select]")?._lp_combobox;
				const selected = combobox?.values?.values().next().value;
				data.set(select.name, selected ?? select.value ?? "");
			});
		return data;
	}

	async _saveAiSettings(event) {
		event.preventDefault();
		event.stopPropagation();

		this._showAiError("");
		this.aiButton.activate();
		const response = await request.post(
			this.endpoints.setAiSettings,
			this._aiSettingsFormData(),
		);
		if (!response.ok) {
			this._showAiError(response.error || "Unable to save AI model settings.");
			this.aiButton.deactivate("Save AI Model Settings");
			return;
		}

		this._aiSettings = response.ai_settings;
		this._aiModelOptions = response.ai_model_options;
		await withTransition(
			() => {
				this._renderAiSettings(response.ai_settings, response.ai_model_options);
				this.aiButton.deactivate();
			},
			{ label: "site-settings:save-ai-models" },
		);
	}
}

export { SiteAiModels };
