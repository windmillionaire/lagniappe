/*! Third-party licenses: /third-party-licenses.txt */
import { B as BaseUpload, u as uploadElement, U as UploadMenu } from './baseUpload.js?v=b560d96b';
import { b as buttons } from './buttons.js?v=b560d96b';
import './directUpload.js?v=b560d96b';
import './foundation.js?v=b560d96b';
import './upstreamUnavailable.js?v=b560d96b';
import './connectivity.js?v=b560d96b';
import './styles.js?v=b560d96b';
import './icons.js?v=b560d96b';
import './dropdown.js?v=b560d96b';
import './combobox.js?v=b560d96b';
import './primitives.js?v=b560d96b';
import './baseForm.js?v=b560d96b';
import './loader.js?v=b560d96b';
import './formatting.js?v=b560d96b';

const FILE_DROPZONE_TEXT =
	"Drop file here, click to upload, or tap to choose camera/files";

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_add_file_to_page
 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_add_multiple_files_to_page_without_existing_file_select
 * @matrix pages : file-upload multi-file
 */
class FileUpload extends BaseUpload {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Upload File",
			submitting: "Uploading File",
			submitted: "File Uploaded",
		};
		this.inputName = "file-upload";
		this.multiple = true;
		this.dropzone = uploadElement.dropzone({ text: FILE_DROPZONE_TEXT });
		this.processing = uploadElement.processing({
			aiCreate: this.target.dataset.aiCreate === "true",
		});
		this.uploadType = "file";
		this.menuOptions = ["remove", "replace", "paste"];
		this.uploadMenu = new UploadMenu(this);
		this.submitButton = buttons.submit({
			kind: "file",
			data: {
				visible: "false",
			},
		});
	}

	get html() {
		return [this.dropzone.element, this.processing.element];
	}

	onFileAttached(_file, context) {
		const fileCount = this.fileInput?.element.files.length || 0;
		this.processing.prefill({
			filename: context.filename,
			isTextFile: context.isTextFile,
			fileCount,
		});
	}

	reset() {
		super.reset();
		this.processing.clear();
	}

	created() {
		this._created = true;
	}

	postreconcile() {
		if (this._created) {
			this.reset();
		}
	}
}

export { FileUpload };
