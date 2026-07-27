import { IndependentDocument } from "../../../elements/editor/independent";
import { ENDPOINTS } from "../../../shared";
import { Condition } from "./base";

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_html_field
 * @features html-field
 * @dimensions builder-html-field
 */
export default class HtmlEditor extends Condition {
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

		const editor = new IndependentDocument({
			target: container,
			kind: this.kind,
			endpoints: this.endpoints,
		});
		editor.init();
		this.destroyables.push(editor);

		this.setTitle("Text Editor");
		this.target.append(this.header, container);
	}
}
