/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=b506293e';
import { r as request, c as captureError, E as ENDPOINTS } from './foundation.js?v=b506293e';
import './connectivity.js?v=b506293e';
import { i as independentEditor, T as Toolbar } from './toolbar.js?v=b506293e';
import { C as Condition } from './base2.js?v=b506293e';
import './upstreamUnavailable.js?v=b506293e';
import './combobox.js?v=b506293e';
import './primitives.js?v=b506293e';
import './icons.js?v=b506293e';
import './queryLifecycle.js?v=b506293e';
import './dropdown.js?v=b506293e';
import './buttons.js?v=b506293e';
import './formatting.js?v=b506293e';
import './baseForm.js?v=b506293e';
import './loader.js?v=b506293e';
import './select2.js?v=b506293e';
import './results.js?v=b506293e';
import './storage.js?v=b506293e';
import './submitter.js?v=b506293e';

const EMPTY_HTML = new Set(["", "<p></p>", "<p><br></p>"]);
const KEEPALIVE_BODY_LIMIT = 64 * 1024;

/**
 * @testable false
 * @covered-by src/script/elements/editor/independent.mjs::IndependentDocument.flush
 * @reason content normalization is exercised through the editor acknowledgement boundary
 */
const normalizeHTML = (html) => {
	const normalized = typeof html === "string" ? html.trim() : "";
	return EMPTY_HTML.has(normalized) ? "" : normalized;
};

/**
 * @testable false
 * @covered-by src/script/elements/editor/independent.mjs::IndependentDocument.flush
 * @reason keepalive eligibility is private flush transport policy
 */
const keepaliveCompatible = (body) => {
	const serialized = JSON.stringify(body);
	return (
		new TextEncoder().encode(serialized).byteLength <= KEEPALIVE_BODY_LIMIT
	);
};

/**
 * @testable infrastructure
 */
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
	 * @testable true
	 * @tests tests_js/test_045_browser_persistence.py::test_independent_editor_failed_load_stays_inert_and_retries
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_html_editor_recovers_from_failed_load_and_save
	 * @matrix editor html-field : authoritative-content error-reporting initial-load retry
	 */
	load() {
		if (this._destroyed) return Promise.resolve(false);
		if (this.container?.hasAttribute("loaded")) return Promise.resolve(true);
		if (this._loadPromise) return this._loadPromise;

		const pending = (async () => {
			this._showLoading();
			const response = await request.get(this.endpoints.getContent, null, {
				replaceErrorPage: false,
			});
			if (response?.ok !== true) {
				this._showFailure(
					response?.error || "Could not load this text. Try again.",
					"load",
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
		})()
			.catch((error) => {
				this.acknowledgedContent = null;
				this._captureUnexpected(error, "independent-document-load");
				this._showFailure("Could not load this text. Try again.", "load");
				return false;
			})
			.finally(() => {
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
		this.statusMessage.textContent = "Loading text…";
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
		if (!this.status || (scope && this._statusScope !== scope)) return;
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
	 * @testable true
	 * @tests tests_js/test_045_browser_persistence.py::test_independent_editor_failed_save_stays_dirty_and_retries
	 * @tests tests_js/test_045_browser_persistence.py::test_independent_editor_serializes_inflight_edits_and_acknowledges_in_order
	 * @tests tests_js/test_045_browser_persistence.py::test_independent_editor_saves_intentional_clear
	 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_html_editor_recovers_from_failed_load_and_save
	 * @matrix editor html-field : concurrent-edit error-reporting intentional-clear keepalive retry serialized-save server-acknowledgement
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
		const pending = this._drainSaves()
			.catch((error) => {
				this._captureUnexpected(error, "independent-document-save");
				if (!this._destroyed) {
					this.dirtyContent = this._currentContent();
					this.pendingContent = null;
					this._pendingKeepalive = false;
					this._showFailure("Changes were not saved. Try again.", "save");
				}
				return false;
			})
			.finally(() => {
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
				const latest = this._currentContent();
				if (latest === this.acknowledgedContent) {
					this.dirtyContent = null;
					this._hideStatus("save");
				} else {
					this.dirtyContent = latest;
					this.pendingContent = latest;
					this._pendingKeepalive = keepalive;
				}
				continue;
			}

			const body = { html };
			const response = await request.put(this.endpoints.save, body, {
				keepalive: keepalive && keepaliveCompatible(body),
				replaceErrorPage: false,
			});
			if (response?.ok !== true) {
				this.dirtyContent = this._destroyed ? null : this._currentContent();
				this.pendingContent = null;
				this._pendingKeepalive = false;
				this._showFailure(
					response?.error || "Changes were not saved. Try again.",
					"save",
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
		return normalizeHTML(this.editor.getHTML());
	}

	_initEditor(html) {
		return new Promise((resolve) => {
			this.editor = independentEditor(this.container);

			this.editor.on("create", () => {
				if (this._destroyed) {
					resolve(false);
					return;
				}
				if (html.length > 0) {
					this.editor.commands.setContent(html);
				} else {
					this.container
						.querySelector(".ProseMirror")
						.classList.add("min-h-[200px]");
					this.editor.commands.focus("start");
				}
				this._markLoaded();
				resolve(true);
			});

			this.editor.on("blur", () => {
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
		this._destroyed = true;
		this.retryButton?.removeEventListener("click", this._retry);
		this.pendingContent = null;
		this._pendingKeepalive = false;
		this.editor?.destroy();
		this.toolbar?.destroy();
		this.editor = null;
		this.toolbar = null;
	}
}

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_html_field
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_html_editor_recovers_from_failed_load_and_save
 * @pair html-field:builder-html-field
 */
class HtmlEditor extends Condition {
	constructor(builder) {
		super(builder);
		this.expand = true;
		this.endpoints = ENDPOINTS.html(builder.key, this.element.schema.id);
		this.kind = "form";
		this._initialized = false;
	}

	init() {
		if (this._initialized) return;
		this._initialized = true;

		const container = document.createElement("div");
		container.className =
			"border-1 border-slate-300 rounded-md overflow-hidden";

		this.document = new IndependentDocument({
			target: container,
			kind: this.kind,
			endpoints: this.endpoints,
		});
		this.builder.registerIndependentDocument(this.document);
		void this.document.init();
		this.destroyables.push(this.document);

		this.setTitle("Text Editor");
		this.target.append(this.header, container);
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
