/*! Third-party licenses: /third-party-licenses.txt */
import { S as STYLES } from './styles.js?v=be1b1fb2';
import { s as setIcon } from './icons.js?v=be1b1fb2';
import { C as Combobox } from './combobox.js?v=be1b1fb2';
import './request.js?v=be1b1fb2';
import './errors.js?v=be1b1fb2';
import './connectivity.js?v=be1b1fb2';
import './utilities.js?v=be1b1fb2';
import './primitives.js?v=be1b1fb2';

/**
 * @testable true
 * @tests tests_js/test_016_combobox_frontend.py::test_dynamic_dropdown_rerenders_each_open_and_keeps_mixed_option_indexes
 * @pair dropdown:dynamic-options
 * @pair dropdown:rerender
 * @pair dropdown:mixed-options
 * @pair dropdown:callback-index
 */
class Dropdown extends Combobox {
	/**
	 * @testable true
	 * @tests tests_js/test_016_combobox_frontend.py::test_combobox_positioning_uses_live_element_by_default_and_explicit_reference_when_configured
	 * @features dropdown
	 * @dimensions positioning
	 */
	init(menu) {
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

		super.init();

		return this;
	}

	_createDropdownButton(item) {
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
		text.textContent = item.name;
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

	showPanel() {
		this._loadOptions().then((items) => {
			if (items !== undefined) this.items = items;
			this._renderOptions();
			const wasOpen = this.panelOpen;
			super.showPanel();
			if (!wasOpen && this.panelOpen) this.onShow?.();
		});
	}

	selectOption(option, event = null) {
		const item = this.items[parseInt(option.dataset.index, 10)];
		const closeOnClick =
			typeof item?.closeOnClick === "function"
				? item.closeOnClick(option, event)
				: item?.closeOnClick !== false;
		if (closeOnClick) this.hidePanel();
		if (item.onClick) {
			item.onClick(option, event);
		}
	}

	addOption(option) {
		this.items.splice(0, 0, option);
		this._renderOptions();
	}

	removeOptions(identifiers) {
		this.hidePanel();
		this.items = this.items.filter((item) => !identifiers.includes(item.id));
		this._renderOptions();
	}

	updateOptions(options = []) {
		this.items = Array.isArray(options) ? options : [];
		this._renderOptions();

		if (!this.items.length && this.panelOpen) {
			this.hidePanel();
			return;
		}

		if (this.panelOpen) {
			super.showPanel();
		}
	}

	elementClick(event) {
		event.stopPropagation();
		event.preventDefault();

		this.panelOpen ? this.hidePanel() : this.showPanel();
	}

	hidePanel() {
		const hidden = super.hidePanel();
		if (hidden) this.onHide?.();
		this.element.blur();
	}
}

export { Dropdown };
