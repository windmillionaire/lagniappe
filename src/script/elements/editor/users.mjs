import { STYLES } from "styles";
import { USER_COLORS } from "../../config/editor";
import { Dropdown } from "../combobox";
import { createMenuButton } from "./dropdowns";

const DEFAULT_USER_COLOR = "rgba(22, 163, 74, 0.6)";

/**
 * @testable false
 * @covered-by src/script/elements/editor/users.mjs::UserManager
 * @reason user dropdown row rendering is private user-manager plumbing
 */
const _userItem = (item) => {
	const itemElt = document.createElement("div");
	itemElt.role = "option";
	itemElt.className = STYLES.dropdown.option.action;

	const dot = document.createElement("span");
	dot.className = "w-2 h-2 rounded-full flex-shrink-0";
	dot.style.backgroundColor = item.color;
	itemElt.appendChild(dot);

	const text = document.createElement("span");
	text.textContent = item.name;
	itemElt.appendChild(text);

	itemElt.style.cursor = "default";
	return { html: itemElt.outerHTML };
};

/**
 * @testable infrastructure
 */
export class UserManager {
	constructor(toolbar) {
		this.toolbar = toolbar;
		this.users = [];
		this.user = null;
		this.button = null;
		this.dropdown = null;
		this.menuSettings = {
			icon: "group",
			title: "Users",
		};
	}

	getUserColor(hash) {
		return (
			this.users.find((user) => user.hash === hash)?.color || DEFAULT_USER_COLOR
		);
	}

	remoteUpdate(userHash) {
		const flash = this.getUserColor(userHash);
		this.toolbar.editor.storage.flashRemoteChanges.color = flash;
	}

	setUsers(users) {
		const incoming = new Set(users.map((u) => u.hash));
		const current = new Set(this.users.map((u) => u.hash));
		if (
			incoming.size === current.size &&
			[...incoming].every((h) => current.has(h))
		) {
			return;
		}

		const menuRow = this.toolbar.element.querySelector(
			'[data-role="toolbar-menus"]',
		);

		if (this.button) {
			if (this.button._lp_combobox) {
				this.button._lp_combobox.destroy();
			}
			this.button.remove();
			this.button = null;
			this.dropdown = null;
		}

		// Reset users if empty
		if (users.length === 0) {
			this.users = [];
			return;
		}

		// Get available colors (colors not already assigned)
		let availableColors = new Set(
			USER_COLORS.filter(
				(color) => !this.users.map((user) => user.color).includes(color),
			),
		);

		// Add new users with colors
		users.forEach((user) => {
			if (!this.users.find((u) => u.hash === user.hash)) {
				const color = availableColors.values().next().value;
				availableColors.delete(color);
				// Reset available colors if we run out
				if (availableColors.size === 0) {
					availableColors = new Set(USER_COLORS);
				}
				this.users.push({
					name: user.name,
					hash: user.hash,
					color,
				});
			}
		});

		// Create the dropdown button
		this.button = createMenuButton(this.menuSettings);
		const items = this.users.map((item) => _userItem(item));

		this.dropdown = new Dropdown(this.button);
		this.dropdown.init({
			items,
			styles: {
				panel: `${STYLES.dropdown.panel} ${STYLES.editor.toolbar.portalIconContext}`,
			},
		});

		menuRow.appendChild(this.button);
	}

	destroy() {
		this.button?._lp_combobox?.destroy();
		this.button?.remove();
		this.users = [];
		this.button = null;
		this.dropdown = null;
	}
}
