/*! Third-party licenses: /third-party-licenses.txt */
import { C as CONFIG } from './builder.js?v=b26991f5';
import './request.js?v=b26991f5';
import './connectivity.js?v=b26991f5';
import { simpleHash } from './utilities.js?v=b26991f5';
import { p as primitives } from './primitives.js?v=b26991f5';
import { S as SelectBox } from './select2.js?v=b26991f5';
import { C as Condition } from './base2.js?v=b26991f5';
import './search.js?v=b26991f5';
import './styles.js?v=b26991f5';
import './endpoints.js?v=b26991f5';
import './combobox.js?v=b26991f5';
import './results.js?v=b26991f5';
import './icons.js?v=b26991f5';
import './formatting.js?v=b26991f5';
import './errors.js?v=b26991f5';
import './entityMenu.js?v=b26991f5';
import './dropdown.js?v=b26991f5';
import './modal.js?v=b26991f5';
import './baseForm.js?v=b26991f5';
import './loader.js?v=b26991f5';
import './facets.js?v=b26991f5';
import './submitter.js?v=b26991f5';

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_table_column_condition_editor
 * @features forms
 * @dimensions builder-table-column
 */
class Columns extends Condition {
	constructor(builder) {
		super(builder);
		this.key = "columns";
		this.messages = {
			submit: "Add Column",
		};
	}

	init() {
		this.element.schema.columns ??= [];

		if (this.index !== -1) {
			this.setTitle("Edit Column");
			this.messages.submit = "Update Column";
			this.setting = { ...this.element.schema.columns[this.index] };
		} else {
			this.setTitle("Create Column");
			this.setting = {};
		}

		super.init();

		this.addColumnType();

		this.showProgress();
	}

	showProgress() {
		if (this.setting.title) {
			this.complete = true;
			this.addColumnName();
		}
		super.showProgress();
	}

	addColumnName() {
		if (this.options.has("name")) return;

		const columnName = primitives.input({
			label: "Column Name",
			placeholder: "enter column name...",
			name: "column-name",
			type: "text",
			value: this.setting.title || null,
		});
		this.options.set("name", columnName);
		this.focusTarget = columnName;

		columnName.addEventListener("input", (e) => {
			this.setting.title = e.target.value;
			this.showProgress();
		});
	}

	_updateSetting(value) {
		delete this.setting.location;
		delete this.setting.input;
		delete this.setting.type;

		if (["out", "in"].includes(value)) {
			this.setting.location = value;
			this.setting.type = "link";
		} else if (value && value !== "checkbox") {
			this.setting.input = value;
			this.setting.type = "input";
		} else if (value === "checkbox") {
			this.setting.type = "checkbox";
		}
	}

	addColumnType() {
		const selectElt = primitives.select({
			label: "Column Type",
			kind: "form",
			placeholder: "select column type...",
			name: this.element.schema.id,
			options: CONFIG.TABLE_COLUMNS.map((input) => ({
				label: input.name,
				value: input.type,
				details: { kind: "form", icon: input.type, name: input.name },
			})),
		});

		this.header.after(selectElt);
		const selectBox = new SelectBox(selectElt);
		const initial =
			this.setting.location || this.setting.input || this.setting.type;
		if (initial) {
			selectBox.values.add(initial);
		}
		selectBox.init();
		this.destroyables.push(selectBox);
		this.focusTarget = selectElt;

		this.target.addEventListener("updated", (e) => {
			const options = Object.values(e.detail.options);
			const value = options[0].id;
			this._updateSetting(value);
			this.addColumnName();
			this.showProgress();
		});
	}

	validate() {
		if (!this.setting.title) {
			this.form.showError("Please enter a column name");
			return false;
		}
		if (!this.setting.type) {
			this.form.showError("Please select a column type");
			return false;
		}
		if (!this.setting.id) {
			this.setting.id = `column-${simpleHash(
				`${this.setting.title}-${this.element.schema.id}`,
			)}`;
		}
		return true;
	}
}

export { Columns as default };
