/*! Third-party licenses: /third-party-licenses.txt */
import { p as primitives } from './primitives.js?v=bc116afe';
import { a as ConditionTarget } from './base2.js?v=bc116afe';
import './styles.js?v=bc116afe';
import './icons.js?v=bc116afe';
import './baseForm.js?v=bc116afe';
import './foundation.js?v=bc116afe';
import './connectivity.js?v=bc116afe';
import './loader.js?v=bc116afe';
import './select2.js?v=bc116afe';
import './combobox.js?v=bc116afe';
import './results.js?v=bc116afe';
import './formatting.js?v=bc116afe';
import './submitter.js?v=bc116afe';

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_status_message_condition_editor
 * @features forms
 * @dimensions builder-status-message
 */
class Status extends ConditionTarget {
	constructor(builder) {
		super(builder);
		this.key = "status";
		this.messages = {
			submit: "Add Status Message",
		};
		this.targetSelectTitle = "Show this status message when";
	}

	init() {
		this.element.schema.status ??= [];

		if (this.index !== -1) {
			this.setTitle("Edit Status Message");
			this.messages.submit = "Update Status Message";
			this.setting = { ...this.element.schema.status[this.index] };
		} else {
			this.setTitle("Create Status Message");
			this.setting = {};
		}

		super.init();

		const targets = this.builder.getEligibleConditionTargets();
		if (targets.length === 0) {
			this.form.showError(
				"Status messages cannot be set using available components. " +
					"Please add a radio button, checkbox, or select menu to the form before " +
					"setting a status message.",
			);
		} else {
			super.addTargetSelect();
		}

		this.showProgress();
	}

	showProgress() {
		const target = this.builder.elements.get(this.setting.id);
		if (!target) return;

		if (this.setting.text) {
			this.complete = true;
		}

		if (target.schema.type === "checkbox") {
			this.addCheckboxTarget();
			this.addStatusText();
		} else {
			this.addChooseValue();
			if (this.setting.value) this.addStatusText();
		}

		super.showProgress();
	}

	addStatusText() {
		if (this.options.has("text")) return;

		const statusText = primitives.input({
			label: "Status Message",
			placeholder: "enter status message...",
			name: "status-message",
			type: "text",
			value: this.setting.text || null,
		});
		this.options.set("text", statusText);
		this.focusTarget = statusText;

		statusText.addEventListener("input", (e) => {
			this.setting.text = e.target.value;
			this.showProgress();
		});
	}

	validate() {
		if (!super.validate()) return false;

		if (!this.setting.text) {
			this.form.showError("Please enter a status message.");
			return false;
		}

		return true;
	}
}

export { Status as default };
