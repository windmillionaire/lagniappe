/*! Third-party licenses: /third-party-licenses.txt */
import { C as CONFIG } from './builder.js?v=bb55a6e4';
import { k as simpleHash } from './foundation.js?v=bb55a6e4';
import './connectivity.js?v=bb55a6e4';
import { p as primitives } from './primitives.js?v=bb55a6e4';
import { S as SelectBox } from './select2.js?v=bb55a6e4';
import { C as Condition } from './base2.js?v=bb55a6e4';
import './search.js?v=bb55a6e4';
import './styles.js?v=bb55a6e4';
import './remote.js?v=bb55a6e4';
import './queryLifecycle.js?v=bb55a6e4';
import './combobox.js?v=bb55a6e4';
import './results.js?v=bb55a6e4';
import './icons.js?v=bb55a6e4';
import './storage.js?v=bb55a6e4';
import './formatting.js?v=bb55a6e4';
import './entityMenu.js?v=bb55a6e4';
import './dropdown.js?v=bb55a6e4';
import './modal.js?v=bb55a6e4';
import './baseForm.js?v=bb55a6e4';
import './loader.js?v=bb55a6e4';
import './facets.js?v=bb55a6e4';
import './submitter.js?v=bb55a6e4';

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_table_column_condition_editor
 * @pair forms:builder-table-column
 */
class Columns extends Condition {
	constructor(builder) {
		super(builder);
		this.key = "columns";
		this.messages = {
			submit: "Add Column",
		};
		this._updated = this._updated.bind(this);
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

		this.target.removeEventListener("updated", this._updated);
		this.target.addEventListener("updated", this._updated);
	}

	_updated(e) {
		const options = Object.values(e.detail.options);
		const value = options[0]?.id;
		if (!value) return;
		this._updateSetting(value);
		this.addColumnName();
		this.showProgress();
	}

	destroy() {
		this.target.removeEventListener("updated", this._updated);
		super.destroy();
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
