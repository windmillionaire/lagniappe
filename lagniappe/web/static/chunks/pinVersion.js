/*! Third-party licenses: /third-party-licenses.txt */
import { r as request } from './foundation.js?v=b052d07c';
import './connectivity.js?v=b052d07c';
import { B as BaseForm } from './baseForm.js?v=b052d07c';
import { b as buttons } from './buttons.js?v=b052d07c';
import { p as primitives } from './primitives.js?v=b052d07c';
import './upstreamUnavailable.js?v=b052d07c';
import './icons.js?v=b052d07c';
import './loader.js?v=b052d07c';
import './styles.js?v=b052d07c';
import './formatting.js?v=b052d07c';

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004h_document_history.py::test_pin_and_clear_document_history
 * @matrix editor : current-content history-pin validation
 */
class PinVersion {
	constructor(toolbar) {
		this.toolbar = toolbar;
		this.name = "pinVersion";
		this.messages = {
			submit: "Pin Version",
			submitting: "Pinning Version...",
			name: "Please name this version",
		};
		this._active = false;
		this.submit = this.submit.bind(this);
	}

	get active() {
		return this._active;
	}

	set active(value) {
		this._active = value;
		if (value) this.focus();
	}

	init() {
		this.target = this.toolbar.element.appendChild(
			document.createElement("form"),
		);
		this.target.className = `mt-4 hidden flex-col gap-4 rounded-md bg-slate-200 p-4 group-data-[open-form="pinVersion"]/toolbar:flex`;
		this.target.dataset.option = this.name;

		this.input = primitives.input({
			name: "name",
			placeholder: "Name this version",
			type: "text",
		});
		this.input.maxLength = 100;
		this.html = [this.input, buttons.submit({ kind: "editor" })];

		this.form = new BaseForm(this);
		this.form.init();
	}

	focus() {
		this.input?.focus();
		this.input?.select();
	}

	reset() {
		this.input.value = "";
		this.form?.resetSubmitButton();
	}

	async submit() {
		const name = this.input.value.trim();
		if (!name) {
			this.form.showError(this.messages.name);
			this.form.resetSubmitButton();
			return;
		}

		const endpoint = this.toolbar.endpoints.history;
		const html = this.toolbar.editor.getHTML();
		const response = await request.post(`${endpoint}/pin`, { name, html });
		if (!response?.ok) {
			this.form.showError(response?.error || "Unable to pin this version");
			this.form.resetSubmitButton();
			return;
		}

		this.reset();
		await this.toolbar.closeForm(this.name);
		await this.toolbar.toggles.documentHistory?.refresh();
	}

	destroy() {
		this.form?.destroy();
	}
}

export { PinVersion as pinVersion };
