import { Modal } from "../../../shared/modal.ts";
import { request } from "../../../shared/request.ts";
import { withTransition } from "../../../shared/transitions.ts";
import { BaseUpload } from "../../base/baseUpload.ts";
import { buttons } from "../../buttons.ts";
import { UploadMenu, uploadElement } from "../../upload.ts";
import type { Toolbar } from "../toolbar.ts";

const IMAGE_DROPZONE_TEXT =
	"Drop image here, click to upload, or tap to choose camera/files<br>All images will be sized down to 1280x720";

class Image extends BaseUpload {
	declare menuOptions: string[];
	declare generate: ReturnType<typeof uploadElement.generateDocumentImage>;
	declare submitButton: HTMLButtonElement;
	declare toolbar: Toolbar;
	declare name: "addImage";
	declare messages: Record<string, string>;
	declare target: HTMLFormElement;
	declare dropzone: ReturnType<typeof uploadElement.dropzone>;
	declare active: boolean;

	constructor(toolbar: Toolbar) {
		super();
		this.toolbar = toolbar;
		this.name = "addImage" as const;
		this.inputName = "add-image";
		this.messages = {
			submit: "Upload Image",
			submitting: "Uploading Image",
			submitted: "Image Uploaded",
		};
		this.uploadType = "image";

		this.target = this.toolbar.element.appendChild(
			document.createElement("form"),
		);
		this.target.dataset.mode = "upload";
		this.target.className = `mt-4 hidden flex-col gap-4 rounded-md bg-slate-200 p-4 group-data-[open-form="addImage"]/toolbar:flex group/upload`;
		this.target.dataset.option = this.name;

		this.dropzone = uploadElement.dropzone({ text: IMAGE_DROPZONE_TEXT });
		this.menuOptions = [
			"remove",
			...(this.toolbar.aiCreate ? ["generate"] : []),
			"paste",
		];
		this.uploadMenu = new UploadMenu(this);
		this.generate = uploadElement.generateDocumentImage();
		this.submitButton = buttons.submit({
			kind: "editor",
		});

		this.submit = this.submit.bind(this);
	}

	get html() {
		return [
			this.dropzone.element,
			...(this.toolbar.aiCreate ? [this.generate.element] : []),
			this.submitButton,
		];
	}

	async init() {
		await super.init();

		this.submitButton.dataset.visible = "false";

		this.target.addEventListener("click", (e) => {
			if ((e.target as Element | null)?.closest("[data-role='cancel']")) {
				this.hideGenerateForm();
			}
		});
	}

	showGenerateForm() {
		withTransition(() => {
			this.dropzone.hide();
			this.reset();
			this.form.toggleSubForm(this.generate);
			this.generate.show();
		});
	}

	hideGenerateForm() {
		withTransition(() => {
			this.form.toggleSubForm(null);
			this.generate.hide();
			this.generate.reset();
			this.dropzone.show();
		});
	}

	reset() {
		this.generate.reset();
		super.reset();
	}

	async submit(submitter: HTMLButtonElement | HTMLInputElement | null) {
		if (this.toolbar.document.addDraftImage) {
			const file = this.fileInput?.element?.files?.[0];
			if (!file) return;
			const src = this.toolbar.document.addDraftImage(file);
			this.toolbar.editor.chain().focus().setImage({ src }).run();
			this.toolbar.toggleForm(this.name);
			return;
		}
		const route = this.toolbar.endpoints?.addImage;
		if (!route) return;
		const prepared = await this.prepareSubmit({ route });
		if (!prepared) return;

		const formData = new FormData(this.target);
		this.applyDirectUploads(formData);
		formData.append("role", submitter?.dataset?.role || "upload");
		formData.append("content", this.toolbar.editor.getText());

		if (submitter) submitter.disabled = true;
		const response = await request.post<{ src: string }>(route, formData);
		if (submitter) submitter.disabled = false;

		if (response?.ok && response.modal) {
			const modal = new Modal(this.toolbar.builder);
			void modal.attach(response.modal as Document, this);
		} else if (response?.ok && response.src) {
			this.toolbar.editor.chain().focus().setImage({ src: response.src }).run();
			this.toolbar.toggleForm(this.name);
		} else if (response?.error) {
			this.form.showError(response.error);
			this.reset();
		}
	}
}

export { Image as addImage };
