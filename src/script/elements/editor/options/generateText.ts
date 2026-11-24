import type { Range } from "@tiptap/core";
import { FormController } from "../../../forms/controller.ts";
import { STYLES } from "../../../generated/styles.mjs";
import { request } from "../../../shared/request.ts";
import { buttons } from "../../buttons.ts";
import { primitives } from "../../primitives.ts";

import type { Toolbar } from "../toolbar.ts";

class GenerateText {
	declare submitButton: HTMLButtonElement;
	declare endpoints: Toolbar["endpoints"];
	declare editor: Toolbar["editor"];
	declare usedWithEditor: boolean;
	declare _active: boolean;
	declare toolbar: Toolbar;
	declare name: "generateText";
	declare messages: Record<string, string>;
	declare target: HTMLFormElement;
	declare prompt: HTMLTextAreaElement;
	declare selectedTextInput: HTMLInputElement;
	declare appendRadio: HTMLInputElement | null;
	declare replaceSelectionRadio: HTMLInputElement | null;
	declare html: HTMLElement[];
	declare form: FormController;
	declare _capturedRange: Range | null;

	constructor(toolbar: Toolbar) {
		this.toolbar = toolbar;
		this.submit = this.submit.bind(this);
		this.editor = toolbar.editor;
		this.endpoints = toolbar.endpoints;
		this.name = "generateText" as const;
		this.messages = {
			prompt: "Please describe the text you'd like to generate.",
			submit: "Generate",
			submitting: "Thinking...",
			submitted: "Text Generated",
		};
		this.submitButton = buttons.submit({
			kind: "editor",
		});

		this.usedWithEditor = true;
		this._onSelectionUpdate = this._onSelectionUpdate.bind(this);
		this._active = false;
		this._capturedRange = null;
	}

	get active() {
		return this._active;
	}

	set active(value: boolean) {
		this._active = value;
		if (value) {
			this._captureSelection();
			this.prompt.focus();
			this.toolbar.editor.on("selectionUpdate", this._onSelectionUpdate);
		} else {
			this.toolbar.editor.off("selectionUpdate", this._onSelectionUpdate);
			this.toolbar.editor.commands.clearSelectionHighlight();
			this._capturedRange = null;
		}
	}

	_onSelectionUpdate() {
		if (this._active) {
			this.toolbar.editor.commands.setSelectionHighlight();
			this._captureSelection();
		}
	}

	_captureSelection() {
		const { from, to } = this.editor.state.selection;
		const hasSelection = from !== to;
		this._capturedRange = { from, to };

		// Update radio button selection based on whether text is selected
		if (hasSelection) {
			if (this.appendRadio) this.appendRadio.checked = false;
			if (this.replaceSelectionRadio) this.replaceSelectionRadio.checked = true;

			const selectedText = this.editor.state.doc.textBetween(from, to, " ");
			this.selectedTextInput.value = selectedText;

			// Update placeholder to be more contextual
			if (selectedText.length > 0) {
				this.prompt.placeholder = `Describe how to modify the selected text: "${
					selectedText.length > 50
						? `${selectedText.substring(0, 50)}...`
						: selectedText
				}"`;
			}
		} else {
			if (this.appendRadio) this.appendRadio.checked = true;
			if (this.replaceSelectionRadio)
				this.replaceSelectionRadio.checked = false;
			this.selectedTextInput.value = "";
			this.prompt.placeholder = "Describe the text you want to generate...";
		}
	}

	init() {
		this.toolbar.editor.commands.setSelectionHighlight();

		this.target = this.toolbar.element.appendChild(
			document.createElement("form"),
		);
		this.target.className = `mt-4 hidden flex-col gap-2 rounded-md bg-slate-200 p-4 group-data-[open-form="generateText"]/toolbar:flex`;
		this.target.dataset.option = this.name;

		// Prompt textarea
		this.prompt = primitives.textarea({
			name: "prompt",
			rows: 3,
			placeholder: "Describe the text you want to generate...",
		});

		// Hidden input for selected text
		this.selectedTextInput = document.createElement("input");
		this.selectedTextInput.type = "hidden";
		this.selectedTextInput.name = "selected_text";
		this.selectedTextInput.value = "";

		const insertModeOptions = this._createInsertModeOptions();

		this.html = [this.prompt, this.selectedTextInput, insertModeOptions];

		this.form = new FormController(this);
		this.form.init();
	}

	_createInsertModeOptions() {
		const optionsContainer = document.createElement("div");
		optionsContainer.dataset.role = "insert-mode";
		optionsContainer.className = STYLES.editor.toolbar.optionPanel;

		const optionsHeader = optionsContainer.appendChild(
			document.createElement("h3"),
		);
		optionsHeader.className = STYLES.editor.toolbar.optionHeader;
		optionsHeader.textContent = "Insert Mode";

		const processing = optionsContainer.appendChild(
			document.createElement("div"),
		);
		processing.dataset.role = "insert-mode";
		processing.className = `${STYLES.upload.context}`;

		const insertOptions = [
			{ value: "append", text: "Append to end of document", checked: true },
			{ value: "replace", text: "Replace entire document" },
			{ value: "prepend", text: "Prepend to beginning" },
			{ value: "quote-top", text: "Add as quote at top" },
			{ value: "cursor", text: "Insert at cursor position" },
			{ value: "replace-selection", text: "Replace selected text" },
		];

		insertOptions.forEach((option) => {
			processing.appendChild(
				primitives.radio({
					name: "insert_mode",
					value: option.value,
					label: option.text,
					checked: option.checked || false,
				}),
			);
		});

		// Store references to radio buttons for selection handling
		this.appendRadio = processing.querySelector<HTMLInputElement>(
			'input[name="insert_mode"][value="append"]',
		);
		this.replaceSelectionRadio = processing.querySelector<HTMLInputElement>(
			'input[name="insert_mode"][value="replace-selection"]',
		);

		return optionsContainer;
	}

	async submit(submitter: HTMLButtonElement | HTMLInputElement | null) {
		const endpoint = this.endpoints?.generateText;
		if (!endpoint) return;
		if (!this.prompt.value) {
			this.form.showError(this.messages.prompt);
			return;
		}

		if (submitter) submitter.disabled = true;

		const formData = new FormData(this.target);
		formData.append("role", submitter?.dataset?.role || "generate");

		const response = await request.post<{ markup: string }>(endpoint, formData);

		if (submitter) submitter.disabled = false;

		if (response?.ok && response.markup) {
			const insertMode = formData.get("insert_mode") || "replace";
			this._addText(response.markup, insertMode);
		} else if (response?.error) {
			this.form.showError(response.error);
		}
	}

	_selectionRange() {
		const highlight = this.editor.commands.getSelectionHighlightRange();
		if (highlight) return highlight;

		const { from, to } = this._capturedRange ?? this.editor.state.selection;
		if (from !== to) {
			return { from, to };
		}

		return null;
	}

	_addText(html: string, insertMode: FormDataEntryValue = "replace") {
		const highlightedRange =
			insertMode === "replace-selection" ? this._selectionRange() : null;
		const cursorRange = insertMode === "cursor" ? this._capturedRange : null;
		this.editor.commands.clearSelectionHighlight();

		const chain = this.editor.chain().focus();

		switch (insertMode) {
			case "replace":
				chain.setContent(html).run();
				break;
			case "append":
				chain
					.command(({ commands }) => {
						commands.focus("end");
						const isEmpty = this.editor.getJSON().content?.length === 0;
						const spacing = isEmpty ? "" : "<p></p>";
						return commands.insertContent(`${spacing}${html}`);
					})
					.run();
				break;
			case "prepend":
				chain
					.command(({ commands }) => {
						commands.focus("start");
						const isEmpty = this.editor.getJSON().content?.length === 0;
						const spacing = isEmpty ? "" : "<p></p>";
						return commands.insertContent(`${html}${spacing}`);
					})
					.run();
				break;
			case "quote-top":
				chain
					.command(({ commands }) => {
						commands.focus("start");
						return commands.insertContent(
							`<blockquote>${html}</blockquote><p></p>`,
						);
					})
					.run();
				break;
			case "cursor":
				if (cursorRange) {
					chain.insertContentAt(cursorRange, html).run();
				} else {
					chain.insertContent(html).run();
				}
				break;
			case "replace-selection":
				if (highlightedRange) {
					chain.insertContentAt(highlightedRange, html).run();
				} else {
					chain.insertContent(html).run();
				}
				break;
			default:
				chain.setContent(html).run();
		}

		this.toolbar.toggleForm(this.name);
	}

	reset() {
		this.prompt.value = "";
		this.prompt.placeholder = "Describe the text you want to generate...";
		this.selectedTextInput.value = "";
		if (this.appendRadio && this.replaceSelectionRadio) {
			this.appendRadio.checked = true;
			this.replaceSelectionRadio.checked = false;
		}
		this.form.resetSubmitButton();
	}
}

export { GenerateText as generateText };
