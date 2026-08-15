/*! Third-party licenses: /third-party-licenses.txt */
import { B as BaseUpload, u as uploadElement, U as UploadMenu } from './baseUpload.js?v=b3ba4dd3';
import { s as sections } from './sections.js?v=b3ba4dd3';
import { w as withTransition, r as request } from './foundation.js?v=b3ba4dd3';
import './connectivity.js?v=b3ba4dd3';
import { c as createIcon } from './icons.js?v=b3ba4dd3';
import './styles.js?v=b3ba4dd3';
import './buttons.js?v=b3ba4dd3';
import './formatting.js?v=b3ba4dd3';
import './dropdown.js?v=b3ba4dd3';
import './combobox.js?v=b3ba4dd3';
import './primitives.js?v=b3ba4dd3';
import './baseForm.js?v=b3ba4dd3';
import './loader.js?v=b3ba4dd3';

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_generate_image_on_page
 * @features pages
 * @dimensions image-generate
 */
class PagePhoto extends BaseUpload {
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
		this.generateForm = sections.generateImageForm();
		this.submitGroup = this.generateForm.submitGroup;
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
					this.hideGenerateForm();
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
	 * @testable false
	 * @covered-by src/script/widgets/pagePhoto.mjs::PagePhoto.uploadImage
	 * @covered-by src/script/widgets/pagePhoto.mjs::PagePhoto._generateImage
	 * @reason private page-shell reconciliation after a page image is created
	 */
	_markImageAvailable() {
		if (!this.dropzone.containsImage) return;

		if (typeof this.view.setAttributeActive === "function") {
			this.view.setAttributeActive("photo", true);
		} else {
			this.view.elt
				.querySelectorAll("[data-has-attribute][data-attribute='photo']")
				.forEach((element) => {
					element.dataset.hasAttribute = "true";
				});
			const attribute = this.view.elt.querySelector(
				"[data-role='attribute'][data-attribute='photo']",
			);
			if (attribute) {
				attribute.dataset.selected = "true";
				const checkbox = attribute.querySelector("input[type='checkbox']");
				if (checkbox) checkbox.checked = true;
			}
		}

		if (typeof this.view.setSecondaryCardActive === "function") {
			this.view.setSecondaryCardActive(this.component.elt, true);
		} else {
			this.view.elt.dataset.secondary = "true";
			this.view.elt.classList.remove("max-w-5xl");
			this.view.elt.classList.add("max-w-7xl");
			this.component.elt.dataset.visible = "true";
			this.component.elt.dataset.persistent = "true";
		}

		this._removePhotoPrompt();
	}

	/**
	 * @testable false
	 * @covered-by src/script/widgets/pagePhoto.mjs::PagePhoto._markImageAvailable
	 * @reason prompt teardown is a small part of page image availability reconciliation
	 */
	_removePhotoPrompt() {
		this.view.elt.querySelector("[data-role='photo-prompt']")?.remove();
	}

	/**
	 * @testable false
	 * @covered-by src/script/widgets/pagePhoto.mjs::PagePhoto.uploadImage
	 * @covered-by src/script/widgets/pagePhoto.mjs::PagePhoto._generateImage
	 * @reason image upload/generation shares layout and prompt reconciliation
	 */
	async _updateImageLayout(mutate) {
		if (typeof this.view.updateLayout === "function") {
			await this.view.updateLayout({
				attribute: "photo",
				attributeActive: true,
				secondary: this.component.elt,
				secondaryActive: true,
				mutate: () => () => {
					mutate();
					this._removePhotoPrompt();
				},
			});
			return;
		}

		return await withTransition(() => {
			mutate();
			this._markImageAvailable();
		});
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_add_image_to_page
	 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_replace_image_on_page
	 * @features pages
	 * @dimensions image-add image-replace
	 */
	async uploadImage() {
		withTransition(() => {
			this.existingImage.dataset.visible = "false";
			this.newImage.dataset.visible = "true";
			this.feedback.replaceChildren(createIcon("spinner"), " Uploading...");
		});

		const prepared = await this.prepareSubmit({ route: this.endpoints.upload });
		if (!prepared) return;

		const response = await request.post(this.endpoints.upload, this.formData);
		if (!this.view.successfulResponse(response, this.component)) return;

		await this._updateImageLayout(() => {
			this._replaceDropzone(response.html);
		});
	}

	removeFile() {
		this.reset();
		this._removeImage();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_remove_image_from_page
	 * @features pages
	 * @dimensions image-remove
	 */
	async _removeImage() {
		const response = await request.delete(this.endpoints.remove);
		if (!this.view.successfulResponse(response, this.component)) return;

		withTransition(() => {
			this._replaceDropzone(response.html);
		});
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_generate_image_on_page
	 * @features pages
	 * @dimensions image-generate
	 */
	async _generateImage() {
		const response = await request.post(this.endpoints.generate, this.formData);
		if (!this.view.successfulResponse(response, this.component)) return;

		await this._updateImageLayout(() => {
			this._replaceDropzone(response.html);
			this.hideGenerateForm({ transition: false });
		});
	}

	reset() {
		super.reset();
		this.generateForm.reset();
		this.hideError();
	}

	showError(message) {
		withTransition(() => {
			if (this.generateForm.visible()) {
				this.form.showError(message);
			} else {
				this.newImage.dataset.visible = "true";
				this.existingImage.dataset.visible = "false";
				const error = document.createElement("span");
				error.className = "text-delete text-base italic";
				error.textContent = message;
				this.feedback.replaceChildren(error);
			}
		});
	}

	hideError() {
		if (this.generateForm.visible()) {
			this.form.hideError();
		} else {
			this.feedback.innerHTML = "drop image here<br>or click to upload";
		}
	}

	showGenerateForm({ transition = true } = {}) {
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
			this.generateForm.hide();
			this.dropzone.show();
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

export { PagePhoto };
