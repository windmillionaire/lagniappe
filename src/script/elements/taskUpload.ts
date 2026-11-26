import { STYLES } from "../generated/styles.mjs";
import { createIcon, setIcon } from "../shared/icons.ts";
import { ENDPOINTS, request } from "../shared/index.ts";
import { withTransition } from "../shared/transitions.ts";
import { BaseUpload } from "./base/baseUpload.ts";
import type { SectionToggle } from "./sectionToggle.ts";
import { UploadMenu, uploadElement } from "./upload.ts";

const UPLOAD_DROPZONE_TEXT =
	"Drop file/photo here, click to upload, or tap to choose camera/files";

export interface TaskAsset {
	key?: string | null;
	id?: string | null;
	name?: string | null;
	filename?: string | null;
	kind?: string | null;
	url?: string | null;
	delete_url?: string | null;
	attached?: boolean | null;
}

type TaskAssets = Record<string, TaskAsset>;
type TaskAssetResponse = { assets: unknown; deleted: unknown };

function isTaskAsset(value: unknown): value is TaskAsset {
	if (!value || typeof value !== "object" || Array.isArray(value)) return false;
	const data: Record<string, unknown> = { ...value };
	return (
		["key", "id", "name", "filename", "kind", "url", "delete_url"].every(
			(key) => data[key] == null || typeof data[key] === "string",
		) &&
		(data.attached == null || typeof data.attached === "boolean")
	);
}

function taskAssets(value: unknown): TaskAssets {
	if (!value || typeof value !== "object" || Array.isArray(value)) return {};
	const entries = Object.entries(value).filter(
		(entry): entry is [string, TaskAsset] => isTaskAsset(entry[1]),
	);
	return Object.fromEntries(entries);
}

interface TaskUploadWidget {
	key?: string | null;
	readonly?: boolean;
}

export class TaskUpload extends BaseUpload {
	declare button: HTMLButtonElement;
	declare action?: string;
	declare widget?: TaskUploadWidget;
	declare assets: TaskAssets;
	declare task: HTMLElement | null;
	declare taskRow: HTMLLIElement | null;
	declare key?: string | null;
	declare endpoints: Partial<ReturnType<typeof ENDPOINTS.TaskUpload>>;
	declare assetsInput: HTMLInputElement;
	declare assetsList: HTMLUListElement;
	declare kind: "file";
	declare messages: Record<string, string>;
	declare menuOptions: string[];
	declare dropzone: ReturnType<typeof uploadElement.dropzone>;
	declare toggle: SectionToggle | null;

	constructor(button: HTMLButtonElement, widget?: TaskUploadWidget) {
		super({
			button,
			action: button.dataset.action,
		});

		this.widget = widget;
		this.target = document.createElement("div");
		this.target.className = "mt-2 w-full flex flex-col gap-2 group/upload";
		this.target.dataset.visible = "false";
		this.button.insertAdjacentElement("afterend", this.target);

		const preload: unknown = JSON.parse(button.dataset.preload || "{}");
		this.assets = taskAssets(preload);
		this.task = button.closest<HTMLElement>("[lp-component]");
		this.taskRow = button.closest<HTMLLIElement>(
			"li[lp-entity][data-kind='task']",
		);
		this.key = this.taskRow?.dataset.key || widget?.key;
		this.endpoints = this.key ? ENDPOINTS.TaskUpload({ key: this.key }) : {};

		this.assetsInput = this._assetsInput();
		this.assetsList = this._assetsList();

		this.kind = "file";
		this.inputName = "task-file";
		this.uploadType = "file";
		this.messages = {
			submit: "Attach File/Photo",
			submitting: "Attaching File/Photo",
			submitted: "File/Photo Attached",
		};
		this.dropzone = uploadElement.dropzone({ text: UPLOAD_DROPZONE_TEXT });
		this.menuOptions = ["replace", "paste"];
		this.uploadMenu = new UploadMenu(this);

		this.toggle = null;
		this._deleteFile = this._deleteFile.bind(this);
	}

	get html() {
		return [this.assetsInput, this.dropzone.element, this.assetsList];
	}

	get formData() {
		const data = new FormData();
		const file = this.fileInput?.element.files?.[0];
		if (file) data.append(this.inputName, file);
		if (this.mimeType?.element) {
			data.append(this.mimeType.element.name, this.mimeType.element.value);
		}
		this._syncAssetsInput();
		data.append(this.assetsInput.name, this.assetsInput.value);

		return this.applyDirectUploads(data);
	}

	async init() {
		await super.init();

		this.toggle?.display();
		this.assetsList.addEventListener("click", this._deleteFile);
		this.renderAssets();
	}

	_assetsInput() {
		const input = document.createElement("input");
		input.type = "hidden";
		input.name = "assets";
		input.value = JSON.stringify(this.assets || {});
		return input;
	}

	_assetsList() {
		const list = document.createElement("ul");
		list.dataset.role = "saved-files";
		list.dataset.kind = "file";
		list.className =
			"outline-2 outline-kind-default rounded-md divide-y-kind-light bg-kind-bg w-full";
		return list;
	}

	_syncAssetsInput() {
		this.assetsInput.value = JSON.stringify(this.assets || {});
	}

	_deleteUrl(file: TaskAsset) {
		if (file.delete_url) return file.delete_url;
		const key = file.key || file.id;
		if (!key || !file.attached || !this.taskRow) return null;
		return this.endpoints.remove?.(key) ?? null;
	}

	_deleteButton(file: TaskAsset) {
		const name = file.name || file.filename || "attachment";
		const button = document.createElement("button");
		button.type = "button";
		button.dataset.role = "delete-task-file";
		button.dataset.kind = "delete";
		button.dataset.active = "false";
		button.dataset.route = this._deleteUrl(file) || "";
		button.className = STYLES.toggle.container;
		button.setAttribute("aria-label", `Delete ${name}`);
		button.title = `Delete ${name}`;

		const active = button.appendChild(document.createElement("span"));
		setIcon(active, "trash.active", STYLES.toggle.icon.active);

		const inactive = button.appendChild(document.createElement("span"));
		setIcon(inactive, "trash.inactive", STYLES.toggle.icon.inactive);

		return button;
	}

	_fileUrl(file: TaskAsset) {
		if (file.url) return file.url;
		if (file.kind === "file" && file.id) return `/files/${file.id}`;
		return "#";
	}

	_assetItem([name, file]: [string, TaskAsset]) {
		const label = file.name || file.filename || name;
		const item = document.createElement("li");
		item.dataset.key = file.key || file.id || "";
		item.dataset.kind = "file";
		item.className =
			"flex flex-row items-center justify-between gap-4 p-4 rounded-md bg-base-bg";

		const link = item.appendChild(document.createElement("a"));
		link.href = this._fileUrl(file);
		link.dataset.kind = "file";
		link.className = STYLES.link.title;
		link.textContent = label;

		item.appendChild(this._deleteButton(file));
		return item;
	}

	renderAssets() {
		this._syncAssetsInput();
		const entries = Object.entries(this.assets || {});
		this.assetsList.dataset.visible = entries.length > 0 ? "true" : "false";
		this.assetsList.replaceChildren(
			...entries.map((entry) => this._assetItem(entry)),
		);
	}

	shouldAutoUpload() {
		return true;
	}

	async autoUpload() {
		await this.uploadFile();
	}

	async uploadFile() {
		const route = this.endpoints.upload;
		if (!route) {
			this.showError("Upload route unavailable");
			return;
		}

		this.dropzone.setContent(createIcon("spinner"), " Uploading...");
		const prepared = await this.prepareSubmit({ route });
		if (!prepared) return;

		const response = await request.post<TaskAssetResponse>(
			route,
			this.formData,
		);
		if (!response?.ok) {
			this.showError(response?.error || "Could not upload attachment");
			return;
		}

		this.assets = taskAssets(response.assets);
		withTransition(() => {
			this.renderAssets();
			this.reset();
		});
		this.target.dispatchEvent(
			new CustomEvent("task-assets-changed", {
				bubbles: true,
				detail: { assets: this.assets, action: "upload" },
			}),
		);
	}

	_removeBadge(file?: TaskAsset) {
		if (!this.task || !file) return;
		const labels = new Set([file.name, file.filename].filter(Boolean));
		const url = this._fileUrl(file);
		const urls = new Set(url === "#" ? [] : [url]);

		this.task.querySelectorAll("[data-kind='file']").forEach((badge) => {
			if (badge.closest("[data-role='saved-files']")) return;
			const link = badge.querySelector("a");
			const text = badge.textContent?.trim();
			const href = link?.getAttribute("href");
			if ((text && labels.has(text)) || (href && urls.has(href))) {
				badge.remove();
			}
		});
	}

	async _deleteFile(e: MouseEvent) {
		const button =
			e.target instanceof Element
				? e.target.closest<HTMLButtonElement>("[data-role='delete-task-file']")
				: null;
		if (!button) return;

		e.preventDefault();
		e.stopPropagation();

		const item = button.closest<HTMLElement>("[data-kind='file']");
		const key = item?.dataset.key;
		const file = Object.values(this.assets || {}).find(
			(asset) => (asset.key || asset.id) === key,
		);
		const route = button.dataset.route;
		if (!route) {
			if (key) {
				this.assets = Object.fromEntries(
					Object.entries(this.assets || {}).filter(
						([, asset]) => (asset.key || asset.id) !== key,
					),
				);
			}
			this.renderAssets();
			return;
		}

		const data = new FormData();
		data.append("assets", JSON.stringify(this.assets || {}));
		button.disabled = true;
		const response = await request.delete<TaskAssetResponse>(route, data);
		button.disabled = false;
		if (!response?.ok) {
			this.showError(response?.error || "Could not delete attachment");
			return;
		}

		this.assets = taskAssets(response.assets);
		withTransition(() => {
			this.renderAssets();
			this._removeBadge(
				isTaskAsset(response.deleted) ? response.deleted : file,
			);
		});
		this.target.dispatchEvent(
			new CustomEvent("task-assets-changed", {
				bubbles: true,
				detail: { assets: this.assets, action: "delete" },
			}),
		);
	}

	get open() {
		return this.target.dataset.visible === "true";
	}

	toggleVisibility() {
		this.target.dataset.visible = this.open ? "false" : "true";
		this.toggle?.display();
	}

	reset() {
		super.reset();
	}

	clear() {
		if (this.open) {
			this.target.dataset.visible = "false";
		} else {
			this.reset();
		}
		this.toggle?.display();
	}

	showError(message: string) {
		super.showError(message);
	}

	hideError() {
		super.hideError();
	}

	destroy() {
		this.assetsList.removeEventListener("click", this._deleteFile);
		super.destroy();
	}
}
