/*! Third-party licenses: /third-party-licenses.txt */
import { r as request, S as STYLES, s as setIcon } from './shared.js?v=b30f3f24';
import { BaseList } from './baseList.js?v=b30f3f24';

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

	handleOfflineQueue({ phase, queue, html, record, records }) {
		if (phase === "queued") return this._offlineQueued(record, queue);
		if (phase === "cancelled") this._offlineCancelled(record);
		if (phase === "overlay") this._offlineOverlay({ queue, html, records });
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

	_offlineOverlay({ queue, html, records }) {
		const list = html.querySelector("[data-widget='HomeActivityList']");
		if (!list) return;

		for (const record of records) {
			if (record.kind !== "note" || record.action !== "create") continue;
			if (this._itemByKey(list, record.client_key)) continue;
			list.prepend(this._renderNote(record, queue));
		}
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
			await this.view.offlineQueue.cancel({
				action: "create",
				client_key: key,
			});
			return;
		}
		if (item.dataset.kind === "note") return;

		const route = `/activity/${key}`;
		if (!this.view.online) {
			await this.view.offlineQueue.queue({
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
	 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_mutation_overlay_hides_deleted_items
	 * @features offline
	 * @dimensions cached-overlay
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
