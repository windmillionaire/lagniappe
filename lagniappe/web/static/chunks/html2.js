/*! Third-party licenses: /third-party-licenses.txt */
import { r as request, E as ENDPOINTS } from './shared.js?v=bda9a134';
import { B as BaseElement } from './baseElement.js?v=bda9a134';
import './primitives.js?v=bda9a134';

/**
 * @testable infrastructure
 */
class HtmlElement extends BaseElement {
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

export { HtmlElement };
