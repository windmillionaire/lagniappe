import type { Editor, Range } from "@tiptap/core";
import { STYLES } from "../../generated/styles.mjs";
import { setIcon } from "../../shared/icons.ts";
import type { Modal } from "../../shared/modal.ts";
import { withTransition } from "../../shared/transitions.ts";
import { debounce } from "../../shared/utilities.ts";
import type { DocumentSaveState } from "../../types/sync.d.ts";
import type { DropdownItem } from "../combobox/dropdown.ts";
import {
	type EditorDocumentAttributes,
	TOOLBAR_MENUS,
	TOOLBAR_TOOLS,
	type ToolbarFormCommand,
	type ToolbarMenu,
	type ToolbarOptionCommand,
	type ToolbarTool,
	type ToolSettings,
} from "./config.ts";
import { toolbarDropdown } from "./dropdowns.ts";
import { MarkdownPastePrompt } from "./options/markdownPaste.ts";
import { FORM_REGISTRY, OPTION_REGISTRY } from "./options/registry.ts";
import { UserManager } from "./users.ts";
import type { DocumentVersions } from "./versions.ts";

type ToolbarDocument = EditorDocumentAttributes & {
	editor: Editor | null;
	container: HTMLElement;
	draftOnly?: boolean;
	addDraftImage?: (file: File) => string;
	versions?: DocumentVersions;
};

export type ToolbarOption = Pick<DropdownItem, "name" | "html" | "onClick"> & {
	active: boolean;
	button: HTMLElement | null;
	form?: boolean;
	command?: ToolSettings["command"];
	init(settings: ToolSettings): void;
	enable?(): void;
	disable?(): void;
	isAvailable?(): boolean;
	show?(): void;
	refresh?(): Promise<void>;
};

interface ToolbarForm {
	active: boolean;
	usedWithEditor?: boolean;
	init(): void | Promise<void>;
	submit?(
		submitter: HTMLButtonElement | HTMLInputElement | null,
	): void | Promise<void>;
	focus?(): void;
	reset?(): void;
	destroy?(): void;
	captureSelection?(): void;
	setActiveColor?(color: string | null | undefined): void;
	setActiveFontStyle?(font: string | null | undefined): void;
}

const registeredOption = async <Key extends string, Option>(
	load: () => Promise<Partial<Record<Key, new (toolbar: Toolbar) => Option>>>,
	command: Key,
	toolbar: Toolbar,
) => {
	const module = await load();
	const OptionClass = module[command];
	if (!OptionClass)
		throw new Error(`Missing editor toolbar registration for ${command}`);
	return new OptionClass(toolbar);
};

const isFormCommand = (
	command: string | undefined,
): command is ToolbarFormCommand =>
	typeof command === "string" && Object.hasOwn(FORM_REGISTRY, command);

const DEBOUNCE_DELAY_MS = 100;

export class Toolbar {
	declare document: ToolbarDocument;
	declare editor: Editor;
	declare kind: NonNullable<EditorDocumentAttributes["kind"]>;
	declare endpoints: EditorDocumentAttributes["endpoints"];
	declare aiCreate: boolean;
	declare publicLimited: boolean;
	declare error: HTMLElement | null;
	declare active: ToolbarOption | null;
	declare _destroyed: boolean;
	declare editorState: ReturnType<typeof debounce<Toolbar, []>>;
	declare toggleForm: ReturnType<
		typeof debounce<Toolbar, [ToolbarFormCommand]>
	>;
	declare windowClick: Toolbar["_windowClick"];
	declare editorClick: Toolbar["_editorClick"];
	declare editorKeydown: Toolbar["_editorKeydown"];
	declare editorLinkEdit: Toolbar["_editorLinkEdit"];
	declare formSubmit: Toolbar["_formSubmit"];
	declare submitFormOption: Toolbar["_submitFormOption"];
	declare builder?: ConstructorParameters<typeof Modal>[0];
	declare element: HTMLDivElement;
	declare editorDom: HTMLElement | null;
	declare options: Record<string, ToolbarOption>;
	declare forms: Partial<Record<ToolbarFormCommand, ToolbarForm>>;
	declare toggles: Partial<
		Record<ToolSettings["command"] | ToolbarFormCommand, ToolbarOption>
	>;
	declare userManager: UserManager | null;
	declare markdownPastePrompt: MarkdownPastePrompt | null;
	declare saveStatus: HTMLSpanElement | null;
	declare _saveState: DocumentSaveState;

	constructor(document: ToolbarDocument) {
		this._destroyed = false;
		this.document = document;
		if (!document.editor)
			throw new Error("Toolbar requires an initialized editor");
		this.editor = document.editor;
		this.kind = document.kind || "default";
		this.endpoints = document.endpoints;
		this.publicLimited = document.target?.dataset?.publicLimited === "true";
		this.aiCreate = document.target?.dataset?.aiCreate === "true";
		this.editorDom = null;
		this.options = {};
		this.forms = {};
		this.toggles = {};
		this.error = null;
		this.active = null;
		this.userManager = null;
		this.markdownPastePrompt = null;
		this.saveStatus = null;
		this._saveState = "idle";
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
		this.markdownPastePrompt = new MarkdownPastePrompt(this);
		this.markdownPastePrompt.init();
		this.userManager = new UserManager(this);
		this.element.addEventListener("submit", this.formSubmit);
		this.editor.on("transaction", this.editorState);
		this.editorDom = this.editor.view.dom;
		this.editorDom.addEventListener("click", this.editorClick);
		this.editorDom.addEventListener("keydown", this.editorKeydown);
		this.editorDom.addEventListener("editor-link-edit", this.editorLinkEdit);
		document.addEventListener("click", this.windowClick, { capture: true });
	}

	_windowClick(e: MouseEvent) {
		const openForm = this.element.dataset.openForm;
		if (!isFormCommand(openForm)) return;
		if (this.document.view?.isDragging) return;
		const target = e.target as Element | null;
		const editorSurface =
			this.document.container?.contains(target) ||
			this.editor.view.dom.contains(target);
		if (editorSurface && !target?.closest("[role='listbox'], #modal")) {
			const form = this.forms[openForm];
			form && !form.usedWithEditor && this.toggleForm(openForm);
		}
	}

	async _editorKeydown(event: KeyboardEvent) {
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

	async _editorLinkEdit(event: CustomEvent<{ range: Range }>) {
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
		if (this._destroyed || this.editor.isDestroyed) return;
		const { selection, storedMarks } = this.editor.state;
		const { $from } = selection;
		const marks = [...$from.marks()];
		if (selection.empty && storedMarks?.length) {
			marks.push(...storedMarks);
		}
		const attrs = $from.parent.attrs;

		const style = this.editor.getAttributes("textStyle");
		if (this.forms.setColor) {
			this.forms.setColor.setActiveColor?.(style.color);
		}
		if (this.forms.setFontFamily) {
			this.forms.setFontFamily.setActiveFontStyle?.(style.fontFamily);
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
				activeOptions.has(key) ||
				(option.name ? this.editor.isActive(option.name) : false);
			if (option.active !== isActive) {
				isActive ? option.enable?.() : option.disable?.();
			}
		}
	}

	_formSubmit(e: SubmitEvent) {
		e.preventDefault();
		e.stopPropagation();
		this.submitFormOption(
			e.submitter as HTMLButtonElement | HTMLInputElement | null,
		);
	}

	_submitFormOption(submitter: HTMLButtonElement | HTMLInputElement | null) {
		const command = this.element.dataset.openForm;
		if (isFormCommand(command)) this.forms[command]?.submit?.(submitter);
	}

	async openForm(command: ToolbarFormCommand) {
		const form = this.forms[command];
		if (this.element.dataset.openForm === command && form?.active) {
			this._focusForm(command);
			return;
		}

		await this._toggleForm(command);
		this._focusForm(command);
	}

	async closeForm(command: ToolbarFormCommand) {
		const form = this.forms[command];
		if (this.element.dataset.openForm !== command || !form?.active) return;

		await this._toggleForm(command);
	}

	_focusForm(command: ToolbarFormCommand) {
		const focus = () => {
			const form = this.forms[command];
			if (this.element.dataset.openForm === command && form?.active) {
				form.focus?.();
			}
		};

		focus();
		requestAnimationFrame(focus);
	}

	async _loadOption(command: ToolbarOptionCommand, settings: ToolSettings) {
		const option = await registeredOption<ToolbarOptionCommand, ToolbarOption>(
			OPTION_REGISTRY[command],
			command,
			this,
		);
		option.init(settings);
		return option;
	}

	async _loadForm(command: ToolbarFormCommand) {
		const form = await registeredOption<ToolbarFormCommand, ToolbarForm>(
			FORM_REGISTRY[command],
			command,
			this,
		);
		form.init();
		return form;
	}

	async _createTools() {
		const toolRow = document.createElement("div");
		toolRow.className = STYLES.editor.toolbar.section;

		const primaryTools = document.createElement("div");
		primaryTools.className = "contents";
		toolRow.appendChild(primaryTools);

		const menuTools = document.createElement("div");
		menuTools.className = "contents";
		menuTools.dataset.role = "toolbar-menus";
		toolRow.appendChild(menuTools);
		if (!this.document.draftOnly) {
			const status = document.createElement("span");
			status.dataset.role = "save-status";
			status.dataset.saveState = "idle";
			status.setAttribute("role", "status");
			status.setAttribute("aria-live", "polite");
			status.className = STYLES.editor.toolbar.saveStatus;
			status.hidden = true;
			this.saveStatus = status;
			toolRow.appendChild(status);
			if (this._saveState !== "idle") this.setSaveState(this._saveState);
		}
		this.element.appendChild(toolRow);

		const buttons = await Promise.all(
			TOOLBAR_TOOLS.map((tool) => this._createToolbarButton(tool)),
		);
		if (this._destroyed) return;
		primaryTools.append(...buttons.filter((button) => button !== null));

		const dropdownButtons = await Promise.all(
			Object.values(TOOLBAR_MENUS).map(async (menu) => {
				return await this._createToolbarMenu(menu);
			}),
		);
		if (this._destroyed) return;
		menuTools.append(...dropdownButtons.filter((button) => button !== null));
	}

	setSaveState(state: DocumentSaveState) {
		this._saveState = state;
		const el = this.saveStatus;
		if (!el) return;
		el.dataset.saveState = state;
		if (state === "idle") {
			el.hidden = true;
			el.replaceChildren();
			return;
		}
		el.hidden = false;
		if (state === "saved") {
			const icon = document.createElement("span");
			setIcon(icon, "check", "icon-xs");
			const label = document.createElement("span");
			label.textContent = "Saved";
			el.replaceChildren(icon, label);
			return;
		}
		if (state === "saving") {
			const label = document.createElement("span");
			label.textContent = "Saving…";
			el.replaceChildren(label);
			return;
		}
		if (state === "dirty") {
			const label = document.createElement("span");
			label.textContent = "Unsaved";
			el.replaceChildren(label);
			return;
		}
		if (state === "offline") {
			const icon = document.createElement("span");
			setIcon(icon, "offline", "icon-xs");
			const prefix = document.createElement("span");
			prefix.className = "hidden sm:inline";
			prefix.textContent = "Saved ";
			const label = document.createElement("span");
			label.textContent = "offline";
			el.replaceChildren(icon, prefix, label);
			return;
		}
		const icon = document.createElement("span");
		setIcon(icon, "offline", "icon-xs");
		const label = document.createElement("span");
		label.textContent = "Retrying…";
		el.replaceChildren(icon, label);
	}

	_toolAllowed(tool: ToolbarTool) {
		if (
			this.document.draftOnly &&
			["documentHistory", "toggleFocus", "generateText"].includes(tool.command)
		)
			return false;
		if (this.publicLimited && tool.command === "addImage") return false;
		if (!this.aiCreate && tool.command === "generateText") return false;
		return true;
	}

	async _createToolbarButton(tool: ToolbarTool) {
		if (!this._toolAllowed(tool)) return null;

		const option = await this._loadOption(tool.command, tool);
		if (tool.name) {
			this.options[tool.name] = option;
		} else {
			this.toggles[tool.command] = option;
		}
		return option.button;
	}

	async _createToolbarMenu(menu: ToolbarMenu) {
		if ("command" in menu) return this._createToolbarButton(menu);
		const menuItems = menu.items.filter((item) => this._toolAllowed(item));
		const items = await Promise.all(
			menuItems.map((item) => this._loadOption(item.command, item)),
		);

		items.forEach((item) => {
			if (item.name) {
				this.options[item.name] = item;
			} else if (item.form && item.command) {
				this.toggles[item.command] = item;
			}
		});

		const dropdownButton = toolbarDropdown(menu, items, () =>
			this._editorState(),
		);
		return dropdownButton;
	}

	async _toggleForm(command: ToolbarFormCommand) {
		const form = this.forms[command];
		const toggle = this.toggles[command];
		const loaded = form || (await this._loadForm(command));

		return withTransition(
			() => {
				if (form) {
					form.active = !form.active;
					this.element.dataset.openForm = form.active ? command : "false";
					form.active ? toggle?.enable?.() : toggle?.disable?.();
					if (!form.active && form.reset) form.reset();
				} else {
					this.forms[command] = loaded;
					this.element.dataset.openForm = command;
					loaded.active = true;
					toggle?.enable?.();
				}
			},
			{ label: `editor:toggle-${command}` },
		);
	}

	destroy() {
		if (this._destroyed) return;
		this._destroyed = true;
		this.editorState.cancel?.();
		this.toggleForm.cancel?.();
		this.markdownPastePrompt?.destroy();
		Object.values(this.forms).forEach((form) => {
			if (form.destroy) form.destroy();
		});
		if (this.userManager) {
			this.userManager.destroy();
		}
		this.editor.off("transaction", this.editorState);
		this.editorDom?.removeEventListener("click", this.editorClick);
		this.editorDom?.removeEventListener("keydown", this.editorKeydown);
		this.editorDom?.removeEventListener(
			"editor-link-edit",
			this.editorLinkEdit,
		);
		this.element?.removeEventListener("submit", this.formSubmit);
		document.removeEventListener("click", this.windowClick, { capture: true });
	}
}
