import Entity from "./base/entity.ts";

export default class Admin extends Entity {
	constructor(node: HTMLElement) {
		super(node);
		this._defaultTabId = node.dataset.defaultTab || "settings";
	}
}
