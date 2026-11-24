import { STYLES } from "../generated/styles.mjs";
import { Dropdown } from "./combobox/dropdown.ts";

/**
 * Adapts template-defined entity actions to the shared Dropdown primitive.
 *
 */
export class EntityMenu {
	constructor(view) {
		this.view = view;
		this.dropdowns = new Set();
	}

	_items(container) {
		const entityKey = container.closest("[data-key]")?.dataset.key;
		return Array.from(
			container.querySelectorAll(
				":scope > [data-role='menu-items'] > [data-menu-item]",
			),
		)
			.filter((item) => !item.disabled && item.dataset.visible !== "false")
			.map((source) => {
				const option = source.cloneNode(true);
				option.hidden = false;
				option.removeAttribute("id");
				option.setAttribute("role", "menuitem");
				option.querySelectorAll("[id]").forEach((element) => {
					element.removeAttribute("id");
				});
				if (entityKey) option.dataset.entityKey = entityKey;

				return {
					html: option.outerHTML,
					onClick: () => source.isConnected && source.click(),
				};
			});
	}

	toggle(container) {
		if (!container) return;
		this._prune();

		const trigger = container.querySelector(
			":scope > [data-role='menu-trigger']",
		);
		const items = this._items(container);
		if (!trigger || items.length === 0) return;
		const title = container
			.closest("[data-menu-anchor]")
			?.querySelector("[data-role='title']");

		const dropdown = new Dropdown(trigger).init({
			items,
			loadOptions: async () => this._items(container),
			placement: "bottom-start",
			positionReference: title || trigger,
			matchReferenceWidth: true,
			styles: { panel: STYLES.dropdown.menu },
			popupRole: "menu",
			optionRole: "menuitem",
			triggerRole: null,
		});
		this.dropdowns.add(dropdown);

		// The first click reached the delegated Core handler before Dropdown was
		// attached to the trigger, so open it explicitly. Later clicks are owned
		// directly by Dropdown.
		return dropdown.showPanel();
	}

	_prune() {
		for (const dropdown of this.dropdowns) {
			if (dropdown.element.isConnected) continue;
			dropdown.destroy();
			this.dropdowns.delete(dropdown);
		}
	}

	destroy() {
		this.dropdowns.forEach((dropdown) => {
			dropdown.destroy();
		});
		this.dropdowns.clear();
		this.view = null;
	}
}
