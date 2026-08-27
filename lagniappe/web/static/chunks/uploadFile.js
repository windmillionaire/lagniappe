/*! Third-party licenses: /third-party-licenses.txt */
import { B as BaseUpload, u as uploadElement, U as UploadMenu } from './baseUpload.js?v=b687b680';
import { b as buttons } from './buttons.js?v=b687b680';
import './foundation.js?v=b687b680';
import './connectivity.js?v=b687b680';
import { F as FacetsBox } from './facets.js?v=b687b680';
import './styles.js?v=b687b680';
import './icons.js?v=b687b680';
import './dropdown.js?v=b687b680';
import './combobox.js?v=b687b680';
import './primitives.js?v=b687b680';
import './baseForm.js?v=b687b680';
import './loader.js?v=b687b680';
import './formatting.js?v=b687b680';
import './remote.js?v=b687b680';
import './queryLifecycle.js?v=b687b680';
import './results.js?v=b687b680';
import './storage.js?v=b687b680';
import './submitter.js?v=b687b680';

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
