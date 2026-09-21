import { STYLES } from "../../generated/styles.mjs";
import { setIcon } from "../../shared/icons.mjs";
import { Dropdown } from "../combobox/dropdown.mjs";

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004j_editor_menus.py::test_compact_editor_menus
 * @matrix editor : compact-menus
 */
export const createMenuButton = (settings) => {
	const button = document.createElement("button");
	button.title = settings.title;
	button.type = "button";
	button.setAttribute("aria-label", settings.title);
	button.className = `${STYLES.editor.toolbar.menu}`;

	const icon = button.appendChild(document.createElement("span"));
	setIcon(icon, settings.icon, STYLES.editor.toolbar.menuIcon);

	const chevron = button.appendChild(document.createElement("span"));
	setIcon(chevron, "menu", STYLES.editor.toolbar.caret);
	return button;
};

/**
 * @testable infrastructure
 */
export const toolbarDropdown = (menu, items, beforeOpen) => {
	const menuButton = createMenuButton(menu);

	const dropdown = new Dropdown(menuButton);
	dropdown.init({
		items,
		loadOptions: async () => {
			await beforeOpen?.();
			return items.filter((item) => item.isAvailable?.() ?? true);
		},
		styles: {
			panel: `${STYLES.dropdown.menu} ${STYLES.editor.toolbar.portalIconContext} w-max max-w-[calc(100vw-0.625rem)]`,
		},
	});

	return menuButton;
};
