import { ENDPOINTS } from "../../../shared/endpoints.mjs";
import { DraftDocument } from "../draftDocument.mjs";
import { Condition } from "./base.mjs";

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
