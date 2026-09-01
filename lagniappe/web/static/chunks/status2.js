/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=b8995073';
import { B as BaseElement } from './baseElement.js?v=b8995073';
import { p as primitives } from './primitives.js?v=b8995073';
import './icons.js?v=b8995073';

/**
 * @testable infrastructure
 */
class StatusElement extends BaseElement {
	constructor(renderer, schema, submission) {
		super(renderer, schema, submission);
		this.messageElement = null;
		this.statusInput = null;
		this.static = true;
	}

	update() {
		const messages = [];
		const activeElementIds = [];
		const statuses = Array.isArray(this.schema.status)
			? this.schema.status
			: [];

		statuses.forEach((status) => {
			if (!status?.id || !status.text) return;

			const element = this.renderer.elements.get(
				`${status.id}-${this.renderer.id}`,
			);
			if (!element) return;

			if (element.active(status.value)) {
				messages.push(status.text);
				activeElementIds.push(element.schema.id);
			}
		});

		this.messageElement.replaceChildren();
		if (messages.length > 0) {
			messages.forEach((message, index) => {
				if (index > 0)
					this.messageElement.appendChild(document.createElement("br"));
				this.messageElement.appendChild(document.createTextNode(message));
			});
			this.elt.dataset.visible = "true";
			this.statusInput.value = JSON.stringify(activeElementIds);
		} else {
			this.elt.dataset.visible = "false";
			this.statusInput.value = null;
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

export { StatusElement };
