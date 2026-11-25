/*! Third-party licenses: /third-party-licenses.txt */
import { b as FormWidget, I as InputElement, T as TextareaElement, S as SelectBox } from './forms.js?v=b6c361d7';
import { s as sections, S as SectionToggle } from './form-sections.js?v=b6c361d7';
import { r as request, c as captureError, w as withTransition } from './foundation.js?v=b6c361d7';
import './connectivity.js?v=b6c361d7';
import { S as STYLES, c as createIcon } from './ui-resources.js?v=b6c361d7';
import { p as primitives } from './ui-controls.js?v=b6c361d7';
import { B as BaseUpload, u as uploadElement, U as UploadMenu } from './uploads.js?v=b6c361d7';

class CreateNote extends FormWidget {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Add Note",
      submitting: "Adding Note",
      submitted: "Note Added"
    };
    this.photoUrl = null;
    this._click = this._click.bind(this);
    this._photoChanged = this._photoChanged.bind(this);
    this._reset = this._reset.bind(this);
  }
  get photoInput() {
    return this.target.querySelector("[name='note-file']");
  }
  get photoSelection() {
    return this.target.querySelector(
      "[data-role='photo-selection']"
    );
  }
  async init() {
    await super.init();
    this.target.addEventListener("click", this._click);
    this.target.addEventListener("reset", this._reset);
    this.photoInput?.addEventListener("change", this._photoChanged);
    this._showPhoto(this.photoInput?.files?.[0]);
  }
  _click(event) {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest("[data-action='add-photo']")) {
      this.photoInput?.click();
    } else if (target.closest("[data-action='remove-photo']")) {
      this._clearPhoto();
    }
  }
  _photoChanged() {
    this._showPhoto(this.photoInput?.files?.[0]);
  }
  _reset() {
    queueMicrotask(() => this._clearPhoto());
  }
  _showPhoto(file) {
    if (!file) {
      this._clearPhoto(false);
      return;
    }
    this._revokePhotoUrl();
    this.photoUrl = URL.createObjectURL(file);
    const preview = this.target.querySelector(
      "[data-role='photo-preview']"
    );
    const name = this.target.querySelector("[data-role='photo-name']");
    if (preview) preview.src = this.photoUrl;
    if (name) name.textContent = file.name;
    if (this.photoSelection) this.photoSelection.dataset.visible = "true";
  }
  _clearPhoto(clearInput = true) {
    this._revokePhotoUrl();
    if (clearInput && this.photoInput) this.photoInput.value = "";
    const preview = this.target.querySelector("[data-role='photo-preview']");
    const name = this.target.querySelector("[data-role='photo-name']");
    if (preview) preview.removeAttribute("src");
    if (name) name.textContent = "";
    if (this.photoSelection) this.photoSelection.dataset.visible = "false";
  }
  _revokePhotoUrl() {
    if (this.photoUrl) URL.revokeObjectURL(this.photoUrl);
    this.photoUrl = null;
  }
  created() {
    super.created();
    this.target.reset();
  }
  offline() {
    return {
      action: "create",
      kind: "note"
    };
  }
  destroy() {
    this.target.removeEventListener("click", this._click);
    this.target.removeEventListener("reset", this._reset);
    this.photoInput?.removeEventListener("change", this._photoChanged);
    this._revokePhotoUrl();
    super.destroy();
  }
}

var note = /*#__PURE__*/Object.freeze({
	__proto__: null,
	CreateNote: CreateNote
});

class PageForm extends FormWidget {
  constructor(attributes) {
    super(attributes);
    this.formSelect = null;
  }
  get submitGroup() {
    return this.target.querySelector("[data-role='submit-group']");
  }
  get nameElement() {
    if (this.schema?.find((elt) => elt.id === "name")) return null;
    return new InputElement(
      { kind: "page", readonly: this.readonly },
      {
        input: "text",
        id: "name",
        title: "Name",
        placeholder: "name this page..."
      },
      this.target.dataset.name || ""
    ).elt;
  }
  get descriptionElement() {
    if (this.schema?.find((elt) => elt.id === "description")) return null;
    return new TextareaElement(
      { kind: "page", readonly: this.readonly },
      {
        input: "textarea",
        id: "description",
        title: "Description",
        placeholder: "describe this page..."
      },
      this.target.dataset.description || ""
    ).elt;
  }
  get formSelectElement() {
    return this._facetElement('[data-action="select-form"]');
  }
  get relatedFormsElement() {
    const section = this.target.querySelector('[data-role="related-forms"]');
    if (!section || this.readonly) return section;
    const controller = new AbortController();
    const signal = controller.signal;
    const setSelected = (formId = null) => {
      section.querySelectorAll("[data-role='related-form']").forEach((badge) => {
        badge.dataset.selected = Boolean(
          formId && badge.dataset.formId === formId
        ).toString();
      });
    };
    section.querySelectorAll("[data-role='related-form']").forEach((badge) => {
      badge.addEventListener(
        "click",
        (e) => {
          e.preventDefault();
          e.stopPropagation();
          const details = this._relatedFormDetails(badge);
          if (!details?.id || !this.formSelect) return;
          this.formSelect.select?.values?.clear();
          this.formSelect.addOption(details);
          setSelected(details.id);
        },
        { signal }
      );
    });
    this.target.addEventListener(
      "updated",
      (e) => {
        const detail = e.detail;
        if (detail?.name !== "form") return;
        const details = Object.values(detail.options || {})[0];
        setSelected(details?.id || null);
      },
      { signal }
    );
    this.target.addEventListener(
      "change",
      (e) => {
        const target = e.target;
        if (target?.name !== "form") return;
        setSelected(target.value || null);
      },
      { signal }
    );
    setSelected(this.formSelect?.details?.id || null);
    this.destroyables.push({
      destroy: () => controller.abort()
    });
    return section;
  }
  get categoriesElement() {
    return this._facetElement('[data-role="categories"]');
  }
  get autofillElement() {
    return sections.autofill(this);
  }
  get prepend() {
    let imageControls = this.target.querySelector(
      "[data-role='photo-prompt']"
    );
    if (this.revisionPreview) {
      imageControls?.remove();
      imageControls = null;
    } else if (imageControls) {
      this.view?._syncPhotoControls?.(void 0, imageControls);
    }
    return [imageControls, this.nameElement, this.descriptionElement];
  }
  get append() {
    return [
      this.formSelectElement,
      this.categoriesElement,
      this.autofillElement
    ];
  }
  _facetElement(selector) {
    const target = this.target.querySelector(selector);
    if (!target) return null;
    const control = SectionToggle.facet(this, target);
    control.init();
    this.destroyables.push(control);
    if (target.matches('[data-action="select-form"]')) {
      this.formSelect = control;
    }
    return control.elt;
  }
  _relatedFormDetails(badge) {
    try {
      return JSON.parse(badge.dataset.details || "{}");
    } catch {
      return {};
    }
  }
}
class PageInfo extends PageForm {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: `Update Page`,
      submitting: `Updating Page`,
      submitted: `Page Updated`,
      queued: "Queued Sync"
    };
    this._changeForm = this._changeForm.bind(this);
  }
  async init() {
    await super.init();
    this.target.addEventListener("updated", this._changeForm);
  }
  async prepareReset(options = {}) {
    const afterInit = options.afterInit;
    await super.prepareReset({
      ...options,
      afterInit: async (widget) => {
        await afterInit?.(widget);
        widget.target.addEventListener("updated", widget._changeForm);
      }
    });
  }
  async reset() {
    await this.prepareReset();
    this.commitReset();
  }
  offline({ data, method, route }) {
    return {
      id: `update:page:${this.key}`,
      action: "update",
      kind: "page",
      method,
      route,
      target_key: this.key,
      data
    };
  }
  handleOfflineQueue({ phase, record }) {
    if (record?.kind !== "page" || record.target_key !== this.key) return;
    if (phase === "queued") {
      this.form?.queued();
      this.setEntityMetadata();
    } else if (phase === "conflict") {
      this._offlineConflict = {
        record,
        response: record.conflictResponse
      };
      return this.stageOfflineConflict();
    } else if (phase === "replayed") {
      this.form?.success();
      this.setEntityMetadata();
    }
  }
  async _changeForm(e) {
    const target = e.target;
    if (!(target instanceof Element) || !target.closest("[data-role='form-select']"))
      return;
    e.stopPropagation();
    const initialTarget = this.initialTarget;
    if (!initialTarget) return;
    const formSelect = initialTarget.querySelector(
      "[data-action='select-form']"
    );
    const preloadedForm = JSON.parse(
      formSelect?.dataset.preload || "{}"
    );
    const selectedForm = Object.values(
      e.detail?.options || {}
    )[0];
    if (!selectedForm?.id) return;
    if (selectedForm.id === preloadedForm?.id) return;
    const route = this.target.dataset.route;
    if (!route) return;
    this.target.classList.add("opacity-50", "pointer-events-none");
    const params = new URLSearchParams();
    params.set("form", selectedForm.id);
    const response = await request.get(route, params);
    if (!this.view.successfulResponse(response, this.component ?? null) || !response) {
      this.target.classList.remove("opacity-50", "pointer-events-none");
      captureError(new Error("Failed to replace form"), this.target, {
        requestedForm: selectedForm
      });
      return;
    }
    this.schema = response.schema ?? null;
    this.submission = response.submission ?? null;
    initialTarget.dataset.formGeneration = String(response.generation || 0);
    const nextFormSelect = initialTarget.querySelector(
      '[data-action="select-form"]'
    );
    if (nextFormSelect)
      nextFormSelect.dataset.preload = JSON.stringify(selectedForm);
    await this.prepareReset();
    await withTransition(
      () => {
        this.commitReset();
        this.target.dataset.visible = "true";
      },
      { label: "page-info:change-form" }
    );
  }
  postreconcile() {
    super.postreconcile();
    this.setEntityMetadata();
  }
}
class CreatePage extends PageForm {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Create Page",
      submitting: "Creating Page",
      submitted: "Page Created"
    };
  }
  async init() {
    await super.init();
    const name = this.target.querySelector("input[name='name']");
    if (name) name.required = true;
  }
  get html() {
    return [
      this.nameElement,
      this.descriptionElement,
      this.formSelectElement,
      this.relatedFormsElement,
      this.categoriesElement,
      this.autofillElement
    ];
  }
  get prepend() {
    return [];
  }
  get append() {
    return [];
  }
  async prereconcile() {
    await super.prereconcile();
    if (this._created) await this.prepareReset();
  }
  postreconcile() {
    const created = this._created;
    if (created) this.commitReset();
    super.postreconcile();
    if (created) {
      this.form?.resetSubmitButton();
    }
    const nameElement = this.target.querySelector("input[name='name']");
    if (this.visible && nameElement) nameElement.focus();
  }
}

var pageInfo = /*#__PURE__*/Object.freeze({
	__proto__: null,
	CreatePage: CreatePage,
	PageForm: PageForm,
	PageInfo: PageInfo
});

const PUBLIC_DIRECTORY_ROOT = "__public_pages__";
const VISIBILITY = {
  public: "This page is public. It can be viewed at this URL: ",
  private: "This page is private."
};
class DocumentSettings extends FormWidget {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Update Public Page",
      submitting: "Updating",
      submitted: "Updated"
    };
  }
  get publicSettings() {
    try {
      return JSON.parse(this.target?.dataset.publicSettings || "{}");
    } catch {
      return {};
    }
  }
  get previewImages() {
    try {
      return JSON.parse(this.target?.dataset.previewImages || "[]");
    } catch {
      return [];
    }
  }
  get directoryCategories() {
    try {
      return JSON.parse(this.target?.dataset.directoryCategories || "[]");
    } catch {
      return [];
    }
  }
  get url() {
    return this.target?.dataset.url || null;
  }
  get formData() {
    const data = super.formData;
    if (data.get("directory-category") === PUBLIC_DIRECTORY_ROOT) {
      data.set("directory-category", "");
    }
    return data;
  }
  set url(value) {
    if (!this.target) return;
    if (value) {
      this.target.dataset.url = value;
    } else {
      delete this.target.dataset.url;
    }
  }
  get statusElement() {
    const status = document.createElement("p");
    status.className = "font-base font-semibold text-base-dark";
    if (this.url) {
      const a = document.createElement("a");
      a.dataset.kind = this.kind;
      a.className = STYLES.link.default;
      a.href = this.url;
      a.textContent = this.url;
      status.append(`${VISIBILITY.public}`, a, ".");
    } else {
      status.textContent = VISIBILITY.private;
    }
    return status;
  }
  get visibilityGroupElement() {
    const visibilityGroup = document.createElement("fieldset");
    visibilityGroup.className = "flex flex-row gap-4";
    const options = [
      { label: "Public", value: "public", checked: !!this.url },
      { label: "Private", value: "private", checked: !this.url }
    ];
    options.forEach((option) => {
      visibilityGroup.appendChild(
        primitives.radio({
          label: option.label,
          name: "visibility",
          value: option.value,
          checked: option.checked,
          required: true,
          kind: this.kind
        })
      );
    });
    return visibilityGroup;
  }
  get discoveryElement() {
    const settings = this.publicSettings;
    const wrapper = document.createElement("div");
    wrapper.className = "flex flex-col gap-3 border-t border-base-light/60 pt-4";
    const heading = document.createElement("h3");
    heading.className = "font-semibold text-base-dark";
    heading.textContent = "Public discovery and sharing preview";
    const siteState = document.createElement("p");
    siteState.className = "text-sm text-base-medium";
    siteState.textContent = this.target?.dataset.siteIndexing === "true" ? "Site discovery is on. This page can opt out or choose how it is grouped in the public directory." : "Site discovery is off. These settings will be ready if it is enabled later.";
    const marker = document.createElement("input");
    marker.type = "hidden";
    marker.name = "public-settings-present";
    marker.value = "true";
    const indexing = primitives.checkbox({
      label: "Allow this page to appear in search results",
      name: "allow-indexing",
      value: "true",
      checked: settings.allow_indexing !== false,
      kind: this.kind
    });
    const title = primitives.input({
      label: "Public title (optional)",
      name: "public-title",
      value: settings.title || "",
      placeholder: "Uses the page name when blank",
      kind: this.kind
    });
    const titleInput = title.querySelector("input");
    if (titleInput) titleInput.maxLength = 120;
    const description = primitives.textarea({
      label: "Public description (optional)",
      name: "public-description",
      value: settings.description || "",
      placeholder: "Uses an excerpt from the document when blank",
      rows: 3,
      kind: this.kind
    });
    const descriptionInput = description.querySelector("textarea");
    if (descriptionInput) descriptionInput.maxLength = 300;
    const directoryCategory = primitives.select({
      label: "Public directory category",
      name: "directory-category",
      kind: this.kind,
      data: {
        preload: JSON.stringify([
          {
            id: settings.directory_category || PUBLIC_DIRECTORY_ROOT
          }
        ])
      },
      options: [
        {
          label: "Public Pages",
          value: PUBLIC_DIRECTORY_ROOT,
          selected: !settings.directory_category
        },
        ...this.directoryCategories.map((category) => ({
          label: category.name,
          value: category.id,
          selected: category.id === settings.directory_category
        }))
      ]
    });
    directoryCategory.dataset.role = "directory-category";
    const directoryCategorySelect = new SelectBox(directoryCategory);
    directoryCategorySelect.init();
    this.destroyables.push(directoryCategorySelect);
    const categoryGuidance = document.createElement("p");
    categoryGuidance.className = "text-sm text-base-medium";
    categoryGuidance.textContent = "Choosing a category publishes that category name in the directory. Only categories already attached to this page are available.";
    const directoryOrder = primitives.input({
      label: "Public directory order (optional)",
      name: "directory-order",
      type: "number",
      value: settings.directory_order != null ? String(settings.directory_order) : "",
      placeholder: "Leave blank to sort alphabetically (1 shows first)",
      kind: this.kind
    });
    const orderInput = directoryOrder.querySelector("input");
    if (orderInput) {
      orderInput.min = "1";
      orderInput.max = "9999";
      orderInput.step = "1";
    }
    wrapper.append(
      heading,
      siteState,
      marker,
      indexing,
      title,
      description,
      directoryCategory,
      categoryGuidance,
      directoryOrder
    );
    const previews = this.previewPickerElement;
    if (previews) wrapper.append(previews);
    return wrapper;
  }
  get previewPickerElement() {
    const images = this.previewImages;
    if (!images.length) return null;
    const selected = this.publicSettings.preview_image_asset || "";
    const fieldset = document.createElement("fieldset");
    fieldset.className = "flex flex-col gap-2";
    const legend = document.createElement("legend");
    legend.className = "mb-2 font-semibold text-base-dark";
    legend.textContent = "Sharing preview image";
    fieldset.append(legend);
    const options = [
      {
        name: "",
        url: this.target.dataset.siteImage,
        alt: "Site image"
      },
      ...images
    ];
    const grid = document.createElement("div");
    grid.className = "grid grid-cols-2 gap-3 sm:grid-cols-3";
    for (const option of options) {
      const choice = primitives.radio({
        label: option.name ? option.alt || "Document image" : "Site image",
        name: "preview-image-asset",
        value: option.name,
        checked: option.name === selected,
        kind: this.kind
      });
      choice.classList.add(
        "flex-col",
        "items-start",
        "rounded-md",
        "border",
        "border-base-light/70",
        "p-2"
      );
      const image = document.createElement("img");
      image.src = option.url;
      image.alt = option.alt || "";
      image.className = "aspect-video w-full rounded object-cover";
      choice.prepend(image);
      grid.append(choice);
    }
    fieldset.append(grid);
    return fieldset;
  }
  get html() {
    return [
      this.statusElement,
      this.visibilityGroupElement,
      this.discoveryElement
    ];
  }
  updated(response) {
    super.updated(response);
    const updatedTarget = (response.html || null)?.querySelector(
      `[data-widget='${this.name}']`
    );
    if (updatedTarget) {
      this.url = updatedTarget.dataset.url || null;
      for (const name of [
        "publicSettings",
        "previewImages",
        "directoryCategories",
        "siteIndexing",
        "siteImage"
      ]) {
        if (updatedTarget.dataset[name] !== void 0) {
          this.target.dataset[name] = updatedTarget.dataset[name];
        }
      }
    }
  }
}

var documentSettings = /*#__PURE__*/Object.freeze({
	__proto__: null,
	DocumentSettings: DocumentSettings
});

class PagePermissions extends FormWidget {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Save Restrictions",
      submitting: "Saving Restrictions",
      submitted: "Restrictions Saved"
    };
  }
}

var pagePermissions = /*#__PURE__*/Object.freeze({
	__proto__: null,
	PagePermissions: PagePermissions
});

class PagePhoto extends BaseUpload {
  constructor(attributes) {
    super(attributes);
    this.dropzone = uploadElement.dropzone({
      element: this.target.querySelector("[data-role='dropzone']")
    });
    this.inputName = "page-photo";
    this.uploadType = "image";
    this.aiCreate = this.target.dataset.aiCreate === "true";
    this.menuOptions = [
      "remove",
      "replace",
      ...this.aiCreate ? ["generate"] : [],
      "paste"
    ];
    this.uploadMenu = new UploadMenu(this);
    this.generateForm = this.aiCreate ? sections.generateImageForm() : null;
    this.submitGroup = this.generateForm?.submitGroup;
    this.messages = {
      submit: "Generate",
      submitting: "Thinking...",
      submitted: "Done"
    };
    this.icon = "generate";
    this._generateImage = this._generateImage.bind(this);
  }
  get html() {
    return [
      this.dropzone.element,
      ...this.generateForm ? [this.generateForm.element] : []
    ];
  }
  get fileAttached() {
    return super.fileAttached || this.dropzone.containsImage;
  }
  get feedback() {
    return this.dropzone.element.querySelector(
      "[data-role='feedback']"
    );
  }
  get existingImage() {
    return this.dropzone.element.querySelector(
      "[data-role='existing-image']"
    );
  }
  get newImage() {
    return this.dropzone.element.querySelector(
      "[data-role='new-image']"
    );
  }
  async init() {
    await super.init();
    if (this.readonly) return;
    if (this.aiCreate) {
      this.submitGroup?.addEventListener("click", (e) => {
        if (e.target instanceof Element && e.target.closest("[data-role='cancel']")) {
          void this.view.cancelPhotoGeneration(this);
        }
      });
      this.target.addEventListener("submit", this._generateImage);
    }
  }
  shouldAutoUpload() {
    return true;
  }
  async autoUpload() {
    await this.uploadImage();
  }
  _replaceDropzone(html) {
    this.reset();
    const newDropzone = html.querySelector(
      "[data-role='dropzone']"
    );
    if (!newDropzone) return;
    newDropzone.querySelectorAll("img[src]").forEach((image) => {
      const source = image.getAttribute("src");
      if (!source || /^(blob|data):/.test(source)) return;
      const url = new URL(source, window.location.href);
      url.searchParams.set("v", Date.now().toString());
      const refreshedSource = url.origin === window.location.origin ? `${url.pathname}${url.search}${url.hash}` : url.href;
      image.setAttribute("src", refreshedSource);
    });
    this.dropzone.element.replaceWith(newDropzone);
    this.dropzone = uploadElement.dropzone({
      element: newDropzone
    });
    this.uploadMenu.destroy();
    this.uploadMenu = new UploadMenu(this);
    this.reset();
    this._initDropZone();
    if (this.uploadMenu) this.uploadMenu.create();
  }
  async uploadImage() {
    return this._withImageMutation(async () => {
      withTransition(() => {
        const existingImage = this.existingImage;
        const newImage = this.newImage;
        if (existingImage) existingImage.dataset.visible = "false";
        if (newImage) newImage.dataset.visible = "true";
        this.feedback?.replaceChildren(createIcon("spinner"), " Uploading...");
      });
      const prepared = await this.prepareSubmit({
        route: this.endpoints.upload
      });
      if (!prepared) return;
      const response = await request.post(this.endpoints.upload, this.formData);
      if (!this.view.successfulResponse(response, this.component) || !response?.html)
        return;
      const { html } = response;
      await this.view.updatePhotoImage(true, () => {
        this._replaceDropzone(html);
      });
    });
  }
  async _withImageMutation(operation) {
    if (this.view.photoBusy || this.readonly) return;
    this.view.setPhotoBusy(true);
    this.target.inert = true;
    try {
      return await operation();
    } finally {
      this.target.inert = false;
      this.view.setPhotoBusy(false);
    }
  }
  removeFile() {
    this.reset();
    this._removeImage();
  }
  async _removeImage() {
    return this._withImageMutation(async () => {
      const response = await request.delete(this.endpoints.remove);
      if (!this.view.successfulResponse(response, this.component) || !response?.html)
        return;
      const { html } = response;
      await this.view.updatePhotoImage(false, () => {
        this._replaceDropzone(html);
      });
    });
  }
  async _generateImage() {
    return this._withImageMutation(async () => {
      const response = await request.post(
        this.endpoints.generate,
        this.formData
      );
      if (!this.view.successfulResponse(response, this.component) || !response?.html)
        return;
      const { html } = response;
      await this.view.updatePhotoImage(true, () => {
        this._replaceDropzone(html);
        this.hideGenerateForm({ transition: false });
      });
    });
  }
  reset() {
    super.reset();
    this.generateForm?.reset();
    this.hideError();
  }
  showError(message) {
    withTransition(() => {
      if (this.generateForm?.visible()) {
        this.form.showError(message);
      } else {
        const newImage = this.newImage;
        const existingImage = this.existingImage;
        if (newImage) newImage.dataset.visible = "true";
        if (existingImage) {
          existingImage.dataset.visible = String(this.dropzone.containsImage);
        }
        const error = document.createElement("span");
        error.className = "text-delete text-base italic";
        error.textContent = message;
        if (this.dropzone.containsImage) {
          if (newImage) newImage.dataset.visible = "false";
          error.dataset.role = "image-error";
          this.dropzone.element.querySelector("[data-role='image-error']")?.remove();
          this.dropzone.element.append(error);
        } else this.feedback?.replaceChildren(error);
      }
    });
  }
  hideError() {
    this.dropzone.element.querySelector("[data-role='image-error']")?.remove();
    if (this.generateForm?.visible()) {
      this.form.hideError();
    } else {
      const feedback = this.feedback;
      if (feedback)
        feedback.innerHTML = "drop image here<br>or click to upload";
    }
  }
  showGenerateForm({ transition = true } = {}) {
    const generateForm = this.generateForm;
    if (!this.aiCreate || this.readonly || !generateForm) return;
    if (generateForm.visible()) {
      generateForm.show();
      return;
    }
    this.view.photoGenerationReturnOpen ??= this.view.photoOpen;
    const show = () => {
      this.reset();
      this.dropzone.hide();
      generateForm.show();
      this.form.showSubmitButton();
    };
    const shouldTransition = transition && (this.view.isSecondaryCardVisible?.(this.component.elt) ?? true);
    if (shouldTransition) {
      return withTransition(show);
    }
    show();
  }
  hideGenerateForm({ transition = true } = {}) {
    const hide = () => {
      this.reset();
      this.generateForm?.hide();
      this.dropzone.show();
      this.view.photoGenerationReturnOpen = null;
    };
    const shouldTransition = transition && (this.view.isSecondaryCardVisible?.(this.component.elt) ?? true);
    if (shouldTransition) {
      return withTransition(hide);
    }
    hide();
  }
}

var pagePhoto = /*#__PURE__*/Object.freeze({
	__proto__: null,
	PagePhoto: PagePhoto
});

export { pagePermissions as a, pagePhoto as b, documentSettings as d, note as n, pageInfo as p };
