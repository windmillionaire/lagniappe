/*! Third-party licenses: /third-party-licenses.txt */
import { B as BaseUpload, u as uploadElement, U as UploadMenu } from './baseUpload.js?v=bb782d98';
import { b as buttons } from './buttons.js?v=bb782d98';
import './foundation.js?v=bb782d98';
import './connectivity.js?v=bb782d98';
import { F as FacetsBox } from './facets.js?v=bb782d98';
import './styles.js?v=bb782d98';
import './icons.js?v=bb782d98';
import './dropdown.js?v=bb782d98';
import './combobox.js?v=bb782d98';
import './primitives.js?v=bb782d98';
import './baseForm.js?v=bb782d98';
import './loader.js?v=bb782d98';
import './formatting.js?v=bb782d98';
import './remote.js?v=bb782d98';
import './queryLifecycle.js?v=bb782d98';
import './results.js?v=bb782d98';
import './storage.js?v=bb782d98';
import './submitter.js?v=bb782d98';

const FILE_DROPZONE_TEXT =
	"Drop file here, click to upload, or tap to choose camera/files";

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_add_file_to_page
 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_add_multiple_files_to_page_hides_existing_file_select
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
		this.selectFile = uploadElement.selectFile();
		this._select = null;
	}

	get html() {
		return [
			this.selectFile.element,
			this.dropzone.element,
			this.processing.element,
		];
	}

	async init() {
		this._select = new FacetsBox(this.selectFile.element);
		this._select.init();
		this.destroyables.push(this._select);

		await super.init();
	}

	onFileAttached(_file, context) {
		const fileCount = this.fileInput?.element.files.length || 0;
		this.toggleSelectFile(fileCount <= 1);
		this.processing.prefill({
			filename: context.filename,
			isTextFile: context.isTextFile,
			fileCount,
		});
	}

	toggleSelectFile(visible) {
		this.selectFile.element.dataset.visible = visible ? "true" : "false";
		if (visible) return;

		this._select?.clear();
		this.selectFile.clear();
	}

	reset() {
		super.reset();
		this.toggleSelectFile(true);
		this._select.clear();
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
