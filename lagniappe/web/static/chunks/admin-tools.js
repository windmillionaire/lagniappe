/*! Third-party licenses: /third-party-licenses.txt */
import { b as buttons } from './ui-controls.js?v=be84e1e9';
import { r as request, w as withTransition, a as clearRecentSearchResults } from './foundation.js?v=be84e1e9';
import { S as SelectBox, a as FacetsBox } from './forms.js?v=be84e1e9';
import './connectivity.js?v=be84e1e9';
import { Modal } from './modal.js?v=be84e1e9';
import { u as uploadElement, B as BaseUpload, U as UploadMenu } from './uploads.js?v=be84e1e9';
import { s as setIcon, S as STYLES } from './ui-resources.js?v=be84e1e9';

class SiteSetting {
  constructor(attributes) {
    Object.assign(this, attributes);
    this.destroyables = [];
  }
  updateSummary(text) {
    const summary = this.target.closest("[data-role='site-settings-section']")?.querySelector("[data-role='section-summary']");
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

class SiteAiModels extends SiteSetting {
  constructor(attributes) {
    super(attributes);
    this._aiSettings = null;
    this._aiModelOptions = null;
    this._aiSelectsInitialized = false;
    this._saveAiSettings = this._saveAiSettings.bind(this);
  }
  init() {
    this.aiForm = this.target.querySelector(
      "[data-role='ai-settings']"
    );
    if (!this.aiForm) return;
    this.aiButton = buttons.active({
      existingButton: this.aiForm.querySelector("button[type='submit']"),
      text: "Save AI Model Settings",
      processingText: "Saving AI Model Settings",
      completedText: "AI Model Settings Saved",
      processingIcon: "spinner",
      completedIcon: "check"
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
    const autoExecute = this.aiForm.querySelector(
      "[name='AI_AUTO_EXECUTE']"
    );
    if (autoExecute) {
      autoExecute.checked = settings.AI_AUTO_EXECUTE === true;
    }
    const pricing = this.aiForm.querySelector(
      "[data-role='ai-pricing-link']"
    );
    if (pricing && modelOptions?.pricing_url) {
      pricing.href = modelOptions.pricing_url;
    }
    const autoSuffix = settings.AI_AUTO_EXECUTE === true ? " \xB7 auto-execute on" : "";
    this.updateSummary(
      `${settings.AI_MODEL} \xB7 utility ${settings.AI_UTILITY_MODEL} \xB7 image ${settings.AI_IMAGE_MODEL}${autoSuffix}`
    );
  }
  _populateAiModelSelect(name, options) {
    const select = this.aiForm?.querySelector(
      `[name='${name}']`
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
        source: option.source
      });
      select.appendChild(element);
    }
    this._refreshSelectBox(select);
  }
  _initAiSelectBoxes() {
    if (!this.aiForm) return;
    if (this._aiSelectsInitialized) {
      this.aiForm.querySelectorAll("[data-role='ai-select'] select").forEach((select) => {
        this._refreshSelectBox(select);
      });
      return;
    }
    this._aiSelectsInitialized = true;
    this.aiForm.querySelectorAll("[data-role='ai-select']").forEach((element) => {
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
      name: option.textContent ?? "",
      kind: option.dataset.kind || "default",
      ...JSON.parse(option.dataset.details || "{}")
    }));
    combobox.updatePanel(combobox.results.create(combobox.items));
    this.syncSelectBox(select, select.value);
  }
  _setAiField(name, value) {
    const field = this.aiForm?.querySelector(`[name='${name}']`);
    if (!field) return;
    field.value = value || "";
    if (field instanceof HTMLSelectElement) this.syncSelectBox(field, value);
  }
  _showAiError(message) {
    const error = this.aiForm?.querySelector(
      "[data-role='ai-error']"
    );
    if (!error) return;
    error.textContent = message || "";
    error.dataset.visible = message ? "true" : "false";
  }
  _aiSettingsFormData() {
    const form = this.aiForm;
    const data = new FormData(form ?? void 0);
    if (!form) return data;
    form.querySelectorAll("[data-role='ai-select'] select").forEach((select) => {
      const combobox = select.closest("[lp-select]")?._lp_combobox;
      const selected = combobox?.values?.values().next().value;
      data.set(select.name, selected ?? select.value ?? "");
    });
    const autoExecute = form.querySelector(
      "[name='AI_AUTO_EXECUTE']"
    );
    if (autoExecute) {
      data.set("AI_AUTO_EXECUTE", autoExecute.checked ? "true" : "false");
    }
    return data;
  }
  async _saveAiSettings(event) {
    event.preventDefault();
    event.stopPropagation();
    const button = this.aiButton;
    if (!button) return;
    this._showAiError("");
    button.activate();
    const response = await request.post(
      this.endpoints.setAiSettings,
      this._aiSettingsFormData()
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
      { label: "site-settings:save-ai-models" }
    );
  }
}

var aiModels = /*#__PURE__*/Object.freeze({
	__proto__: null,
	SiteAiModels: SiteAiModels
});

class SiteAdministrators extends SiteSetting {
  constructor(attributes) {
    super(attributes);
    this._administrators = [];
    this._candidates = [];
    this._canManage = false;
    this._demotionModal = null;
    this._submit = this._submit.bind(this);
    this._click = this._click.bind(this);
  }
  init() {
    this.form = this.target.querySelector(
      "[data-role='administrator-form']"
    );
    this.list = this.target.querySelector(
      "[data-role='administrator-list']"
    );
    this.error = this.target.querySelector(
      "[data-role='administrator-error']"
    );
    const input = this.form?.querySelector(
      "input[name='user_key']"
    );
    if (!input) return;
    this.selector = new FacetsBox(input);
    this.selector.init();
    this.form?.addEventListener("submit", this._submit);
    this.list?.addEventListener("click", this._click);
  }
  updated(response) {
    this._administrators = response.administrators || [];
    this._candidates = response.administrator_candidates || [];
    this._canManage = response.can_manage_administrators === true;
  }
  postreconcile() {
    this._render();
  }
  _render() {
    if (!this.list || !this.form) return;
    this.list.replaceChildren(
      ...this._administrators.map(
        (administrator) => this._administratorRow(administrator)
      )
    );
    this.selector?.clear({ notify: false });
    this.selector?.updatePanel("");
    this.form.dataset.visible = this._canManage ? "true" : "false";
    const submit = this.form.querySelector("button");
    if (submit) submit.disabled = !this._candidates.length;
    this.updateSummary(
      `${this._administrators.length} ${this._administrators.length === 1 ? "administrator" : "administrators"}`
    );
  }
  _administratorRow(administrator) {
    const item = document.createElement("li");
    item.dataset.role = "administrator";
    item.dataset.owner = administrator.is_owner ? "true" : "false";
    item.className = "flex flex-col gap-2 rounded-md border border-base-light/70 bg-white/80 p-3 sm:flex-row sm:items-center sm:justify-between";
    const details = document.createElement("div");
    const name = document.createElement("strong");
    name.className = "block text-sm text-base-dark";
    name.textContent = `${administrator.name}${administrator.is_owner ? " \u2014 Primary Owner" : ""}`;
    const email = document.createElement("span");
    email.className = "block text-xs text-base-medium";
    email.textContent = administrator.email;
    const status = document.createElement("span");
    status.className = "block text-xs text-base-medium";
    status.dataset.role = "administrator-last-login";
    status.textContent = administrator.awaiting_first_sign_in ? "Awaiting first sign-in" : administrator.last_login ? `Last signed in ${new Date(administrator.last_login).toLocaleString()}` : "Never signed in";
    details.append(name, email, status);
    item.append(details);
    if (this._canManage && !administrator.is_owner && administrator.key) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.role = "demote-administrator";
      button.dataset.key = administrator.key;
      button.dataset.name = administrator.name;
      button.dataset.kind = "delete";
      button.className = "action-button shrink-0 rounded-md px-3 py-1.5 text-sm font-semibold";
      button.textContent = "Remove Administrator";
      item.append(button);
    }
    return item;
  }
  async _submit(event) {
    event.preventDefault();
    const select = this.form?.querySelector(
      "select[name='user_key']"
    );
    if (!select?.value) return;
    this._showError();
    const response = await request.post(
      this.endpoints.promote,
      { user_key: select.value }
    );
    if (!response?.ok) return this._showError(response?.error);
    this.updated(response);
    this._render();
  }
  async _click(event) {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const button = target.closest(
      "[data-role='demote-administrator']"
    );
    if (!button?.dataset.key || !this.list?.contains(button)) return;
    const route = this.endpoints.demote(button.dataset.key);
    this._showError();
    this._demotionModal?.destroy();
    const modal = new Modal(this.view, button);
    this._demotionModal = modal;
    await modal.load(route);
    if (this._demotionModal !== modal || !modal.modal) return;
    const confirm = modal.modal.querySelector(
      "[data-role='delete']"
    );
    if (!confirm) return;
    let submitting = false;
    confirm.addEventListener("click", async () => {
      if (submitting) return;
      submitting = true;
      confirm.disabled = true;
      const spinner = confirm.querySelector("#spinner");
      if (spinner) spinner.dataset.visible = "true";
      const response = await request.delete(route);
      if (!response?.ok) {
        submitting = false;
        confirm.disabled = false;
        if (spinner) spinner.dataset.visible = "false";
        this._showError(response?.error);
        return;
      }
      await modal.remove();
      if (this._demotionModal === modal) this._demotionModal = null;
      this.updated(response);
      this._render();
    });
  }
  _showError(message = "") {
    if (!this.error) return;
    this.error.textContent = message;
    this.error.dataset.visible = message ? "true" : "false";
  }
  destroy() {
    this._demotionModal?.destroy();
    this._demotionModal = null;
    this.form?.removeEventListener("submit", this._submit);
    this.list?.removeEventListener("click", this._click);
    this.selector?.destroy();
    super.destroy();
  }
}

var administrators = /*#__PURE__*/Object.freeze({
	__proto__: null,
	SiteAdministrators: SiteAdministrators
});

const INSTANCE_CLASSES = {
  automatic: ["F1", "F2", "F4", "F4_1G"],
  basic: ["B1", "B2", "B4", "B4_1G", "B8"]
};
const DEFAULT_INSTANCE_CLASS = {
  automatic: "F2",
  basic: "B2"
};
const MEMORY_SAFE_WORKER_CLASSES = /* @__PURE__ */ new Set(["F2", "B2"]);
const MEMORY_SAFE_WORKER_LIMIT = 3;
class SiteDeployment extends SiteSetting {
  constructor(attributes) {
    super(attributes);
    this._deployment = null;
    this._saveDeployment = this._saveDeployment.bind(this);
  }
  init() {
    this.deploymentForm = this.target.querySelector(
      "[data-role='deployment-settings']"
    );
    if (!this.deploymentForm) return;
    this.deploymentButton = buttons.active({
      existingButton: this.deploymentForm.querySelector(
        "button[type='submit']"
      ),
      text: "Save Deployment Settings",
      processingText: "Saving Deployment Settings",
      completedText: "Deployment Settings Saved",
      processingIcon: "spinner",
      completedIcon: "check"
    });
    this.deploymentForm.addEventListener("submit", this._saveDeployment);
    this.deploymentForm.querySelectorAll("[data-role='deployment-select']").forEach((element) => {
      const select = new SelectBox(element);
      select.init();
      this.destroyables.push(select);
    });
    this.deploymentForm.querySelector("[name='DEPLOY_SCALING_TYPE']")?.addEventListener("change", () => {
      this._syncInstanceClassOptions();
      this._syncInstanceControls();
      this._syncWorkerLimit();
    });
    this.deploymentForm.querySelector("[name='DEPLOY_INSTANCE_CLASS']")?.addEventListener("change", () => this._syncWorkerLimit());
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
      data.minIdleInstances
    );
    this._setDeploymentField("DEPLOY_IDLE_TIMEOUT", String(data.idleTimeout));
    this._syncInstanceClassOptions({ preserveCurrent: true });
    this._syncInstanceControls();
    this._syncWorkerLimit();
    this._updateDeploymentSummary(data);
  }
  _updateDeploymentSummary(deployment) {
    const scaling = deployment.scalingType === "automatic" ? "Automatic" : "Basic";
    const workers = Number(deployment.workerCount) === 1 ? "worker" : "workers";
    const maxInstances = Number(deployment.maxInstances) === 1 ? "max instance" : "max instances";
    const instanceText = deployment.scalingType === "automatic" ? `${deployment.minIdleInstances} min idle \xB7 ${deployment.maxInstances} ${maxInstances}` : `${deployment.maxInstances} ${maxInstances}`;
    this.updateSummary(
      `${scaling} \xB7 ${deployment.workerCount} ${workers} \xB7 ${deployment.instanceClass} \xB7 ${instanceText}`
    );
  }
  _normalizeDeployment(deployment) {
    const first = (value, fallback) => value === void 0 || value === null || value === "" ? fallback : value;
    return {
      scalingType: first(deployment.DEPLOY_SCALING_TYPE, "basic"),
      workerCount: first(deployment.DEPLOY_WORKER_COUNT, 3),
      instanceClass: first(deployment.DEPLOY_INSTANCE_CLASS, "B2"),
      maxInstances: first(deployment.DEPLOY_MAX_INSTANCES, 1),
      minIdleInstances: first(deployment.DEPLOY_MIN_IDLE_INSTANCES, 1),
      idleTimeout: first(deployment.DEPLOY_IDLE_TIMEOUT, "15m")
    };
  }
  _setDeploymentField(name, value) {
    this.deploymentForm?.querySelectorAll(
      `[name='${name}']`
    ).forEach((field) => {
      field.value = String(value);
      if (field instanceof window.HTMLSelectElement) {
        this.syncSelectBox(field, value ? String(value) : void 0);
      }
    });
  }
  _syncInstanceClassOptions({ preserveCurrent = false } = {}) {
    if (!this.deploymentForm) return;
    const scaling = this.deploymentForm.querySelector(
      "[name='DEPLOY_SCALING_TYPE']"
    );
    const instanceClass = this.deploymentForm.querySelector(
      "[name='DEPLOY_INSTANCE_CLASS']"
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
    const combobox = instanceClass.closest("[lp-select]")?._lp_combobox;
    if (combobox) {
      combobox.items = options.filter((option) => allowed.includes(option.value)).map((option) => {
        const details = JSON.parse(
          option.dataset.details || "{}"
        );
        return {
          id: option.value,
          name: option.textContent,
          kind: instanceClass.dataset.kind || "default",
          ...details
        };
      });
      combobox.updatePanel(combobox.results.create(combobox.items));
    }
    if (!preserveCurrent || !allowed.includes(instanceClass.value)) {
      this._setDeploymentField(
        "DEPLOY_INSTANCE_CLASS",
        DEFAULT_INSTANCE_CLASS[scalingType]
      );
    } else {
      this.syncSelectBox(instanceClass, instanceClass.value);
    }
  }
  _syncInstanceControls() {
    if (!this.deploymentForm) return;
    const scaling = this.deploymentForm.querySelector(
      "[name='DEPLOY_SCALING_TYPE']"
    );
    const automatic = scaling?.value === "automatic";
    const basicGroup = this.deploymentForm.querySelector(
      "[data-role='basic-instance-count']"
    );
    const automaticGroup = this.deploymentForm.querySelector(
      "[data-role='automatic-instance-counts']"
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
    const instanceClass = this.deploymentForm.querySelector(
      "[name='DEPLOY_INSTANCE_CLASS']"
    )?.value;
    const workerInput = this.deploymentForm.querySelector(
      "[name='DEPLOY_WORKER_COUNT']"
    );
    if (!workerInput) return;
    const memoryLimited = instanceClass !== void 0 && MEMORY_SAFE_WORKER_CLASSES.has(instanceClass);
    workerInput.max = memoryLimited ? String(MEMORY_SAFE_WORKER_LIMIT) : "20";
    if (memoryLimited && Number(workerInput.value) > MEMORY_SAFE_WORKER_LIMIT) {
      workerInput.value = String(MEMORY_SAFE_WORKER_LIMIT);
    }
    const guidance = this.deploymentForm.querySelector(
      "[data-role='deployment-worker-guidance']"
    );
    if (guidance) {
      guidance.textContent = memoryLimited ? `${instanceClass} supports at most three workers; each worker adds application memory use.` : "Workers multiply application memory use; monitor memory after increasing them.";
    }
  }
  _showDeploymentError(message) {
    const error = this.deploymentForm?.querySelector(
      "[data-role='deployment-error']"
    );
    if (!error) return;
    error.textContent = message || "";
    error.dataset.visible = message ? "true" : "false";
  }
  async _saveDeployment(event) {
    event.preventDefault();
    event.stopPropagation();
    if (!this.deploymentForm || !this.deploymentButton) return;
    this._showDeploymentError("");
    this.deploymentButton.activate();
    const response = await request.post(
      this.endpoints.setDeploymentSettings,
      new FormData(this.deploymentForm)
    );
    if (!response?.ok) {
      this._showDeploymentError(
        response?.error || "Unable to save deployment."
      );
      this.deploymentButton.deactivate("Save Deployment Settings");
      return;
    }
    this._deployment = response.deployment;
    this._renderDeployment(response.deployment);
    this.deploymentButton.deactivate();
  }
}

var deployment = /*#__PURE__*/Object.freeze({
	__proto__: null,
	SiteDeployment: SiteDeployment
});

const display = (value) => value || "None";
class SiteInstallationAccess extends SiteSetting {
  updated(response) {
    this._access = response.installation_access;
  }
  postreconcile() {
    if (this._access) this._render(this._access);
  }
  _render(access) {
    this.updateSummary(access.summary);
    this.target.dataset.state = access.state;
    const fields = {
      project: access.project_id,
      owner: access.owner_email,
      installer: access.installer_email,
      deployer: access.deployer_email,
      bootstrap: access.bootstrap_admin_email,
      runtime: access.runtime_service_account,
      "email-service": access.authentication_email?.service,
      "email-sender": access.authentication_email?.sender_email,
      "email-login": access.authentication_email?.login
    };
    for (const [name, value] of Object.entries(fields)) {
      const field = this.target.querySelector(`[data-field='${name}']`);
      if (field) field.textContent = display(value);
    }
    const status = this.target.querySelector("[data-role='handoff-status']");
    const statusTitle = status?.querySelector("[data-role='status-title']");
    const statusDescription = status?.querySelector(
      "[data-role='status-description']"
    );
    if (statusTitle && statusDescription && access.state === "application-complete") {
      statusTitle.textContent = "Application handoff configured";
      statusDescription.textContent = "The saved deployer is the permanent Owner and automatic installer bootstrap is closed. Confirm Cloud IAM separately before considering cloud cleanup complete.";
    } else if (statusTitle && statusDescription && access.state === "pending") {
      statusTitle.textContent = "Delegated handoff pending";
      statusDescription.textContent = "Keep the installer\u2019s Google Cloud access until setup handoff completes. Removing it early can prevent deployment and managed-resource transfer.";
    } else if (statusTitle && statusDescription) {
      statusTitle.textContent = "Owner-managed installation";
      statusDescription.textContent = "The permanent Owner also installed this site; there is no separate delegated installer to hand off.";
    }
    const iamLink = this.target.querySelector(
      "[data-role='project-iam-link']"
    );
    if (iamLink) iamLink.href = access.project_iam_url;
    const email = access.authentication_email;
    const emailDetails = this.target.querySelector(
      "[data-role='authentication-email-details']"
    );
    if (emailDetails)
      emailDetails.dataset.visible = email?.configured ? "true" : "false";
    const emailWarning = this.target.querySelector(
      "[data-role='installer-email-warning']"
    );
    if (emailWarning) {
      emailWarning.dataset.visible = email?.uses_installer ? "true" : "false";
    }
    const handoffInstructions = this.target.querySelector(
      "[data-role='handoff-instructions']"
    );
    if (handoffInstructions) {
      handoffInstructions.dataset.visible = access.state === "pending" ? "true" : "false";
    }
  }
}

var installationAccess = /*#__PURE__*/Object.freeze({
	__proto__: null,
	SiteInstallationAccess: SiteInstallationAccess
});

const SPLASH_PREFIX = "splash-";
class SiteImage extends SiteSetting {
  constructor(attributes) {
    super(attributes);
    this._siteImage = null;
    this._uploadInitialization = null;
    this._uploadImage = this._uploadImage.bind(this);
  }
  updated(response) {
    this._siteImage = response.site_image;
  }
  postreconcile() {
    if (this._siteImage) this._renderSiteImage(this._siteImage);
  }
  opened() {
    if (this._uploadInitialization) return this._uploadInitialization;
    const pending = this._initUpload().catch((error) => {
      if (this._uploadInitialization === pending) {
        this._uploadInitialization = null;
      }
      throw error;
    });
    this._uploadInitialization = pending;
    return pending;
  }
  async _initUpload() {
    const uploadForm = this.target.querySelector(
      "[data-role='upload-site-image']"
    );
    if (!uploadForm) return;
    const dropzone = uploadElement.dropzone({
      text: "Drop image here, click to upload, or tap to choose camera/files"
    });
    const upload = new BaseUpload({
      target: uploadForm,
      dropzone,
      submitButton: uploadForm.querySelector("button[type='submit']"),
      inputName: "site-image",
      uploadType: "image",
      menuOptions: ["paste", "remove"],
      messages: {
        submit: "Update Site Image",
        submitting: "Processing Image",
        submitted: "Image Processed"
      },
      html: [dropzone.element]
    });
    this.upload = upload;
    upload.uploadMenu = new UploadMenu(upload);
    await upload.init();
    this.destroyables.push(upload);
    uploadForm.addEventListener("submit", this._uploadImage);
  }
  async _uploadImage(event) {
    event.preventDefault();
    event.stopPropagation();
    const upload = this.upload;
    if (!upload) return;
    const prepared = await upload.prepareSubmit({
      route: this.endpoints.setSiteImage
    });
    if (!prepared) return;
    const response = await request.post(
      this.endpoints.setSiteImage,
      upload.formData
    );
    if (!response?.ok) {
      if (response?.error) upload.showError(response.error);
      upload.form?.resetSubmitButton();
      return;
    }
    upload.form?.success();
    const image = response.site_image;
    if (image) {
      this._siteImage = image;
      withTransition(() => {
        this._renderSiteImage(image);
      });
    }
  }
  _renderSiteImage(imageData) {
    const container = this.target.querySelector("[data-role='site-image']");
    if (!container || !imageData) return;
    const entries = Object.entries(imageData).filter(
      ([name]) => !name.startsWith(SPLASH_PREFIX)
    );
    const fragment = document.createDocumentFragment();
    const previewUrl = imageData["apple-touch-icon.png"] || imageData["logo-192x192.png"];
    if (previewUrl) {
      const preview = document.createElement("img");
      preview.src = `${previewUrl}?v=${Date.now()}`;
      preview.alt = "Site image";
      preview.className = "size-20 rounded-lg object-contain";
      fragment.appendChild(preview);
    }
    if (entries.length > 0) {
      const grid = document.createElement("div");
      grid.className = "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2";
      for (const [filename, url] of entries) {
        const link = document.createElement("a");
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.className = "flex flex-row items-center gap-2 rounded-md border border-base-light/50 bg-white px-3 py-2 text-sm hover:bg-base-bg transition-colors";
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
    this.updateSummary(`${entries.length} generated files`);
    container.replaceChildren(fragment);
  }
}

var image = /*#__PURE__*/Object.freeze({
	__proto__: null,
	SiteImage: SiteImage
});

class SiteMaintenance extends SiteSetting {
  constructor(attributes) {
    super(attributes);
    this._migrationStatus = null;
    this._cacheStatus = null;
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
    this._renderCacheStatus(this._cacheStatus);
  }
  _initActions() {
    const cacheButton = this.target.querySelector(
      "[data-role='rebuild-cache']"
    );
    const updateButton = this.target.querySelector(
      "[data-role='site-update']"
    );
    if (!cacheButton || !updateButton) return;
    const rebuildCache = buttons.active({
      existingButton: cacheButton,
      icon: "database",
      text: "Refresh Cache",
      processingText: "Refreshing Cache",
      completedText: "Cache Refreshed",
      processingIcon: "spinner",
      completedIcon: "check"
    });
    rebuildCache.element.addEventListener("click", async () => {
      rebuildCache.activate();
      this._cacheStatus = null;
      this._renderCacheStatus(null);
      const response = await request.post(
        this.endpoints.rebuildCache
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
          { label: "site-settings:cache-error" }
        );
        return;
      }
      this._cacheStatus = response.cache_status || null;
      this._renderCacheStatus(this._cacheStatus);
      rebuildCache.deactivate(
        this._cacheStatus?.failed ? "Cache Refreshed \u2014 Review Errors" : void 0
      );
      clearRecentSearchResults();
    });
    const applyUpdates = buttons.active({
      existingButton: updateButton,
      icon: "installation",
      text: "Apply Updates",
      processingText: "Applying Site Updates",
      completedText: "Updates Applied",
      processingIcon: "spinner",
      completedIcon: "check"
    });
    applyUpdates.element.addEventListener("click", async () => {
      applyUpdates.activate();
      const response = await request.post(
        this.endpoints.siteUpdate
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
          { label: "site-settings:update-error" }
        );
        return;
      }
      await withTransition(
        () => {
          applyUpdates.deactivate();
          this._renderMigrationStatus(this._migrationStatus);
        },
        { label: "site-settings:update-complete" }
      );
      clearRecentSearchResults();
    });
  }
  _renderCacheStatus(status) {
    const panel = this.target.querySelector(
      "[data-role='cache-status']"
    );
    if (!panel) return;
    panel.dataset.visible = status ? "true" : "false";
    if (!status) return;
    const title = panel.querySelector("[data-role='cache-status-title']");
    const summary = panel.querySelector("[data-role='cache-status-summary']");
    const list = panel.querySelector("[data-role='cache-status-errors']");
    if (!title || !summary || !list) return;
    title.textContent = status.failed ? "Cache refreshed with errors" : "Cache refreshed";
    const errors = status.errors || [];
    summary.textContent = `${status.processed} records processed; ${status.failed} skipped.` + (status.failed ? " Skipped records could not be safely cached. Review them, then refresh again." : "") + (status.failed > errors.length ? ` Showing ${errors.length} errors.` : "");
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
    const configurationButton = this.target.querySelector(
      "[data-role='configuration']"
    );
    if (!configurationButton) return;
    const configuration = buttons.active({
      existingButton: configurationButton,
      icon: "configuration",
      text: "Configuration",
      processingText: "Loading Configuration",
      completedText: "Configuration",
      completedIcon: "configuration"
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
  _renderMigrationStatus(status) {
    const panel = this.target.querySelector(
      "[data-role='migration-status']"
    );
    if (!panel) return;
    const title = panel.querySelector("[data-role='migration-status-title']");
    const summary = panel.querySelector(
      "[data-role='migration-status-summary']"
    );
    const results = panel.querySelector(
      "[data-role='migration-status-results']"
    );
    const errors = panel.querySelector(
      "[data-role='migration-status-errors']"
    );
    if (!title || !summary || !results || !errors) return;
    const updateButton = this.target.querySelector(
      "[data-role='site-update']"
    );
    const cacheButton = this.target.querySelector(
      "[data-role='rebuild-cache']"
    );
    results.replaceChildren();
    errors.replaceChildren();
    panel.dataset.visible = "true";
    const state = status?.status || "current";
    const counts = status?.counts || {};
    const pendingCount = (counts.pending || 0) + (counts.failed || 0) + (counts.interrupted || 0) + (counts.blocked || 0);
    if (updateButton) {
      updateButton.disabled = !["pending", "failed"].includes(state);
      updateButton.title = pendingCount ? `Apply ${pendingCount} pending site ${pendingCount === 1 ? "update" : "updates"}` : "All site updates are complete";
    }
    if (cacheButton) {
      cacheButton.disabled = !status?.cache_refresh_allowed;
      cacheButton.title = status?.cache_refresh_allowed ? "Refresh cached and search data" : "Apply all site updates before refreshing the cache";
    }
    const version = status?.current_version ? `Version ${status.current_version}. ` : "";
    const visibleMigrations = (status?.migrations || []).filter(
      (migration) => migration.source !== "fresh-install"
    );
    const visibleCompleted = visibleMigrations.filter(
      (migration) => migration.state === "complete"
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
        summary.textContent = visibleCompleted ? `${version}${visibleCompleted} site ${visibleCompleted === 1 ? "update" : "updates"} completed.` : `${version}No site updates are required.`;
    }
    const appendDetail = (list, detail, label = "") => {
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
    const stateLabels = {
      complete: "Completed",
      pending: "Pending",
      running: "Running",
      failed: "Failed",
      interrupted: "Interrupted \u2014 retry available",
      blocked: "Blocked by an earlier update",
      "audit-error": "Audit error"
    };
    const releases = /* @__PURE__ */ new Map();
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
        (migration) => migration.state !== "complete"
      );
      const releaseSummary = document.createElement("summary");
      const completed = migrations.filter(
        (migration) => migration.state === "complete"
      ).length;
      releaseSummary.textContent = `Version ${release} \u2014 ${completed}/${migrations.length} completed`;
      releaseSummary.className = STYLES.siteSettings.migration.releaseSummary;
      releaseDetails.appendChild(releaseSummary);
      const migrationList = document.createElement("ul");
      migrationList.className = STYLES.siteSettings.migration.migrationList;
      for (const migration of migrations) {
        const migrationItem = document.createElement("li");
        const attempts = migration.attempts || [];
        const attemptCount = attempts.length;
        const detailAttempt = migration.state === "complete" ? [...attempts].reverse().find((attempt) => attempt.status === "complete") : attempts.at(-1);
        migrationItem.textContent = `${migration.id} \u2014 ${migration.label}: ${stateLabels[migration.state] || migration.state}`;
        if (migration.completed_at) {
          const completion = document.createElement("div");
          const completedVersion = migration.completed_version ? `version ${migration.completed_version}` : "an earlier version";
          const completedBuild = migration.completed_build_id ? `, build ${migration.completed_build_id}` : "";
          completion.textContent = `Completed on ${completedVersion}${completedBuild} \xB7 ${attemptCount} recorded ${attemptCount === 1 ? "attempt" : "attempts"}`;
          completion.className = STYLES.siteSettings.migration.completion;
          migrationItem.appendChild(completion);
        }
        if (migration.audit_error) {
          appendDetail(
            errors,
            { message: migration.audit_error },
            `${migration.id} audit`
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
        const repairDetails = migration.id === "MSG-001" ? [] : detailAttempt?.repairs || [];
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
            failure.url ? migration.id : `${migration.id} ${failure.key}`
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

var maintenance = /*#__PURE__*/Object.freeze({
	__proto__: null,
	SiteMaintenance: SiteMaintenance
});

class SiteServiceProviders extends SiteSetting {
  updated(response) {
    this._links = response.service_providers;
  }
  postreconcile() {
    if (this._links) this._renderServiceProviders(this._links);
  }
  _renderServiceProviders(links) {
    const container = this.target.querySelector(
      "[data-role='service-providers']"
    );
    if (!container || !links?.length) return;
    const grid = document.createElement("div");
    grid.className = "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3";
    for (const link of links) {
      const card = document.createElement("a");
      card.href = link.url;
      card.target = "_blank";
      card.rel = "noopener noreferrer";
      card.className = "group/link flex flex-col gap-1 rounded-lg border border-base-light/50 bg-white px-4 py-3 shadow-sm hover:bg-base-bg transition-colors";
      const titleRow = document.createElement("div");
      titleRow.className = "flex flex-row items-center gap-1";
      const icon = document.createElement("span");
      setIcon(
        icon,
        link.icon,
        "text-base-dark text-lg group-hover/link:text-kind-default transition-colors text-sm"
      );
      const title = document.createElement("span");
      title.className = "text-sm font-semibold text-base-dark group-hover/link:text-kind-default transition-colors";
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

var providers = /*#__PURE__*/Object.freeze({
	__proto__: null,
	SiteServiceProviders: SiteServiceProviders
});

const PUBLIC_PAGE_SETTINGS_ENDPOINT = "/l/site-settings/public-pages";
class SitePublicPages extends SiteSetting {
  constructor(attributes) {
    super({ ...attributes, endpoints: {} });
    this._settings = null;
    this._save = this._save.bind(this);
  }
  async init() {
    this.form = this.target.querySelector(
      "[data-role='public-page-settings']"
    );
    if (!this.form) return;
    this.button = buttons.active({
      existingButton: this.form.querySelector("button[type='submit']"),
      text: "Save Public Page Settings",
      processingText: "Saving Public Page Settings",
      completedText: "Public Page Settings Saved",
      processingIcon: "spinner",
      completedIcon: "check"
    });
    this.form.addEventListener("submit", this._save);
    const response = await request.get(
      PUBLIC_PAGE_SETTINGS_ENDPOINT
    );
    if (response?.ok && response.public_pages) {
      this._settings = response.public_pages;
      this._render(response.public_pages);
    } else {
      this._showError(
        response?.error || "Unable to load public page settings."
      );
    }
  }
  updated(response) {
    if (response.public_pages) this._settings = response.public_pages;
  }
  postreconcile() {
    if (this._settings) this._render(this._settings);
  }
  _render(settings) {
    const enabled = settings.PUBLIC_PAGE_INDEXING === true;
    const field = this.form?.querySelector(
      "[name='PUBLIC_PAGE_INDEXING']"
    );
    if (field) field.checked = enabled;
    this.updateSummary(
      enabled ? "Search discovery is on" : "Search discovery is off"
    );
  }
  _showError(message) {
    const error = this.form?.querySelector(
      "[data-role='public-pages-error']"
    );
    if (!error) return;
    error.textContent = message || "";
    error.dataset.visible = message ? "true" : "false";
  }
  async _save(event) {
    event.preventDefault();
    event.stopPropagation();
    const { form, button } = this;
    if (!form || !button) return;
    this._showError("");
    button.activate();
    const data = new FormData();
    data.set(
      "PUBLIC_PAGE_INDEXING",
      form.querySelector("[name='PUBLIC_PAGE_INDEXING']")?.checked ? "true" : "false"
    );
    const response = await request.post(
      PUBLIC_PAGE_SETTINGS_ENDPOINT,
      data
    );
    if (!response?.ok || !response.public_pages) {
      this._showError(
        response?.error || "Unable to save public page settings."
      );
      button.deactivate("Save Public Page Settings");
      return;
    }
    this._settings = response.public_pages;
    this._render(response.public_pages);
    button.deactivate();
  }
  destroy() {
    this.form?.removeEventListener("submit", this._save);
    super.destroy();
  }
}

const SECTION_STORAGE_KEY = "lagniappe:site-settings-section";
const DEFAULT_SECTION = "maintenance";
const SETTING_WIDGETS = {
  maintenance: "SiteMaintenance",
  administrators: "SiteAdministrators",
  "installation-access": "SiteInstallationAccess",
  deployment: "SiteDeployment",
  "ai-models": "SiteAiModels",
  "service-providers": "SiteServiceProviders",
  "site-image": "SiteImage"
};
class SiteSettings {
  constructor(attributes) {
    Object.assign(this, attributes);
    this.sections = /* @__PURE__ */ new Map();
    this.settingWidgets = /* @__PURE__ */ new Map();
    this._sectionRequest = 0;
    this._click = this._click.bind(this);
  }
  async init() {
    this._collectSections();
    await this._loadSettingWidgets();
    this.target.addEventListener("click", this._click);
    const savedSection = localStorage.getItem(SECTION_STORAGE_KEY);
    const initialSection = savedSection && this.sections.has(savedSection) ? savedSection : DEFAULT_SECTION;
    await this.settingWidgets.get(initialSection)?.opened?.();
    this._setOpenSection(initialSection, { persist: false });
    this.target.setAttribute("initialized", "");
  }
  _collectSections() {
    this.target.querySelectorAll("[data-role='site-settings-section']").forEach((section) => {
      const name = section.dataset.section;
      if (name) this.sections.set(name, section);
    });
  }
  async _loadSettingWidgets() {
    await Promise.all(
      Object.entries(SETTING_WIDGETS).map(async ([section, widgetName]) => {
        const widget = await this.component.loadWidget(widgetName);
        if (widget) this.settingWidgets.set(section, widget);
      })
    );
    const target = this.sections.get("public-pages")?.querySelector("[data-widget='SitePublicPages']");
    if (target) {
      const widget = new SitePublicPages({ target, kind: "page" });
      await widget.init();
      this.settingWidgets.set("public-pages", widget);
    }
  }
  updated(response) {
    this.settingWidgets.forEach((widget) => {
      widget.updated?.(response);
      widget.modified = true;
    });
    this.modified = true;
  }
  // ViewComponent.load() reconciles a loaded inactive widget before activate()
  // assigns it as current. Child widgets do the actual response rendering.
  postreconcile() {
  }
  _click(event) {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const section = target.closest(
      "[data-role='site-settings-section']"
    );
    if (!section || !this.target.contains(section)) return;
    const toggle = target.closest("[data-role='expand']");
    if (toggle) {
      event.preventDefault();
      event.stopPropagation();
      void this._toggleSection(section.dataset.section);
      return;
    }
    const header = target.closest("header");
    if (!header || !section.contains(header)) return;
    if (target.closest("button, a, input, select, textarea")) return;
    void this._toggleSection(section.dataset.section);
  }
  async _toggleSection(name) {
    const nextOpen = !this._isSectionOpen(name);
    const nextSection = nextOpen ? name : null;
    const request = ++this._sectionRequest;
    await (nextSection ? this.settingWidgets.get(nextSection)?.opened?.() : void 0);
    if (request !== this._sectionRequest) return;
    return withTransition(() => this._setOpenSection(nextSection), {
      label: "site-settings:toggle-section"
    });
  }
  _setOpenSection(name, { persist = true } = {}) {
    this.sections.forEach((section, sectionName) => {
      const open = sectionName === name;
      section.dataset.open = open ? "true" : "false";
      const body = section.querySelector(
        "[data-role='section-body']"
      );
      if (body) body.dataset.visible = open ? "true" : "false";
      const toggle = section.querySelector(
        "[data-role='expand']"
      );
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
  }
  _isSectionOpen(name) {
    return name !== void 0 && this.sections.get(name)?.dataset.open === "true";
  }
  destroy() {
    this.target.removeEventListener("click", this._click);
    this.settingWidgets.get("public-pages")?.destroy?.();
  }
}

var siteSettings = /*#__PURE__*/Object.freeze({
	__proto__: null,
	SiteSettings: SiteSettings
});

export { aiModels as a, administrators as b, image as c, deployment as d, installationAccess as i, maintenance as m, providers as p, siteSettings as s };
