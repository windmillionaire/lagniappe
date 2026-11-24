import { captureError, ENDPOINTS, request } from "../shared/index.ts";
import {
	BaseElement,
	type ElementRenderer,
	type ElementSchema,
} from "./base/baseElement.ts";

export class HtmlElement extends BaseElement {
	declare html: string | null;
	declare _destroyed: boolean;

	constructor(
		renderer: ElementRenderer,
		schema: ElementSchema,
		submission?: unknown,
	) {
		super(renderer, schema, submission);
		this.static = true;
		this.html = null;
		this._destroyed = false;
	}

	async _getHtml() {
		const form = this.renderer.form;
		if (!form?.key) return "";
		return await request
			.get<{ markup: string }>(
				ENDPOINTS.html(form.key, this.schema.id).getContent,
			)
			.then((response) => response?.markup ?? "")
			.catch((error) => {
				captureError(error, form.target, {
					schema: this.schema,
				});
				return "";
			});
	}

	create() {
		if (this._elt) return this._elt;

		const elt = document.createElement("div");
		elt.className = "html-content";

		const fields = this.renderer.form?.htmlFields;
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
