import { BaseList, type ListAttributes } from "../../elements/base/baseList.ts";
import { STYLES } from "../../generated/styles.mjs";
import { setIcon } from "../../shared/icons.ts";
import { request } from "../../shared/index.ts";
import type {
	OfflineMutationRecord,
	OfflineQueue,
	QueueContext,
} from "../../shared/offlineQueue.ts";
import { withTransition } from "../../shared/transitions.ts";
import type Core from "../../views/base/core.ts";

type ActivityListAttributes = ListAttributes & {
	component: ListAttributes["component"] & { elt?: HTMLElement; name?: string };
	view: Pick<Core, "addFlash" | "offlineQueue" | "ensureOfflineQueue"> & {
		online: boolean;
		syncHomeSectionState?(component: ActivityListAttributes["component"]): void;
	};
};

export class HomeActivityList extends BaseList {
	declare component: ActivityListAttributes["component"];
	declare view: ActivityListAttributes["view"];

	constructor(attributes: ActivityListAttributes) {
		super(attributes);
		this._click = this._click.bind(this);
	}

	init() {
		this.target.addEventListener("click", this._click);
	}

	async _click(e: Event) {
		if (!(e.target instanceof Element)) return;
		const button = e.target.closest<HTMLButtonElement>(
			"[data-action='delete-activity']",
		);
		if (!button) return;

		await this.deleteActivity(button);
	}

	handleOfflineQueue({ phase, queue, record }: QueueContext) {
		if (phase === "queued") return this._offlineQueued(record, queue);
		if (phase === "cancelled") return this._offlineCancelled(record);
	}

	_offlineQueued(record: OfflineMutationRecord, queue: OfflineQueue) {
		if (record.kind === "note" && record.action === "create") {
			const key = record.client_key;
			if (key) return queue.response(this._renderNote(record, queue, key));
		}

		if (record.action === "delete") return this._removeByKey(record.target_key);
	}

	_offlineCancelled(record: OfflineMutationRecord) {
		if (record.action === "create") return this._removeByKey(record.client_key);
	}

	async deleteActivity(button: HTMLButtonElement) {
		const key = button.dataset.key;
		const item = button.closest<HTMLElement>(
			"li[data-key], [lp-entity][data-key]",
		);
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

		const route = `/l/activity/${key}`;
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
		if (response?.ok) {
			await withTransition(() => this._commitRemoveItem(item), {
				label: "home:activity-delete",
			});
		}
	}

	_renderNote(record: OfflineMutationRecord, queue: OfflineQueue, key: string) {
		const body = queue.field(record, "body");
		const visibility = queue.field(record, "visibility") || "private";
		const file = record.files?.[0]?.file;

		const item = document.createElement("li");
		item.dataset.key = key;
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
		button.dataset.key = key;
		button.type = "button";
		button.setAttribute("aria-label", "Discard pending note");
		button.title = "Discard pending note";
		item.append(button);

		const icon = document.createElement("span");
		setIcon(icon, "close");
		button.append(icon);

		return item;
	}

	_itemByKey(root: HTMLElement | null, key?: string | null) {
		if (!root || !key) return null;
		return Array.from(root.querySelectorAll<HTMLElement>("[data-key]")).find(
			(item) => item.dataset.key === key,
		);
	}

	_removeByKey(key?: string | null) {
		const item = this._itemByKey(this.target, key);
		if (!item) return undefined;
		return withTransition(() => this._commitRemoveItem(item), {
			label: "home:activity-offline-remove",
		});
	}

	_commitRemoveItem(item: HTMLElement) {
		const list = item.closest("ul");
		item.remove();

		if (list && list.querySelectorAll("li").length === 0) {
			list.dataset.visible = "false";
			this.view.syncHomeSectionState?.(this.component);
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
