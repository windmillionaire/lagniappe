/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=b05079d4';
import { s as setIcon } from './icons.js?v=b05079d4';
import { p as primitives } from './primitives.js?v=b05079d4';

const NON_HISTORY_FILLABLE_TYPES = new Set(["html", "signature", "status"]);

/**
 * @testable infrastructure
 * @tests tests_js/test_028_form_state_split.py::test_direct_form_controls_clear_inputs_and_textareas
 * @covered-by src/script/elements/renderer.mjs::Renderer.render
 * @covered-by src/script/elements/form.mjs::FormElement._click
 */
class BaseElement {
	constructor(renderer, schema, submission) {
		this.renderer = renderer;
		this.schema = schema;
		this.readonly = renderer.readonly;
		this.element = null;
		this.destroyables = [];
		this.submission = submission;
		this.static = false;
		this._elt = null;
		this._read = null;
		this._edit = null;
	}

	get submission() {
		return this._submission ?? null;
	}

	set submission(value) {
		const submission = value ?? null;
		if (
			submission === null ||
			(typeof submission === "object" && Object.keys(submission).length === 0)
		) {
			this._submission = null;
		} else {
			this._submission = submission;
		}
	}

	get hasSubmission() {
		return this.submission !== null && this.submission !== "";
	}

	get showEmptyFields() {
		return this.renderer.showEmptyFields;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_fill_controls_cover_submission_elements
	 * @features tasks
	 * @dimensions history-fill element-matrix
	 */
	get historyFillable() {
		return !NON_HISTORY_FILLABLE_TYPES.has(this.schema?.type);
	}

	get historyFillPersistsDefault() {
		return true;
	}

	get canHistoryFill() {
		return Boolean(
			this.renderer.historyFillEnabled &&
				this.historyFillable &&
				!this.readonly &&
				!this.cellEditing &&
				!this.static &&
				!this.hasSubmission &&
				this.schema?.id,
		);
	}

	get mode() {
		if (this.renderer.mode) {
			return this.renderer.mode;
		} else if (this.readonly) {
			return "read";
		} else if (this.hasSubmission) {
			return "read";
		} else {
			return "edit";
		}
	}

	get id() {
		if (this.renderer.id) {
			return `${this.schema.id}-${this.renderer.id}`;
		}
		return this.schema.id;
	}

	get cellEditing() {
		return this.renderer.cellEditing === true;
	}

	get label() {
		if (this.cellEditing) return null;
		return this.schema.title || this.schema.label;
	}

	get read() {
		return this._read;
	}

	get edit() {
		return this._edit;
	}

	get cellEdit() {
		const edit = this.edit;
		if (!edit) return null;

		this._elt = edit;
		edit.dataset.editing = "true";
		edit.dataset.type = this.schema.type;
		return edit;
	}

	get cell() {
		if (this.cellEditing) return this.cellEdit;
		if (!this.hasSubmission) return null;
		return this.read?.innerHTML ?? "";
	}

	readonlyPlaceholder() {
		const empty = document.createElement("p");
		empty.className = `${STYLES.form.submission.default} text-base-medium italic`;
		empty.textContent = "Not provided";
		return empty;
	}

	historyValueAvailable(value) {
		if (value === null || value === undefined || value === "") return false;
		if (Array.isArray(value)) return value.length > 0;
		if (typeof value === "object") return Object.keys(value).length > 0;
		return true;
	}

	fillFromHistory(value) {
		if (!this.historyValueAvailable(value)) return false;

		this.submission = value;
		this._elt.classList.add("opacity-50", "pointer-events-none");

		this.destroy();
		const elt = this.create();
		this._elt.replaceWith(elt);
		this._elt = elt;
		this.elt.dispatchEvent(new Event("change", { bubbles: true }));
		return true;
	}

	historyFillButton(value, onFill = null) {
		if (!this.canHistoryFill || !this.historyValueAvailable(value)) return null;

		const button = document.createElement("button");
		button.type = "button";
		button.dataset.role = "history-fill";
		button.ariaLabel = "Fill from latest history";
		button.title = "Fill from latest history";
		button.className = STYLES.form.icon;
		setIcon(
			button.appendChild(document.createElement("span")),
			"historyFill",
			"icon-sm",
		);

		button.addEventListener("click", (event) => {
			event.preventDefault();
			event.stopPropagation();
			if (this.fillFromHistory(value)) {
				if (this.historyFillPersistsDefault) onFill?.(this.schema.id);
			}
		});

		return button;
	}

	addHistoryFill(value, onFill = null) {
		const button = this.historyFillButton(value, onFill);
		if (!button) return false;

		const elt = this.elt;
		if (!elt) return false;

		const label =
			elt.dataset?.role === "label"
				? elt
				: elt.querySelector("[data-role='label']");
		if (!label || label.querySelector("[data-role='history-fill']")) {
			return false;
		}

		label.append(button);
		return true;
	}

	create() {
		let elt;
		if (this.readonly && this.schema.type !== "table") {
			elt = document.createElement("div");
			const label = primitives.label({
				label: this.label,
				tag: "h3",
			});
			elt.appendChild(label);
		} else {
			elt = this.edit;
		}
		if (!elt) return null;

		const label =
			elt.dataset?.role === "label"
				? elt
				: elt.querySelector("[data-role='label']");

		elt.id = this.id;
		elt.classList.add("form-element", "group/element");
		if (this.schema.type !== "table") {
			elt.dataset.mode = this.mode;
		}

		let read = null;
		if (this.hasSubmission) {
			read = this.read;
		} else if (this.showEmptyFields && !this.static) {
			read = this.readonlyPlaceholder();
		}
		if (read) {
			read.dataset.role = "read";
			elt.appendChild(read);
			if (!this.readonly) {
				const button = document.createElement("button");
				button.type = "button";
				button.dataset.role = "edit";
				button.ariaLabel = `Edit ${this.label}`;
				button.title = `Edit ${this.label}`;
				button.className = `group-data-[mode=edit]/element:hidden ${STYLES.form.icon}`;
				setIcon(
					button.appendChild(document.createElement("span")),
					"edit",
					"icon-sm",
				);
				label.append(button);
			} else {
				elt.classList.add("flex", "flex-col", "gap-1");
			}
		}

		if (this.clear && this.mode === "read" && !this.readonly) {
			const clearButton = label.appendChild(document.createElement("button"));
			clearButton.type = "button";
			clearButton.dataset.role = "clear";
			clearButton.dataset.kind = "delete";
			clearButton.ariaLabel = `Clear ${this.label}`;
			clearButton.title = `Clear ${this.label}`;
			clearButton.className = `group-data-[mode=read]/element:hidden ${STYLES.form.icon}`;
			setIcon(
				clearButton.appendChild(document.createElement("span")),
				"clear",
				"icon-sm",
			);
		}

		elt._lp_element = this;
		return elt;
	}

	get elt() {
		if (this._elt) return this._elt;
		if (
			this.readonly &&
			!this.hasSubmission &&
			!this.static &&
			!this.showEmptyFields
		)
			return null;

		this._elt = this.create();
		return this._elt;
	}

	destroy() {
		this.destroyables.forEach((d) => {
			if (d.destroy) d.destroy();
		});
		this.destroyables = [];
		this._read = null;
		this._edit = null;
	}

	update(value) {
		if (this.elt.contains(document.activeElement)) {
			return false;
		} else if (!this.changed(value)) {
			return true;
		}

		if (this.updateSubmission) {
			this.updateSubmission(value);
			return true;
		}

		this.submission = value;
		this._elt.classList.add("opacity-50", "pointer-events-none");

		this.destroy();
		const elt = this.create();
		this._elt.replaceWith(elt);
		this._elt = elt;
		return true;
	}
}

export { BaseElement as B };
