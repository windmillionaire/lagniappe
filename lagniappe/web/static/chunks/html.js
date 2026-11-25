/*! Third-party licenses: /third-party-licenses.txt */
import { r as request, c as captureError, E as ENDPOINTS } from './foundation.js?v=b74a2211';
import { S as STYLES } from './ui-resources.js?v=b74a2211';
import { i as independentEditor, a as Toolbar } from './document.js?v=b74a2211';
import { C as Condition } from './builder-controls.js?v=b74a2211';
import './upstreamUnavailable.js?v=b74a2211';
import './connectivity.js?v=b74a2211';
import './combobox.js?v=b74a2211';
import './ui-controls.js?v=b74a2211';
import './forms.js?v=b74a2211';
import './modal.js?v=b74a2211';
import './builder.js?v=b74a2211';
import './directUpload.js?v=b74a2211';
import './polling.js?v=b74a2211';

const EMPTY_HTML = /* @__PURE__ */ new Set(["", "<p></p>", "<p><br></p>"]);
const KEEPALIVE_BODY_LIMIT = 64 * 1024;
const normalizeHTML = (html) => {
  const normalized = typeof html === "string" ? html.trim() : "";
  return EMPTY_HTML.has(normalized) ? "" : normalized;
};
const keepaliveCompatible = (body) => {
  const serialized = JSON.stringify(body);
  return new TextEncoder().encode(serialized).byteLength <= KEEPALIVE_BODY_LIMIT;
};
class IndependentDocument {
  constructor(attributes) {
    Object.assign(this, attributes);
    this.acknowledgedContent = null;
    this.dirtyContent = null;
    this.pendingContent = null;
    this._destroyed = false;
    this._loadPromise = null;
    this._savePromise = null;
    this._pendingKeepalive = false;
    this._statusScope = null;
  }
  init() {
    this._createSurface();
    this.ready = this.load();
    return this.ready;
  }
  /**
   * Keep the independent editor inert until the authoritative value is known.
   * A failed request remains visibly retryable and never publishes blank
   * content as loaded state.
   *
   */
  load() {
    if (this._destroyed) return Promise.resolve(false);
    if (this.container?.hasAttribute("loaded")) return Promise.resolve(true);
    if (this._loadPromise) return this._loadPromise;
    const pending = (async () => {
      this._showLoading();
      const endpoint = this.endpoints?.getContent;
      if (!endpoint) throw new Error("Missing document content endpoint");
      const response = await request.get(
        endpoint,
        null,
        {
          replaceErrorPage: false
        }
      );
      if (response?.ok !== true) {
        this._showFailure(
          response?.error || "Could not load this text. Try again.",
          "load"
        );
        return false;
      }
      const html = normalizeHTML(response.markup ?? response.html);
      this.acknowledgedContent = html;
      this.dirtyContent = null;
      this.pendingContent = null;
      await this._publishLoadedContent(html);
      if (this._destroyed) return false;
      this._hideStatus();
      return true;
    })().catch((error) => {
      this.acknowledgedContent = null;
      this._captureUnexpected(error, "independent-document-load");
      this._showFailure("Could not load this text. Try again.", "load");
      return false;
    }).finally(() => {
      if (this._loadPromise === pending) this._loadPromise = null;
    });
    this._loadPromise = pending;
    this.ready = pending;
    return pending;
  }
  _createSurface() {
    this.status = document.createElement("div");
    this.status.className = STYLES.message;
    this.status.dataset.kind = "error";
    this.status.dataset.role = "editor-status";
    this.status.dataset.visible = "false";
    this.status.setAttribute("aria-live", "polite");
    this.status.hidden = true;
    this.statusMessage = document.createElement("span");
    this.statusMessage.dataset.role = "message";
    this.retryButton = document.createElement("button");
    this.retryButton.type = "button";
    this.retryButton.className = STYLES.button.submit;
    this.retryButton.dataset.role = "retry";
    this.retryButton.textContent = "Retry";
    this.retryButton.hidden = true;
    this._retry = this._retryFailedOperation.bind(this);
    this.retryButton.addEventListener("click", this._retry);
    this.status.append(this.statusMessage, this.retryButton);
    this.container = document.createElement("div");
    this.container.dataset.role = "editor";
    this.container.className = `${STYLES.editor.container} opacity-50 pointer-events-none`;
    this.container.inert = true;
    this.container.setAttribute("aria-busy", "true");
    this.target.replaceChildren(this.status, this.container);
  }
  _showLoading() {
    if (this._destroyed) return;
    this._statusScope = "load";
    this.status.dataset.kind = "form";
    this.statusMessage.textContent = "Loading text\u2026";
    this.retryButton.hidden = true;
    this.retryButton.disabled = true;
    this.status.hidden = false;
    this.status.dataset.visible = "true";
    this.container.inert = true;
    this.container.setAttribute("aria-busy", "true");
  }
  _showFailure(message, scope) {
    if (this._destroyed) return;
    this._statusScope = scope;
    this.status.dataset.kind = "error";
    this.statusMessage.textContent = message;
    this.retryButton.hidden = false;
    this.retryButton.disabled = false;
    this.status.hidden = false;
    this.status.dataset.visible = "true";
    if (scope === "load") this.container.removeAttribute("aria-busy");
  }
  _hideStatus(scope = null) {
    if (!this.status || scope && this._statusScope !== scope) return;
    this._statusScope = null;
    this.statusMessage.textContent = "";
    this.retryButton.hidden = true;
    this.retryButton.disabled = false;
    this.status.hidden = true;
    this.status.dataset.visible = "false";
  }
  _retryFailedOperation() {
    if (this._destroyed || this.retryButton.disabled) return;
    this.retryButton.disabled = true;
    const retry = this._statusScope === "load" ? this.load() : this.flush();
    void retry.finally(() => {
      if (!this._destroyed) this.retryButton.disabled = false;
    });
  }
  async _publishLoadedContent(html) {
    if (this._destroyed) return;
    if (this.readonly) {
      this.container.innerHTML = html;
      this._markLoaded();
      return;
    }
    const ready = this._initEditor(html);
    this._initToolbar();
    await ready;
  }
  _markLoaded() {
    if (this._destroyed) return;
    this.container.inert = false;
    this.container.removeAttribute("aria-busy");
    this.container.classList.remove("opacity-50", "pointer-events-none");
    this.container.setAttribute("loaded", "");
  }
  /**
   * Serialize saves and advance the baseline only after the server accepts the
   * exact submitted value. Edits made while a PUT is active are coalesced into
   * one latest follow-up value.
   *
   */
  flush({ keepalive = false } = {}) {
    if (this.readonly || this._destroyed || !this.editor) {
      return Promise.resolve(this.dirtyContent === null);
    }
    const html = this._currentContent();
    this.dirtyContent = html === this.acknowledgedContent ? null : html;
    if (this._savePromise) {
      this.pendingContent = html;
      this._pendingKeepalive ||= keepalive;
      return this._savePromise;
    }
    if (this.dirtyContent === null) {
      this._hideStatus("save");
      return Promise.resolve(true);
    }
    this.pendingContent = html;
    this._pendingKeepalive = keepalive;
    const pending = this._drainSaves().catch((error) => {
      this._captureUnexpected(error, "independent-document-save");
      if (!this._destroyed) {
        this.dirtyContent = this._currentContent();
        this.pendingContent = null;
        this._pendingKeepalive = false;
        this._showFailure("Changes were not saved. Try again.", "save");
      }
      return false;
    }).finally(() => {
      if (this._savePromise === pending) this._savePromise = null;
    });
    this._savePromise = pending;
    return pending;
  }
  async _drainSaves() {
    while (this.pendingContent !== null && !this._destroyed) {
      const html = this.pendingContent;
      const keepalive = this._pendingKeepalive;
      this.pendingContent = null;
      this._pendingKeepalive = false;
      if (html === this.acknowledgedContent) {
        const latest2 = this._currentContent();
        if (latest2 === this.acknowledgedContent) {
          this.dirtyContent = null;
          this._hideStatus("save");
        } else {
          this.dirtyContent = latest2;
          this.pendingContent = latest2;
          this._pendingKeepalive = keepalive;
        }
        continue;
      }
      const body = { html };
      const endpoint = this.endpoints?.save;
      if (!endpoint) throw new Error("Missing document save endpoint");
      const response = await request.put(endpoint, body, {
        keepalive: keepalive && keepaliveCompatible(body),
        replaceErrorPage: false
      });
      if (response?.ok !== true) {
        this.dirtyContent = this._destroyed ? null : this._currentContent();
        this.pendingContent = null;
        this._pendingKeepalive = false;
        this._showFailure(
          response?.error || "Changes were not saved. Try again.",
          "save"
        );
        return false;
      }
      this.acknowledgedContent = html;
      if (this._destroyed) {
        this.dirtyContent = null;
        return true;
      }
      const latest = this._currentContent();
      if (latest === this.acknowledgedContent) {
        this.dirtyContent = null;
        this._hideStatus("save");
        continue;
      }
      this.dirtyContent = latest;
      this.pendingContent = latest;
      this._pendingKeepalive ||= keepalive;
    }
    return this.dirtyContent === null;
  }
  _currentContent() {
    return normalizeHTML(this.editor?.getHTML());
  }
  _initEditor(html) {
    return new Promise((resolve) => {
      const editor = independentEditor(this.container, html);
      this.editor = editor;
      editor.on("create", () => {
        if (this._destroyed) {
          resolve(false);
          return;
        }
        if (!html.length) {
          this.container.querySelector(".ProseMirror")?.classList.add("min-h-[200px]");
          editor.commands.focus("start");
        }
        this._markLoaded();
        resolve(true);
      });
      editor.on("blur", () => {
        requestAnimationFrame(() => {
          const activeElement = document.activeElement;
          if (activeElement?.closest("[data-role='toolbar'], [role='listbox']"))
            return;
          void this.flush({ keepalive: true });
        });
      });
    });
  }
  _initToolbar() {
    this.toolbar = new Toolbar(this);
    this.toolbar.init();
    this.target.prepend(this.toolbar.element);
  }
  _captureUnexpected(error, context) {
    captureError(error, this.target, { context });
  }
  hide() {
    this.target.classList.add("hidden");
  }
  show() {
    this.target.classList.remove("hidden");
  }
  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;
    this.retryButton?.removeEventListener("click", this._retry);
    this.pendingContent = null;
    this._pendingKeepalive = false;
    this.toolbar?.destroy();
    this.editor?.destroy();
    this.editor = null;
    this.toolbar = null;
  }
}

class DraftDocument extends IndependentDocument {
  constructor(attributes) {
    super(attributes);
    this.draftOnly = true;
  }
  load() {
    if (this._destroyed) return Promise.resolve(false);
    if (this.container.hasAttribute("loaded")) return Promise.resolve(true);
    if (this._loadPromise) return this._loadPromise;
    this._loadPromise = (async () => {
      const html = this.builder.htmlFields[this.fieldId];
      if (typeof html !== "string") {
        this._showFailure(
          "Original text is unavailable. Reload the builder to try again.",
          "load"
        );
        return false;
      }
      this.acknowledgedContent = html;
      await this._publishLoadedContent(this.builder.previewHtml(html));
      if (this._destroyed) return false;
      this._lastFlushedContent = this._currentContent();
      this.editor?.on("update", () => this.flush());
      this._hideStatus();
      return true;
    })().finally(() => {
      this._loadPromise = null;
    });
    return this._loadPromise;
  }
  flush() {
    if (this._destroyed || !this.editor || !this.container.hasAttribute("loaded"))
      return Promise.resolve(false);
    const html = this._currentContent();
    if (html !== this._lastFlushedContent) {
      this.builder.setHtml(this.fieldId, html);
      this._lastFlushedContent = html;
    }
    return Promise.resolve(true);
  }
  addDraftImage(file) {
    return this.builder.addDraftImage(this.fieldId, file);
  }
}

class HtmlEditor extends Condition {
  constructor(builder) {
    super(builder);
    this.expand = true;
    this.endpoints = ENDPOINTS.html(builder.key, this.element.schema.id);
    this.kind = "form";
    this._initialized = false;
  }
  init() {
    if (this._initialized) return this.document?.ready;
    this._initialized = true;
    const container = document.createElement("div");
    container.className = "border-1 border-slate-300 rounded-md overflow-hidden";
    this.document = new DraftDocument({
      target: container,
      kind: this.kind,
      endpoints: this.endpoints,
      builder: this.builder,
      fieldId: this.element.schema.id
    });
    this.builder.registerIndependentDocument(this.document);
    const ready = this.document.init();
    this.destroyables.push(this.document);
    this.setTitle("Text Editor");
    this.target.append(this.header, container);
    return ready;
  }
  destroy() {
    if (this.document) {
      this.builder.unregisterIndependentDocument(this.document);
    }
    super.destroy();
    this.document = null;
  }
}

export { HtmlEditor as default };
