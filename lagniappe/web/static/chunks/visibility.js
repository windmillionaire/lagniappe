/*! Third-party licenses: /third-party-licenses.txt */
import { a as ConditionTarget } from './base2.js?v=bd163a0f';
import './styles.js?v=bd163a0f';
import './baseForm.js?v=bd163a0f';
import './foundation.js?v=bd163a0f';
import './connectivity.js?v=bd163a0f';
import './icons.js?v=bd163a0f';
import './primitives.js?v=bd163a0f';
import './loader.js?v=bd163a0f';
import './select2.js?v=bd163a0f';
import './combobox.js?v=bd163a0f';
import './results.js?v=bd163a0f';
import './storage.js?v=bd163a0f';
import './formatting.js?v=bd163a0f';
import './submitter.js?v=bd163a0f';

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
		this.element.schema.visibility ??= [];

		if (this.index !== -1) {
			this.setTitle("Edit Visibility Condition");
			this.messages.submit = "Update Visibility Condition";
			this.setting = { ...this.element.schema.visibility[this.index] };
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
