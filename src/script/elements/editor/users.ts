import { STYLES } from "../../generated/styles.mjs";
import { Dropdown } from "../combobox/index.ts";
import { USER_COLORS } from "./config.ts";
import { createMenuButton } from "./dropdowns.ts";
import type { Toolbar } from "./toolbar.ts";

interface KnownUser {
	name: string;
	hash: string;
	color: string;
}

interface PresenceUser {
	hash?: string;
	name?: string;
}

const DEFAULT_USER_COLOR = "rgba(22, 163, 74, 0.6)";

const _userItem = (item: KnownUser) => {
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

export class UserManager {
	declare toolbar: Toolbar;
	declare menuSettings: { icon: string; title: string };
	declare users: KnownUser[];
	declare knownUsers: Map<string, KnownUser>;
	declare user: PresenceUser | null;
	declare button: HTMLButtonElement | null;
	declare dropdown: Dropdown | null;

	constructor(toolbar: Toolbar) {
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

	getUserColor(
		hash: string | null | undefined,
		user: PresenceUser | null = null,
	) {
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

	remoteUpdate(
		userHash: string | null | undefined,
		user: PresenceUser | null = null,
	) {
		const storage = this.toolbar.editor.storage.flashRemoteChanges;
		storage.color = this.getUserColor(userHash, user);
		storage.author =
			(userHash ? this.knownUsers.get(userHash)?.name : undefined) ?? "";
	}

	setUsers(users: PresenceUser[]) {
		const menuRow = this.toolbar.element.querySelector(
			'[data-role="toolbar-menus"]',
		);

		if (this.button) {
			this.dropdown?.destroy();
			this.button.remove();
			this.button = null;
			this.dropdown = null;
		}

		const activeUsers = new Map<string, { hash: string; name: string }>();
		for (const user of users) {
			if (user?.hash && user?.name)
				activeUsers.set(user.hash, { hash: user.hash, name: user.name });
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

		menuRow?.appendChild(this.button);
	}

	destroy() {
		this.dropdown?.destroy();
		this.button?.remove();
		this.users = [];
		this.knownUsers.clear();
		this.button = null;
		this.dropdown = null;
	}
}
