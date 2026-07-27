import { withTransition } from "../shared";
import { BaseUpload } from "./base/baseUpload";
import { UploadMenu, uploadElement } from "./upload";

const AUTOFILL_DROPZONE_TEXT = "Click or drop to add a related image or a pdf";

/**
 * @testable infrastructure
 */
export class AutofillUpload extends BaseUpload {
	constructor(attributes) {
		super(attributes);
		this.parent = attributes.parent;
		this.target = attributes.target;
		this.name = "autofill";
		this.icon = "generate";
		this.uploadType = "file";
		this.deferred = true;

		this.messages = {
			submit: "Autofill Form",
			submitting: "Starting...",
			submitted: "Autofill queued",
		};

		this.context = uploadElement.contextUpload({
			text: AUTOFILL_DROPZONE_TEXT,
		});
		this.inputName = "autofill-file";
		this.dropzone = this.context.dropzone;
		this.menuOptions = ["remove", "replace", "paste"];
		this.uploadMenu = new UploadMenu(this);

		this._initialized = false;
		this._click = this._click.bind(this);
	}

	init() {
		this.parent.target.addEventListener("click", this._click);
	}

	get submitGroup() {
		return this.target.querySelector("[data-role='autofill-submit-group']");
	}

	get submitButton() {
		return this.submitGroup?.querySelector("button[type='submit']") ?? null;
	}

	_canFallbackToMultipart() {
		return false;
	}

	_click(e) {
		const role = e.target.closest("button")?.dataset?.role;
		if (!["cancel-autofill", "show-autofill"].includes(role)) return;

		e.preventDefault();
		e.stopPropagation();

		withTransition(async () => {
			if (!this._initialized) {
				await super.init();
				this.target.append(this.submitGroup);
				this._initialized = true;
			}

			if (role === "show-autofill") {
				this.target.dataset.visible = "true";
				this.parent.form.toggleSubForm(this);
				this.target.querySelector("textarea").focus();
			} else if (role === "cancel-autofill") {
				this.target.dataset.visible = "false";
				this.parent.form.toggleSubForm();
				this.reset();
				this.target.querySelector("textarea").value = "";
			}
		});
	}

	get html() {
		return [this.context.element];
	}
}
