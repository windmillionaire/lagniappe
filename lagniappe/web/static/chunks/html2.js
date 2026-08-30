/*! Third-party licenses: /third-party-licenses.txt */
import { r as request, E as ENDPOINTS, c as captureError } from './foundation.js?v=bd7dbd9a';
import './connectivity.js?v=bd7dbd9a';
import { B as BaseElement } from './baseElement.js?v=bd7dbd9a';
import './styles.js?v=bd7dbd9a';
import './icons.js?v=bd7dbd9a';
import './primitives.js?v=bd7dbd9a';

/**
 * @testable infrastructure
 */
class HtmlElement extends BaseElement {
	constructor(renderer, schema, submission) {
		super(renderer, schema, submission);
		this.static = true;
		this.html = null;
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
