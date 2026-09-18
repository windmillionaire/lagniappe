/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=b560d96b';
import { s as setIcon } from './icons.js?v=b560d96b';

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004d_document.py::test_formatting_persists
 * @matrix editor : formatting
 */
class ToolbarButton {
	constructor(toolbar) {
		this.toolbar = toolbar;
		this.active = false;
		this.button = document.createElement("button");
	}

	_isInlineMarkToggle() {
		return [
			"bold",
			"italic",
			"underline",
			"strike",
			"superscript",
			"subscript",
		].includes(this.name);
	}

	_addButtonIcon(icon) {
		const iconElement = document.createElement("span");
		setIcon(iconElement, icon);
		this.button.replaceChildren(iconElement);
	}

	init(settings) {
		Object.assign(this, settings);
		this.button.title = this.title;
		this.button.type = "button";
		this.button.dataset.active = "false";
		if (this.name) {
			this.button.className = `${STYLES.editor.toolbar.tool} data-[active=true]:bg-slate-300`;
		} else {
			this.button.className = `${STYLES.editor.toolbar.tool}`;
		}
		this._addButtonIcon(this.icon);
		this.button.addEventListener("click", () => this.onClick());
	}

	onClick() {
		const editor = this.toolbar.editor;
		const chain = editor.chain().focus();
		const shouldCollapseEmptySelection =
			editor.isEmpty && this._isInlineMarkToggle();
		if (shouldCollapseEmptySelection) chain.setTextSelection(1);
		chain[this.command](this.args).run();
		this.active ? this.disable() : this.enable();
	}

	enable() {
		if (!this.name) return;
		this.active = true;
		this.button.dataset.active = "true";
	}

	disable() {
		if (!this.name) return;
		this.active = false;
		this.button.dataset.active = "false";
	}
}

/**
 * @testable infrastructure
 */
class ToggleFocusButton extends ToolbarButton {
	onClick() {
		this.active = !this.active;
		const editorContainer = this.button.closest("[data-widget]");
		if (this.active) {
			editorContainer.dataset.fullscreen = "true";
			this._addButtonIcon("minimize");
		} else {
			editorContainer.dataset.fullscreen = "false";
			this._addButtonIcon("maximize");
		}
	}
}

export { ToolbarButton, ToolbarButton as redo, ToolbarButton as toggleBold, ToggleFocusButton as toggleFocus, ToolbarButton as toggleItalic, ToolbarButton as undo };
