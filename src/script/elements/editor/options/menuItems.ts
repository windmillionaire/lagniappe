import type { CanCommands } from "@tiptap/core";
import { STYLES } from "../../../generated/styles.mjs";
import { setIcon } from "../../../shared/icons.ts";

import type { ComboboxOptionElement } from "../../combobox/combobox.ts";
import type {
	ToolArgument,
	ToolbarFormCommand,
	ToolSettings,
} from "../config.ts";
import type { Toolbar } from "../toolbar.ts";
import { runToolCommand } from "./toolbarButtons.ts";

class ToolbarMenuItem {
	declare onClick: ToolbarMenuItem["_onClick"];
	declare toolbar: Toolbar;
	declare active: boolean;
	declare button: HTMLElement;
	declare command: ToolSettings["command"];
	declare args: ToolArgument;
	declare title: string;
	declare icon: string;
	declare name?: string;
	declare form?: boolean;

	constructor(toolbar: Toolbar) {
		this.toolbar = toolbar;
		this.active = false;
		this.button = document.createElement("button");
		this.onClick = this._onClick.bind(this);
	}

	get html() {
		return this.button.outerHTML;
	}

	_buttonIcon(icon: string) {
		const iconElement = document.createElement("span");
		setIcon(iconElement, icon, STYLES.dropdown.icon);
		return iconElement.outerHTML;
	}

	_buttonText(text: string) {
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

	init(settings: ToolSettings) {
		Object.assign(this, settings);
		this.button.role = "option";
		(this.button as HTMLButtonElement).type = "button";
		this.button.dataset.active = "false";
		this.button.className = `${STYLES.dropdown.option.action} group`;

		this.button.innerHTML = [
			this._buttonIcon(this.icon),
			this._buttonText(this.title),
			this._buttonCheck(),
		].join("");
	}

	_onClick(option: ComboboxOptionElement) {
		this.button = option;
		const editor = this.toolbar.editor;
		const chain = editor.chain().focus();
		if (
			editor.isEmpty &&
			["bulletList", "orderedList", "taskList"].includes(this.name || "")
		) {
			chain.setTextSelection(1);
		}

		// Use local toggle intent so the command always mirrors the clicked state.
		if (this.active) {
			if (this.command === "toggleHeading") {
				chain.setParagraph().run();
			} else if (this.command === "toggleUnderline") {
				chain.unsetUnderline().run();
			} else if (this.command === "toggleStrike") {
				chain.unsetStrike().run();
			} else if (this.command === "toggleCode") {
				chain.unsetCode().run();
			} else if (this.command === "toggleSuperscript") {
				chain.unsetSuperscript().run();
			} else if (this.command === "toggleSubscript") {
				chain.unsetSubscript().run();
			} else if (this.command === "toggleCodeBlock") {
				chain.toggleCodeBlock().run();
			} else if (this.command === "toggleBlockquote") {
				chain.lift("blockquote").run();
			} else {
				runToolCommand(chain, this.command, this.args);
			}
			this.disable();
			return;
		}

		runToolCommand(chain, this.command, this.args);
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

class TableMenuItem extends ToolbarMenuItem {
	isAvailable() {
		const editor = this.toolbar.editor;
		if (editor.isDestroyed || !editor.isEditable) return false;
		const inTable = editor.isActive("table");
		if (this.command === "insertTable" ? inTable : !inTable) return false;
		const command = editor.can()[this.command as keyof CanCommands] as (
			arg: ToolArgument,
		) => boolean;
		return command(this.args);
	}

	_onClick(option: ComboboxOptionElement) {
		if (!this.isAvailable()) return;
		super._onClick(option);
	}
}

class ClearFormatMenuItem extends ToolbarMenuItem {
	_onClick(option: ComboboxOptionElement) {
		this.button = option;
		this.toolbar.editor.chain().focus().clearNodes().unsetAllMarks().run();
	}
}

class FormMenuItem extends ToolbarMenuItem {
	_onClick(option: ComboboxOptionElement) {
		this.button = option;
		this.toolbar.toggleForm(this.command as ToolbarFormCommand);
	}
}

export {
	ClearFormatMenuItem as clearFormat, // Style
	FormMenuItem as setFontFamily, // Style
	FormMenuItem as setColor, // Style
	FormMenuItem as addLink, // Insert
	FormMenuItem as addImage, // Insert
	FormMenuItem as addYouTube, // Insert
	FormMenuItem as generateText, // Insert
	TableMenuItem as insertTable, // Table
	TableMenuItem as toggleHeaderRow, // Table
	TableMenuItem as addRowBefore, // Table
	TableMenuItem as addRowAfter, // Table
	TableMenuItem as addColumnBefore, // Table
	TableMenuItem as addColumnAfter, // Table
	TableMenuItem as deleteRow, // Table
	TableMenuItem as deleteColumn, // Table
	TableMenuItem as deleteTable, // Table
	ToolbarMenuItem as toggleBulletList, // Lists
	ToolbarMenuItem as toggleOrderedList, // Lists
	ToolbarMenuItem as toggleTaskList, // Lists
	ToolbarMenuItem as toggleUnderline, // Style
	ToolbarMenuItem as toggleStrike, // Style
	ToolbarMenuItem as toggleCode, // Style
	ToolbarMenuItem as toggleSuperscript, // Style
	ToolbarMenuItem as toggleSubscript, // Style
	ToolbarMenuItem as toggleHeading, // Headings
	ToolbarMenuItem as setParagraph, // Headings
	ToolbarMenuItem as setHorizontalRule, // Insert
	ToolbarMenuItem as toggleCodeBlock, // Insert
	ToolbarMenuItem as toggleBlockquote, // Insert
	ToolbarMenuItem as setTextAlign, // Align
};
