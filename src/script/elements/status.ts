import { STYLES } from "../generated/styles.mjs";
import {
	BaseElement,
	type ElementRenderer,
	type ElementSchema,
} from "./base/baseElement.ts";
import { primitives } from "./primitives.ts";

export class StatusElement extends BaseElement {
	declare messageElement: HTMLSpanElement | null;
	declare statusInput: HTMLInputElement | null;

	constructor(
		renderer: ElementRenderer,
		schema: ElementSchema,
		submission?: unknown,
	) {
		super(renderer, schema, submission);
		this.messageElement = null;
		this.statusInput = null;
		this.static = true;
	}

	update(): undefined {
		const elt = this.elt;
		const { messageElement, statusInput } = this;
		if (!elt || !messageElement || !statusInput) return;
		const messages: string[] = [];
		const activeElementIds: string[] = [];
		const statuses = Array.isArray(this.schema.status)
			? this.schema.status
			: [];

		statuses.forEach((status) => {
			if (!status?.id || !status.text) return;

			const element = this.renderer.elements?.get(
				`${status.id}-${this.renderer.id}`,
			);
			if (!element) return;

			if (element.active?.(status.value)) {
				messages.push(status.text);
				activeElementIds.push(element.schema.id);
			}
		});

		messageElement.replaceChildren();
		if (messages.length > 0) {
			messages.forEach((message, index) => {
				if (index > 0) messageElement.appendChild(document.createElement("br"));
				messageElement.appendChild(document.createTextNode(message));
			});
			elt.dataset.visible = "true";
			statusInput.value = JSON.stringify(activeElementIds);
		} else {
			elt.dataset.visible = "false";
			statusInput.value = "";
		}
	}

	create() {
		if (this._elt) return this._elt;

		const elt = document.createElement("div");
		elt.dataset.kind = "status";
		elt.className = STYLES.message;
		elt.dataset.visible = "false";

		this.messageElement = elt.appendChild(document.createElement("span"));
		this.statusInput = elt.appendChild(
			primitives.input({
				name: this.schema.id,
				type: "hidden",
			}),
		);

		return elt;
	}
}
