import { STYLES } from "styles";
import { withTransition } from "../shared";
import { iconDefinition, setIcon } from "../shared/icons";
import { FacetsBox } from "./combobox/facets";
import { DueDate } from "./dueDate";
import { formatting } from "./formatting";
import { TaskUpload } from "./taskUpload";

/**
 * @testable infrastructure
 */
const clearButton = (open) => {
	const clearButton = document.createElement("button");
	clearButton.dataset.role = "clear";
	clearButton.dataset.kind = "delete";
	clearButton.type = "button";
	clearButton.className = STYLES.form.icon;
	setIcon(
		clearButton.appendChild(document.createElement("span")),
		open ? "x" : "clear",
		"icon-sm",
	);
	return clearButton;
};

/**
 * @testable infrastructure
 */
const dueDateText = (parent) => {
	if (!parent.active) {
		return formatting.text({
			kind: parent.kind,
			text: parent.button.dataset.title,
		});
	}

	const schedule = parent.schedule;
	let displayText = "Due";

	if (schedule.due) {
		displayText += ` ${formatting.date(schedule.due)}`;
	} else {
		displayText = "No Due Date";
	}

	if (schedule.recurring) {
		const interval = schedule.recurring.interval || "1";
		const unit = schedule.recurring.unit || "day";
		const pluralUnit = parseInt(interval, 10) > 1 ? `${unit}s` : unit;
		displayText += ` (repeats when completed after ${interval} ${pluralUnit})`;
	} else if (schedule.scheduled) {
		displayText += ` (repeats ${
			schedule.scheduled.text || schedule.scheduled.mode
		})`;
	} else if (schedule.periodic) {
		displayText += ` (repeats ${schedule.periodic.text || "periodically"})`;
	}

	return formatting.text({ kind: parent.kind, text: displayText });
};

/**
 * @testable infrastructure
 */
const detailsText = (parent) => {
	if (!parent.active) {
		return formatting.text({
			kind: parent.kind,
			text: parent.button.dataset.title,
		});
	}

	return formatting.name({ ...parent.details, link: !parent.readonly });
};

/**
 * @testable infrastructure
 */
const fileText = (parent) => {
	const firstAsset = Object.values(parent.assets || {})[0];
	const filename =
		parent.filename || firstAsset?.name || firstAsset?.filename || "";

	if (!parent.active || !filename) {
		return formatting.text({
			kind: parent.kind,
			text: "Attach File/Photo",
		});
	}

	const display =
		filename.length > 20 ? `${filename.substring(0, 17)}...` : filename;

	return formatting.text({
		kind: parent.kind,
		text: display,
	});
};

/**
 * @testable false
 * @covered-by src/script/elements/sectionToggle.mjs::FacetControl
 */
const detailsLinkRow = (details) => {
	if (!details?.name) return null;
	const kind = details.kind || details.index || details.type || "default";

	const row = document.createElement("div");
	row.dataset.kind = kind;
	row.className = `${STYLES.form.submission.default} text-kind-default`;

	const name = formatting.name({ ...details, link: Boolean(details.id) });
	row.appendChild(
		formatting.iconLabel({
			icon: iconDefinition(kind) ? kind : "in",
			kind,
			content: name,
			iconClasses: "text-kind-default",
		}),
	);

	return row;
};

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_project
 * @pair tasks:select-toggle-layout
 */
export class SectionToggle {
	static facet(widget, element) {
		return new FacetControl(widget, element);
	}

	static date(widget, button) {
		const control = new DueDate(button, widget);
		control.toggle = new SectionToggle(control, widget);
		return control;
	}

	static upload(widget, button) {
		const control = new TaskUpload(button, widget);
		control.toggle = new SectionToggle(control, widget);
		return control;
	}

	constructor(parent, widget = parent.widget) {
		this.parent = parent;
		this.widget = widget;
		this.readonly = Boolean(
			widget?.readonly ||
				parent?.readonly ||
				parent?.button?.dataset.readonly === "true" ||
				parent?.button?.disabled,
		);
		this.init();
	}

	init() {
		if (this.readonly) return;

		this.parent.button.addEventListener("click", (e) => {
			if (e.target.closest("a")) {
				return;
			}

			e.preventDefault();
			e.stopPropagation();

			if (e.target.closest("[data-role='clear']")) {
				this.parent.clear();
			} else {
				this.parent.toggleVisibility();
			}
		});
		this.parent.button.addEventListener("keydown", (e) => {
			if (!["Enter", "Escape"].includes(e.key)) return;

			e.preventDefault();
			e.stopPropagation();

			if (e.target.closest("[data-role='clear']")) {
				this.parent.clear();
			} else {
				this.parent.toggleVisibility();
			}
		});
	}

	_setButtonReadonly() {
		if (!this.readonly) return;

		const button = this.parent.button;
		button.dataset.readonly = "true";
		button.disabled = true;
		button.setAttribute("aria-disabled", "true");
	}

	display() {
		let text = "";
		if (this.parent.action === "schedule") {
			text = dueDateText(this.parent);
		} else if (this.parent.index) {
			text = detailsText(this.parent);
		} else if (this.parent.action === "uploadFile") {
			text = fileText(this.parent);
		}

		const semanticIcon =
			this.parent.action === "schedule"
				? "dueDate"
				: this.parent.icon || this.parent.index;
		const icon = iconDefinition(semanticIcon) ? semanticIcon : this.parent.kind;

		const title = formatting.iconLabel({
			icon,
			kind: this.parent.kind,
			content: text,
			classes: "flex-1 leading-normal",
			iconClasses: "text-kind-default",
		});

		let action = null;
		if (!this.readonly) {
			action =
				this.parent.active || this.parent.open
					? clearButton(this.parent.open)
					: null;
		}

		const contents = [title, action].filter(Boolean);

		this.parent.button.replaceChildren(...contents);
		this._setButtonReadonly();
	}
}

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_add_category_to_page
 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_switch_page_form
 * @tests tests_e2e/005_pages/test_005d_page_permissions.py::test_page_viewer_reads_page_without_page_editing_affordances
 * @tests tests_e2e/007_categories/test_007e_category_permissions.py::test_category_viewer_opens_readonly_settings
 * @tests tests_e2e/006_tasks/test_006a_page_task_scheduling.py::test_page_task_add_due_date
 * @matrix categories : default-form readonly
 * @matrix pages : form-switch readonly
 * @pairs pages:category-add task-assignment:assignee-preservation task-scheduling:due-date
 */
class FacetControl {
	constructor(widget, element) {
		this.widget = widget;
		this.root = element?.closest?.("[lp-select]") || element;
		this.button = this.root?.matches?.("button[lp-select]") ? this.root : null;
		this.container = this._container();
		this.input = this.button
			? null
			: this.root?.querySelector?.("input, select") || this.root;
		this.source = this.button || this.input || this.root;
		this.action = this.source?.dataset.action;
		this.index = this.source?.dataset.index || this.root?.dataset.index;
		this.kind =
			this.source?.dataset.kind || this.root?.dataset.kind || this.index;
		this.details = this._preload()[0] || {};
		this.select = null;
		this.element = null;
		this.toggle = null;
		this.open = false;

		this._updated = this._updated.bind(this);
		this._deactivate = this._deactivate.bind(this);
	}

	_container() {
		if (!this.button) return this.root?.closest?.("[data-role]");

		const parent = this.button.parentElement?.closest?.("[data-role]");
		if (parent && !this.button.dataset.role) return parent;
		return parent?.dataset.role === this.button.dataset.role
			? parent
			: this.button;
	}

	get elt() {
		return this.container || this.root;
	}

	get readonly() {
		return Boolean(
			this.widget?.readonly ||
				this.source?.dataset.readonly === "true" ||
				this.root?.dataset.readonly === "true" ||
				this.source?.disabled,
		);
	}

	get active() {
		return Object.keys(this.details).length > 0;
	}

	init() {
		if (!this.root) return;

		if (this.readonly) {
			this._initReadonly();
			return;
		}

		this.button ? this._initButtonFacet() : this._initInputFacet();
	}

	_preload() {
		const raw = this.source?.dataset.preload || this.root?.dataset.preload;
		if (!raw) return [];

		try {
			const parsed = JSON.parse(raw);
			if (Array.isArray(parsed)) {
				return parsed.filter((item) => {
					if (!item) return false;
					return typeof item !== "object" || Object.keys(item).length > 0;
				});
			}
			if (parsed && typeof parsed === "object") {
				return Object.keys(parsed).length > 0 ? [parsed] : [];
			}
			return parsed ? [parsed] : [];
		} catch {
			return [];
		}
	}

	_initReadonly() {
		this.root.dataset.readonly = "true";
		const rows = this._preload()
			.map((details) =>
				detailsLinkRow({
					kind: this.kind,
					index: this.index,
					...details,
				}),
			)
			.filter(Boolean);

		if (rows.length === 0) return;
		this.source.replaceWith(...rows);
	}

	_initButtonFacet() {
		this.toggle = new SectionToggle(this, this.widget);
		this.toggle.display();

		this.select = new FacetsBox(this.button);
		this.element = document.createElement("input");
		this.element.className = STYLES.select.default;
		this.element.dataset.visible = "false";
		this.element.dataset.kind = this.kind;
		this.element.name = this.button.dataset.name || this.index;
		this.button.after(this.element);

		this.select.element = this.element;
		this.select.init();

		this.select.element.addEventListener("updated", this._updated);
		this.select.element.addEventListener("deactivate", this._deactivate);
	}

	_initInputFacet() {
		this.select = new FacetsBox(this.root);
		this.select.init();
	}

	_updated(e) {
		if (Object.values(e.detail.options).length > 0) {
			this.details = Object.values(e.detail.options)[0];
		} else {
			this.details = {};
		}
		this.open = false;
		this._reconcile();
	}

	_deactivate() {
		this.open = false;
		this._reconcile();
	}

	toggleVisibility() {
		if (this.readonly) return;
		this.open = !this.open;
		this._reconcile();
	}

	_reconcile() {
		if (!this.button || !this.element) return;

		withTransition(() => {
			if (!this.open) {
				this.button.dataset.visible = "true";
				this.element.dataset.visible = "false";
				this.button.focus({ preventScroll: true });
			} else {
				this.button.dataset.visible = "false";
				this.element.dataset.visible = "true";
				this.element.focus({ preventScroll: true });
				this.select.showPanel();
			}
			this.toggle.display();
		});
	}

	addOption(option) {
		this.details = option || {};
		this.select?.addOption(option);
		this.toggle?.display();
	}

	clear() {
		if (this.readonly) return;
		this.details = {};
		this.select?.clear();
		this.open = false;
		this._reconcile();
	}

	destroy() {
		if (this.select?.element) {
			this.select.element.removeEventListener("updated", this._updated);
			this.select.element.removeEventListener("deactivate", this._deactivate);
		}
		this.select?.destroy();
	}
}
