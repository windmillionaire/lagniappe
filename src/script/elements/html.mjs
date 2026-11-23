import { captureError, ENDPOINTS, request } from "../shared/index.mjs";
import { BaseElement } from "./base/baseElement.mjs";

export class HtmlElement extends BaseElement {
	constructor(renderer, schema, submission) {
		super(renderer, schema, submission);
		this.static = true;
		this.html = null;
		this._destroyed = false;
	}

	async _getHtml() {
		return await request
			.get(ENDPOINTS.html(this.renderer.form.key, this.schema.id).getContent)
			.then((response) => response.markup)
			.catch((error) => {
				captureError(error, this.renderer.form.target, {
					schema: this.schema,
				});
				return "";
			});
	}

	create() {
		if (this._elt) return this._elt;

		const elt = document.createElement("div");
		elt.className = "html-content";

		const fields = this.renderer.form.htmlFields;
		if (fields && Object.hasOwn(fields, this.schema.id)) {
			this.html = fields[this.schema.id];
			elt.innerHTML = this.html;
		} else if (this.html === null) {
			this._getHtml().then((html) => {
				if (this._destroyed) return;
				this.html = html;
				elt.innerHTML = html;
			});
		} else {
			elt.innerHTML = this.html;
		}

		return elt;
	}

	destroy() {
		this._destroyed = true;
		super.destroy();
	}
}
