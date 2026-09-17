/*! Third-party licenses: /third-party-licenses.txt */
import { B as BaseUpload } from './baseUpload.js?v=be0bc88b';
import { u as uploadElement, U as UploadMenu } from './upload.js?v=be0bc88b';
import './baseForm.js?v=be0bc88b';
import './foundation.js?v=be0bc88b';
import './upstreamUnavailable.js?v=be0bc88b';
import './connectivity.js?v=be0bc88b';
import './icons.js?v=be0bc88b';
import './primitives.js?v=be0bc88b';
import './styles.js?v=be0bc88b';
import './loader.js?v=be0bc88b';
import './buttons.js?v=be0bc88b';
import './formatting.js?v=be0bc88b';
import './dropdown.js?v=be0bc88b';
import './combobox.js?v=be0bc88b';

const INGRESS_DROPZONE_TEXT =
	"Drop a file here or click to upload. Only CSV files are supported.";

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002g_home_import.py::test_open_import_form
 * @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_file_input
 * @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_drag_drop
 * @matrix ingress : drag-drop file-input upload-form
 */
class IngressFileUpload extends BaseUpload {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Upload File",
			submitting: "Uploading",
			submitted: "Uploaded",
		};
		this.uploadType = "file";
		this.inputName = "ingress-file";

		this.dropzone = uploadElement.dropzone({
			text: INGRESS_DROPZONE_TEXT,
		});
		this.submitButton = this.target.querySelector("button[type='submit']");
		this.menuOptions = ["paste"];
		this.uploadMenu = new UploadMenu(this);
	}

	get html() {
		return [this.dropzone.element];
	}

	async init() {
		await super.init();
		this.form.hideSubmitButton();
	}

	async created() {
		this.form.success();
		this.createdFile = true;
	}

	postreconcile() {
		if (this.createdFile) {
			super.reset();
			this.visible = false;
			this.target.dataset.visible = "false";
			this.createdFile = false;
		}
	}
}

export { IngressFileUpload };
