/*! Third-party licenses: /third-party-licenses.txt */
import { B as BaseUpload } from './baseUpload.js?v=bb1ed2ee';
import { u as uploadElement, U as UploadMenu } from './upload.js?v=bb1ed2ee';
import './baseForm.js?v=bb1ed2ee';
import './foundation.js?v=bb1ed2ee';
import './upstreamUnavailable.js?v=bb1ed2ee';
import './connectivity.js?v=bb1ed2ee';
import './icons.js?v=bb1ed2ee';
import './primitives.js?v=bb1ed2ee';
import './styles.js?v=bb1ed2ee';
import './loader.js?v=bb1ed2ee';
import './buttons.js?v=bb1ed2ee';
import './formatting.js?v=bb1ed2ee';
import './dropdown.js?v=bb1ed2ee';
import './combobox.js?v=bb1ed2ee';

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
