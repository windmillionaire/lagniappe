/*! Third-party licenses: /third-party-licenses.txt */
import { C as CONFIG, f as fieldKind } from './builder.js?v=bedf900f';
import { g as generateElementId } from './foundation.js?v=bedf900f';
import './connectivity.js?v=bedf900f';
import { p as primitives } from './primitives.js?v=bedf900f';
import { S as SelectBox } from './select2.js?v=bedf900f';
import { C as Condition } from './base2.js?v=bedf900f';
import './search.js?v=bedf900f';
import './styles.js?v=bedf900f';
import './remote.js?v=bedf900f';
import './queryLifecycle.js?v=bedf900f';
import './combobox.js?v=bedf900f';
import './results.js?v=bedf900f';
import './icons.js?v=bedf900f';
import './storage.js?v=bedf900f';
import './formatting.js?v=bedf900f';
import './upstreamUnavailable.js?v=bedf900f';
import './entityMenu.js?v=bedf900f';
import './dropdown.js?v=bedf900f';
import './upload.js?v=bedf900f';
import './buttons.js?v=bedf900f';
import './modal.js?v=bedf900f';
import './polling.js?v=bedf900f';
import './baseForm.js?v=bedf900f';
import './loader.js?v=bedf900f';
import './facets.js?v=bedf900f';
import './submitter.js?v=bedf900f';

/**
 * @testable true
 * @tests tests_e2e/003_forms/test_003b_form_builder.py::test_table_column_condition_editor
 * @pair forms:builder-table-column
 * @matrix forms : stable-identity
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
		if (this.index !== -1) {
			this.setTitle("Edit Column");
			this.messages.submit = "Update Column";
			this.setting = { ...this.element.schema.columns?.[this.index] };
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
		const saved = this.builder
			.savedField(this.element.schema.id)
			?.columns?.find((column) => column.id === this.setting.id);
		if (saved) {
			const notice = document.createElement("p");
			notice.className = "text-sm text-base-medium";
			notice.textContent =
				"Save will convert this column. Values that cannot be converted will be cleared.";
			this.header.after(notice);
			this.destroyables.push({ destroy: () => notice.remove() });
		}
		const selectElt = primitives.select({
			label: "Column Type",
			kind: "form",
			placeholder: "select column type...",
			name: this.element.schema.id,
			options: CONFIG.TABLE_COLUMNS.filter(
				(input) =>
					!saved ||
					(this.builder.conversionCatalog?.rules[fieldKind(saved)]?.[
						input.type
					] &&
						this.builder.conversionCatalog.rules[fieldKind(saved)][
							input.type
						] !== "ai"),
			).map((input) => ({
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
		this.columnType = selectBox;
		this.destroyables.push(selectBox);
		this.focusTarget = selectElt;

		this.target.removeEventListener("updated", this._updated);
		this.target.addEventListener("updated", this._updated);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_036b_builder_draft.py::test_saved_controls_refresh_without_replacing_draft_inputs
	 * @matrix forms : builder-save stable-identity
	 */
	refreshSavedState() {}

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
		this.columnType = null;
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
			do {
				this.setting.id = generateElementId("column");
			} while (
				this.element.schema.columns?.some(
					(column) => column.id === this.setting.id,
				)
			);
		}
		return true;
	}
}

export { Columns as default };
