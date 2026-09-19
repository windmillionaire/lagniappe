import { STYLES } from "../generated/styles.mjs";
import { createIcon } from "../shared/icons.mjs";
import { buttons } from "./buttons.mjs";
import { Dropdown } from "./combobox/dropdown.mjs";
import { primitives } from "./primitives.mjs";

const DEFAULT_DROPZONE_TEXT =
	"Drop file here, click to upload, or tap to choose camera/files";

/**
 * @testable infrastructure
 */
const visibility = () => {
	const group = document.createElement("fieldset");
	group.className = "flex flex-row items-center gap-4";
	group.name = "visibility";

	const options = [
		{ text: "Public", value: "public", checked: false },
		{ text: "Private", value: "private", checked: false },
	];

	options.forEach((option) => {
		group.appendChild(
			primitives.radio(
				{
					...option,
					name: "visibility",
					required: true,
				},
				{
					label: STYLES.label.row,
					radio: STYLES.radio.default,
				},
			),
		);
	});

	return group;
};

/**
 * @testable infrastructure
 */
const hiddenFileInput = (widget) => {
	const hiddenInput = document.createElement("input");
	hiddenInput.name = `${widget.inputName}`;
	hiddenInput.type = "file";
	hiddenInput.className = "hidden";
	hiddenInput.accept = "*/*";
	hiddenInput.multiple = Boolean(widget.multiple);

	return {
		element: hiddenInput,
		clear: () => {
			hiddenInput.value = "";
		},
	};
};

/**
 * @testable infrastructure
 */
const mimeType = () => {
	const mimeTypeInput = document.createElement("input");
	mimeTypeInput.type = "hidden";
	mimeTypeInput.name = "mimetype";

	return {
		element: mimeTypeInput,
		clear: () => {
			mimeTypeInput.value = "";
		},
	};
};

/**
 * @testable infrastructure
 */
const access = () => {
	const accessGroup = document.createElement("div");
	accessGroup.className = `${STYLES.upload.options} hidden`;
	accessGroup.dataset.role = "access";

	const accessHeader = accessGroup.appendChild(document.createElement("h3"));
	accessHeader.className = `${STYLES.upload.header} -mb-2`;
	accessHeader.textContent = "Access";

	const accessText = accessGroup.appendChild(document.createElement("p"));
	accessText.innerHTML =
		"Public files can be viewed by anyone on the web with the address.<br />" +
		"Private files can only be viewed by logged-in users with permission to view this page.";
	accessText.className = "sm:text-sm text-base-dark";

	accessGroup.appendChild(visibility());
	return accessGroup;
};

/**
 * @testable infrastructure
 */
const processing = ({ aiCreate = true } = {}) => {
	const optionsContainer = document.createElement("div");
	optionsContainer.dataset.role = "options";
	optionsContainer.dataset.visible = "false";
	optionsContainer.className = STYLES.upload.options;

	const optionsHeader = optionsContainer.appendChild(
		document.createElement("h3"),
	);

	optionsHeader.className = `${STYLES.upload.header} -mb-2`;
	optionsHeader.textContent = "Further Processing";

	const editName = primitives.input({
		name: "display-name",
		type: "text",
		label: "Edit File Name",
		kind: "file",
		data: {
			role: "display-name",
		},
	});
	optionsContainer.appendChild(editName);

	const extract = primitives.checkbox({
		name: "extract",
		label: "Extract text (OCR)",
		visible: false,
	});

	const searchText = primitives.checkbox({
		name: "search-text",
		label: "Add file text to search index",
		visible: false,
	});

	const summarize = primitives.checkbox({
		name: "summarize",
		label: "Summarize file content",
		visible: false,
	});

	const searchSummary = primitives.checkbox({
		name: "search-summary",
		label: "Add file summary to search index",
		visible: false,
	});

	const options = optionsContainer.appendChild(document.createElement("div"));
	options.dataset.role = "processing";
	options.className = STYLES.upload.processing;
	options.append(
		extract,
		searchText,
		...(aiCreate ? [summarize, searchSummary] : []),
	);

	/**
	 * @testable false
	 * @covered-by src/script/elements/upload.mjs::processing
	 * @reason option visibility helper is private processing-section plumbing
	 */
	const setOptionVisibility = (element, visible) => {
		element.dataset.visible = visible ? "true" : "false";
	};

	/**
	 * @testable false
	 * @covered-by src/script/elements/upload.mjs::processing
	 * @reason reset helper is private processing-section plumbing
	 */
	const resetOptionVisibility = () => {
		[extract, searchText, summarize, searchSummary].forEach((element) => {
			setOptionVisibility(element, false);
		});
	};

	/**
	 * @testable false
	 * @covered-by src/script/elements/upload.mjs::processing
	 * @reason display-name visibility is private processing-section plumbing
	 */
	const setDisplayNameVisibility = (visible) => {
		const input = editName.querySelector("input");
		editName.dataset.visible = visible ? "true" : "false";
		input.disabled = !visible;
		if (!visible) input.value = "";
	};

	/**
	 * @testable false
	 * @covered-by src/script/elements/upload.mjs::processing
	 * @reason prefill helper is private processing-section plumbing
	 */
	const prefill = ({ filename, isTextFile, fileCount = 1 }) => {
		const singleFile = fileCount <= 1;
		editName.querySelector("input").value = singleFile ? filename || "" : "";
		setDisplayNameVisibility(singleFile);
		optionsContainer.dataset.visible = "true";
		resetOptionVisibility();

		if (isTextFile) {
			setOptionVisibility(searchText, true);
			if (aiCreate) setOptionVisibility(summarize, true);
		} else {
			setOptionVisibility(extract, true);
			if (aiCreate) setOptionVisibility(summarize, true);
		}
	};

	options.addEventListener("change", (event) => {
		const { target } = event;
		if (target.name === "extract") {
			searchText.dataset.visible = target.checked ? "true" : "false";
		}
		if (target.name === "summarize") {
			searchSummary.dataset.visible = target.checked ? "true" : "false";
		}
	});

	return {
		element: optionsContainer,
		prefill: prefill,
		show: () => {
			optionsContainer.dataset.visible = "true";
		},
		hide: () => {
			optionsContainer.dataset.visible = "false";
		},
		clear: () => {
			editName.querySelector("input").value = "";
			setDisplayNameVisibility(true);
			options.querySelectorAll("input[type='checkbox']").forEach((cb) => {
				cb.checked = false;
			});
			resetOptionVisibility();
			optionsContainer.dataset.visible = "false";
		},
	};
};

/**
 * @testable infrastructure
 */
const menuButton = () => {
	const menuButtonContainer = document.createElement("div");
	menuButtonContainer.dataset.role = "upload-menu";
	menuButtonContainer.className = "absolute top-2 right-2";
	const menuButton = menuButtonContainer.appendChild(
		document.createElement("button"),
	);
	menuButton.className =
		"size-7 flex items-center justify-center rounded-md opacity-30 bg-base-default text-white";
	menuButton.type = "button";
	menuButton.replaceChildren(createIcon("dropdown"));

	return menuButtonContainer;
};

/**
 * @testable infrastructure
 */
const contextDescription = (settings = {}) => {
	const description = document.createElement("textarea");
	description.className = `${STYLES.textarea} grow h-24 placeholder:text-center`;
	description.name = settings.name || "autofill-description";
	if (settings.placeholder) description.placeholder = settings.placeholder;
	if (settings.rows) description.rows = settings.rows;
	return description;
};

/**
 * @testable infrastructure
 */
const contextUpload = (settings = {}) => {
	const container = document.createElement("div");
	container.className = "flex flex-col gap-1";

	if (settings.label !== false) {
		const header = primitives.label({
			label: settings.label || "Autofill Context",
			tag: "h3",
		});
		container.appendChild(header);
	}

	const context = container.appendChild(document.createElement("div"));
	context.dataset.role = "context";
	context.className = settings.stacked
		? "flex flex-col gap-3"
		: STYLES.upload.contextRow;

	const dropzoneElement = dropzone({ text: settings.text });
	const description = contextDescription({
		name: settings.descriptionName,
		placeholder: settings.descriptionPlaceholder,
		rows: settings.descriptionRows,
	});

	context.append(dropzoneElement.element);
	context.append(description);

	if (settings.explain !== false) {
		const explain = primitives.explain_prompt({
			explain: settings.explain || "autofill",
			visible: true,
			classes: ["mt-1"],
		});
		container.append(explain);
	}

	return {
		element: container,
		dropzone: dropzoneElement,
		description: description,
		clear: () => {
			dropzoneElement.clear();
			description.value = "";
		},
	};
};

/**
 * @testable infrastructure
 */
const dropzone = (options) => {
	const { text = DEFAULT_DROPZONE_TEXT, element = null } = options;

	let dropzone, textElement;
	if (!element) {
		dropzone = document.createElement("div");
		dropzone.dataset.role = "dropzone";
		dropzone.className = STYLES.upload.dropzone;
		textElement = dropzone.appendChild(document.createElement("p"));
		textElement.innerHTML = text || "";
	} else {
		dropzone = element;
	}

	let menu = dropzone.querySelector("[data-role='upload-menu']");
	if (!menu) {
		menu = menuButton();
		dropzone.appendChild(menu);
	}

	return {
		element: dropzone,
		menuButton: menu,
		get containsImage() {
			return dropzone.querySelector("img") !== null;
		},
		clear: () => {
			if (element) return;
			if (textElement) textElement.innerHTML = text || "";
		},
		setText: (newText) => {
			if (element) return;
			if (textElement) textElement.innerHTML = newText;
		},
		hide: () => {
			dropzone.dataset.visible = "false";
		},
		show: () => {
			dropzone.dataset.visible = "true";
		},
	};
};

/**
 * @testable infrastructure
 */
export class UploadMenu {
	constructor(instance) {
		this.instance = instance;
		this.dropdown = null;
		this.itemBuilders = {
			remove: () => this._buildRemove(),
			replace: () => this._buildReplace(),
			generate: () => this._buildGenerate(),
			paste: () => this._buildPaste(),
		};
	}

	get button() {
		return this.instance.dropzone?.menuButton ?? null;
	}

	get options() {
		return this.instance.menuOptions ?? [];
	}

	get items() {
		return this.options
			.map((option) => {
				const build = this.itemBuilders[option];
				return typeof build === "function" ? build() : null;
			})
			.filter(Boolean);
	}

	create() {
		const button = this.button;
		if (!button) return;

		const items = this.items;
		if (this.dropdown && this.dropdown.parent !== button) {
			this.dropdown.destroy();
			this.dropdown = null;
		}

		if (this.dropdown) {
			this.dropdown.updateOptions(items);
			return;
		}

		const toolbarPortalClass = button.closest?.("[data-role='toolbar']")
			? ` ${STYLES.editor.toolbar.portalIconContext}`
			: "";
		this.dropdown = new Dropdown(button).init({
			items: items,
			placement: "bottom-end",
			styles: {
				panel: `${STYLES.dropdown.panel}${toolbarPortalClass}`,
			},
		});
	}

	_buildRemove() {
		if (!this.instance.fileAttached) return null;
		return {
			name: "Remove",
			icon: "delete",
			kind: "delete",
			onClick: () => this.instance.removeFile(),
		};
	}

	_buildReplace() {
		return {
			name: "Replace",
			icon: "replace",
			kind: "default",
			onClick: () => this.instance.replaceFile(),
		};
	}

	_buildGenerate() {
		return {
			name: "Generate",
			icon: "generate",
			kind: this.instance.kind || "default",
			onClick: () => this.instance.showGenerateForm(),
		};
	}

	_buildPaste() {
		return {
			name: "Paste",
			icon: "paste",
			kind: "default",
			onClick: () => this.instance.processPaste(),
		};
	}

	destroy() {
		this.dropdown?.destroy();
		this.dropdown = null;
	}
}

/**
 * @testable infrastructure
 */
const generateDocumentImage = () => {
	const container = document.createElement("div");
	container.dataset.role = "generate-image";
	container.className = "flex flex-col gap-4";
	container.dataset.visible = "false";

	const prompt = container.appendChild(
		primitives.textarea({
			name: "prompt",
			placeholder:
				"Describe the image you wish to create (or leave blank to generate an illustration for this document's content)",
			rows: 3,
			kind: "default",
		}),
	);

	const submitGroup = container.appendChild(document.createElement("div"));
	submitGroup.dataset.role = "submit-group";
	submitGroup.className = "flex flex-wrap gap-2 w-full";

	submitGroup.appendChild(
		buttons.submit({
			role: "cancel",
			text: "Cancel",
			kind: "editor",
			type: "button",
		}),
	);

	const submitButton = submitGroup.appendChild(
		buttons.submit({
			role: "generate",
			kind: "editor",
			type: "submit",
		}),
	);

	return {
		element: container,
		submitGroup: submitGroup,
		submitButton: submitButton,
		messages: {
			submit: "Generate",
			submitting: "Thinking...",
			submitted: "Done",
		},
		icon: "generate",
		reset: () => {
			container.dataset.visible = "false";
			prompt.value = "";
		},
		visible: () => {
			return container.dataset.visible === "true";
		},
		hide: () => {
			container.dataset.visible = "false";
		},
		show: () => {
			container.dataset.visible = "true";
			prompt.focus();
		},
	};
};
export const uploadElement = {
	dropzone,
	contextDescription,
	hiddenFileInput,
	mimeType,
	access,
	processing,
	menuButton,
	contextUpload,
	generateDocumentImage,
};
