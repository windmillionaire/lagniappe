/*! Third-party licenses: /third-party-licenses.txt */
import { S as STYLES, c as createIcon, s as setIcon } from './ui-resources.js?v=b1ee16b4';
import { E as ENDPOINTS, r as request, w as withTransition } from './foundation.js?v=b1ee16b4';
import './connectivity.js?v=b1ee16b4';
import { p as primitives, b as buttons } from './ui-controls.js?v=b1ee16b4';
import { F as FormController } from './forms.js?v=b1ee16b4';
import { d as directUpload } from './directUpload.js?v=b1ee16b4';
import { D as Dropdown } from './combobox.js?v=b1ee16b4';

const DEFAULT_DROPZONE_TEXT = "Drop file here, click to upload, or tap to choose camera/files";
const visibility = () => {
  const group = document.createElement("fieldset");
  group.className = "flex flex-row items-center gap-4";
  group.name = "visibility";
  const options = [
    { text: "Public", value: "public", checked: false },
    { text: "Private", value: "private", checked: false }
  ];
  options.forEach((option) => {
    group.appendChild(
      primitives.radio({
        ...option,
        name: "visibility",
        required: true
      })
    );
  });
  return group;
};
const hiddenFileInput = (widget) => {
  const hiddenInput = document.createElement("input");
  hiddenInput.name = `${widget.inputName}`;
  hiddenInput.type = "file";
  hiddenInput.className = "hidden";
  hiddenInput.accept = "*/*";
  hiddenInput.multiple = Boolean(widget.multiple);
  return {
    element: hiddenInput,
    clear: () => {
      hiddenInput.value = "";
    }
  };
};
const mimeType = () => {
  const mimeTypeInput = document.createElement("input");
  mimeTypeInput.type = "hidden";
  mimeTypeInput.name = "mimetype";
  return {
    element: mimeTypeInput,
    clear: () => {
      mimeTypeInput.value = "";
    }
  };
};
const access = () => {
  const accessGroup = document.createElement("div");
  accessGroup.className = `${STYLES.upload.options} hidden`;
  accessGroup.dataset.role = "access";
  const accessHeader = accessGroup.appendChild(document.createElement("h3"));
  accessHeader.className = `${STYLES.upload.header} -mb-2`;
  accessHeader.textContent = "Access";
  const accessText = accessGroup.appendChild(document.createElement("p"));
  accessText.innerHTML = "Public files can be viewed by anyone on the web with the address.<br />Private files can only be viewed by logged-in users with permission to view this page.";
  accessText.className = "sm:text-sm text-base-dark";
  accessGroup.appendChild(visibility());
  return accessGroup;
};
const processing = ({ aiCreate = true } = {}) => {
  const optionsContainer = document.createElement("div");
  optionsContainer.dataset.role = "options";
  optionsContainer.dataset.visible = "false";
  optionsContainer.className = STYLES.upload.options;
  const optionsHeader = optionsContainer.appendChild(
    document.createElement("h3")
  );
  optionsHeader.className = `${STYLES.upload.header} -mb-2`;
  optionsHeader.textContent = "Further Processing";
  const editName = primitives.input({
    name: "display-name",
    type: "text",
    label: "Edit File Name",
    kind: "file",
    data: {
      role: "display-name"
    }
  });
  optionsContainer.appendChild(editName);
  const extract = primitives.checkbox({
    name: "extract",
    label: "Extract text (OCR)",
    visible: false
  });
  const searchText = primitives.checkbox({
    name: "search-text",
    label: "Add file text to search index",
    visible: false
  });
  const summarize = primitives.checkbox({
    name: "summarize",
    label: "Summarize file content",
    visible: false
  });
  const searchSummary = primitives.checkbox({
    name: "search-summary",
    label: "Add file summary to search index",
    visible: false
  });
  const options = optionsContainer.appendChild(document.createElement("div"));
  options.dataset.role = "processing";
  options.className = STYLES.upload.processing;
  options.append(
    extract,
    searchText,
    ...aiCreate ? [summarize, searchSummary] : []
  );
  const setOptionVisibility = (element, visible) => {
    element.dataset.visible = visible ? "true" : "false";
  };
  const resetOptionVisibility = () => {
    [extract, searchText, summarize, searchSummary].forEach((element) => {
      setOptionVisibility(element, false);
    });
  };
  const setDisplayNameVisibility = (visible) => {
    const input = editName.querySelector("input");
    editName.dataset.visible = visible ? "true" : "false";
    if (input) {
      input.disabled = !visible;
      if (!visible) input.value = "";
    }
  };
  const prefill = ({
    filename,
    isTextFile,
    fileCount = 1
  }) => {
    const singleFile = fileCount <= 1;
    const input = editName.querySelector("input");
    if (input) input.value = singleFile ? filename || "" : "";
    setDisplayNameVisibility(singleFile);
    optionsContainer.dataset.visible = "true";
    resetOptionVisibility();
    if (isTextFile) {
      setOptionVisibility(searchText, true);
      if (aiCreate) setOptionVisibility(summarize, true);
    } else {
      setOptionVisibility(extract, true);
      if (aiCreate) setOptionVisibility(summarize, true);
    }
  };
  options.addEventListener("change", (event) => {
    const { target } = event;
    if (!(target instanceof HTMLInputElement)) return;
    if (target.name === "extract") {
      searchText.dataset.visible = target.checked ? "true" : "false";
    }
    if (target.name === "summarize") {
      searchSummary.dataset.visible = target.checked ? "true" : "false";
    }
  });
  return {
    element: optionsContainer,
    prefill,
    show: () => {
      optionsContainer.dataset.visible = "true";
    },
    hide: () => {
      optionsContainer.dataset.visible = "false";
    },
    clear: () => {
      const input = editName.querySelector("input");
      if (input) input.value = "";
      setDisplayNameVisibility(true);
      options.querySelectorAll("input[type='checkbox']").forEach((cb) => {
        cb.checked = false;
      });
      resetOptionVisibility();
      optionsContainer.dataset.visible = "false";
    }
  };
};
const menuButton = () => {
  const menuButtonContainer = document.createElement("div");
  menuButtonContainer.dataset.role = "upload-menu";
  menuButtonContainer.className = "absolute top-2 right-2";
  const menuButton2 = menuButtonContainer.appendChild(
    document.createElement("button")
  );
  menuButton2.className = "size-7 flex items-center justify-center rounded-md opacity-30 bg-base-default text-white";
  menuButton2.type = "button";
  menuButton2.replaceChildren(createIcon("dropdown"));
  return menuButtonContainer;
};
const contextDescription = (settings = {}) => {
  const description = document.createElement("textarea");
  description.className = `${STYLES.textarea} grow h-24 placeholder:text-center`;
  description.name = settings.name || "autofill-description";
  if (settings.placeholder) description.placeholder = settings.placeholder;
  if (settings.rows) description.rows = settings.rows;
  return description;
};
const contextUpload = (settings = {}) => {
  const container = document.createElement("div");
  container.className = "flex flex-col gap-1";
  if (settings.label !== false) {
    const header = primitives.label({
      label: settings.label || "Autofill Context",
      tag: "h3"
    });
    container.appendChild(header);
  }
  const context = container.appendChild(document.createElement("div"));
  context.dataset.role = "context";
  context.className = settings.stacked ? "flex flex-col gap-3" : STYLES.upload.contextRow;
  const dropzoneElement = dropzone({ text: settings.text });
  const description = contextDescription({
    name: settings.descriptionName,
    placeholder: settings.descriptionPlaceholder,
    rows: settings.descriptionRows
  });
  context.append(dropzoneElement.element);
  context.append(description);
  return {
    element: container,
    dropzone: dropzoneElement,
    description,
    clear: () => {
      dropzoneElement.clear();
      description.value = "";
    }
  };
};
const dropzone = (options) => {
  const { text = DEFAULT_DROPZONE_TEXT, element = null } = options;
  let dropzone2;
  let textElement;
  if (!element) {
    dropzone2 = document.createElement("div");
    dropzone2.dataset.role = "dropzone";
    dropzone2.className = STYLES.upload.dropzone;
    textElement = dropzone2.appendChild(document.createElement("p"));
    textElement.innerHTML = text || "";
  } else {
    dropzone2 = element;
  }
  let menu = dropzone2.querySelector("[data-role='upload-menu']");
  if (!menu) {
    menu = menuButton();
    dropzone2.appendChild(menu);
  }
  return {
    element: dropzone2,
    menuButton: menu,
    get containsImage() {
      return dropzone2.querySelector("img") !== null;
    },
    clear: () => {
      if (element) return;
      if (textElement) textElement.innerHTML = text || "";
    },
    setText: (newText) => {
      if (element) return;
      if (textElement) textElement.textContent = newText;
    },
    setContent: (...children) => {
      textElement?.replaceChildren(...children);
    },
    hide: () => {
      dropzone2.dataset.visible = "false";
    },
    show: () => {
      dropzone2.dataset.visible = "true";
    }
  };
};
class UploadMenu {
  constructor(instance) {
    this.instance = instance;
    this.dropdown = null;
    this.itemBuilders = {
      remove: () => this._buildRemove(),
      replace: () => this._buildReplace(),
      generate: () => this._buildGenerate(),
      paste: () => this._buildPaste()
    };
  }
  get button() {
    return this.instance.dropzone?.menuButton ?? null;
  }
  get options() {
    return this.instance.menuOptions ?? [];
  }
  get items() {
    return this.options.map((option) => {
      const build = this.itemBuilders[option];
      return typeof build === "function" ? build() : null;
    }).filter((item) => item !== null);
  }
  create() {
    const button = this.button;
    if (!button) return;
    const items = this.items;
    if (this.dropdown && this.dropdown.parent !== button) {
      this.dropdown.destroy();
      this.dropdown = null;
    }
    if (this.dropdown) {
      this.dropdown.updateOptions(items);
      return;
    }
    const toolbarPortalClass = button.closest?.("[data-role='toolbar']") ? ` ${STYLES.editor.toolbar.portalIconContext}` : "";
    this.dropdown = new Dropdown(button).init({
      items,
      placement: "bottom-end",
      styles: {
        panel: `${STYLES.dropdown.panel}${toolbarPortalClass}`
      }
    });
  }
  _buildRemove() {
    if (!this.instance.fileAttached) return null;
    return {
      name: "Remove",
      icon: "delete",
      kind: "delete",
      onClick: () => this.instance.removeFile()
    };
  }
  _buildReplace() {
    return {
      name: "Replace",
      icon: "replace",
      kind: "default",
      onClick: () => this.instance.replaceFile()
    };
  }
  _buildGenerate() {
    return {
      name: "Generate",
      icon: "generate",
      kind: this.instance.kind || "default",
      onClick: () => this.instance.showGenerateForm?.()
    };
  }
  _buildPaste() {
    return {
      name: "Paste",
      icon: "paste",
      kind: "default",
      onClick: () => this.instance.processPaste()
    };
  }
  destroy() {
    this.dropdown?.destroy();
    this.dropdown = null;
  }
}
const generateDocumentImage = () => {
  const container = document.createElement("div");
  container.dataset.role = "generate-image";
  container.className = "flex flex-col gap-4";
  container.dataset.visible = "false";
  const prompt = container.appendChild(
    primitives.textarea({
      name: "prompt",
      placeholder: "Describe the image you wish to create (or leave blank to generate an illustration for this document's content)",
      rows: 3})
  );
  const submitGroup = container.appendChild(document.createElement("div"));
  submitGroup.dataset.role = "submit-group";
  submitGroup.className = "flex flex-wrap gap-2 w-full";
  submitGroup.appendChild(
    buttons.submit({
      role: "cancel",
      text: "Cancel",
      kind: "editor",
      type: "button"
    })
  );
  const submitButton = submitGroup.appendChild(
    buttons.submit({
      role: "generate",
      kind: "editor",
      type: "submit"
    })
  );
  return {
    element: container,
    submitGroup,
    submitButton,
    messages: {
      submit: "Generate",
      submitting: "Thinking...",
      submitted: "Done"
    },
    icon: "generate",
    reset: () => {
      container.dataset.visible = "false";
      prompt.value = "";
    },
    visible: () => {
      return container.dataset.visible === "true";
    },
    hide: () => {
      container.dataset.visible = "false";
    },
    show: () => {
      container.dataset.visible = "true";
      prompt.focus();
    }
  };
};
const uploadElement = {
  dropzone,
  contextDescription,
  hiddenFileInput,
  mimeType,
  access,
  processing,
  menuButton,
  contextUpload,
  generateDocumentImage
};

const PASTE_ERROR = "File detected in clipboard but not accessible. Try pressing Cmd+V (Mac) or Ctrl+V (Windows/Linux) to paste instead.";
const CLIPBOARD_ERROR = "Couldn't access clipboard.";
const CLIPBOARD_PERMISSION_ERROR = "Clipboard permission denied.";
const CLIPBOARD_ACCESS_NOT_AVAILABLE_ERROR = "Clipboard access not available.";
const CLIPBOARD_NO_FILE_ERROR = "No valid file found in clipboard.";
const DROP_ERROR = (error) => `Error dropping file: ${errorMessage(error)}`;
const PROCESS_NEW_FILE_ERROR = (error) => `Error processing file: ${errorMessage(error)}`;
const FILE_TOO_LARGE_ERROR = (fileSizeMB, maxSizeMB) => `File is too large (${fileSizeMB}MB). Maximum file size is ${maxSizeMB}MB.`;
const IMAGE_LOAD_ERROR = (error) => `Failed to load image: ${errorMessage(error)}`;
const IMAGE_PROCESS_ERROR = `Failed to process image`;
const NOT_IMAGE_ERROR = "This upload only accepts images. Choose an image file (for example PNG, JPEG, or WebP).";
const DIRECT_UPLOAD_FALLBACK_LIMIT = 30 * 1024 * 1024;
const DIRECT_UPLOAD_FALLBACK_MAX_FILES = 5;
const DEFAULT_FILE_UPLOAD_LIMIT = 2 * 1024 * 1024 * 1024;
const DEFAULT_IMAGE_UPLOAD_LIMIT = 100 * 1024 * 1024;
const DIRECT_UPLOAD_REQUIRED_ERROR = "This file is too large for the compatibility upload path. Please try again.";
const INDIVIDUAL_FILES_ONLY_ERROR = "Only individual files are supported";
function errorMessage(error) {
  return typeof error === "object" && error !== null && "message" in error ? error.message : void 0;
}
async function containsDroppedDirectory(dataTransfer, files = Array.from(dataTransfer?.files || [])) {
  const items = Array.from(dataTransfer?.items || []).filter(
    (item) => item.kind === "file"
  );
  for (const item of items) {
    const entry = item.webkitGetAsEntry?.();
    if (entry?.isDirectory) return true;
    if (!entry && "getAsFileSystemHandle" in item && typeof item.getAsFileSystemHandle === "function") {
      try {
        const handle = await item.getAsFileSystemHandle();
        if (handle && typeof handle === "object" && "kind" in handle && handle.kind === "directory") {
          return true;
        }
      } catch (_error) {
      }
    }
  }
  return files.some((file) => file.size === 0 && !file.type);
}
function isLikelyImageFile(file) {
  if (file.type?.startsWith("image/")) return true;
  if (file.type && file.type !== "application/octet-stream") return false;
  const name = (file.name || "").toLowerCase();
  return /\.(png|jpe?g|gif|webp|bmp|svg|heic|heif|avif|ico|tiff?)$/.test(name);
}
function mimeToExtension(mimeType) {
  if (!mimeType) return "bin";
  const map = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "text/plain": "txt"
  };
  if (map[mimeType]) return map[mimeType];
  const [, sub] = mimeType.split("/");
  if (!sub) return "bin";
  const base = sub.split("+")[0];
  return base.replace(/[^a-z0-9]/gi, "") || "bin";
}
function defaultClipboardFilename(mimeType) {
  return `paste-${Date.now()}.${mimeToExtension(mimeType)}`;
}
function resolvedClipboardFileName(blob, typeHint) {
  const mime = blob.type || typeHint;
  if ("name" in blob && typeof blob.name === "string") {
    const name = blob.name.trim();
    if (name.includes(".")) return name;
  }
  return defaultClipboardFilename(mime);
}
class BaseUpload {
  constructor(attributes) {
    Object.assign(this, attributes);
    this.maxWidth = 1280;
    this.maxHeight = 720;
    this.destroyables = [];
    this.keyboardPaste = this._keyboardPaste.bind(this);
    this.windowFocus = this._windowFocus.bind(this);
    this.directUploads = [];
    this.directUploadSignature = null;
    this.directUploadSelectionSignature = null;
  }
  async init() {
    this.form = new FormController(this);
    await this.form.init();
    if (this.readonly) {
      this.dropzone?.menuButton?.remove();
      return;
    }
    this._initDropZone();
    this._initFileInput();
    if (this.uploadMenu) this.uploadMenu.create();
    window.addEventListener("focus", this.windowFocus);
    window.addEventListener("paste", this.keyboardPaste);
  }
  get formData() {
    const data = this.target instanceof HTMLFormElement ? new FormData(this.target) : new FormData();
    return this.applyDirectUploads(data);
  }
  _windowFocus() {
    this.fileDialogOpen = false;
  }
  _initFileInput() {
    if (this.fileInput) return;
    this.fileInput = uploadElement.hiddenFileInput(this);
    this.form.target.appendChild(this.fileInput.element);
    this.mimeType = uploadElement.mimeType();
    this.form.target.appendChild(this.mimeType.element);
    const input = this.fileInput.element;
    input.addEventListener("change", () => {
      const files = input.files;
      if (files && files.length > 0) {
        this._processNewFiles(files, {
          source: "select",
          preserveExisting: false
        });
      }
      this.fileDialogOpen = false;
    });
  }
  _processImage(file) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      const objectUrl = URL.createObjectURL(file);
      img.onload = () => {
        URL.revokeObjectURL(objectUrl);
        const canvas = document.createElement("canvas");
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          reject(new Error(IMAGE_PROCESS_ERROR));
          return;
        }
        const scale = Math.min(
          this.maxWidth / img.width,
          this.maxHeight / img.height,
          1
        );
        const width = Math.round(img.width * scale);
        const height = Math.round(img.height * scale);
        canvas.width = width;
        canvas.height = height;
        ctx.fillStyle = "#FFFFFF";
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(img, 0, 0, width, height);
        canvas.toBlob(
          (blob) => {
            if (!blob) {
              reject(new Error(IMAGE_PROCESS_ERROR));
              return;
            }
            resolve(
              new File([blob], file.name, {
                type: file.type,
                lastModified: Date.now()
              })
            );
          },
          file.type,
          0.92
        );
      };
      img.onerror = (event) => {
        URL.revokeObjectURL(objectUrl);
        reject(new Error(IMAGE_LOAD_ERROR(errorMessage(event))));
      };
      img.src = objectUrl;
    });
  }
  get filename() {
    const file = this.fileInput.element.files?.[0];
    if (!file) return "";
    const name = file.name;
    const extensionIndex = name.lastIndexOf(".");
    return extensionIndex > 0 ? name.substring(0, extensionIndex) : name;
  }
  get textFileAttached() {
    return this.fileInput.element.files?.[0]?.type.startsWith("text/") ?? false;
  }
  get fileAttached() {
    return (this.fileInput?.element.files?.length ?? 0) > 0;
  }
  get fileLabel() {
    const files = Array.from(this.fileInput?.element.files || []);
    if (files.length === 0) return "";
    if (files.length === 1) return this.filename;
    return `${files.length} files selected`;
  }
  onFileAccepted(_file, _context) {
  }
  shouldAutoUpload(_file, _context) {
    return typeof this.uploadImage === "function";
  }
  async autoUpload(file, context) {
    if (typeof this.uploadImage === "function") {
      return this.uploadImage(file, context);
    }
  }
  applyDefaultAttachUI(_file, context) {
    if (this.dropzone) {
      this.dropzone.setText(context.filename);
    }
    this.form?.showSubmitButton();
  }
  onFileAttached(_file, _context) {
  }
  get directUploadRoute() {
    return this.route || this.target?.dataset?.route || this.endpoints?.upload;
  }
  get uploadLimit() {
    if (this.maxFileSize) return this.maxFileSize;
    return this.uploadType === "image" ? DEFAULT_IMAGE_UPLOAD_LIMIT : DEFAULT_FILE_UPLOAD_LIMIT;
  }
  get uploadLimitLabel() {
    return Math.round(this.uploadLimit / (1024 * 1024));
  }
  currentFileSignature() {
    return Array.from(this.fileInput?.element?.files || []).map(
      (file) => [file.name, file.size, file.type, file.lastModified].join(":")
    ).join("|");
  }
  applyDirectUploads(data) {
    if (!this.directUploads?.length) return data;
    data.delete(this.inputName);
    data.set(
      "direct_uploads",
      JSON.stringify(
        this.directUploads.map(({ _fileSignature, ...record }) => record)
      )
    );
    return data;
  }
  _canFallbackToMultipart(files) {
    return files.length <= DIRECT_UPLOAD_FALLBACK_MAX_FILES && files.reduce((total, file) => total + file.size, 0) <= DIRECT_UPLOAD_FALLBACK_LIMIT;
  }
  _directUploadFileSignature(file, index) {
    return [index, file.name, file.size, file.type, file.lastModified].join(
      ":"
    );
  }
  _updateDirectUploadProgress(file, loaded, total) {
    const percent = total ? Math.round(loaded / total * 100) : 0;
    const name = file.name || "file";
    this.dropzone?.setText(`Uploading ${name} - ${percent}%`);
  }
  async prepareSubmit({ route = null } = {}) {
    const files = Array.from(this.fileInput?.element?.files || []);
    if (!files.length) {
      this.directUploads = [];
      this.directUploadSignature = null;
      this.directUploadSelectionSignature = null;
      return true;
    }
    const signature = this.currentFileSignature();
    if (this.directUploadSignature === signature && this.directUploads.length) {
      return true;
    }
    const uploadRoute = route || this.directUploadRoute;
    if (!uploadRoute) {
      if (this._canFallbackToMultipart(files)) return true;
      this.showError(DIRECT_UPLOAD_REQUIRED_ERROR);
      return false;
    }
    const reusable = this.directUploadSelectionSignature === signature ? new Map(
      this.directUploads.map((record) => [record._fileSignature, record])
    ) : /* @__PURE__ */ new Map();
    const completed = [];
    let activeFile = null;
    try {
      for (const [index, file] of files.entries()) {
        if (!file.size) continue;
        activeFile = file;
        const fileSignature = this._directUploadFileSignature(file, index);
        const existing = reusable.get(fileSignature);
        if (existing) {
          completed.push(existing);
          continue;
        }
        const session = await directUpload.createSession({
          route: uploadRoute,
          file,
          inputName: this.inputName
        });
        const metadata = await directUpload.upload({
          file,
          sessionUrl: session.session_url,
          chunkSize: session.chunk_size,
          onProgress: (loaded, total) => {
            this._updateDirectUploadProgress(file, loaded, total);
          }
        });
        completed.push({
          _fileSignature: fileSignature,
          token: session.token,
          input_name: this.inputName,
          filename: file.name,
          content_type: file.type || "application/octet-stream",
          size: file.size,
          generation: metadata.generation,
          path: metadata.name
        });
      }
    } catch {
      this.directUploads = completed;
      this.directUploadSignature = null;
      this.directUploadSelectionSignature = signature;
      if (this._canFallbackToMultipart(files)) {
        this.directUploads = [];
        this.directUploadSelectionSignature = null;
        return true;
      }
      const filename = activeFile?.name || "one of the selected files";
      this.showError(
        `Could not upload ${filename}. Try again; completed uploads will be kept.`
      );
      return false;
    }
    this.directUploads = completed;
    this.directUploadSignature = signature;
    this.directUploadSelectionSignature = signature;
    return true;
  }
  async _processNewFile(file, options = {}) {
    const source = options.source || "unknown";
    const maxFileSize = this.uploadLimit;
    if (file.size > maxFileSize) {
      const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
      this.showError(FILE_TOO_LARGE_ERROR(fileSizeMB, this.uploadLimitLabel));
      return;
    }
    if (this.uploadType === "image" && !isLikelyImageFile(file)) {
      this.showError(NOT_IMAGE_ERROR);
      this.fileInput?.clear();
      return;
    }
    let processed = file;
    if (this.uploadType === "image") {
      try {
        processed = await this._processImage(file);
      } catch (error) {
        this.showError(PROCESS_NEW_FILE_ERROR(error));
        return;
      }
    }
    const dataTransfer = new DataTransfer();
    if (this.multiple && options.preserveExisting !== false) {
      Array.from(this.fileInput.element.files || []).forEach((existing) => {
        dataTransfer.items.add(existing);
      });
    }
    dataTransfer.items.add(processed);
    this.fileInput.element.files = dataTransfer.files;
    this.directUploads = [];
    this.directUploadSignature = null;
    this.directUploadSelectionSignature = null;
    this.uploadMenu?.create();
    this.hideError();
    const context = {
      source,
      originalFile: file,
      file: processed,
      filename: this.multiple ? this.fileLabel : this.filename,
      isTextFile: this.textFileAttached,
      mimeType: file.type || ""
    };
    this.mimeType.element.value = context.mimeType;
    this.onFileAccepted(processed, context);
    if (this.shouldAutoUpload(processed, context)) {
      await this.autoUpload(processed, context);
    } else {
      this.applyDefaultAttachUI(processed, context);
    }
    this.onFileAttached(processed, context);
  }
  async _processNewFiles(files, options = {}) {
    const selected = Array.from(files || []);
    if (!this.multiple) {
      if (selected[0]) await this._processNewFile(selected[0], options);
      return;
    }
    let preserveExisting = options.preserveExisting;
    for (const file of selected) {
      await this._processNewFile(file, {
        ...options,
        preserveExisting
      });
      if (preserveExisting === false) preserveExisting = true;
    }
  }
  _initDropZone() {
    if (!this.dropzone) return;
    this.dropzone.element.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    });
    this.dropzone.element.addEventListener("drop", async (event) => {
      event.preventDefault();
      try {
        const files = Array.from(event.dataTransfer?.files || []);
        if (await containsDroppedDirectory(event.dataTransfer, files)) {
          this.showError(INDIVIDUAL_FILES_ONLY_ERROR);
          return;
        }
        if (files.length > 0) {
          await this._processNewFiles(files, { source: "drop" });
        }
      } catch (error) {
        this.showError(DROP_ERROR(error));
      }
    });
    this.dropzone.element.addEventListener("click", (e) => {
      const target = e.target;
      if (this.fileDialogOpen || !target || !("closest" in target) || typeof target.closest !== "function" || target.closest("[data-role='upload-menu']")) {
        return;
      }
      if (target.closest('[data-role="dropzone"]')) {
        e.preventDefault();
        e.stopPropagation();
        this.fileDialogOpen = true;
        this.fileInput.element.click();
      }
    });
  }
  async processPaste() {
    const processFile = async (item, type) => {
      const blob = await item.getType(type);
      const fileName = resolvedClipboardFileName(blob, type);
      const file = new File([blob], fileName, { type: blob.type || type });
      await this._processNewFile(file, { source: "paste" });
    };
    try {
      const clipboardItems = await navigator.clipboard.read();
      if (clipboardItems.length > 0) {
        const imageTypes = ["image/png", "image/jpeg", "image/webp"];
        const item = clipboardItems[0];
        for (const type of imageTypes) {
          if (item.types.includes(type)) {
            await processFile(item, type);
            return;
          }
        }
        if (item.types && item.types.length > 0) {
          const type = item.types[0];
          await processFile(item, type);
        } else {
          this.showError(PASTE_ERROR);
        }
        this.pasteActive = true;
        setTimeout(() => {
          this.pasteActive = false;
        }, 3e3);
      } else {
        this.showError(CLIPBOARD_NO_FILE_ERROR);
      }
    } catch (error) {
      const name = error && typeof error === "object" && "name" in error ? error.name : void 0;
      if (name === "NotAllowedError") {
        this.showError(CLIPBOARD_PERMISSION_ERROR);
      } else if (name === "SecurityError") {
        this.showError(CLIPBOARD_ACCESS_NOT_AVAILABLE_ERROR);
      } else {
        this.showError(CLIPBOARD_ERROR);
      }
    }
  }
  _keyboardPaste(event) {
    if (!this.pasteActive) return;
    event.preventDefault();
    if (!event.clipboardData?.files?.length) {
      this.showError(CLIPBOARD_NO_FILE_ERROR);
      this.pasteActive = false;
      return;
    }
    const file = event.clipboardData.files[0];
    if (file) {
      const mime = file.type || "application/octet-stream";
      const nameOk = typeof file.name === "string" && file.name.trim() && file.name.includes(".");
      const toProcess = nameOk ? file : new File([file], defaultClipboardFilename(mime), {
        type: file.type,
        lastModified: file.lastModified
      });
      this._processNewFile(toProcess, { source: "keyboard-paste" });
    } else {
      this.showError(CLIPBOARD_NO_FILE_ERROR);
    }
    this.pasteActive = false;
  }
  replaceFile() {
    this.fileDialogOpen = true;
    this.fileInput.element.click();
  }
  reset() {
    this.directUploads = [];
    this.directUploadSignature = null;
    this.directUploadSelectionSignature = null;
    this.fileInput?.clear();
    this.mimeType?.clear();
    this.dropzone?.clear();
    this.form?.resetSubmitButton();
    this.form?.hideSubmitButton();
  }
  removeFile() {
    this.reset();
  }
  hideError() {
    this.form.hideError();
  }
  showError(message) {
    this.form.showError(message);
  }
  destroy() {
    this.uploadMenu?.destroy();
    this.form?.destroy();
    window.removeEventListener("focus", this.windowFocus);
    window.removeEventListener("paste", this.keyboardPaste);
    this.destroyables.forEach((destroyable) => {
      if (destroyable.destroy) destroyable.destroy();
    });
    this.destroyables = [];
  }
}

const UPLOAD_DROPZONE_TEXT = "Drop file/photo here, click to upload, or tap to choose camera/files";
function isTaskAsset(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const data = { ...value };
  return ["key", "id", "name", "filename", "kind", "url", "delete_url"].every(
    (key) => data[key] == null || typeof data[key] === "string"
  ) && (data.attached == null || typeof data.attached === "boolean");
}
function taskAssets(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const entries = Object.entries(value).filter(
    (entry) => isTaskAsset(entry[1])
  );
  return Object.fromEntries(entries);
}
class TaskUpload extends BaseUpload {
  constructor(button, widget) {
    super({
      button,
      action: button.dataset.action
    });
    this.widget = widget;
    this.target = document.createElement("div");
    this.target.className = "w-full flex flex-col gap-2 group/upload";
    this.target.dataset.visible = "false";
    this.button.insertAdjacentElement("afterend", this.target);
    const preload = JSON.parse(button.dataset.preload || "{}");
    this.assets = taskAssets(preload);
    this.task = button.closest("[lp-component]");
    this.taskRow = button.closest(
      "li[lp-entity][data-kind='task']"
    );
    this.key = this.taskRow?.dataset.key || widget?.key;
    this.endpoints = this.key ? ENDPOINTS.TaskUpload({ key: this.key }) : {};
    this.assetsInput = this._assetsInput();
    this.assetsList = this._assetsList();
    this.kind = "file";
    this.inputName = "task-file";
    this.uploadType = "file";
    this.messages = {
      submit: "Attach File/Photo",
      submitting: "Attaching File/Photo",
      submitted: "File/Photo Attached"
    };
    this.dropzone = uploadElement.dropzone({ text: UPLOAD_DROPZONE_TEXT });
    this.menuOptions = ["replace", "paste"];
    this.uploadMenu = new UploadMenu(this);
    this.toggle = null;
    this._deleteFile = this._deleteFile.bind(this);
  }
  get html() {
    return [this.assetsInput, this.dropzone.element, this.assetsList];
  }
  get formData() {
    const data = new FormData();
    const file = this.fileInput?.element.files?.[0];
    if (file) data.append(this.inputName, file);
    if (this.mimeType?.element) {
      data.append(this.mimeType.element.name, this.mimeType.element.value);
    }
    this._syncAssetsInput();
    data.append(this.assetsInput.name, this.assetsInput.value);
    return this.applyDirectUploads(data);
  }
  async init() {
    await super.init();
    this.toggle?.display();
    this.assetsList.addEventListener("click", this._deleteFile);
    this.renderAssets();
  }
  _assetsInput() {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = "assets";
    input.value = JSON.stringify(this.assets || {});
    return input;
  }
  _assetsList() {
    const list = document.createElement("ul");
    list.dataset.role = "saved-files";
    list.dataset.kind = "file";
    list.className = "outline-2 outline-kind-default rounded-md divide-y-kind-light bg-kind-bg w-full";
    return list;
  }
  _syncAssetsInput() {
    this.assetsInput.value = JSON.stringify(this.assets || {});
  }
  _deleteUrl(file) {
    if (file.delete_url) return file.delete_url;
    const key = file.key || file.id;
    if (!key || !file.attached || !this.taskRow) return null;
    return this.endpoints.remove?.(key) ?? null;
  }
  _deleteButton(file) {
    const name = file.name || file.filename || "attachment";
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.role = "delete-task-file";
    button.dataset.kind = "delete";
    button.dataset.active = "false";
    button.dataset.route = this._deleteUrl(file) || "";
    button.className = STYLES.toggle.container;
    button.setAttribute("aria-label", `Delete ${name}`);
    button.title = `Delete ${name}`;
    const active = button.appendChild(document.createElement("span"));
    setIcon(active, "trash.active", STYLES.toggle.icon.active);
    const inactive = button.appendChild(document.createElement("span"));
    setIcon(inactive, "trash.inactive", STYLES.toggle.icon.inactive);
    return button;
  }
  _fileUrl(file) {
    if (file.url) return file.url;
    if (file.kind === "file" && file.id) return `/files/${file.id}`;
    return "#";
  }
  _assetItem([name, file]) {
    const label = file.name || file.filename || name;
    const item = document.createElement("li");
    item.dataset.key = file.key || file.id || "";
    item.dataset.kind = "file";
    item.className = "flex flex-row items-center justify-between gap-4 p-4 rounded-md bg-base-bg";
    const link = item.appendChild(document.createElement("a"));
    link.href = this._fileUrl(file);
    link.dataset.kind = "file";
    link.className = STYLES.link.title;
    link.textContent = label;
    item.appendChild(this._deleteButton(file));
    return item;
  }
  renderAssets() {
    this._syncAssetsInput();
    const entries = Object.entries(this.assets || {});
    this.assetsList.dataset.visible = entries.length > 0 ? "true" : "false";
    this.assetsList.replaceChildren(
      ...entries.map((entry) => this._assetItem(entry))
    );
  }
  shouldAutoUpload() {
    return true;
  }
  async autoUpload() {
    await this.uploadFile();
  }
  async uploadFile() {
    const route = this.endpoints.upload;
    if (!route) {
      this.showError("Upload route unavailable");
      return;
    }
    this.dropzone.setContent(createIcon("spinner"), " Uploading...");
    const prepared = await this.prepareSubmit({ route });
    if (!prepared) return;
    const response = await request.post(
      route,
      this.formData
    );
    if (!response?.ok) {
      this.showError(response?.error || "Could not upload attachment");
      return;
    }
    withTransition(() => {
      this.assets = taskAssets(response.assets);
      this.renderAssets();
      this.reset();
    });
  }
  _removeBadge(file) {
    if (!this.task || !file) return;
    const labels = new Set([file.name, file.filename].filter(Boolean));
    const url = this._fileUrl(file);
    const urls = new Set(url === "#" ? [] : [url]);
    this.task.querySelectorAll("[data-kind='file']").forEach((badge) => {
      if (badge.closest("[data-role='saved-files']")) return;
      const link = badge.querySelector("a");
      const text = badge.textContent?.trim();
      const href = link?.getAttribute("href");
      if (text && labels.has(text) || href && urls.has(href)) {
        badge.remove();
      }
    });
  }
  async _deleteFile(e) {
    const button = e.target instanceof Element ? e.target.closest("[data-role='delete-task-file']") : null;
    if (!button) return;
    e.preventDefault();
    e.stopPropagation();
    const item = button.closest("[data-kind='file']");
    const key = item?.dataset.key;
    const file = Object.values(this.assets || {}).find(
      (asset) => (asset.key || asset.id) === key
    );
    const route = button.dataset.route;
    if (!route) {
      if (key) {
        this.assets = Object.fromEntries(
          Object.entries(this.assets || {}).filter(
            ([, asset]) => (asset.key || asset.id) !== key
          )
        );
      }
      this.renderAssets();
      return;
    }
    const data = new FormData();
    data.append("assets", JSON.stringify(this.assets || {}));
    button.disabled = true;
    const response = await request.delete(route, data);
    button.disabled = false;
    if (!response?.ok) {
      this.showError(response?.error || "Could not delete attachment");
      return;
    }
    withTransition(() => {
      this.assets = taskAssets(response.assets);
      this.renderAssets();
      this._removeBadge(
        isTaskAsset(response.deleted) ? response.deleted : file
      );
    });
  }
  toggleVisibility() {
    this.target.dataset.visible = this.target.dataset.visible === "true" ? "false" : "true";
  }
  reset() {
    super.reset();
  }
  clear() {
    this.reset();
    this.toggle?.display();
  }
  showError(message) {
    super.showError(message);
  }
  hideError() {
    super.hideError();
  }
  destroy() {
    this.assetsList.removeEventListener("click", this._deleteFile);
    super.destroy();
  }
}

const AI_DROPZONE_TEXT = "Drop files here, click to upload, or paste a screenshot.";
class CreateToolReport extends BaseUpload {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Start",
      submitting: "Starting",
      submitted: "Started"
    };
    this.icon = "generate";
    this.uploadType = "file";
    this.inputName = "tool-files";
    this.multiple = true;
    this.header = this.target.querySelector(
      "[data-role='header']"
    );
    this.submitGroup = this.target.querySelector(
      "[data-role='submit-group']"
    );
    this.submitButton = this.target.querySelector(
      "[data-role='start-report']"
    );
    this.emailSubmissions = this.target.querySelector(
      "[data-role='email-submissions']"
    );
    this.emailAddress = this.target.querySelector(
      "[data-role='email-address']"
    );
    this.emailCopyButton = this.target.querySelector(
      "[data-role='email-copy']"
    );
    this.autoExecuteControl = this.target.querySelector(
      "[data-role='auto-execute-control']"
    );
    this.context = uploadElement.contextUpload({
      text: AI_DROPZONE_TEXT,
      label: false,
      descriptionName: "instructions",
      descriptionPlaceholder: "Ask a question or describe what you want done\u2026",
      descriptionRows: 5,
      stacked: true
    });
    this.dropzone = this.context.dropzone;
    this.menuOptions = ["remove", "replace", "paste"];
    this.uploadMenu = new UploadMenu(this);
  }
  async init() {
    await super.init();
    this.context.description?.addEventListener("input", () => {
      this.form?.showSubmitButton();
    });
    this.emailCopyButton?.addEventListener("click", () => {
      void this.copyEmailAddress();
    });
    this.dropzone?.show();
  }
  get html() {
    return [this.context.element, this.autoExecuteControl];
  }
  async copyEmailAddress() {
    const button = this.emailCopyButton;
    const address = this.emailAddress?.textContent?.trim();
    if (!button || !address) return;
    let copied = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(address);
        copied = true;
      }
    } catch {
      copied = false;
    }
    if (!copied) {
      const textarea = document.createElement("textarea");
      textarea.value = address;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.append(textarea);
      textarea.select();
      try {
        copied = document.execCommand("copy");
      } catch {
        copied = false;
      }
      textarea.remove();
      button.focus();
    }
    button.textContent = copied ? "Copied" : "Copy failed";
    clearTimeout(this.emailCopyResetTimer);
    this.emailCopyResetTimer = setTimeout(() => {
      if (button.isConnected) button.textContent = "Copy";
    }, 2e3);
  }
  applyDefaultAttachUI(_file, _context) {
    if (this.dropzone) this.dropzone.setText(this.fileLabel);
    this.form?.showSubmitButton();
  }
  async prepareSubmit(options = {}) {
    if (!this.context.description?.value?.trim() && !this.fileAttached) {
      this.showError("Add files or instructions before creating a report.");
      return false;
    }
    return super.prepareSubmit(options);
  }
  async created() {
    this.form.success();
    this.createdReport = true;
  }
  _resetUI() {
    this.context?.clear();
    this.dropzone?.show();
    const autoExecute = this.target.querySelector(
      "[name='auto_execute']"
    );
    if (autoExecute) {
      autoExecute.checked = autoExecute.dataset.defaultChecked === "true";
    }
    this.form?.hideSubmitButton();
  }
  reset() {
    super.reset();
    this._resetUI();
  }
  postreconcile() {
    if (this.createdReport) {
      this.reset();
      this.visible = false;
      this.target.dataset.visible = "false";
      this.createdReport = false;
    }
  }
}

var tools = /*#__PURE__*/Object.freeze({
	__proto__: null,
	CreateToolReport: CreateToolReport
});

const FILE_DROPZONE_TEXT = "Drop file here, click to upload, or tap to choose camera/files";
class FileUpload extends BaseUpload {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Upload File",
      submitting: "Uploading File",
      submitted: "File Uploaded"
    };
    this.inputName = "file-upload";
    this.multiple = true;
    this.dropzone = uploadElement.dropzone({ text: FILE_DROPZONE_TEXT });
    this.processing = uploadElement.processing({
      aiCreate: this.target.dataset.aiCreate === "true"
    });
    this.uploadType = "file";
    this.menuOptions = ["remove", "replace", "paste"];
    this.uploadMenu = new UploadMenu(this);
    this.submitButton = buttons.submit({
      kind: "file",
      data: {
        visible: "false"
      }
    });
  }
  get html() {
    return [this.dropzone.element, this.processing.element];
  }
  onFileAttached(...[_file, context]) {
    const fileCount = this.fileInput?.element.files?.length || 0;
    this.processing.prefill({
      filename: context.filename,
      isTextFile: context.isTextFile,
      fileCount
    });
  }
  reset() {
    super.reset();
    this.processing.clear();
  }
  created() {
    this._created = true;
  }
  postreconcile() {
    if (this._created) {
      this.reset();
    }
  }
}

var uploadFile = /*#__PURE__*/Object.freeze({
	__proto__: null,
	FileUpload: FileUpload
});

const INGRESS_DROPZONE_TEXT = "Drop a file here or click to upload. Only CSV files are supported.";
class IngressFileUpload extends BaseUpload {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Upload File",
      submitting: "Uploading",
      submitted: "Uploaded"
    };
    this.uploadType = "file";
    this.inputName = "ingress-file";
    this.dropzone = uploadElement.dropzone({
      text: INGRESS_DROPZONE_TEXT
    });
    this.submitButton = this.target.querySelector("button[type='submit']");
    this.menuOptions = ["paste"];
    this.uploadMenu = new UploadMenu(this);
  }
  get html() {
    return [this.dropzone.element];
  }
  async init() {
    await super.init();
    this.form.hideSubmitButton();
  }
  async created() {
    this.form.success();
    this.createdFile = true;
  }
  postreconcile() {
    if (this.createdFile) {
      super.reset();
      this.visible = false;
      this.target.dataset.visible = "false";
      this.createdFile = false;
    }
  }
}

var ingressUpload = /*#__PURE__*/Object.freeze({
	__proto__: null,
	IngressFileUpload: IngressFileUpload
});

export { BaseUpload as B, TaskUpload as T, UploadMenu as U, uploadFile as a, ingressUpload as i, tools as t, uploadElement as u };
