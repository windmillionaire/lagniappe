/*! Third-party licenses: /third-party-licenses.txt */
import { B as BaseUpload, u as uploadElement, U as UploadMenu } from './baseUpload.js?v=b211475b';
import './styles.js?v=b211475b';
import './request.js?v=b211475b';
import './errors.js?v=b211475b';
import './connectivity.js?v=b211475b';
import './icons.js?v=b211475b';
import './utilities.js?v=b211475b';
import './buttons.js?v=b211475b';
import './formatting.js?v=b211475b';
import './dropdown.js?v=b211475b';
import './combobox.js?v=b211475b';
import './primitives.js?v=b211475b';
import './baseForm.js?v=b211475b';
import './loader.js?v=b211475b';

const ORGANIZE_DROPZONE_TEXT =
	"Drop files here, click to upload, or paste a screenshot.";

const TOOL_DEFAULTS = {
	organize: {
		placeholder: "Optional guidance for organizing these files...",
		explain: "organize",
		upload: true,
	},
	ask: {
		placeholder: "Ask a question about your workspace...",
		explain: "ask",
		upload: false,
	},
	create: {
		placeholder: "Describe what you want Lagniappe to create...",
		explain: "create",
		upload: false,
	},
};

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002j_home_tools.py::test_tools_create_form_has_expected_controls
 * @features ai-report
 * @dimensions upload-form multi-file instructions tool-switcher ask create explain-button
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
		this.toolInput = this.target.querySelector("[data-role='tool-input']");
		this.switcher = this.target.querySelector("[data-role='tool-switcher']");
		this.submitGroup = this.target.querySelector("[data-role='submit-group']");
		this.submitButton = this.target.querySelector("[data-role='start-report']");
		this.explainButton = this.target.querySelector("[data-role='explain']");
		this.activeTool = this.toolInput?.value || "organize";
		this.context = uploadElement.contextUpload({
			text: ORGANIZE_DROPZONE_TEXT,
			label: false,
			descriptionName: "instructions",
			descriptionPlaceholder: "Optional guidance for organizing these files...",
			descriptionRows: 5,
			stacked: true,
			explain: false,
		});
		this.dropzone = this.context.dropzone;
		this.menuOptions = ["remove", "replace", "paste"];
		this.uploadMenu = new UploadMenu(this);
	}

	async init() {
		await super.init();
		this.toolButtons = Array.from(
			this.target.querySelectorAll("[data-role='tool-switcher'] [data-tool]"),
		);
		this.toolButtons.forEach((button) => {
			button.addEventListener("click", () => this.setTool(button.dataset.tool));
		});
		this.context.description?.addEventListener("input", () => {
			this.toggleExplainButton();
			this.form?.showSubmitButton();
		});
		this.setTool(this.activeTool, { reset: false });
	}

	get html() {
		return [this.toolInput, this.switcher, this.context.element];
	}

	toolConfig(tool) {
		const button = this.toolButtons?.find(
			(option) => option.dataset.tool === tool,
		);
		const defaults = TOOL_DEFAULTS[tool] || TOOL_DEFAULTS.organize;
		return {
			...defaults,
			route: button?.dataset.route,
			placeholder: button?.dataset.placeholder || defaults.placeholder,
			explain: button?.dataset.explain || defaults.explain,
			upload: button?.dataset.upload
				? button.dataset.upload === "true"
				: defaults.upload,
		};
	}

	setTool(tool, { reset = true } = {}) {
		if (!TOOL_DEFAULTS[tool]) return;

		this.activeTool = tool;
		const config = this.toolConfig(tool);
		if (this.toolInput) this.toolInput.value = tool;
		if (config.route) {
			this.route = config.route;
			this.target.dataset.route = config.route;
		}
		if (this.context.description) {
			this.context.description.placeholder = config.placeholder;
		}
		if (this.explainButton) this.explainButton.dataset.explain = config.explain;

		this.toolButtons?.forEach((button) => {
			button.dataset.active =
				button.dataset.tool === this.activeTool ? "true" : "false";
		});

		if (config.upload) {
			this.dropzone?.show();
			this.dropzone?.setText(
				this.fileAttached ? this.fileLabel : ORGANIZE_DROPZONE_TEXT,
			);
		} else {
			this.fileInput?.clear();
			this.mimeType?.clear();
			this.dropzone?.clear();
			this.dropzone?.hide();
		}

		if (reset) this.form?.resetSubmitButton();
		this.toggleExplainButton();
	}

	toggleExplainButton() {
		if (!this.explainButton) return;
		const hasText = Boolean(this.context.description?.value?.trim());
		this.explainButton.dataset.visible = hasText ? "true" : "false";
	}

	showExplainButton() {
		if (this.explainButton) this.explainButton.dataset.visible = "true";
	}

	applyDefaultAttachUI(_file, _context) {
		if (this.dropzone) this.dropzone.setText(this.fileLabel);
		this.showExplainButton();
		this.form?.showSubmitButton();
	}

	async created() {
		this.form.success();
		this.createdReport = true;
	}

	reset() {
		super.reset();
		this.context?.clear();
		this.setTool(this.activeTool, { reset: false });
		this.form?.hideSubmitButton();
		this.toggleExplainButton();
	}

	async postreconcile() {
		if (this.createdReport) {
			this.reset();
			this.visible = false;
			this.target.dataset.visible = "false";
			this.createdReport = false;
		}
	}
}

export { CreateToolReport };
