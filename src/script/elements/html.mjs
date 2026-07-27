import { ENDPOINTS, request } from "../shared";
import { BaseElement } from "./base/baseElement";

/**
 * @testable infrastructure
 */
export class HtmlElement extends BaseElement {
	constructor(renderer, schema, submission) {
		super(renderer, schema, submission);
		this.static = true;
		this.html = null;
	}

	async _getHtml() {
		return await request
			.get(ENDPOINTS.html(this.renderer.form.key, this.schema.id).getContent)
			.then((response) => response.markup)
			.catch((error) => {
				captureError(error, this.renderer.form.target, {
					schema: this.schema,
				});
			});
	}

	create() {
		if (this._elt) return this._elt;

		const elt = document.createElement("div");
		elt.className = "html-content";

		if (!this.html) {
			this._getHtml().then((html) => {
				this.html = html;
				elt.innerHTML = html;
			});
		} else {
			elt.innerHTML = this.html;
		}

		return elt;
	}
}
