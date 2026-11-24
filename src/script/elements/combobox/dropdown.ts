import type { Placement, ReferenceElement } from "@floating-ui/dom";
import { STYLES } from "../../generated/styles.mjs";
import { setIcon } from "../../shared/icons.ts";
import {
	Combobox,
	type ComboboxOption,
	type ComboboxOptionElement,
} from "./combobox.ts";

type DropdownOptionHandler<Result> = (
	option: ComboboxOptionElement,
	event: MouseEvent | null,
) => Result;

export interface DropdownItem extends ComboboxOption {
	icon?: string;
	html?: string;
	closeOnClick?: boolean | DropdownOptionHandler<boolean>;
	onClick?: DropdownOptionHandler<void>;
}

type DropdownLoader = () =>
	| DropdownItem[]
	| undefined
	| Promise<DropdownItem[] | undefined>;

export interface DropdownMenu {
	placement?: Placement;
	items?: DropdownItem[];
	styles?: Partial<Combobox["styles"]>;
	popupRole?: string;
	optionRole?: string;
	positionReference?: ReferenceElement | null;
	matchReferenceWidth?: boolean;
	triggerRole?: string | null;
	loadOptions?: DropdownLoader;
	onShow?: () => void;
	onHide?: () => void;
}

export class Dropdown extends Combobox<[menu: DropdownMenu]> {
	declare items: DropdownItem[];
	declare _loadOptions: DropdownLoader;
	declare onShow: (() => void) | null;
	declare onHide: (() => void) | null;

	init(menu: DropdownMenu): this {
		this.placement = menu.placement ?? "bottom-start";
		this.items = menu.items || [];
		this.styles = { ...this.styles, ...(menu.styles || {}) };
		this.popupRole = menu.popupRole || this.popupRole;
		this.optionRole = menu.optionRole || this.optionRole;
		if ("positionReference" in menu) {
			this.positionReference = menu.positionReference;
		}
		this.matchReferenceWidth =
			menu.matchReferenceWidth ?? this.matchReferenceWidth;
		if ("triggerRole" in menu) this.triggerRole = menu.triggerRole;
		this._loadOptions = menu.loadOptions || (async () => this.items);
		this.onShow = menu.onShow || null;
		this.onHide = menu.onHide || null;

		super.init(menu);

		return this;
	}

	_createDropdownButton(item: DropdownItem) {
		const itemButton = document.createElement("button");
		itemButton.className = STYLES.dropdown.option.action;
		itemButton.type = "button";
		itemButton.setAttribute("role", this.optionRole);

		if (item.icon) {
			const icon = document.createElement("span");
			icon.dataset.kind = item.kind;
			setIcon(icon, item.icon, `${STYLES.dropdown.icon} text-kind-default`);
			itemButton.appendChild(icon);
		}

		const text = document.createElement("span");
		text.textContent = item.name ?? null;
		itemButton.appendChild(text);

		return itemButton.outerHTML;
	}

	_renderOptions() {
		if (this.items.length === 0) {
			this.updatePanel("");
			return;
		}

		const html = this.items
			.map((item) => item.html || this._createDropdownButton(item))
			.join("");

		this.updatePanel(html);
	}

	async showPanel() {
		const items = await this._loadOptions();
		if (items !== undefined) this.items = items;
		this._renderOptions();
		const wasOpen = this.panelOpen;
		const opened = await super.showPanel();
		if (!wasOpen && opened) this.onShow?.();
		return opened;
	}

	selectOption(option: ComboboxOptionElement, event: MouseEvent | null = null) {
		const item = this.items[Number.parseInt(option.dataset.index ?? "", 10)];
		const closeOnClick =
			typeof item?.closeOnClick === "function"
				? item.closeOnClick(option, event)
				: item?.closeOnClick !== false;
		if (closeOnClick) this.hidePanel();
		if (item.onClick) {
			item.onClick(option, event);
		}
	}

	addOption(option: DropdownItem) {
		this.items.splice(0, 0, option);
		this._renderOptions();
	}

	removeOptions(identifiers: readonly (string | undefined)[]) {
		this.hidePanel();
		this.items = this.items.filter((item) => !identifiers.includes(item.id));
		this._renderOptions();
	}

	updateOptions(options: DropdownItem[] = []) {
		this.items = Array.isArray(options) ? options : [];
		this._renderOptions();

		if (!this.items.length && this.panelOpen) {
			this.hidePanel();
			return;
		}

		if (this.panelOpen) {
			void super.showPanel();
		}
	}

	elementClick(event: MouseEvent) {
		event.stopPropagation();
		event.preventDefault();

		this.panelOpen ? this.hidePanel() : void this.showPanel();
	}

	hidePanel(): undefined {
		const hidden = super.hidePanel();
		if (hidden) this.onHide?.();
		this.element.blur();
	}
}
