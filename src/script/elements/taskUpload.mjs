import { STYLES } from "styles";
import { ENDPOINTS, request, withTransition } from "../shared";
import { createIcon, setIcon } from "../shared/icons";
import { BaseUpload } from "./base/baseUpload";
import { UploadMenu, uploadElement } from "./upload";

const UPLOAD_DROPZONE_TEXT =
	"Drop file/photo here, click to upload, or tap to choose camera/files";

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_file
 * @features tasks
 * @dimensions create file-upload
 */
export class TaskUpload extends BaseUpload {
	constructor(button, widget) {
		super({
			button,
			action: button.dataset.action,
		});

		this.widget = widget;
		this.target = document.createElement("div");
		this.target.className = "w-full flex flex-col gap-2 group/upload";
		this.target.dataset.visible = "false";
		this.button.insertAdjacentElement("afterend", this.target);

		this.assets = JSON.parse(button.dataset.preload || "{}");
		this.task = button.closest("[lp-component]");
		this.taskRow = button.closest("li[lp-entity][data-kind='task']");
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
		const file = this.fileInput?.element.files[0];
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

	_deleteUrl(file) {
		if (file.delete_url) return file.delete_url;
		const key = file.key || file.id;
		if (!key || !file.attached || !this.taskRow) return null;
		return this.endpoints.remove(key);
	}

	_deleteButton(file) {
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

	_fileUrl(file) {
		if (file.url) return file.url;
		if (file.kind === "file" && file.id) return `/files/${file.id}`;
		return "#";
	}

	_assetItem([name, file]) {
		const label = file.name || file.filename || name;
		const item = document.createElement("li");
		item.dataset.key = file.key || file.id || "";
		item.dataset.kind = "file";
		item.className =
			"flex flex-row items-baseline justify-between gap-4 p-4 rounded-md bg-base-bg";

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
		if (!this.endpoints.upload) {
			this.showError("Upload route unavailable");
			return;
		}

		this.dropzone.setText(`${createIcon("spinner").outerHTML} Uploading...`);
		const prepared = await this.prepareSubmit({ route: this.endpoints.upload });
		if (!prepared) return;

		const response = await request.post(this.endpoints.upload, this.formData);
		if (!response.ok) {
			this.showError(response.error || "Could not upload attachment");
			return;
		}

		withTransition(() => {
			this.assets = response.assets || {};
			this.renderAssets();
			this.reset();
		});
	}

	_removeBadge(file) {
		if (!this.task || !file) return;
		const labels = new Set([file.name, file.filename].filter(Boolean));
		const url = this._fileUrl(file);
		const urls = new Set(url === "#" ? [] : [url]);

		this.task.querySelectorAll("[data-kind='file']").forEach((badge) => {
			if (badge.closest("[data-role='saved-files']")) return;
			const link = badge.querySelector("a");
			const text = badge.textContent.trim();
			if (labels.has(text) || (link && urls.has(link.getAttribute("href")))) {
				badge.remove();
			}
		});
	}

	async _deleteFile(e) {
		const button = e.target.closest("[data-role='delete-task-file']");
		if (!button) return;

		e.preventDefault();
		e.stopPropagation();

		const item = button.closest("[data-kind='file']");
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
		const response = await request.delete(route, data);
		button.disabled = false;
		if (!response.ok) {
			this.showError(response.error || "Could not delete attachment");
			return;
		}

		withTransition(() => {
			this.assets = response.assets || {};
			this.renderAssets();
			this._removeBadge(response.deleted || file);
		});
	}

	toggleVisibility() {
		this.target.dataset.visible =
			this.target.dataset.visible === "true" ? "false" : "true";
	}

	reset() {
		super.reset();
	}

	clear() {
		this.reset();
		this.toggle.display();
	}

	showError(message) {
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
