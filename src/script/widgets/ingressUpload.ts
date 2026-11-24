import { BaseUpload } from "../elements/base/baseUpload.ts";
import { UploadMenu, uploadElement } from "../elements/upload.ts";

const INGRESS_DROPZONE_TEXT =
	"Drop a file here or click to upload. Only CSV files are supported.";

export class IngressFileUpload extends BaseUpload {
	declare messages: Record<string, string>;
	declare dropzone: ReturnType<typeof uploadElement.dropzone>;
	declare submitButton: HTMLButtonElement | null;
	declare menuOptions: "paste"[];
	declare createdFile?: boolean;
	declare visible?: boolean;

	constructor(attributes: ConstructorParameters<typeof BaseUpload>[0]) {
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
