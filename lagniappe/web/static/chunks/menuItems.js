/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bb782d98';
import { s as setIcon } from './icons.js?v=bb782d98';

/**
 * @testable true
 * @tests tests_js/test_033_editor_menu_items.py::test_editor_menu_item_serializes_current_active_state
 * @matrix editor : dropdown-rerender menu-active-state
 */
class ToolbarMenuItem {
	constructor(toolbar) {
		this.toolbar = toolbar;
		this.active = false;
		this.button = document.createElement("button");
		this.onClick = this._onClick.bind(this);
	}

	get html() {
		return this.button.outerHTML;
	}

	_buttonIcon(icon) {
		const iconElement = document.createElement("span");
		setIcon(iconElement, icon, STYLES.dropdown.icon);
		return iconElement.outerHTML;
	}

	_buttonText(text) {
		const textElement = document.createElement("span");
		textElement.textContent = text;
		return textElement.outerHTML;
	}

	_buttonCheck() {
		const checkContainer = document.createElement("div");
		if (this.name || this.form) {
			checkContainer.className =
				"invisible ml-auto grid size-lh place-items-center group-data-[active=true]:visible";
		} else {
			checkContainer.className =
				"invisible ml-auto grid size-lh place-items-center";
		}

		const check = checkContainer.appendChild(document.createElement("span"));
		setIcon(check, "check");
		return checkContainer.outerHTML;
	}

	init(settings) {
		Object.assign(this, settings);
		this.button.role = "option";
		this.button.dataset.active = "false";
		this.button.className = `${STYLES.dropdown.option.action} group`;

		this.button.innerHTML = [
			this._buttonIcon(this.icon),
			this._buttonText(this.title),
			this._buttonCheck(),
		].join("");
	}

	_onClick(option) {
		this.button = option;
		const editor = this.toolbar.editor;
		const chain = editor.chain().focus();

		// Use local toggle intent so the command always mirrors the clicked state.
		if (this.active) {
			if (this.command === "toggleHeading") {
				chain.setParagraph().run();
			} else if (this.command === "toggleUnderline") {
				chain.unsetUnderline().run();
			} else if (this.command === "toggleStrike") {
				chain.unsetStrike().run();
			} else if (this.command === "toggleSuperscript") {
				chain.unsetSuperscript().run();
			} else if (this.command === "toggleSubscript") {
				chain.unsetSubscript().run();
			} else if (this.command === "toggleCodeBlock") {
				chain.unsetCodeBlock().run();
			} else if (this.command === "toggleBlockquote") {
				chain.lift("blockquote").run();
			} else if (this.args === undefined) {
				chain[this.command]().run();
			} else {
				chain[this.command](this.args).run();
			}
			this.disable();
			return;
		}

		if (this.args === undefined) {
			chain[this.command]().run();
		} else {
			chain[this.command](this.args).run();
		}
		if (this.name) this.enable();
	}

	enable() {
		this.active = true;
		this.button.dataset.active = "true";
	}

	disable() {
		this.active = false;
		this.button.dataset.active = "false";
	}
}

/**
 * @testable infrastructure
 */
class ClearFormatMenuItem extends ToolbarMenuItem {
	_onClick(option) {
		this.button = option;
		this.toolbar.editor.chain().focus().clearNodes().unsetAllMarks().run();
	}
}

/**
 * @testable infrastructure
 */
class FormMenuItem extends ToolbarMenuItem {
	_onClick(option) {
		this.button = option;
		this.toolbar.toggleForm(this.command);
	}
}

export { FormMenuItem as addImage, FormMenuItem as addLink, FormMenuItem as addYouTube, ClearFormatMenuItem as clearFormat, FormMenuItem as generateText, FormMenuItem as setColor, FormMenuItem as setFontFamily, ToolbarMenuItem as setHorizontalRule, ToolbarMenuItem as setParagraph, ToolbarMenuItem as setTextAlign, ToolbarMenuItem as toggleBlockquote, ToolbarMenuItem as toggleCodeBlock, ToolbarMenuItem as toggleHeading, ToolbarMenuItem as toggleStrike, ToolbarMenuItem as toggleSubscript, ToolbarMenuItem as toggleSuperscript, ToolbarMenuItem as toggleUnderline };
