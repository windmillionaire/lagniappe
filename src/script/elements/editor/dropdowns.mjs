import { STYLES } from "styles";
import { setIcon } from "../../shared/icons";
import { Dropdown } from "../combobox/dropdown";

/**
 * @testable infrastructure
 */
export const createMenuButton = (settings) => {
	const button = document.createElement("button");
	button.title = settings.title;
	button.className = `${STYLES.editor.toolbar.menu}`;

	const icon = button.appendChild(document.createElement("span"));
	setIcon(icon, settings.icon, STYLES.editor.toolbar.menuIcon);

	const title = button.appendChild(document.createElement("span"));
	title.textContent = settings.title;
	title.className = "hidden md:inline";

	const chevron = button.appendChild(document.createElement("span"));
	setIcon(chevron, "menu", STYLES.editor.toolbar.caret);
	return button;
};

/**
 * @testable infrastructure
 */
export const toolbarDropdown = (menu, items) => {
	const menuButton = createMenuButton(menu);

	const dropdown = new Dropdown(menuButton);
	dropdown.init({
		items,
		styles: {
			panel: `${STYLES.dropdown.menu} ${STYLES.editor.toolbar.portalIconContext}`,
		},
	});

	return menuButton;
};
