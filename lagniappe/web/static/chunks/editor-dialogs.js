/*! Third-party licenses: /third-party-licenses.txt */
import { F as FormController } from './forms.js?v=b6c361d7';
import { r as request, E as ENDPOINTS, w as withTransition } from './foundation.js?v=b6c361d7';
import { p as primitives, b as buttons } from './ui-controls.js?v=b6c361d7';
import { C as COLOR_MENU, F as FONT_MENU, I as IMAGE_GROUPS, T as ToolbarButton, r as runToolCommand, g as getMarkRange, n as normalizeLinkAttributes } from './document.js?v=b6c361d7';
import { S as STYLES } from './ui-resources.js?v=b6c361d7';
import { a as RemoteQueryCombobox, R as Results } from './combobox.js?v=b6c361d7';
import { Modal } from './modal.js?v=b6c361d7';
import { B as BaseUpload, u as uploadElement, U as UploadMenu } from './uploads.js?v=b6c361d7';

class PinVersion {
  constructor(toolbar) {
    this.toolbar = toolbar;
    this.name = "pinVersion";
    this.messages = {
      submit: "Pin Version",
      submitting: "Pinning Version...",
      name: "Please name this version"
    };
    this._active = false;
    this.submit = this.submit.bind(this);
  }
  get active() {
    return this._active;
  }
  set active(value) {
    this._active = value;
    if (value) this.focus();
  }
  init() {
    this.target = this.toolbar.element.appendChild(
      document.createElement("form")
    );
    this.target.className = `mt-4 hidden flex-col gap-4 rounded-md bg-slate-200 p-4 group-data-[open-form="pinVersion"]/toolbar:flex`;
    this.target.dataset.option = this.name;
    this.input = primitives.input({
      name: "name",
      placeholder: "Name this version",
      type: "text"
    });
    this.input.maxLength = 100;
    this.html = [this.input, buttons.submit({ kind: "editor" })];
    this.form = new FormController(this);
    this.form.init();
  }
  focus() {
    this.input?.focus();
    this.input?.select();
  }
  reset() {
    this.input.value = "";
    this.form?.resetSubmitButton();
  }
  async submit() {
    const name = this.input.value.trim();
    if (!name) {
      this.form.showError(this.messages.name);
      this.form.resetSubmitButton();
      return;
    }
    const endpoint = this.toolbar.endpoints?.history;
    const html = this.toolbar.editor.getHTML();
    const response = await request.post(`${endpoint}/pin`, { name, html });
    if (!response?.ok) {
      this.form.showError(response?.error || "Unable to pin this version");
      this.form.resetSubmitButton();
      return;
    }
    this.reset();
    await this.toolbar.closeForm(this.name);
    await this.toolbar.toggles.documentHistory?.refresh?.();
  }
  destroy() {
    this.form?.destroy();
  }
}

var pinVersion = /*#__PURE__*/Object.freeze({
	__proto__: null,
	pinVersion: PinVersion
});

class ColorPicker {
  constructor(toolbar) {
    this.toolbar = toolbar;
    this.name = "setColor";
    this.usedWithEditor = true;
    this.active = false;
    this.toggles = /* @__PURE__ */ new Map();
  }
  _colorSwatch(color, title) {
    const colorButton = document.createElement("button");
    colorButton.className = `size-6 rounded transition-transform hover:scale-110 hover:outline-2 hover:outline-offset-2 data-[active=true]:outline-2 data-[active=true]:outline-offset-2`;
    colorButton.style.backgroundColor = color;
    colorButton.style.outlineColor = color;
    colorButton.title = title;
    colorButton.dataset.active = "false";
    colorButton.dataset.color = color;
    return colorButton;
  }
  setActiveColor(activeColor) {
    this.toggles.forEach((toggle, color) => {
      const isActive = color === activeColor;
      if (isActive !== toggle.active) {
        toggle.button.dataset.active = isActive ? "true" : "false";
        toggle.active = isActive;
      }
    });
  }
  init() {
    const colorOptions = this.toolbar.element.appendChild(
      document.createElement("div")
    );
    colorOptions.dataset.option = this.name;
    colorOptions.className = `mt-4 hidden flex-row flex-wrap items-center gap-2 group-data-[open-form="setColor"]/toolbar:flex group`;
    COLOR_MENU.forEach(({ color, title }) => {
      const colorButton = this._colorSwatch(color, title);
      this.toggles.set(color, { active: false, button: colorButton });
    });
    colorOptions.append(
      ...Array.from(this.toggles.values()).map((toggle) => toggle.button)
    );
    this.active = true;
    colorOptions.addEventListener("click", (e) => {
      const colorButton = e.target?.closest("button");
      if (!colorButton) return;
      const color = colorButton.dataset.color;
      if (!color) return;
      const toggle = this.toggles.get(color);
      if (!toggle) return;
      const currentActive = Array.from(this.toggles.values()).find(
        (t) => t.active && t !== toggle
      );
      if (currentActive) {
        currentActive.active = false;
        currentActive.button.dataset.active = "false";
      }
      toggle.active = !toggle.active;
      colorButton.dataset.active = toggle.active ? "true" : "false";
      if (toggle.active) {
        this.toolbar.editor.chain().focus().setColor(color).run();
      } else {
        this.toolbar.editor.chain().focus().unsetColor().run();
      }
    });
  }
}

var setColor = /*#__PURE__*/Object.freeze({
	__proto__: null,
	setColor: ColorPicker
});

class FontFamilyPicker {
  constructor(toolbar) {
    this.toolbar = toolbar;
    this.name = "setFontFamily";
    this.usedWithEditor = true;
    this.active = false;
    this.toggles = /* @__PURE__ */ new Map();
  }
  _fontToggle(style, name) {
    const fontButton = document.createElement("button");
    fontButton.className = `cursor-pointer rounded bg-slate-200 px-3 py-1.5 text-base transition-transform hover:scale-110 hover:bg-slate-300 data-[active=true]:bg-slate-300 sm:text-sm`;
    fontButton.textContent = name;
    fontButton.dataset.style = style;
    fontButton.title = name;
    fontButton.dataset.active = "false";
    return fontButton;
  }
  setActiveFontStyle(activeFont) {
    this.toggles.forEach((toggle, style) => {
      const isActive = style === activeFont;
      if (isActive !== toggle.active) {
        toggle.button.dataset.active = isActive ? "true" : "false";
        toggle.active = isActive;
      }
    });
  }
  init() {
    const fontOptions = this.toolbar.element.appendChild(
      document.createElement("div")
    );
    fontOptions.dataset.option = this.name;
    fontOptions.className = `group mt-4 hidden flex-row flex-wrap items-center gap-2 group-data-[open-form="setFontFamily"]/toolbar:flex`;
    FONT_MENU.forEach(({ style, name }) => {
      const fontButton = this._fontToggle(style, name);
      this.toggles.set(style, { active: false, button: fontButton });
    });
    fontOptions.append(
      ...Array.from(this.toggles.values()).map((toggle) => toggle.button)
    );
    this.active = true;
    fontOptions.addEventListener("click", (e) => {
      const fontButton = e.target?.closest("button");
      if (!fontButton) return;
      const style = fontButton.dataset.style;
      if (!style) return;
      const toggle = this.toggles.get(style);
      if (!toggle) return;
      const currentActive = Array.from(this.toggles.values()).find(
        (t) => t.active && t !== toggle
      );
      if (currentActive) {
        currentActive.active = false;
        currentActive.button.dataset.active = "false";
      }
      toggle.active = !toggle.active;
      fontButton.dataset.active = toggle.active ? "true" : "false";
      if (toggle.active) {
        this.toolbar.editor.chain().focus().setFontFamily(style).run();
      } else {
        this.toolbar.editor.chain().focus().unsetFontFamily().run();
      }
    });
  }
}

var setFontFamily = /*#__PURE__*/Object.freeze({
	__proto__: null,
	setFontFamily: FontFamilyPicker
});

class ImageOptions {
  constructor(toolbar) {
    this.toolbar = toolbar;
    this.name = "setImage";
    this.usedWithEditor = true;
    this.active = false;
    this.toggles = {};
    this.imagePosition = null;
  }
  init() {
    const imageSettings = this.toolbar.element.appendChild(
      document.createElement("div")
    );
    imageSettings.dataset.option = this.name;
    imageSettings.dataset.position = "false";
    imageSettings.className = `${STYLES.editor.toolbar.imageSettings}`;
    IMAGE_GROUPS.forEach((group, index) => {
      const wrapper = imageSettings.appendChild(document.createElement("div"));
      wrapper.className = `${STYLES.editor.toolbar.tools}`;
      group.forEach((settings) => {
        const option = new ToolbarButton(this.toolbar);
        option.init(settings);
        option.onClick = () => this.toggleOption(option);
        this.toggles[String(option.name)] = option;
        if (option.name) {
          this.toolbar.options[option.name] = option;
        }
        wrapper.appendChild(option.button);
      });
      if (index < IMAGE_GROUPS.length - 1) {
        const divider = document.createElement("div");
        divider.className = `${STYLES.editor.toolbar.divider}`;
        imageSettings.appendChild(divider);
      }
    });
  }
  toggleOption(option) {
    const currentOption = Object.values(this.toggles).find(
      (toggle) => toggle.active && toggle.name
    );
    option.active = !option.active;
    option.active ? option.enable() : option.disable();
    currentOption?.disable();
    runToolCommand(
      this.toolbar.editor.chain(),
      option.command,
      option.args,
      true
    );
  }
}

var setImage = /*#__PURE__*/Object.freeze({
	__proto__: null,
	setImage: ImageOptions
});

const ABSOLUTE_URL_PATTERN = /^[a-z][a-z0-9+.-]*:/i;
const BARE_DOMAIN_PATTERN = /^[^\s/]+\.[^\s]+(?:\/.*)?$/;
class LinkSearchBox extends RemoteQueryCombobox {
  constructor(element, addLink) {
    super(element);
    this.addLink = addLink;
    this.index = "search";
    this.results = new Results(this.index);
    this.endpoints = ENDPOINTS.search;
    this.placement = "bottom-start";
  }
  init() {
    this.styles.panel = `${STYLES.dropdown.panel} ${STYLES.editor.toolbar.portalIconContext} w-64 sm:w-96 mt-2`;
    super.init();
  }
  _input(event) {
    const query = event.target.value.trim();
    if (this.addLink.linkHref(query)) {
      this.settleQueryInput({ clear: true });
      return;
    }
    if (query.length > 2) {
      return this._search(query);
    }
    this.settleQueryInput({ clear: true });
  }
  elementClick(event) {
    super.elementClick(event);
    if (!this.panelOpen && this.options.length > 0) this.showPanel();
  }
  _search(query) {
    const params = new URLSearchParams();
    params.set("q", query);
    return this.runQuery(
      query,
      (token) => request.get(this.endpoints.bar, params, {
        signal: token.signal
      }),
      (response) => {
        if (response?.ok) {
          this.updatePanel(response.results || null);
        } else {
          this.clearQueryResults();
        }
        return this.showPanel();
      }
    );
  }
  selectOption(option) {
    if (!option.dataset.url) return;
    this.results.save(option);
    this.hidePanel();
    this.addLink.applySearchResult(option.dataset.url);
  }
}
class AddLink {
  constructor(toolbar) {
    this.toolbar = toolbar;
    this.editor = toolbar.editor;
    this.submit = this.submit.bind(this);
    this.name = "addLink";
    this.messages = {
      select: "Please select some text first",
      link: "Please add a URL",
      submit: "Set Link"
    };
    this.usedWithEditor = false;
    this._onSelectionUpdate = this._onSelectionUpdate.bind(this);
    this._active = false;
    this.linkState = null;
    this.combobox = null;
  }
  get active() {
    return this._active;
  }
  set active(value) {
    this._active = value;
    if (value) {
      this.captureSelection();
      this.focus();
      this.editor.on("selectionUpdate", this._onSelectionUpdate);
    } else {
      this.editor.off("selectionUpdate", this._onSelectionUpdate);
      this.editor.commands.clearSelectionHighlight();
    }
  }
  get emailMode() {
    return this.toolbar.kind === "email";
  }
  _onSelectionUpdate() {
    if (this._active) {
      this.captureSelection();
    }
  }
  init() {
    this.target = this.toolbar.element.appendChild(
      document.createElement("form")
    );
    this.target.className = `mt-4 hidden flex-col gap-4 rounded-md bg-slate-200 p-4 group-data-[open-form="addLink"]/toolbar:flex`;
    this.target.dataset.option = this.name;
    this.link = primitives.input({
      name: "link",
      placeholder: "Paste URL or search...",
      type: "search"
    });
    this.combobox = new LinkSearchBox(this.link, this);
    const submit = buttons.submit({
      kind: "editor"
    });
    this.html = [this.link, submit];
    this.form = new FormController(this);
    this.form.init();
    this.form.destroyables.push(this.combobox);
    this.combobox.init();
  }
  focus() {
    this.link?.focus();
    this.link?.select();
  }
  captureSelection() {
    const { from, to } = this.editor.state.selection;
    if (from !== to) {
      this.editor.commands.setSelectionHighlight();
    } else {
      this.editor.commands.clearSelectionHighlight();
    }
    this.linkState = this.findCurrentLink();
    this.link.value = this.displayHref(this.linkState?.attrs?.href || "");
  }
  findCurrentLink() {
    const linkType = this.editor.state.schema.marks.link;
    if (!linkType) return null;
    const { selection } = this.editor.state;
    if (selection.empty) {
      const range = getMarkRange(selection.$from, linkType);
      return range ? this.singleLinkInRange(range) : null;
    }
    return this.singleLinkInRange({
      from: selection.from,
      to: selection.to
    });
  }
  singleLinkInRange(range) {
    const linkType = this.editor.state.schema.marks.link;
    const links = /* @__PURE__ */ new Map();
    this.editor.state.doc.nodesBetween(range.from, range.to, (node, pos) => {
      if (!node.isText) return true;
      const mark = node.marks.find((mark2) => mark2.type === linkType);
      if (!mark) return true;
      const key = JSON.stringify(mark.attrs);
      const from = Math.max(range.from, pos);
      const to = Math.min(range.to, pos + node.nodeSize);
      const link2 = links.get(key) || { attrs: mark.attrs, from, to };
      link2.from = Math.min(link2.from, from);
      link2.to = Math.max(link2.to, to);
      links.set(key, link2);
      return true;
    });
    const values = Array.from(links.values());
    if (values.length !== 1) return null;
    const link = values[0];
    return {
      attrs: link.attrs,
      range: { from: link.from, to: link.to }
    };
  }
  highlightRange() {
    return this.editor.commands.getSelectionHighlightRange();
  }
  activeRange() {
    return this.linkState?.range || this.highlightRange();
  }
  displayHref(href) {
    if (!href || !this.emailMode) return href;
    return this.fullyQualifiedUrl(href) || href;
  }
  linkHref(value) {
    const href = value.trim();
    if (!href) return "";
    if (this.emailMode) {
      return this.fullyQualifiedUrl(href);
    }
    if (ABSOLUTE_URL_PATTERN.test(href) || href.startsWith("//") || href.startsWith("/") || href.startsWith("#") || href.startsWith("?")) {
      return href;
    }
    if (BARE_DOMAIN_PATTERN.test(href)) {
      return `https://${href}`;
    }
    return null;
  }
  fullyQualifiedUrl(value) {
    const href = value.trim();
    if (!href) return "";
    try {
      if (ABSOLUTE_URL_PATTERN.test(href)) {
        return new URL(href).href;
      }
      if (href.startsWith("//")) {
        return new URL(`${window.location.protocol}${href}`).href;
      }
      if (href.startsWith("/") || href.startsWith("#") || href.startsWith("?")) {
        return new URL(href, window.location.origin).href;
      }
      return new URL(`https://${href}`).href;
    } catch (_error) {
      return null;
    }
  }
  linkAttributes(href) {
    if (this.emailMode) return { href };
    return normalizeLinkAttributes({ href });
  }
  applySearchResult(url) {
    const href = this.emailMode ? this.fullyQualifiedUrl(url) : url;
    if (!href) {
      this.form.showError(this.messages.link);
      return;
    }
    this.link.value = href;
    this.submit();
  }
  reset() {
    this.linkState = null;
    this.link.value = "";
    this.combobox?.hidePanel();
    this.form?.resetSubmitButton();
  }
  submit() {
    const range = this.activeRange();
    const href = this.linkHref(this.link.value);
    if (href && range) {
      this.editor.chain().focus().setTextSelection(range).setLink(this.linkAttributes(href)).run();
      this.form.resetSubmitButton();
      this.toolbar.closeForm(this.name);
    } else if (!this.link.value.trim() && range) {
      const linkRange = this.linkState?.range || this.singleLinkInRange(range)?.range;
      if (!linkRange) {
        this.form.showError(this.messages.link);
        return;
      }
      this.editor.chain().focus().setTextSelection(linkRange).unsetLink().run();
      this.form.resetSubmitButton();
      this.toolbar.closeForm(this.name);
    } else if (!range) {
      this.form.showError(this.messages.select);
    } else {
      this.form.showError(this.messages.link);
    }
  }
  destroy() {
    this.form?.destroy();
  }
}

var addLink = /*#__PURE__*/Object.freeze({
	__proto__: null,
	addLink: AddLink
});

const IMAGE_DROPZONE_TEXT = "Drop image here, click to upload, or tap to choose camera/files<br>All images will be sized down to 1280x720";
class Image extends BaseUpload {
  constructor(toolbar) {
    super();
    this.toolbar = toolbar;
    this.name = "addImage";
    this.inputName = "add-image";
    this.messages = {
      submit: "Upload Image",
      submitting: "Uploading Image",
      submitted: "Image Uploaded"
    };
    this.uploadType = "image";
    this.target = this.toolbar.element.appendChild(
      document.createElement("form")
    );
    this.target.dataset.mode = "upload";
    this.target.className = `mt-4 hidden flex-col gap-4 rounded-md bg-slate-200 p-4 group-data-[open-form="addImage"]/toolbar:flex group/upload`;
    this.target.dataset.option = this.name;
    this.dropzone = uploadElement.dropzone({ text: IMAGE_DROPZONE_TEXT });
    this.menuOptions = [
      "remove",
      ...this.toolbar.aiCreate ? ["generate"] : [],
      "paste"
    ];
    this.uploadMenu = new UploadMenu(this);
    this.generate = uploadElement.generateDocumentImage();
    this.submitButton = buttons.submit({
      kind: "editor"
    });
    this.submit = this.submit.bind(this);
  }
  get html() {
    return [
      this.dropzone.element,
      ...this.toolbar.aiCreate ? [this.generate.element] : [],
      this.submitButton
    ];
  }
  async init() {
    await super.init();
    this.submitButton.dataset.visible = "false";
    this.target.addEventListener("click", (e) => {
      if (e.target?.closest("[data-role='cancel']")) {
        this.hideGenerateForm();
      }
    });
  }
  showGenerateForm() {
    withTransition(() => {
      this.dropzone.hide();
      this.reset();
      this.form.toggleSubForm(this.generate);
      this.generate.show();
    });
  }
  hideGenerateForm() {
    withTransition(() => {
      this.form.toggleSubForm(null);
      this.generate.hide();
      this.generate.reset();
      this.dropzone.show();
    });
  }
  reset() {
    this.generate.reset();
    super.reset();
  }
  async submit(submitter) {
    if (this.toolbar.document.addDraftImage) {
      const file = this.fileInput?.element?.files?.[0];
      if (!file) return;
      const src = this.toolbar.document.addDraftImage(file);
      this.toolbar.editor.chain().focus().setImage({ src }).run();
      this.toolbar.toggleForm(this.name);
      return;
    }
    const route = this.toolbar.endpoints?.addImage;
    if (!route) return;
    const prepared = await this.prepareSubmit({ route });
    if (!prepared) return;
    const formData = new FormData(this.target);
    this.applyDirectUploads(formData);
    formData.append("role", submitter?.dataset?.role || "upload");
    formData.append("content", this.toolbar.editor.getText());
    if (submitter) submitter.disabled = true;
    const response = await request.post(route, formData);
    if (submitter) submitter.disabled = false;
    if (response?.ok && response.modal) {
      const modal = new Modal(this.toolbar.builder);
      void modal.attach(response.modal, this);
    } else if (response?.ok && response.src) {
      this.toolbar.editor.chain().focus().setImage({ src: response.src }).run();
      this.toolbar.toggleForm(this.name);
    } else if (response?.error) {
      this.form.showError(response.error);
      this.reset();
    }
  }
}

var addImage = /*#__PURE__*/Object.freeze({
	__proto__: null,
	addImage: Image
});

class AddYouTube {
  constructor(toolbar) {
    this.toolbar = toolbar;
    this.submit = this.submit.bind(this);
    this.endpoints = toolbar.endpoints;
    this.name = "addYouTube";
    this.messages = {
      url: "Please add a YouTube URL",
      submit: "Add YouTube Video"
    };
    this._active = false;
  }
  get active() {
    return this._active;
  }
  set active(value) {
    this._active = value;
    this.link.focus();
  }
  init() {
    this.target = this.toolbar.element.appendChild(
      document.createElement("form")
    );
    this.target.className = `mt-4 hidden flex-col gap-4 rounded-md bg-slate-200 p-4 group-data-[open-form="addYouTube"]/toolbar:flex`;
    this.target.dataset.option = this.name;
    this.link = primitives.input({
      name: "url",
      placeholder: "YouTube URL...",
      type: "url"
    });
    const submit = buttons.submit({
      kind: "editor"
    });
    this.html = [this.link, submit];
    this.form = new FormController(this);
    this.form.init();
  }
  submit() {
    const url = this.link.value;
    if (url) {
      this.toolbar.editor.chain().focus().setYoutubeVideo({ src: url }).run();
      this.form.resetSubmitButton();
      this.toolbar.toggleForm(this.name);
      this.link.value = "";
    } else {
      this.form.showError(this.messages.url);
    }
  }
}

var addYouTube = /*#__PURE__*/Object.freeze({
	__proto__: null,
	addYouTube: AddYouTube
});

class GenerateText {
  constructor(toolbar) {
    this.toolbar = toolbar;
    this.submit = this.submit.bind(this);
    this.editor = toolbar.editor;
    this.endpoints = toolbar.endpoints;
    this.name = "generateText";
    this.messages = {
      prompt: "Please describe the text you'd like to generate.",
      submit: "Generate",
      submitting: "Thinking...",
      submitted: "Text Generated"
    };
    this.submitButton = buttons.submit({
      kind: "editor"
    });
    this.usedWithEditor = true;
    this._onSelectionUpdate = this._onSelectionUpdate.bind(this);
    this._active = false;
    this._capturedRange = null;
  }
  get active() {
    return this._active;
  }
  set active(value) {
    this._active = value;
    if (value) {
      this._captureSelection();
      this.prompt.focus();
      this.toolbar.editor.on("selectionUpdate", this._onSelectionUpdate);
    } else {
      this.toolbar.editor.off("selectionUpdate", this._onSelectionUpdate);
      this.toolbar.editor.commands.clearSelectionHighlight();
      this._capturedRange = null;
    }
  }
  _onSelectionUpdate() {
    if (this._active) {
      this.toolbar.editor.commands.setSelectionHighlight();
      this._captureSelection();
    }
  }
  _captureSelection() {
    const { from, to } = this.editor.state.selection;
    const hasSelection = from !== to;
    this._capturedRange = { from, to };
    if (hasSelection) {
      if (this.appendRadio) this.appendRadio.checked = false;
      if (this.replaceSelectionRadio) this.replaceSelectionRadio.checked = true;
      const selectedText = this.editor.state.doc.textBetween(from, to, " ");
      this.selectedTextInput.value = selectedText;
      if (selectedText.length > 0) {
        this.prompt.placeholder = `Describe how to modify the selected text: "${selectedText.length > 50 ? `${selectedText.substring(0, 50)}...` : selectedText}"`;
      }
    } else {
      if (this.appendRadio) this.appendRadio.checked = true;
      if (this.replaceSelectionRadio)
        this.replaceSelectionRadio.checked = false;
      this.selectedTextInput.value = "";
      this.prompt.placeholder = "Describe the text you want to generate...";
    }
  }
  init() {
    this.toolbar.editor.commands.setSelectionHighlight();
    this.target = this.toolbar.element.appendChild(
      document.createElement("form")
    );
    this.target.className = `mt-4 hidden flex-col gap-2 rounded-md bg-slate-200 p-4 group-data-[open-form="generateText"]/toolbar:flex`;
    this.target.dataset.option = this.name;
    this.prompt = primitives.textarea({
      name: "prompt",
      rows: 3,
      placeholder: "Describe the text you want to generate..."
    });
    this.selectedTextInput = document.createElement("input");
    this.selectedTextInput.type = "hidden";
    this.selectedTextInput.name = "selected_text";
    this.selectedTextInput.value = "";
    const insertModeOptions = this._createInsertModeOptions();
    this.html = [this.prompt, this.selectedTextInput, insertModeOptions];
    this.form = new FormController(this);
    this.form.init();
  }
  _createInsertModeOptions() {
    const optionsContainer = document.createElement("div");
    optionsContainer.dataset.role = "insert-mode";
    optionsContainer.className = STYLES.editor.toolbar.optionPanel;
    const optionsHeader = optionsContainer.appendChild(
      document.createElement("h3")
    );
    optionsHeader.className = STYLES.editor.toolbar.optionHeader;
    optionsHeader.textContent = "Insert Mode";
    const processing = optionsContainer.appendChild(
      document.createElement("div")
    );
    processing.dataset.role = "insert-mode";
    processing.className = `${STYLES.upload.context}`;
    const insertOptions = [
      { value: "append", text: "Append to end of document", checked: true },
      { value: "replace", text: "Replace entire document" },
      { value: "prepend", text: "Prepend to beginning" },
      { value: "quote-top", text: "Add as quote at top" },
      { value: "cursor", text: "Insert at cursor position" },
      { value: "replace-selection", text: "Replace selected text" }
    ];
    insertOptions.forEach((option) => {
      processing.appendChild(
        primitives.radio({
          name: "insert_mode",
          value: option.value,
          label: option.text,
          checked: option.checked || false
        })
      );
    });
    this.appendRadio = processing.querySelector(
      'input[name="insert_mode"][value="append"]'
    );
    this.replaceSelectionRadio = processing.querySelector(
      'input[name="insert_mode"][value="replace-selection"]'
    );
    return optionsContainer;
  }
  async submit(submitter) {
    const endpoint = this.endpoints?.generateText;
    if (!endpoint) return;
    if (!this.prompt.value) {
      this.form.showError(this.messages.prompt);
      return;
    }
    if (submitter) submitter.disabled = true;
    const formData = new FormData(this.target);
    formData.append("role", submitter?.dataset?.role || "generate");
    const response = await request.post(endpoint, formData);
    if (submitter) submitter.disabled = false;
    if (response?.ok && response.markup) {
      const insertMode = formData.get("insert_mode") || "replace";
      this._addText(response.markup, insertMode);
    } else if (response?.error) {
      this.form.showError(response.error);
    }
  }
  _selectionRange() {
    const highlight = this.editor.commands.getSelectionHighlightRange();
    if (highlight) return highlight;
    const { from, to } = this._capturedRange ?? this.editor.state.selection;
    if (from !== to) {
      return { from, to };
    }
    return null;
  }
  _addText(html, insertMode = "replace") {
    const highlightedRange = insertMode === "replace-selection" ? this._selectionRange() : null;
    const cursorRange = insertMode === "cursor" ? this._capturedRange : null;
    this.editor.commands.clearSelectionHighlight();
    const chain = this.editor.chain().focus();
    switch (insertMode) {
      case "replace":
        chain.setContent(html).run();
        break;
      case "append":
        chain.command(({ commands }) => {
          commands.focus("end");
          const isEmpty = this.editor.getJSON().content?.length === 0;
          const spacing = isEmpty ? "" : "<p></p>";
          return commands.insertContent(`${spacing}${html}`);
        }).run();
        break;
      case "prepend":
        chain.command(({ commands }) => {
          commands.focus("start");
          const isEmpty = this.editor.getJSON().content?.length === 0;
          const spacing = isEmpty ? "" : "<p></p>";
          return commands.insertContent(`${html}${spacing}`);
        }).run();
        break;
      case "quote-top":
        chain.command(({ commands }) => {
          commands.focus("start");
          return commands.insertContent(
            `<blockquote>${html}</blockquote><p></p>`
          );
        }).run();
        break;
      case "cursor":
        if (cursorRange) {
          chain.insertContentAt(cursorRange, html).run();
        } else {
          chain.insertContent(html).run();
        }
        break;
      case "replace-selection":
        if (highlightedRange) {
          chain.insertContentAt(highlightedRange, html).run();
        } else {
          chain.insertContent(html).run();
        }
        break;
      default:
        chain.setContent(html).run();
    }
    this.toolbar.toggleForm(this.name);
  }
  reset() {
    this.prompt.value = "";
    this.prompt.placeholder = "Describe the text you want to generate...";
    this.selectedTextInput.value = "";
    if (this.appendRadio && this.replaceSelectionRadio) {
      this.appendRadio.checked = true;
      this.replaceSelectionRadio.checked = false;
    }
    this.form.resetSubmitButton();
  }
}

var generateText = /*#__PURE__*/Object.freeze({
	__proto__: null,
	generateText: GenerateText
});

export { setFontFamily as a, setImage as b, addLink as c, addImage as d, addYouTube as e, generateText as g, pinVersion as p, setColor as s };
