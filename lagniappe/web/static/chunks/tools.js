/*! Third-party licenses: /third-party-licenses.txt */
import { B as BaseUpload, u as uploadElement, U as UploadMenu } from './baseUpload.js?v=b518b165';
import './controller.js?v=b518b165';
import './primitives.js?v=b518b165';
import './styles.js?v=b518b165';
import './icons.js?v=b518b165';
import './foundation.js?v=b518b165';
import './upstreamUnavailable.js?v=b518b165';
import './connectivity.js?v=b518b165';
import './loader.js?v=b518b165';
import './directUpload.js?v=b518b165';
import './buttons.js?v=b518b165';
import './formatting.js?v=b518b165';
import './dropdown.js?v=b518b165';
import './combobox.js?v=b518b165';

const AI_DROPZONE_TEXT =
	"Drop files here, click to upload, or paste a screenshot.";

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_tools_create_form_has_expected_controls
 * @tests tests_js/test_043_ai_email_frontend.mjs::test_ai_email_address_selection_and_copy_controls
 * @matrix ai-report : absent-markup ask clipboard-fallback create email-address-selection instructions multi-file status-reset tool-switcher upload-form
 */
class CreateToolReport extends BaseUpload {
	constructor(attributes) {
		super(attributes);
		this.messages = {
			submit: "Start",
			submitting: "Starting",
			submitted: "Started",
		};
		this.icon = "generate";
		this.uploadType = "file";
		this.inputName = "tool-files";
		this.multiple = true;

		this.header = this.target.querySelector("[data-role='header']");
		this.submitGroup = this.target.querySelector("[data-role='submit-group']");
		this.submitButton = this.target.querySelector("[data-role='start-report']");
		this.emailSubmissions = this.target.querySelector(
			"[data-role='email-submissions']",
		);
		this.emailAddress = this.target.querySelector(
			"[data-role='email-address']",
		);
		this.emailCopyButton = this.target.querySelector(
			"[data-role='email-copy']",
		);
		this.context = uploadElement.contextUpload({
			text: AI_DROPZONE_TEXT,
			label: false,
			descriptionName: "instructions",
			descriptionPlaceholder: "Ask a question or describe what you want done…",
			descriptionRows: 5,
			stacked: true,
		});
		this.dropzone = this.context.dropzone;
		this.menuOptions = ["remove", "replace", "paste"];
		this.uploadMenu = new UploadMenu(this);
	}

	async init() {
		await super.init();
		this.context.description?.addEventListener("input", () => {
			this.form?.showSubmitButton();
		});
		this.emailCopyButton?.addEventListener("click", () => {
			void this.copyEmailAddress();
		});
		this.dropzone?.show();
	}

	get html() {
		return [this.context.element];
	}

	async copyEmailAddress() {
		const button = this.emailCopyButton;
		const address = this.emailAddress?.textContent?.trim();
		if (!button || !address) return;
		let copied = false;
		try {
			if (navigator.clipboard?.writeText) {
				await navigator.clipboard.writeText(address);
				copied = true;
			}
		} catch {
			copied = false;
		}
		if (!copied) {
			const textarea = document.createElement("textarea");
			textarea.value = address;
			textarea.setAttribute("readonly", "");
			textarea.style.position = "fixed";
			textarea.style.opacity = "0";
			document.body.append(textarea);
			textarea.select();
			try {
				copied = document.execCommand("copy");
			} catch {
				copied = false;
			}
			textarea.remove();
			button.focus();
		}
		button.textContent = copied ? "Copied" : "Copy failed";
		clearTimeout(this.emailCopyResetTimer);
		this.emailCopyResetTimer = setTimeout(() => {
			if (button.isConnected) button.textContent = "Copy";
		}, 2000);
	}

	applyDefaultAttachUI(_file, _context) {
		if (this.dropzone) this.dropzone.setText(this.fileLabel);
		this.form?.showSubmitButton();
	}

	async prepareSubmit(options = {}) {
		if (!this.context.description?.value?.trim() && !this.fileAttached) {
			this.showError("Add files or instructions before creating a report.");
			return false;
		}
		return super.prepareSubmit(options);
	}

	async created() {
		this.form.success();
		this.createdReport = true;
	}

	_resetUI() {
		this.context?.clear();
		this.dropzone?.show();
		this.form?.hideSubmitButton();
	}

	reset() {
		super.reset();
		this._resetUI();
	}

	postreconcile() {
		if (this.createdReport) {
			this.reset();
			this.visible = false;
			this.target.dataset.visible = "false";
			this.createdReport = false;
		}
	}
}

export { CreateToolReport };
