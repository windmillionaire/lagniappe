/*! Third-party licenses: /third-party-licenses.txt */
import { S as STYLES } from './styles.js?v=b3f50eb1';
import { F as FormElement } from './form2.js?v=b3f50eb1';
import { InputElement } from './input.js?v=b3f50eb1';
import { p as primitives } from './primitives.js?v=b3f50eb1';
import { S as SectionToggle } from './sectionToggle.js?v=b3f50eb1';
import { TextareaElement } from './textarea.js?v=b3f50eb1';
import { s as setIcon } from './icons.js?v=b3f50eb1';
import './baseForm.js?v=b3f50eb1';
import './request.js?v=b3f50eb1';
import './errors.js?v=b3f50eb1';
import './connectivity.js?v=b3f50eb1';
import './utilities.js?v=b3f50eb1';
import './loader.js?v=b3f50eb1';
import './baseElement.js?v=b3f50eb1';
import './formatting.js?v=b3f50eb1';
import './facets.js?v=b3f50eb1';
import './endpoints.js?v=b3f50eb1';
import './combobox.js?v=b3f50eb1';
import './results.js?v=b3f50eb1';
import './submitter.js?v=b3f50eb1';
import './buttons.js?v=b3f50eb1';
import './baseUpload.js?v=b3f50eb1';
import './dropdown.js?v=b3f50eb1';

/**
 * @testable true
 * @tests tests_e2e/011_files/test_011c_file_processing_reconciliation.py::test_file_summary_completion_stages_authoritative_info_until_reset
 * @tests tests_e2e/011_files/test_011c_file_processing_reconciliation.py::test_file_extract_completion_prompts_reload_for_text_tab_after_reset
 * @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_info_page_links_can_be_added_and_removed
 * @features file
 * @dimensions extract summarize polling status summary reload text-tab active-reset linked-pages
 */
class FileInfo extends FormElement {
	constructor(attributes) {
		super(attributes);
		this.aiCreate = this.target.dataset.aiCreate === "true";
		this.messages = {
			submit: "Update File",
			submitting: "Updating File",
			submitted: "File Updated",
		};
		this._taskSettings = {
			extract: {
				role: "extract",
				action: "Extract Text",
				title: "Text Extraction",
			},
			summarize: {
				role: "summarize",
				action: "Summarize File Content",
				title: "Content Summarization",
			},
		};
		this._refreshExtractOnReconcile = false;
	}

	get html() {
		const status = document.createElement("div");
		status.className = "flex flex-col gap-2";
		status.append(
			...[
				this._taskStatus(this._taskSettings.extract),
				this._taskStatus(this._taskSettings.summarize),
			].filter(Boolean),
		);
		return [
			this.filenameElement,
			this.nameElement,
			this.mimetypeElement,
			status,
			this.descriptionElement,
			this.pagesElement,
		];
	}

	async init() {
		await super.init();
	}

	get nameElement() {
		return new InputElement(
			{ kind: "file", readonly: this.readonly },
			{
				input: "text",
				id: "name",
				title: "Display Name",
				placeholder: "name this file...",
			},
			this.target.dataset.name || "",
		).elt;
	}

	get descriptionElement() {
		return new TextareaElement(
			{ kind: "file", readonly: this.readonly },
			{
				input: "textarea",
				id: "description",
				title: "Description",
				placeholder: "describe this file...",
			},
			this.target.dataset.description || "",
		).elt;
	}

	get filenameElement() {
		const wrapper = document.createElement("div");
		wrapper.className = "flex flex-col gap-1";

		const label = wrapper.appendChild(document.createElement("h3"));
		label.className = STYLES.label.default;
		label.textContent = "File Name";

		const value = wrapper.appendChild(document.createElement("p"));
		value.className = "sm:text-sm text-kind-default";
		value.textContent = this.target.dataset.filename;

		return wrapper;
	}

	get mimetypeElement() {
		const mimetype = this.target.dataset.mimetype;
		if (!mimetype) return null;

		const wrapper = document.createElement("div");
		wrapper.className = "flex flex-col gap-1";

		const label = wrapper.appendChild(document.createElement("h3"));
		label.className = STYLES.label.default;
		label.textContent = "File Type";

		const value = wrapper.appendChild(document.createElement("p"));
		value.className = "sm:text-sm text-kind-default";
		const encoding = this.target.dataset.encoding;
		value.textContent = encoding ? `${mimetype} (${encoding})` : mimetype;

		return wrapper;
	}

	get pagesElement() {
		return this._facetElement('[data-role="pages"]');
	}

	_facetElement(selector) {
		const target = this.target.querySelector(selector);
		if (!target) return null;

		const control = SectionToggle.facet(this, target);
		control.init();
		this.destroyables.push(control);
		return control.elt;
	}

	_taskStatus(taskSettings) {
		const taskOptions = this.options?.[taskSettings.role];
		if (
			taskSettings.role === "summarize" &&
			!this.aiCreate &&
			!taskOptions?.enabled
		) {
			return null;
		}

		const status = document.createElement("div");
		status.dataset.role = taskSettings.role;

		if (!taskOptions?.enabled) {
			status.appendChild(
				primitives.checkbox({
					name: `enable-${taskSettings.role}`,
					label: taskSettings.action,
					checked: taskOptions?.enabled || false,
				}),
			);
		} else {
			const header = status.appendChild(document.createElement("h3"));
			header.className = STYLES.label.default;
			header.textContent = taskSettings.title;
			const statusText = status.appendChild(document.createElement("p"));
			statusText.className = "sm:text-sm text-base-dark italic";

			if (!taskOptions.complete && taskOptions.status) {
				const spinner = statusText.appendChild(document.createElement("span"));
				setIcon(spinner, "spinner", "mr-2");
				const text = statusText.appendChild(document.createElement("span"));
				text.textContent = taskOptions.status;
			} else if (!taskOptions.complete && taskOptions.error) {
				statusText.className = "sm:text-sm text-delete-default italic";
				statusText.textContent = taskOptions.error;
			} else if (taskOptions.complete && taskOptions.status) {
				statusText.textContent = taskOptions.status;
			}
		}

		return status;
	}

	updated(response) {
		super.updated(response);

		const target = response.html?.querySelector("[data-widget='FileInfo']");
		const options = target?.dataset.options;
		if (!options) {
			this._refreshExtractOnReconcile = false;
			return;
		}

		this.options = JSON.parse(options);
		const hasTextTab = Boolean(document.getElementById("text"));
		this._refreshExtractOnReconcile =
			this.options.extract?.complete === true && !hasTextTab;
	}

	async postreconcile() {
		await super.postreconcile();
		this.setEntityMetadata();
		if (this._refreshExtractOnReconcile) {
			this._refreshExtractOnReconcile = false;
			this.view.showExtractReloadNotice?.();
		}
	}

	destroy() {
		super.destroy();
	}
}

export { FileInfo };
