/*! Third-party licenses: /third-party-licenses.txt */
import { B as BaseUpload, u as uploadElement, U as UploadMenu } from './baseUpload.js?v=be1b1fb2';
import './styles.js?v=be1b1fb2';
import './request.js?v=be1b1fb2';
import './errors.js?v=be1b1fb2';
import './connectivity.js?v=be1b1fb2';
import './icons.js?v=be1b1fb2';
import './utilities.js?v=be1b1fb2';
import './buttons.js?v=be1b1fb2';
import './formatting.js?v=be1b1fb2';
import './dropdown.js?v=be1b1fb2';
import './combobox.js?v=be1b1fb2';
import './primitives.js?v=be1b1fb2';
import './baseForm.js?v=be1b1fb2';
import './loader.js?v=be1b1fb2';

const INGRESS_DROPZONE_TEXT =
	"Drop a file here or click to upload. Only CSV files are supported.";

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002g_home_import.py::test_open_import_form
 * @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_file_input
 * @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_drag_drop
 * @features ingress
 * @dimensions upload-form file-input drag-drop
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

	async postreconcile() {
		if (this.createdFile) {
			await super.reset();
			this.visible = false;
			this.target.dataset.visible = "false";
			this.createdFile = false;
		}
	}
}

export { IngressFileUpload };
