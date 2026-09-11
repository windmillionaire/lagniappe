import { ENDPOINTS } from "../../../shared";
import { DraftDocument } from "../draftDocument";
import { Condition } from "./base";

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_html_field
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_html_editor_recovers_from_failed_load_and_save
 * @pair html-field:builder-html-field
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
		if (this._initialized) return this.document?.ready;
		this._initialized = true;

		const container = document.createElement("div");
		container.className =
			"border-1 border-slate-300 rounded-md overflow-hidden";

		this.document = new DraftDocument({
			target: container,
			kind: this.kind,
			endpoints: this.endpoints,
			builder: this.builder,
			fieldId: this.element.schema.id,
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
