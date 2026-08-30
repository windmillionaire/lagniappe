import { BaseUpload } from "../../elements/base/baseUpload";
import { UploadMenu, uploadElement } from "../../elements/upload";
import { request, withTransition } from "../../shared";
import { setIcon } from "../../shared/icons";
import { SiteSetting } from "./base";

const SPLASH_PREFIX = "splash-";

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008g_site_settings.py::test_site_settings_image_upload_generates_and_persists_site_images
 * @matrix admin : generated-images lazy-initialization metadata public-preview site-image-upload
 */
export class SiteImage extends SiteSetting {
	constructor(attributes) {
		super(attributes);
		this._siteImage = null;
		this._uploadInitialization = null;
		this._uploadImage = this._uploadImage.bind(this);
	}

	updated(response) {
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
		const uploadForm = this.target.querySelector(
			"[data-role='upload-site-image']",
		);
		if (!uploadForm) return;

		const dropzone = uploadElement.dropzone({
			text: "Drop image here, click to upload, or tap to choose camera/files",
		});

		this.upload = new BaseUpload({
			target: uploadForm,
			dropzone: dropzone,
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

		this.upload.uploadMenu = new UploadMenu(this.upload);
		await this.upload.init();
		this.destroyables.push(this.upload);

		uploadForm.addEventListener("submit", this._uploadImage);
	}

	async _uploadImage(event) {
		event.preventDefault();
		event.stopPropagation();

		const prepared = await this.upload.prepareSubmit({
			route: this.endpoints.setSiteImage,
		});
		if (!prepared) return;

		const response = await request.post(
			this.endpoints.setSiteImage,
			this.upload.formData,
		);
		if (!response.ok) {
			if (response.error) this.upload.showError(response.error);
			this.upload.form?.resetSubmitButton();
			return;
		}

		this.upload.form?.success();
		if (response.site_image) {
			this._siteImage = response.site_image;
			withTransition(() => {
				this._renderSiteImage(response.site_image);
			});
		}
	}

	_renderSiteImage(imageData) {
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
