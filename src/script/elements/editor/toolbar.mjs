import { STYLES } from "styles";
import { TOOLBAR_MENUS, TOOLBAR_TOOLS } from "../../config/editor";
import { debounce, withTransition } from "../../shared";
import { toolbarDropdown } from "./dropdowns";
import { FORM_REGISTRY, OPTION_REGISTRY } from "./options/registry";
import { UserManager } from "./users";

const DEBOUNCE_DELAY_MS = 100;

/**
 * @testable false
 * @covered-by src/script/elements/editor/options/toolbarButtons.mjs::ToolbarButton
 * @covered-by src/script/elements/editor/options/setColor.mjs::ColorPicker
 * @covered-by src/script/elements/editor/options/setFontFamily.mjs::FontFamilyPicker
 * @covered-by src/script/elements/editor/options/addLink.mjs::AddLink
 * @covered-by src/script/elements/editor/options/addYouTube.mjs::AddYouTube
 * @covered-by src/script/elements/editor/options/addImage.mjs::Image
 * @covered-by src/script/elements/editor/options/documentHistory.mjs::DocumentHistoryButton
 * @reason toolbar shell loads option owners; individual option classes own editor behavior
 */
export class Toolbar {
	constructor(document) {
		this.document = document;
		this.editor = document.editor;
		this.kind = document.kind || "default";
		this.endpoints = document.endpoints;
		this.publicLimited = document.target?.dataset?.publicLimited === "true";
		this.element = null;
		this.options = {};
		this.forms = {};
		this.toggles = {};
		this.error = null;
		this.active = null;
		this.userManager = null;
		this.editorState = debounce(
			this._editorState.bind(this),
			DEBOUNCE_DELAY_MS,
		);
		this.windowClick = this._windowClick.bind(this);
		this.editorClick = this._editorClick.bind(this);
		this.editorKeydown = this._editorKeydown.bind(this);
		this.editorLinkEdit = this._editorLinkEdit.bind(this);
		this.formSubmit = this._formSubmit.bind(this);
		this.submitFormOption = this._submitFormOption.bind(this);
		this.toggleForm = debounce(this._toggleForm.bind(this), DEBOUNCE_DELAY_MS);
	}

	init() {
		this.element = document.createElement("div");
		this.element.tabIndex = -1;
		this.element.dataset.role = "toolbar";
		this.element.dataset.openForm = "false";
		this.element.className = `${STYLES.editor.toolbar.container[this.kind]} ${STYLES.editor.toolbar.iconContext}`;

		this._createTools();
		this.userManager = new UserManager(this);
		this.element.addEventListener("submit", this.formSubmit);
		this.editor.on("transaction", this.editorState);
		this.editor.view.dom.addEventListener("click", this.editorClick);
		this.editor.view.dom.addEventListener("keydown", this.editorKeydown);
		this.editor.view.dom.addEventListener(
			"editor-link-edit",
			this.editorLinkEdit,
		);
		document.addEventListener("click", this.windowClick, { capture: true });
	}

	_windowClick(e) {
		const openForm = this.element.dataset.openForm;
		if (openForm === "false") return;
		if (this.document.view?.isDragging) return;
		const editorSurface =
			this.document.container?.contains(e.target) ||
			this.editor.view.dom.contains(e.target);
		if (editorSurface && !e.target.closest("[role='listbox'], #modal")) {
			const form = this.forms[openForm];
			form && !form.usedWithEditor && this.toggleForm(openForm);
		}
	}

	async _editorKeydown(event) {
		if (
			(event.ctrlKey || event.metaKey) &&
			!event.altKey &&
			event.key.toLowerCase() === "k"
		) {
			event.preventDefault();
			event.stopPropagation();
			await this.openForm("addLink");
		}
	}

	async _editorLinkEdit(event) {
		event.preventDefault();
		event.stopPropagation();

		const range = event.detail?.range;
		if (range) {
			this.editor.chain().focus().setTextSelection(range).run();
		}

		await this.openForm("addLink");
		this.forms.addLink?.captureSelection?.();
		this.forms.addLink?.focus?.();
	}

	async _editorClick() {
		const image = this.editor.getAttributes("image");
		const onImage = Object.keys(image).length > 0;
		const setImageActive = this.forms.setImage?.active;
		if (onImage && !setImageActive) {
			await this._toggleForm("setImage");
		} else if (!onImage && setImageActive) {
			await this._toggleForm("setImage");
		}
	}

	async _editorState() {
		const { selection, storedMarks } = this.editor.state;
		const { $from } = selection;
		const marks = [...$from.marks()];
		if (selection.empty && storedMarks?.length) {
			marks.push(...storedMarks);
		}
		const attrs = $from.parent.attrs;

		const style = this.editor.getAttributes("textStyle");
		if (this.forms.setColor) {
			this.forms.setColor.setActiveColor(style.color);
		}
		if (this.forms.setFontFamily) {
			this.forms.setFontFamily.setActiveFontStyle(style.fontFamily);
		}

		const activeOptions = new Set(marks.map((mark) => mark.type.name));

		const image = this.editor.getAttributes("image");
		if (Object.keys(image).length > 0) {
			activeOptions.add(`alignment:${image.alignment}`);
			activeOptions.add(`float:${image.float}`);
		}

		for (const [key, value] of Object.entries(attrs)) {
			if (value) activeOptions.add(`${key}:${value}`);
		}

		for (const node of [
			"bulletList",
			"orderedList",
			"taskList",
			"blockquote",
		]) {
			if (this.editor.isActive(node)) activeOptions.add(node);
		}

		for (const [key, option] of Object.entries(this.options)) {
			const isActive =
				activeOptions.has(key) || this.editor.isActive(option.name);
			if (option.active !== isActive) {
				isActive ? option.enable() : option.disable();
			}
		}
	}

	_formSubmit(e) {
		e.preventDefault();
		e.stopPropagation();
		this.submitFormOption(e.submitter);
	}

	_submitFormOption(submitter) {
		const form = this.forms[this.element.dataset.openForm];
		if (form) form.submit(submitter);
	}

	async openForm(command) {
		const form = this.forms[command];
		if (this.element.dataset.openForm === command && form?.active) {
			this._focusForm(command);
			return;
		}

		await this._toggleForm(command);
		this._focusForm(command);
	}

	async closeForm(command) {
		const form = this.forms[command];
		if (this.element.dataset.openForm !== command || !form?.active) return;

		await this._toggleForm(command);
	}

	_focusForm(command) {
		const focus = () => {
			const form = this.forms[command];
			if (this.element.dataset.openForm === command && form?.active) {
				form.focus?.();
			}
		};

		focus();
		requestAnimationFrame(focus);
	}

	async _loadOption(command, settings) {
		const module = await OPTION_REGISTRY[command]();
		const option = new module[command](this);
		option.init(settings);
		return option;
	}

	async _loadForm(command) {
		const module = await FORM_REGISTRY[command]();
		const form = new module[command](this);
		form.init();
		return form;
	}

	async _createTools() {
		const toolRow = document.createElement("div");
		toolRow.className = `${STYLES.editor.toolbar.tools}`;

		const primaryTools = document.createElement("div");
		primaryTools.className = STYLES.editor.toolbar.section;
		const buttons = await Promise.all(
			TOOLBAR_TOOLS.map((tool) => this._createToolbarButton(tool)),
		);
		primaryTools.append(...buttons.filter(Boolean));
		toolRow.appendChild(primaryTools);

		const menuTools = document.createElement("div");
		menuTools.className = STYLES.editor.toolbar.section;
		menuTools.dataset.role = "toolbar-menus";
		const dropdownButtons = await Promise.all(
			Object.values(TOOLBAR_MENUS).map(async (menu) => {
				return await this._createToolbarMenu(menu);
			}),
		);
		menuTools.append(...dropdownButtons);
		toolRow.appendChild(menuTools);

		this.element.appendChild(toolRow);
	}

	_toolAllowed(tool) {
		if (!this.publicLimited) return true;
		return !["addImage", "generateText"].includes(tool.command);
	}

	async _createToolbarButton(tool) {
		if (!this._toolAllowed(tool)) return null;

		const option = await this._loadOption(tool.command, tool);
		if (tool.name) {
			this.options[tool.name] = option;
		} else {
			this.toggles[tool.command] = option;
		}
		return option.button;
	}

	async _createToolbarMenu(menu) {
		const menuItems = menu.items.filter((item) => this._toolAllowed(item));
		const items = await Promise.all(
			menuItems.map((item) => this._loadOption(item.command, item)),
		);

		items.forEach((item) => {
			if (item.name) {
				this.options[item.name] = item;
			} else if (item.form) {
				this.toggles[item.command] = item;
			}
		});

		const dropdownButton = toolbarDropdown(menu, items);
		return dropdownButton;
	}

	_toggleForm(command) {
		const form = this.forms[command];
		const toggle = this.toggles[command];

		return withTransition(async () => {
			if (form) {
				form.active = !form.active;
				this.element.dataset.openForm = form.active ? command : "false";
				form.active ? toggle?.enable() : toggle?.disable();
				if (!form.active && form.reset) form.reset();
			} else {
				const form = await this._loadForm(command);
				this.forms[command] = form;
				this.element.dataset.openForm = command;
				form.active = true;
				toggle?.enable();
			}
		});
	}

	destroy() {
		Object.values(this.forms).forEach((form) => {
			if (form.destroy) form.destroy();
		});
		if (this.userManager) {
			this.userManager.destroy();
		}
		this.editor.off("selectionUpdate", this.editorState);
		this.editor.view.dom.removeEventListener("click", this.editorClick);
		this.editor.view.dom.removeEventListener("keydown", this.editorKeydown);
		this.editor.view.dom.removeEventListener(
			"editor-link-edit",
			this.editorLinkEdit,
		);
		document.removeEventListener("click", this.windowClick, { capture: true });
	}
}
