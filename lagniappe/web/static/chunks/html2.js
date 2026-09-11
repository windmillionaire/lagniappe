/*! Third-party licenses: /third-party-licenses.txt */
import { r as request, E as ENDPOINTS, c as captureError } from './foundation.js?v=b110e8d6';
import './connectivity.js?v=b110e8d6';
import { B as BaseElement } from './baseElement.js?v=b110e8d6';
import './upstreamUnavailable.js?v=b110e8d6';
import './styles.js?v=b110e8d6';
import './icons.js?v=b110e8d6';
import './primitives.js?v=b110e8d6';

/**
 * @testable infrastructure
 */
class HtmlElement extends BaseElement {
	constructor(renderer, schema, submission) {
		super(renderer, schema, submission);
		this.static = true;
		this.html = null;
		this._destroyed = false;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_037_html_element_frontend.py::test_html_element_reports_request_failure_without_masking_original
	 * @pair form-html:error-reporting
	 */
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

	/**
	 * @testable true
	 * @matrix forms : draft-history
	 */
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

export { HtmlElement };
