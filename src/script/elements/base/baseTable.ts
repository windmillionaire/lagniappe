import { withTransition } from "../../shared/transitions.ts";
import {
	EmbeddedTableVisibility,
	type ExpandedTableButton,
	ExpandedTableCell,
	type ExpandedTableView,
} from "../embeddedTable.ts";

export interface EmbeddedTableAttributes<
	View extends ExpandedTableView = ExpandedTableView,
	Component = unknown,
> {
	target: HTMLElement;
	view: View;
	component: Component;
	visible?: boolean;
	modified?: boolean;
}

interface TablePanel {
	visible?: boolean;
	initialized?: boolean;
	disable(): void;
	reconcile(): unknown;
}

export interface TableComponent {
	elt: HTMLElement;
	active?: TablePanel | null;
	widgets: {
		TableVisibility?: TablePanel | null;
		TableSorting?: (TablePanel & { refreshRows?(): unknown }) | null;
	};
}

export type BaseTableAttributes<
	View extends ExpandedTableView = ExpandedTableView,
	Component extends TableComponent = TableComponent,
> = EmbeddedTableAttributes<View, Component>;

export interface ToggleColumnFilterDetail {
	button: HTMLButtonElement | null;
	column: string | undefined;
}

export class EmbeddedTable<
	View extends ExpandedTableView = ExpandedTableView,
	Component = unknown,
> {
	declare target: HTMLElement;
	declare view: View;
	declare component: Component;
	declare visible?: boolean;
	declare modified?: boolean;
	declare click: (event: MouseEvent) => void;
	declare _visibility: EmbeddedTableVisibility | null;

	constructor(attributes: EmbeddedTableAttributes<View, Component>) {
		Object.assign(this, attributes);
		this.click = this._click.bind(this);
		this._visibility = null;
	}

	init() {
		document.addEventListener("click", this.click);
		this.modified = true;
		this.visible = true;
	}

	_click(e: MouseEvent) {
		this._clickExpandedTableCell(e);
	}

	_clickExpandedTableCell(e: MouseEvent) {
		const expand =
			e.target instanceof Element
				? e.target.closest<ExpandedTableButton>("button[data-role='expand']")
				: null;
		if (!expand || !this.target.contains(expand)) return false;

		e.preventDefault();
		e.stopPropagation();
		this._expandTableCell(expand);
		return true;
	}

	initVisibility(
		table: HTMLTableElement | null,
		storageKey: string | null = null,
	) {
		if (!table) return null;

		this._visibility = new EmbeddedTableVisibility(table, storageKey);
		this._visibility.init();
		return this._visibility;
	}

	async _expandTableCell(button: ExpandedTableButton) {
		if (!button._embeddedTable) {
			button._embeddedTable = new ExpandedTableCell(this.view, button);
		}
		button._embeddedTable.toggle();
	}

	destroy() {
		document.removeEventListener("click", this.click);
	}
}

export class BaseTable<
	View extends ExpandedTableView = ExpandedTableView,
	Component extends TableComponent = TableComponent,
> extends EmbeddedTable<View, Component> {
	declare keydown: (event: KeyboardEvent) => void;

	constructor(attributes: BaseTableAttributes<View, Component>) {
		super(attributes);
		this.keydown = this._keydown.bind(this);
	}

	init() {
		super.init();
		document.addEventListener("keydown", this.keydown);
	}

	get header() {
		return this.component.elt.querySelector("thead > tr:first-child");
	}

	get visibilityWidget() {
		return this.component.widgets.TableVisibility;
	}

	get sortingWidget() {
		return this.component.widgets.TableSorting;
	}

	_click(e: MouseEvent) {
		if (this._clickExpandedTableCell(e)) return;
		const target = e.target;
		if (!(target instanceof Element)) return;

		const visibility = this.visibilityWidget;
		const sorting = this.sortingWidget;
		const open = visibility?.visible || sorting?.visible;

		if (!target.closest("thead")) {
			open &&
				withTransition(() => {
					[visibility, sorting].forEach((widget) => {
						if (widget) widget.disable();
						if (widget) widget.reconcile();
					});
					if (
						this.component.active === visibility ||
						this.component.active === sorting
					) {
						this.component.active = null;
						this.component.elt.dataset.open = "false";
					}
				});
			return;
		}

		if (target.closest("button[lp-show$=':TableVisibility']")) {
			return;
		} else if (this.header?.contains(target)) {
			const header = target.closest<HTMLTableCellElement>("th[data-ordering]");
			if (!header) return;

			const event = new CustomEvent<ToggleColumnFilterDetail>(
				"toggle-column-filter",
				{
					detail: {
						button: target.closest("button"),
						column: header.dataset.column,
					},
					bubbles: true,
				},
			);
			this.target.dispatchEvent(event);
		}
	}

	_keydown(e: KeyboardEvent) {
		if (e.key === "Escape") {
			const visibility = this.visibilityWidget;
			const sorting = this.sortingWidget;
			const open = visibility?.visible || sorting?.visible;
			if (!open) return;

			withTransition(() => {
				[visibility, sorting].forEach((widget) => {
					if (widget) widget.disable();
					if (widget) widget.reconcile();
				});
				if (
					this.component.active === visibility ||
					this.component.active === sorting
				) {
					this.component.active = null;
					this.component.elt.dataset.open = "false";
				}
			});
		}
	}

	destroy() {
		super.destroy();
		document.removeEventListener("keydown", this.keydown);
	}
}
