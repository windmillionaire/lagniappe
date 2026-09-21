import { IndependentDocument } from "../../elements/editor/independent.mjs";

/**
 * @testable infrastructure
 * @covered-by src/script/views/builder/draft.mjs::BuilderDraft
 */
export class DraftDocument extends IndependentDocument {
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
					"load",
				);
				return false;
			}
			this.acknowledgedContent = html;
			await this._publishLoadedContent(this.builder.previewHtml(html));
			if (this._destroyed) return false;
			this._lastFlushedContent = this._currentContent();
			this.editor.on("update", () => this.flush());
			this._hideStatus();
			return true;
		})().finally(() => {
			this._loadPromise = null;
		});
		return this._loadPromise;
	}

	/**
	 * @testable true
	 * @matrix forms : draft-history
	 */
	flush() {
		if (
			this._destroyed ||
			!this.editor ||
			!this.container.hasAttribute("loaded")
		)
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
