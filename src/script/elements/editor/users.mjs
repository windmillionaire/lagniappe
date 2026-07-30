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
		this.knownUsers = new Map();
		this.user = null;
		this.button = null;
		this.dropdown = null;
		this.menuSettings = {
			icon: "group",
			title: "Users",
		};
	}

	getUserColor(hash, user = null) {
		if (!hash) return "";
		let known = this.knownUsers.get(hash);
		if (!known && user?.name) {
			known = {
				name: user.name,
				hash,
				color:
					USER_COLORS[this.knownUsers.size % USER_COLORS.length] ??
					DEFAULT_USER_COLOR,
			};
			this.knownUsers.set(hash, known);
		} else if (known && user?.name) {
			known.name = user.name;
		}
		return known?.color || DEFAULT_USER_COLOR;
	}

	remoteUpdate(userHash, user = null) {
		const storage = this.toolbar.editor.storage.flashRemoteChanges;
		storage.color = this.getUserColor(userHash, user);
		storage.author = this.knownUsers.get(userHash)?.name ?? "";
	}

	setUsers(users) {
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

		const activeUsers = new Map();
		for (const user of users) {
			if (user?.hash && user?.name) activeUsers.set(user.hash, user);
		}
		this.users = [...activeUsers.values()].map((user) => {
			const color = this.getUserColor(user.hash, user);
			return this.knownUsers.get(user.hash) ?? { ...user, color };
		});
		if (this.users.length === 0) return;

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
		this.knownUsers.clear();
		this.button = null;
		this.dropdown = null;
	}
}
