import { BaseUpload } from "../../elements/base/baseUpload.ts";
import { UploadMenu, uploadElement } from "../../elements/upload.ts";
import type { ENDPOINTS } from "../../shared/endpoints.ts";
import { setIcon } from "../../shared/icons.ts";
import { request } from "../../shared/index.ts";
import { withTransition } from "../../shared/transitions.ts";
import { SiteSetting, type SiteSettingAttributes } from "./base.ts";

const SPLASH_PREFIX = "splash-";

class SiteImageUpload extends BaseUpload {
	onFileAttached() {
		const button = this.form?.submitButton;
		if (button) button.disabled = false;
	}

	reset() {
		super.reset();
		const button = this.form?.submitButton;
		if (button) {
			button.dataset.visible = "true";
			button.disabled = true;
		}
	}
}

type ImageEndpoints = ReturnType<typeof ENDPOINTS.SiteImage>;
type SiteImageFiles = Record<string, string>;

interface SiteImageResponse {
	site_image?: SiteImageFiles | null;
}

export class SiteImage extends SiteSetting<ImageEndpoints> {
	declare _siteImage: SiteImageResponse["site_image"];
	declare _uploadInitialization: Promise<void> | null;
	declare upload?: BaseUpload;

	constructor(attributes: SiteSettingAttributes<ImageEndpoints>) {
		super(attributes);
		this._siteImage = null;
		this._uploadInitialization = null;
		this._uploadImage = this._uploadImage.bind(this);
	}

	updated(response: SiteImageResponse) {
		this._siteImage = response.site_image;
	}

	postreconcile() {
		if (this._siteImage) this._renderSiteImage(this._siteImage);
	}

	opened() {
		if (this._uploadInitialization) return this._uploadInitialization;

		const pending = this._initUpload().catch((error) => {
			if (this._uploadInitialization === pending) {
				this._uploadInitialization = null;
			}
			throw error;
		});
		this._uploadInitialization = pending;
		return pending;
	}

	async _initUpload() {
		const uploadForm = this.target.querySelector<HTMLFormElement>(
			"[data-role='upload-site-image']",
		);
		if (!uploadForm) return;

		const dropzone = uploadElement.dropzone({
			text: "Drop image here, click to upload, or tap to choose camera/files",
		});

		const upload = new SiteImageUpload({
			target: uploadForm,
			dropzone,
			submitButton: uploadForm.querySelector("button[type='submit']"),
			inputName: "site-image",
			uploadType: "image",
			menuOptions: ["paste", "remove"],
			messages: {
				submit: "Update Site Image",
				submitting: "Processing Image",
				submitted: "Image Processed",
			},
			html: [dropzone.element],
		});

		this.upload = upload;
		upload.uploadMenu = new UploadMenu(upload);
		await upload.init();
		if (upload.form?.submitButton) {
			upload.form.submitButton.disabled = !upload.fileAttached;
		}
		this.destroyables.push(upload);

		uploadForm.addEventListener("submit", this._uploadImage);
	}

	async _uploadImage(event: SubmitEvent) {
		event.preventDefault();
		event.stopPropagation();
		const upload = this.upload;
		if (!upload) return;

		const prepared = await upload.prepareSubmit({
			route: this.endpoints.setSiteImage,
		});
		if (!prepared) return;

		const response = await request.post<SiteImageResponse>(
			this.endpoints.setSiteImage,
			upload.formData,
		);
		if (!response?.ok) {
			if (response?.error) upload.showError(response.error);
			upload.form?.resetSubmitButton();
			return;
		}

		upload.form?.success();
		const image = response.site_image;
		if (image) {
			this._siteImage = image;
			withTransition(() => {
				this._renderSiteImage(image);
			});
		}
	}

	_renderSiteImage(imageData: SiteImageFiles) {
		const container = this.target.querySelector("[data-role='site-image']");
		if (!container || !imageData) return;

		const entries = Object.entries(imageData).filter(
			([name]) => !name.startsWith(SPLASH_PREFIX),
		);
		const fragment = document.createDocumentFragment();

		const previewUrl =
			imageData["apple-touch-icon.png"] || imageData["logo-192x192.png"];
		if (previewUrl) {
			const preview = document.createElement("img");
			preview.src = `${previewUrl}?v=${Date.now()}`;
			preview.alt = "Site image";
			preview.className = "size-20 rounded-lg object-contain";
			fragment.appendChild(preview);
		}

		if (entries.length > 0) {
			const grid = document.createElement("div");
			grid.className = "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2";

			for (const [filename, url] of entries) {
				const link = document.createElement("a");
				link.href = url;
				link.target = "_blank";
				link.rel = "noopener noreferrer";
				link.className =
					"flex flex-row items-center gap-2 rounded-md border border-base-light/50 bg-white px-3 py-2 text-sm hover:bg-base-bg transition-colors";

				const icon = document.createElement("span");
				setIcon(icon, "image", "icon-xs text-base-medium");

				const name = document.createElement("span");
				name.className = "text-base-dark font-medium truncate grow text-xs";
				name.textContent = filename;

				const arrow = document.createElement("span");
				setIcon(arrow, "next", "icon-xs text-base-medium");

				link.append(icon, name, arrow);
				grid.appendChild(link);
			}

			fragment.appendChild(grid);
		}

		this.updateSummary(`${entries.length} generated files`);
		container.replaceChildren(fragment);
	}
}
