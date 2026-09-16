/*! Third-party licenses: /third-party-licenses.txt */
import { a as ConditionTarget } from './base2.js?v=bb1ed2ee';
import './styles.js?v=bb1ed2ee';
import './baseForm.js?v=bb1ed2ee';
import './foundation.js?v=bb1ed2ee';
import './upstreamUnavailable.js?v=bb1ed2ee';
import './connectivity.js?v=bb1ed2ee';
import './icons.js?v=bb1ed2ee';
import './primitives.js?v=bb1ed2ee';
import './loader.js?v=bb1ed2ee';
import './select2.js?v=bb1ed2ee';
import './combobox.js?v=bb1ed2ee';
import './results.js?v=bb1ed2ee';
import './storage.js?v=bb1ed2ee';
import './formatting.js?v=bb1ed2ee';
import './submitter.js?v=bb1ed2ee';

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_field_visibility
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_field_visibility_select_multiple_values
 * @matrix forms : builder-field-visibility select-or-values
 */
class Visibility extends ConditionTarget {
	constructor(builder) {
		super(builder);
		this.key = "visibility";
		this.targetSelectTitle = "Show this element when";
		this.messages = {
			submit: "Add Visibility Condition",
		};
	}

	init() {
		if (this.index !== -1) {
			this.setTitle("Edit Visibility Condition");
			this.messages.submit = "Update Visibility Condition";
			this.setting = { ...this.element.schema.visibility?.[this.index] };
		} else {
			this.setTitle("Create Visibility Condition");
			this.setting = {};
		}

		super.init();

		const targets = this.builder.getEligibleConditionTargets();
		if (targets.length === 0) {
			this.form.showError(
				"Visibility cannot be set using available components. " +
					"Please add a radio button, checkbox, or select menu to the form before " +
					"setting the visibility of this element.",
			);
		} else {
			super.addTargetSelect();
		}

		this.showProgress();
	}

	showProgress() {
		const target = this.builder.elements.get(this.setting.id);
		if (!target) return;

		if (target.schema.type === "checkbox") {
			this.addCheckboxTarget();
			this.complete = true;
		} else {
			this.addChooseValue();
			if (this.setting.value) this.complete = true;
		}

		super.showProgress();
	}
}

export { Visibility as default };
