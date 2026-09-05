/*! Third-party licenses: /third-party-licenses.txt */
import { B as BaseUpload, u as uploadElement, U as UploadMenu } from './baseUpload.js?v=ba683140';
import './styles.js?v=ba683140';
import './foundation.js?v=ba683140';
import './upstreamUnavailable.js?v=ba683140';
import './connectivity.js?v=ba683140';
import './icons.js?v=ba683140';
import './buttons.js?v=ba683140';
import './formatting.js?v=ba683140';
import './dropdown.js?v=ba683140';
import './combobox.js?v=ba683140';
import './primitives.js?v=ba683140';
import './baseForm.js?v=ba683140';
import './loader.js?v=ba683140';

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
