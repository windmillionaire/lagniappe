import { BaseUpload } from "../elements/base/baseUpload.ts";
import { sections } from "../elements/sections.ts";
import { UploadMenu, uploadElement } from "../elements/upload.ts";
import type { ENDPOINTS } from "../shared/endpoints.ts";
import { createIcon } from "../shared/icons.ts";
import { request } from "../shared/index.ts";
import { withTransition } from "../shared/transitions.ts";

import type ViewComponent from "../views/base/component.ts";
import type Page from "../views/page.ts";

type PagePhotoView = Pick<
	Page,
	| "photoBusy"
	| "photoOpen"
	| "photoGenerationReturnOpen"
	| "setPhotoBusy"
	| "cancelPhotoGeneration"
	| "updatePhotoImage"
	| "successfulResponse"
> &
	Partial<Pick<Page, "isSecondaryCardVisible">>;
type PagePhotoComponent = Pick<ViewComponent, "elt" | "showError">;
type PagePhotoEndpoints = ReturnType<typeof ENDPOINTS.PagePhoto>;
type PagePhotoAttributes = NonNullable<
	ConstructorParameters<typeof BaseUpload>[0]
> & {
	view: PagePhotoView;
	component: PagePhotoComponent;
	endpoints: PagePhotoEndpoints;
};

export class PagePhoto extends BaseUpload {
	declare view: PagePhotoView;
	declare component: PagePhotoComponent;
	declare endpoints: PagePhotoEndpoints;
	declare dropzone: ReturnType<typeof uploadElement.dropzone>;
	declare uploadMenu: UploadMenu;
	declare aiCreate: boolean;
	declare menuOptions: ("remove" | "replace" | "generate" | "paste")[];
	declare generateForm: ReturnType<typeof sections.generateImageForm> | null;
	declare submitGroup?: HTMLElement;
	declare messages: Record<string, string>;
	declare icon: string;

	constructor(attributes: PagePhotoAttributes) {
		super(attributes);
		this.dropzone = uploadElement.dropzone({
			element: this.target.querySelector<HTMLElement>("[data-role='dropzone']"),
		});
		this.inputName = "page-photo";
		this.uploadType = "image";
		this.aiCreate = this.target.dataset.aiCreate === "true";
		this.menuOptions = [
			"remove",
			"replace",
			...(this.aiCreate ? ["generate" as const] : []),
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
			...(this.generateForm ? [this.generateForm.element] : []),
		];
	}

	get fileAttached() {
		return super.fileAttached || this.dropzone.containsImage;
	}

	get feedback() {
		return this.dropzone.element.querySelector<HTMLElement>(
			"[data-role='feedback']",
		);
	}

	get existingImage() {
		return this.dropzone.element.querySelector<HTMLElement>(
			"[data-role='existing-image']",
		);
	}

	get newImage() {
		return this.dropzone.element.querySelector<HTMLElement>(
			"[data-role='new-image']",
		);
	}

	async init() {
		await super.init();
		if (this.readonly) return;

		if (this.aiCreate) {
			this.submitGroup?.addEventListener("click", (e) => {
				if (
					e.target instanceof Element &&
					e.target.closest("[data-role='cancel']")
				) {
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

	_replaceDropzone(html: Document) {
		this.reset();
		const newDropzone = html.querySelector<HTMLElement>(
			"[data-role='dropzone']",
		);
		if (!newDropzone) return;
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

	async uploadImage() {
		return this._withImageMutation(async () => {
			withTransition(() => {
				const existingImage = this.existingImage;
				const newImage = this.newImage;
				if (existingImage) existingImage.dataset.visible = "false";
				if (newImage) newImage.dataset.visible = "true";
				this.feedback?.replaceChildren(createIcon("spinner"), " Uploading...");
			});

			const prepared = await this.prepareSubmit({
				route: this.endpoints.upload,
			});
			if (!prepared) return;

			const response = await request.post(this.endpoints.upload, this.formData);
			if (
				!this.view.successfulResponse(response, this.component) ||
				!response?.html
			)
				return;
			const { html } = response;

			await this.view.updatePhotoImage(true, () => {
				this._replaceDropzone(html);
			});
		});
	}

	async _withImageMutation(operation: () => Promise<void>) {
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

	async _removeImage() {
		return this._withImageMutation(async () => {
			const response = await request.delete(this.endpoints.remove);
			if (
				!this.view.successfulResponse(response, this.component) ||
				!response?.html
			)
				return;
			const { html } = response;

			await this.view.updatePhotoImage(false, () => {
				this._replaceDropzone(html);
			});
		});
	}

	async _generateImage() {
		return this._withImageMutation(async () => {
			const response = await request.post(
				this.endpoints.generate,
				this.formData,
			);
			if (
				!this.view.successfulResponse(response, this.component) ||
				!response?.html
			)
				return;
			const { html } = response;

			await this.view.updatePhotoImage(true, () => {
				this._replaceDropzone(html);
				this.hideGenerateForm({ transition: false });
			});
		});
	}

	reset() {
		super.reset();
		this.generateForm?.reset();
		this.hideError();
	}

	showError(message: string) {
		withTransition(() => {
			if (this.generateForm?.visible()) {
				this.form.showError(message);
			} else {
				const newImage = this.newImage;
				const existingImage = this.existingImage;
				if (newImage) newImage.dataset.visible = "true";
				if (existingImage) {
					existingImage.dataset.visible = String(this.dropzone.containsImage);
				}
				const error = document.createElement("span");
				error.className = "text-delete text-base italic";
				error.textContent = message;
				if (this.dropzone.containsImage) {
					if (newImage) newImage.dataset.visible = "false";
					error.dataset.role = "image-error";
					this.dropzone.element
						.querySelector("[data-role='image-error']")
						?.remove();
					this.dropzone.element.append(error);
				} else this.feedback?.replaceChildren(error);
			}
		});
	}

	hideError() {
		this.dropzone.element.querySelector("[data-role='image-error']")?.remove();
		if (this.generateForm?.visible()) {
			this.form.hideError();
		} else {
			const feedback = this.feedback;
			if (feedback)
				feedback.innerHTML = "drop image here<br>or click to upload";
		}
	}

	showGenerateForm({ transition = true } = {}) {
		const generateForm = this.generateForm;
		if (!this.aiCreate || this.readonly || !generateForm) return;
		if (generateForm.visible()) {
			generateForm.show();
			return;
		}
		this.view.photoGenerationReturnOpen ??= this.view.photoOpen;
		const show = () => {
			this.reset();
			this.dropzone.hide();
			generateForm.show();
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
