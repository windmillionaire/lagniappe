/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bdbb928b';
import { Dropdown } from './dropdown.js?v=bdbb928b';
import './icons.js?v=bdbb928b';
import './combobox.js?v=bdbb928b';
import './foundation.js?v=bdbb928b';
import './connectivity.js?v=bdbb928b';
import './primitives.js?v=bdbb928b';

/**
 * Adapts template-defined entity actions to the shared Dropdown primitive.
 *
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_completed_task_can_move_to_another_page
 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_delete_page_from_title_menu
 * @tests tests_e2e/003_forms/test_003a_forms.py::test_copy_form_from_builder_title_menu
 * @tests tests_js/test_016_combobox_frontend.py::test_entity_title_menu_anchors_to_the_title_bottom_left
 * @matrix entity-menu : builder-copy readiness state-linking title-menu title-positioning
 * @matrix pages tasks : title-menu
 */
class EntityMenu {
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

export { EntityMenu };
