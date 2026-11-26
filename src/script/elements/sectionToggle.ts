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

const clearButton = (
	open: boolean | undefined,
	label: string,
	onClick: () => void,
) => {
	const button = document.createElement("button");
	button.dataset.role = "clear";
	button.dataset.kind = "default";
	button.type = "button";
	button.className = STYLES.form.icon;
	button.setAttribute("aria-label", label);
	button.title = label;
	setIcon(
		button.appendChild(document.createElement("span")),
		open ? "x" : "clear",
		"icon-xs text-delete-default",
	);
	const text = button.appendChild(document.createElement("span"));
	text.textContent = open ? "Close" : "Clear";
	button.addEventListener("click", (e) => {
		e.preventDefault();
		e.stopPropagation();
		onClick();
	});
	return button;
};

const openLinkButton = (parent: SectionToggleControl) => {
	if (!parent.index || !parent.active || parent.open || !parent.details?.id) {
		return null;
	}
	const details = {
		kind: parent.kind,
		index: parent.index,
		...parent.details,
	};
	const href = formatting.url(details).toString();
	const label = parent.details.name
		? `Open ${parent.details.name}`
		: `Open ${parent.button?.dataset.title || "item"}`;
	const link = document.createElement("a");
	link.dataset.role = "open-link";
	link.dataset.kind = String(details.kind || parent.kind || "default");
	link.href = href;
	link.className = STYLES.form.icon;
	link.setAttribute("aria-label", label);
	link.title = label;
	setIcon(link.appendChild(document.createElement("span")), "right", "icon-xs");
	const text = link.appendChild(document.createElement("span"));
	text.textContent = "Open";
	return link;
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

	return formatting.name({ ...parent.details, link: false });
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

	return formatting.text({
		kind: parent.kind,
		text: filename,
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
	declare row: HTMLDivElement | null;

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
		this.row = null;
		this.init();
	}

	_ensureRow() {
		const button = this.parent.button;
		if (!button) return null;
		const existing = button.parentElement;
		if (existing?.dataset.role === "section-toggle-row") {
			this.row = existing as HTMLDivElement;
			return this.row;
		}
		if (!existing) return null;
		const row = document.createElement("div");
		row.dataset.role = "section-toggle-row";
		if (this.parent.kind) row.dataset.kind = this.parent.kind;
		row.className = STYLES.select.row;
		existing.insertBefore(row, button);
		row.appendChild(button);
		this.row = row;
		return row;
	}

	init() {
		this._ensureRow();
		if (this.readonly) return;

		this.parent.button?.addEventListener("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			this.parent.toggleVisibility();
		});
		this.parent.button?.addEventListener("keydown", (e) => {
			if (e.key !== "Escape" || !this.parent.open) return;
			e.preventDefault();
			e.stopPropagation();
			this.parent.toggleVisibility();
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
		const button = this.parent.button;
		if (!button) return;
		const row = this._ensureRow();

		let text: Node | string = "";
		if (this.parent.action === "schedule") {
			text = dueDateText(this.parent);
		} else if (this.parent.index) {
			text = detailsText(this.parent);
		} else if (this.parent.action === "uploadFile") {
			text = fileText(this.parent);
		}

		const label = document.createElement("span");
		label.className = STYLES.select.label;
		if (typeof text === "string") label.textContent = text;
		else label.appendChild(text);

		const fullText = label.textContent?.trim() || "";
		if (fullText) button.title = fullText;
		else button.removeAttribute("title");

		const contents: Node[] = [label];
		if (!this.readonly) {
			button.setAttribute("aria-expanded", String(Boolean(this.parent.open)));
			const chevron = document.createElement("span");
			setIcon(chevron, "down", STYLES.select.expandIndicator);
			contents.push(chevron);
		} else {
			button.removeAttribute("aria-expanded");
		}

		button.replaceChildren(...contents);

		if (row) {
			const heading =
				row.parentElement?.querySelector<HTMLElement>(
					":scope > .select-heading, :scope > h3, :scope > [data-role='label']",
				) ?? null;
			const actionHost = heading ?? row;
			for (const container of heading ? [row, heading] : [row]) {
				for (const node of container.querySelectorAll(
					":scope > [data-role='open-link'], :scope > [data-role='clear']",
				)) {
					node.remove();
				}
			}

			const link = openLinkButton(this.parent);
			if (link) actionHost.appendChild(link);

			const needsToggleClose = Boolean(this.parent.index);
			if (
				!this.readonly &&
				(this.parent.active || (this.parent.open && needsToggleClose))
			) {
				const fieldTitle = button.dataset.title || "selection";
				const clearLabel = this.parent.open
					? `Close ${fieldTitle}`
					: `Clear ${fieldTitle}`;
				actionHost.appendChild(
					clearButton(this.parent.open, clearLabel, () => this.parent.clear()),
				);
			}
		}

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
		const button = this.button;
		const wrapper = document.createElement("div");
		wrapper.className = "min-w-0 w-full";
		wrapper.setAttribute("lp-select", "");
		if (button.dataset.action) wrapper.dataset.action = button.dataset.action;
		if (this.kind) wrapper.dataset.kind = String(this.kind);
		if (button.dataset.preload)
			wrapper.dataset.preload = button.dataset.preload;
		if (button.dataset.title) wrapper.dataset.title = button.dataset.title;

		const input = document.createElement("input");
		input.className = STYLES.select.default;
		input.name = String(button.dataset.name || this.index || "");
		if (this.index) input.dataset.index = this.index;
		if (this.kind) input.dataset.kind = String(this.kind);
		if (button.dataset.placeholder) {
			input.dataset.placeholder = button.dataset.placeholder;
		}
		if (button.dataset.creatable) {
			input.dataset.creatable = button.dataset.creatable;
		}
		if (button.dataset.formType) {
			input.dataset.formType = button.dataset.formType;
		}
		if (button.dataset.permission) {
			input.dataset.permission = button.dataset.permission;
		}
		if (button.dataset.multiple) {
			input.dataset.multiple = button.dataset.multiple;
		}

		wrapper.appendChild(input);
		button.replaceWith(wrapper);

		this.root = wrapper as FacetSource;
		this.source = wrapper as FacetSource;
		this.element = input;
		this.select = new FacetsBox(wrapper);
		this.select.init();

		this.select.element.addEventListener("updated", this._updated);
		this._syncHeadingActions();
	}

	_syncHeadingActions() {
		const host =
			this.container?.querySelector<HTMLElement>(
				":scope > .select-heading, :scope > h3, :scope > [data-role='label']",
			) ?? null;
		if (!host) return;
		for (const node of host.querySelectorAll(
			":scope > [data-role='open-link'], :scope > [data-role='clear']",
		)) {
			node.remove();
		}
		if (this.readonly || !this.active) return;

		const link = openLinkButton(this);
		if (link) host.appendChild(link);

		const fieldTitle =
			this.source?.dataset.title || this.button?.dataset.title || "selection";
		host.appendChild(
			clearButton(false, `Clear ${fieldTitle}`, () => this.clear()),
		);
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
		if (this.toggle) {
			this._reconcile();
		} else {
			this._syncHeadingActions();
		}
	}

	_deactivate() {
		this.open = false;
		this._reconcile();
	}

	toggleVisibility() {
		if (this.readonly) return;
		if (!this.toggle) {
			this.element?.focus({ preventScroll: true });
			return;
		}
		this.open = !this.open;
		this._reconcile();
	}

	_reconcile() {
		const { button, element, select, toggle } = this;
		if (!button || !element || !toggle) return;

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
			toggle.display();
		});
	}

	addOption(option?: ComboboxOption) {
		this.details = option || {};
		this.select?.addOption(option);
		if (this.toggle) {
			this.toggle.display();
		} else {
			this._syncHeadingActions();
		}
	}

	clear() {
		if (this.readonly) return;
		this.details = {};
		this.select?.clear();
		this.open = false;
		if (this.toggle) {
			this._reconcile();
		} else {
			this._syncHeadingActions();
		}
	}

	destroy() {
		if (this.select?.element) {
			this.select.element.removeEventListener("updated", this._updated);
			this.select.element.removeEventListener("deactivate", this._deactivate);
		}
		this.select?.destroy();
	}
}
