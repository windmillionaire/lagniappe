/*! Third-party licenses: /third-party-licenses.txt */
import { r as request } from './request.js?v=b7488009';
import './connectivity.js?v=b7488009';
import { Modal } from './modal.js?v=b7488009';
import { withTransition } from './utilities.js?v=b7488009';
import { B as BaseUpload, u as uploadElement, U as UploadMenu } from './baseUpload.js?v=b7488009';
import { b as buttons } from './buttons.js?v=b7488009';
import './errors.js?v=b7488009';
import './styles.js?v=b7488009';
import './endpoints.js?v=b7488009';
import './icons.js?v=b7488009';
import './dropdown.js?v=b7488009';
import './combobox.js?v=b7488009';
import './primitives.js?v=b7488009';
import './baseForm.js?v=b7488009';
import './loader.js?v=b7488009';
import './formatting.js?v=b7488009';

const IMAGE_DROPZONE_TEXT =
	"Drop image here, click to upload, or tap to choose camera/files<br>All images will be sized down to 1280x720";

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004e_document_forms.py::test_add_image_generate_toggle
 * @tests tests_e2e/004_projects/test_004e_document_forms.py::test_add_image
 * @features editor
 * @dimensions image-generate-toggle image-upload image-selection
 */
class Image extends BaseUpload {
	constructor(toolbar) {
		super();
		this.toolbar = toolbar;
		this.name = "addImage";
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
			if (e.target.closest("[data-role='cancel']")) {
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

	async submit(submitter) {
		const prepared = await this.prepareSubmit({
			route: this.toolbar.endpoints.addImage,
		});
		if (!prepared) return;

		const formData = new FormData(this.target);
		this.applyDirectUploads(formData);
		formData.append("role", submitter?.dataset?.role || "upload");
		formData.append("content", this.toolbar.editor.getText());

		if (submitter) submitter.disabled = true;
		const response = await request.post(
			this.toolbar.endpoints.addImage,
			formData,
		);
		if (submitter) submitter.disabled = false;

		if (response.ok && response.modal) {
			const modal = new Modal(this.toolbar.builder);
			modal.attach(response.modal, this);
		} else if (response.ok && response.src) {
			this.toolbar.editor.chain().focus().setImage({ src: response.src }).run();
			this.toolbar.toggleForm(this.name);
		} else if (response.error) {
			this.form.showError(response.error);
			this.reset();
		}
	}
}

export { Image as addImage };
