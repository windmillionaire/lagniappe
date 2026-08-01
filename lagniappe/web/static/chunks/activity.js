/*! Third-party licenses: /third-party-licenses.txt */
import { S as STYLES } from './styles.js?v=b211475b';
import { BaseList } from './baseList.js?v=b211475b';
import { r as request } from './request.js?v=b211475b';
import './connectivity.js?v=b211475b';
import { s as setIcon } from './icons.js?v=b211475b';
import './utilities.js?v=b211475b';
import './errors.js?v=b211475b';

/**
 * @testable infrastructure
 */
class HomeActivityList extends BaseList {
	constructor(attributes) {
		super(attributes);
		this._click = this._click.bind(this);
	}

	init() {
		this.target.addEventListener("click", this._click);
	}

	async _click(e) {
		const button = e.target.closest("[data-action='delete-activity']");
		if (!button) return;

		await this.deleteActivity(button);
	}

	handleOfflineQueue({ phase, queue, record }) {
		if (phase === "queued") return this._offlineQueued(record, queue);
		if (phase === "cancelled") this._offlineCancelled(record);
	}

	_offlineQueued(record, queue) {
		if (record.kind === "note" && record.action === "create") {
			return queue.response(this._renderNote(record, queue));
		}

		if (record.action === "delete") this._removeByKey(record.target_key);
	}

	_offlineCancelled(record) {
		if (record.action === "create") this._removeByKey(record.client_key);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_delete_activity_item_from_home
	 * @features activity notes notifications
	 * @dimensions delete
	 */
	async deleteActivity(button) {
		const key = button.dataset.key;
		const item = button.closest("li[data-key], [lp-entity][data-key]");
		if (!key || !item) return;

		if (key.startsWith("offline:")) {
			const queue =
				this.view.offlineQueue || (await this.view.ensureOfflineQueue?.());
			await queue?.cancel({
				action: "create",
				client_key: key,
			});
			return;
		}
		if (item.dataset.kind === "note") return;

		const route = `/activity/${key}`;
		if (!this.view.online) {
			const queue =
				this.view.offlineQueue || (await this.view.ensureOfflineQueue?.());
			await queue?.queue({
				id: `delete:${key}`,
				kind: item.dataset.kind || "activity",
				action: "delete",
				method: "DELETE",
				route,
				target_key: key,
			});
			return;
		}

		button.disabled = true;
		const response = await request.delete(route);
		button.disabled = false;
		if (response?.ok) this._removeItem(item);
	}

	_renderNote(record, queue) {
		const body = queue.field(record, "body");
		const visibility = queue.field(record, "visibility") || "private";
		const file = record.files?.[0]?.file;

		const item = document.createElement("li");
		item.dataset.key = record.client_key;
		item.dataset.kind = "note";
		item.dataset.offline = "true";
		item.className = [STYLES.note.item.home, "opacity-80"].join(" ");

		const content = document.createElement("div");
		content.className = STYLES.note.content;
		item.append(content);

		if (body) {
			const bodyElt = document.createElement("span");
			bodyElt.className = STYLES.note.body;
			bodyElt.textContent = body;
			content.append(bodyElt);
		}

		if (file) {
			const image = document.createElement("img");
			image.src = URL.createObjectURL(file);
			image.className = STYLES.note.photo.home;
			image.alt = "";
			content.append(image);
		}

		const meta = document.createElement("span");
		meta.className = STYLES.note.meta;
		meta.textContent = `Pending sync · ${visibility === "everyone" ? "Everyone" : "Private"}`;
		content.append(meta);

		const button = document.createElement("button");
		button.className = STYLES.note.discard;
		button.dataset.action = "delete-activity";
		button.dataset.key = record.client_key;
		button.type = "button";
		button.setAttribute("aria-label", "Discard pending note");
		button.title = "Discard pending note";
		item.append(button);

		const icon = document.createElement("span");
		setIcon(icon, "close");
		button.append(icon);

		return item;
	}

	_itemByKey(root, key) {
		if (!root || !key) return null;
		return Array.from(root.querySelectorAll("[data-key]")).find((item) => {
			return item.dataset.key === key;
		});
	}

	_removeByKey(key) {
		const item = this._itemByKey(this.target, key);
		if (item) this._removeItem(item);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_reload_uses_server_state_until_replay
	 * @features offline
	 * @dimensions optimistic-mutation
	 */
	_removeItem(item) {
		const list = item.closest("ul");
		item.remove();

		if (list && list.querySelectorAll("li").length === 0) {
			list.dataset.visible = "false";
		}
	}

	postreconcile() {
		const updated = this._updated;
		super.postreconcile();
		if (updated) {
			this.destroy();
			this.init();
		}
		this.target.setAttribute("loaded", "");
	}

	destroy() {
		this.target.removeEventListener("click", this._click);
	}
}

export { HomeActivityList };
