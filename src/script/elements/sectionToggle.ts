import { STYLES } from "../generated/styles.mjs";
import { iconDefinition, setIcon } from "../shared/icons.ts";
import { withTransition } from "../shared/transitions.ts";
import type { ComboboxOption, ComboboxTrigger } from "./combobox/combobox.ts";
import { FacetsBox, isFacetOption } from "./combobox/facets.ts";
import { DueDate, type TaskSchedule } from "./dueDate.ts";
import { formatting } from "./formatting.ts";
import { type TaskAsset, TaskUpload } from "./taskUpload.ts";

interface SectionToggleWidget {
	readonly?: boolean;
	key?: string | null;
}

interface SectionToggleControl {
	widget?: SectionToggleWidget;
	button: HTMLButtonElement | null;
	readonly?: boolean;
	action?: string;
	kind?: string;
	index?: string;
	icon?: string;
	active?: boolean;
	open?: boolean;
	schedule?: TaskSchedule;
	details?: ComboboxOption;
	filename?: string;
	assets?: Record<string, TaskAsset>;
	clear(): void;
	toggleVisibility(): void;
}

type FacetSource = ComboboxTrigger & { disabled?: boolean };

const clearButton = (open?: boolean) => {
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

const dueDateText = (parent: SectionToggleControl) => {
	if (!parent.active) {
		return formatting.text({
			kind: parent.kind,
			text: parent.button?.dataset.title,
		});
	}

	const schedule = parent.schedule ?? {};
	let displayText = "Due";

	if (schedule.due) {
		displayText += ` ${formatting.date(schedule.due)}`;
	} else {
		displayText = "No Due Date";
	}

	if (schedule.recurring) {
		const interval = schedule.recurring.interval || "1";
		const unit = schedule.recurring.unit || "day";
		const pluralUnit = parseInt(String(interval), 10) > 1 ? `${unit}s` : unit;
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

const detailsText = (parent: SectionToggleControl) => {
	if (!parent.active) {
		return formatting.text({
			kind: parent.kind,
			text: parent.button?.dataset.title,
		});
	}

	return formatting.name({ ...parent.details, link: !parent.readonly });
};

const fileText = (parent: SectionToggleControl) => {
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

const detailsLinkRow = (
	details: ComboboxOption & { index?: string; type?: string },
) => {
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

export class SectionToggle {
	declare parent: SectionToggleControl;
	declare widget?: SectionToggleWidget;
	declare readonly: boolean;

	static facet(widget: SectionToggleWidget, element: HTMLElement | null) {
		return new FacetControl(widget, element);
	}

	static date(widget: SectionToggleWidget, button: HTMLButtonElement) {
		const control = new DueDate(button, widget);
		control.toggle = new SectionToggle(control, widget);
		return control;
	}

	static upload(widget: SectionToggleWidget, button: HTMLButtonElement) {
		const control = new TaskUpload(button, widget);
		control.toggle = new SectionToggle(control, widget);
		return control;
	}

	constructor(parent: SectionToggleControl, widget = parent.widget) {
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

		this.parent.button?.addEventListener("click", (e) => {
			const { target } = e;
			if (!(target instanceof Element) || target.closest("a")) {
				return;
			}

			e.preventDefault();
			e.stopPropagation();

			if (target.closest("[data-role='clear']")) {
				this.parent.clear();
			} else {
				this.parent.toggleVisibility();
			}
		});
		this.parent.button?.addEventListener("keydown", (e) => {
			if (!["Enter", "Escape"].includes(e.key)) return;

			e.preventDefault();
			e.stopPropagation();

			if (
				e.target instanceof Element &&
				e.target.closest("[data-role='clear']")
			) {
				this.parent.clear();
			} else {
				this.parent.toggleVisibility();
			}
		});
	}

	_setButtonReadonly() {
		if (!this.readonly) return;

		const button = this.parent.button;
		if (!button) return;
		button.dataset.readonly = "true";
		button.disabled = true;
		button.setAttribute("aria-disabled", "true");
	}

	display() {
		let text: Node | string = "";
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

		const contents = action ? [title, action] : [title];

		this.parent.button?.replaceChildren(...contents);
		this._setButtonReadonly();
	}
}

export class FacetControl {
	declare widget: SectionToggleWidget;
	declare root: FacetSource | null;
	declare button: HTMLButtonElement | null;
	declare container: HTMLElement | null;
	declare input: FacetSource | null;
	declare source: FacetSource | null;
	declare action?: string;
	declare index?: string;
	declare kind?: string;
	declare details: ComboboxOption;
	declare select: FacetsBox | null;
	declare element: HTMLInputElement | null;
	declare toggle: SectionToggle | null;
	declare open: boolean;

	constructor(widget: SectionToggleWidget, element: HTMLElement | null) {
		this.widget = widget;
		this.root = element?.closest<FacetSource>("[lp-select]") || element;
		this.button = this.root?.matches("button[lp-select]")
			? (this.root as HTMLButtonElement)
			: null;
		this.container = this._container();
		this.input = this.button
			? null
			: this.root?.querySelector<FacetSource>("input, select") || this.root;
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
		if (!this.button)
			return this.root?.closest<HTMLElement>("[data-role]") ?? null;

		const parent =
			this.button.parentElement?.closest<HTMLElement>("[data-role]");
		if (parent && !this.button.dataset.role) return parent;
		return parent && parent.dataset.role === this.button.dataset.role
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
			const parsed: unknown = JSON.parse(raw);
			return (Array.isArray(parsed) ? parsed : [parsed])
				.filter(isFacetOption)
				.filter((item) => Object.keys(item).length > 0);
		} catch {
			return [];
		}
	}

	_initReadonly() {
		if (!this.root || !this.source) return;
		this.root.dataset.readonly = "true";
		const rows = this._preload()
			.map((details) =>
				detailsLinkRow({
					kind: this.kind,
					index: this.index,
					...details,
				}),
			)
			.filter((row) => row !== null);

		if (rows.length === 0) return;
		this.source.replaceWith(...rows);
	}

	_initButtonFacet() {
		if (!this.button) return;
		this.toggle = new SectionToggle(this, this.widget);
		this.toggle.display();

		this.select = new FacetsBox(this.button);
		this.element = document.createElement("input");
		this.element.className = STYLES.select.default;
		this.element.dataset.visible = "false";
		this.element.dataset.kind = String(this.kind);
		this.element.name = String(this.button.dataset.name || this.index);
		this.button.after(this.element);

		this.select.element = this.element;
		this.select.init();

		this.select.element.addEventListener("updated", this._updated);
		this.select.element.addEventListener("deactivate", this._deactivate);
	}

	_initInputFacet() {
		if (!this.root) return;
		this.select = new FacetsBox(this.root);
		this.select.init();
	}

	_updated(e: Event) {
		const detail: unknown = e instanceof CustomEvent ? e.detail : null;
		const options =
			detail && typeof detail === "object" && "options" in detail
				? detail.options
				: null;
		this.details =
			options && typeof options === "object"
				? (Object.values(options).find(isFacetOption) ?? {})
				: {};
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
		const { button, element, select, toggle } = this;
		if (!button || !element) return;

		withTransition(() => {
			if (!this.open) {
				button.dataset.visible = "true";
				element.dataset.visible = "false";
				button.focus({ preventScroll: true });
			} else {
				button.dataset.visible = "false";
				element.dataset.visible = "true";
				element.focus({ preventScroll: true });
				select?.showPanel();
			}
			toggle?.display();
		});
	}

	addOption(option?: ComboboxOption) {
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
