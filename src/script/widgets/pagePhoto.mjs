import { BaseUpload } from "../elements/base/baseUpload";
import { sections } from "../elements/sections";
import { UploadMenu, uploadElement } from "../elements/upload";
import { request, withTransition } from "../shared";
import { createIcon } from "../shared/icons";

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_generate_image_on_page
 * @matrix pages : image-generate photo-visibility photo-prompt ai-disabled
 */
export class PagePhoto extends BaseUpload {
	constructor(attributes) {
		super(attributes);
		this.dropzone = uploadElement.dropzone({
			element: this.target.querySelector("[data-role='dropzone']"),
		});
		this.inputName = "page-photo";
		this.uploadType = "image";
		this.aiCreate = this.target.dataset.aiCreate === "true";
		this.menuOptions = [
			"remove",
			"replace",
			...(this.aiCreate ? ["generate"] : []),
			"paste",
		];
		this.uploadMenu = new UploadMenu(this);
		this.generateForm = this.aiCreate ? sections.generateImageForm() : null;
		this.submitGroup = this.generateForm?.submitGroup;
		this.messages = {
			submit: "Generate",
			submitting: "Thinking...",
			submitted: "Done",
		};
		this.icon = "generate";

		this._generateImage = this._generateImage.bind(this);
	}

	get html() {
		return [
			this.dropzone.element,
			...(this.aiCreate ? [this.generateForm.element] : []),
		];
	}

	get fileAttached() {
		return super.fileAttached || this.dropzone.containsImage;
	}

	get feedback() {
		return this.dropzone.element.querySelector("[data-role='feedback']");
	}

	get existingImage() {
		return this.dropzone.element.querySelector("[data-role='existing-image']");
	}

	get newImage() {
		return this.dropzone.element.querySelector("[data-role='new-image']");
	}

	async init() {
		await super.init();
		if (this.readonly) return;

		if (this.aiCreate) {
			this.submitGroup.addEventListener("click", (e) => {
				if (e.target.closest("[data-role='cancel']")) {
					void this.view.cancelPhotoGeneration(this);
				}
			});

			this.target.addEventListener("submit", this._generateImage);
		}
	}

	shouldAutoUpload() {
		return true;
	}

	async autoUpload() {
		await this.uploadImage();
	}

	_replaceDropzone(html) {
		this.reset();
		const newDropzone = html.querySelector("[data-role='dropzone']");
		newDropzone.querySelectorAll("img[src]").forEach((image) => {
			const source = image.getAttribute("src");
			if (!source || /^(blob|data):/.test(source)) return;

			const url = new URL(source, window.location.href);
			url.searchParams.set("v", Date.now().toString());
			const refreshedSource =
				url.origin === window.location.origin
					? `${url.pathname}${url.search}${url.hash}`
					: url.href;
			image.setAttribute("src", refreshedSource);
		});
		this.dropzone.element.replaceWith(newDropzone);
		this.dropzone = uploadElement.dropzone({
			element: newDropzone,
		});
		this.uploadMenu.destroy();
		this.uploadMenu = new UploadMenu(this);

		this.reset();
		this._initDropZone();
		if (this.uploadMenu) this.uploadMenu.create();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_add_image_to_page
	 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_replace_image_on_page
	 * @matrix pages : image-add image-replace upload-error
	 */
	async uploadImage() {
		return this._withImageMutation(async () => {
			withTransition(() => {
				this.existingImage.dataset.visible = "false";
				this.newImage.dataset.visible = "true";
				this.feedback.replaceChildren(createIcon("spinner"), " Uploading...");
			});

			const prepared = await this.prepareSubmit({
				route: this.endpoints.upload,
			});
			if (!prepared) return;

			const response = await request.post(this.endpoints.upload, this.formData);
			if (!this.view.successfulResponse(response, this.component)) return;

			await this.view.updatePhotoImage(true, () => {
				this._replaceDropzone(response.html);
			});
		});
	}

	/**
	 * @testable false
	 * @covered-by src/script/widgets/pagePhoto.mjs::PagePhoto.uploadImage
	 * @covered-by src/script/widgets/pagePhoto.mjs::PagePhoto._generateImage
	 * @covered-by src/script/widgets/pagePhoto.mjs::PagePhoto._removeImage
	 * @reason serialize image changes while keeping view controls and editor availability aligned
	 */
	async _withImageMutation(operation) {
		if (this.view.photoBusy || this.readonly) return;
		this.view.setPhotoBusy(true);
		this.target.inert = true;
		try {
			return await operation();
		} finally {
			this.target.inert = false;
			this.view.setPhotoBusy(false);
		}
	}

	removeFile() {
		this.reset();
		this._removeImage();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_remove_image_from_page
	 * @pair pages:image-remove
	 */
	async _removeImage() {
		return this._withImageMutation(async () => {
			const response = await request.delete(this.endpoints.remove);
			if (!this.view.successfulResponse(response, this.component)) return;

			await this.view.updatePhotoImage(false, () => {
				this._replaceDropzone(response.html);
			});
		});
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_generate_image_on_page
	 * @pair pages:image-generate
	 */
	async _generateImage() {
		return this._withImageMutation(async () => {
			const response = await request.post(
				this.endpoints.generate,
				this.formData,
			);
			if (!this.view.successfulResponse(response, this.component)) return;

			await this.view.updatePhotoImage(true, () => {
				this._replaceDropzone(response.html);
				this.hideGenerateForm({ transition: false });
			});
		});
	}

	reset() {
		super.reset();
		this.generateForm?.reset();
		this.hideError();
	}

	showError(message) {
		withTransition(() => {
			if (this.generateForm?.visible()) {
				this.form.showError(message);
			} else {
				this.newImage.dataset.visible = "true";
				this.existingImage.dataset.visible = String(
					this.dropzone.containsImage,
				);
				const error = document.createElement("span");
				error.className = "text-delete text-base italic";
				error.textContent = message;
				if (this.dropzone.containsImage) {
					this.newImage.dataset.visible = "false";
					error.dataset.role = "image-error";
					this.dropzone.element
						.querySelector("[data-role='image-error']")
						?.remove();
					this.dropzone.element.append(error);
				} else this.feedback.replaceChildren(error);
			}
		});
	}

	hideError() {
		this.dropzone.element.querySelector("[data-role='image-error']")?.remove();
		if (this.generateForm?.visible()) {
			this.form.hideError();
		} else {
			this.feedback.innerHTML = "drop image here<br>or click to upload";
		}
	}

	showGenerateForm({ transition = true } = {}) {
		if (!this.aiCreate || this.readonly) return;
		if (this.generateForm.visible()) {
			this.generateForm.show();
			return;
		}
		this.view.photoGenerationReturnOpen ??= this.view.photoOpen;
		const show = () => {
			this.reset();
			this.dropzone.hide();
			this.generateForm.show();
			this.form.showSubmitButton();
		};
		const shouldTransition =
			transition &&
			(this.view.isSecondaryCardVisible?.(this.component.elt) ?? true);

		if (shouldTransition) {
			return withTransition(show);
		}
		show();
	}

	hideGenerateForm({ transition = true } = {}) {
		const hide = () => {
			this.reset();
			this.generateForm?.hide();
			this.dropzone.show();
			this.view.photoGenerationReturnOpen = null;
		};
		const shouldTransition =
			transition &&
			(this.view.isSecondaryCardVisible?.(this.component.elt) ?? true);

		if (shouldTransition) {
			return withTransition(hide);
		}
		hide();
	}
}
