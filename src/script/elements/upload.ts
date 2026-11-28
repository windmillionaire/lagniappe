import { STYLES } from "../generated/styles.mjs";
import { createIcon } from "../shared/icons.ts";
import { buttons } from "./buttons.ts";
import { primitives } from "./primitives.ts";

const DEFAULT_DROPZONE_TEXT =
	"Drop file here, click to upload, or tap to choose camera/files";

interface FileInputSettings {
	inputName: string;
	multiple?: boolean;
}

interface ProcessingSettings {
	aiCreate?: boolean;
}

interface ProcessingSelection {
	filename?: string;
	isTextFile: boolean;
	fileCount?: number;
}

interface ContextDescriptionSettings {
	name?: string;
	placeholder?: string;
	rows?: number;
}

interface ContextUploadSettings {
	label?: string | false;
	stacked?: boolean;
	text?: string;
	descriptionName?: string;
	descriptionPlaceholder?: string;
	descriptionRows?: number;
}

interface DropzoneOptions {
	text?: string | null;
	element?: HTMLElement | null;
}

interface UploadMenuHost {
	dropzone?: { menuButton?: HTMLElement | null } | null;
	menuOptions?: readonly string[];
	fileAttached: boolean;
	kind?: string | null;
	removeFile(): void;
	replaceFile(): void;
	showGenerateForm?(): unknown;
	processPaste(): unknown;
}

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
			primitives.radio({
				...option,
				name: "visibility",
				required: true,
			}),
		);
	});

	return group;
};

const hiddenFileInput = (widget: FileInputSettings) => {
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

const processing = ({ aiCreate = true }: ProcessingSettings = {}) => {
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

	const setOptionVisibility = (element: HTMLElement, visible: boolean) => {
		element.dataset.visible = visible ? "true" : "false";
	};

	const resetOptionVisibility = () => {
		[extract, searchText, summarize, searchSummary].forEach((element) => {
			setOptionVisibility(element, false);
		});
	};

	const setDisplayNameVisibility = (visible: boolean) => {
		const input = editName.querySelector("input");
		editName.dataset.visible = visible ? "true" : "false";
		if (input) {
			input.disabled = !visible;
			if (!visible) input.value = "";
		}
	};

	const prefill = ({
		filename,
		isTextFile,
		fileCount = 1,
	}: ProcessingSelection) => {
		const singleFile = fileCount <= 1;
		const input = editName.querySelector("input");
		if (input) input.value = singleFile ? filename || "" : "";
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
		if (!(target instanceof HTMLInputElement)) return;
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
			const input = editName.querySelector("input");
			if (input) input.value = "";
			setDisplayNameVisibility(true);
			options
				.querySelectorAll<HTMLInputElement>("input[type='checkbox']")
				.forEach((cb) => {
					cb.checked = false;
				});
			resetOptionVisibility();
			optionsContainer.dataset.visible = "false";
		},
	};
};

const menuButton = (overlay = false) => {
	const menuContainer = document.createElement("div");
	menuContainer.dataset.role = "upload-menu";
	menuContainer.className = overlay
		? "absolute top-2 right-2 z-10 not-italic flex flex-wrap items-center justify-end gap-1.5 empty:hidden"
		: "not-italic flex flex-wrap items-center justify-center gap-1.5 empty:hidden";
	return menuContainer;
};

const contextDescription = (settings: ContextDescriptionSettings = {}) => {
	const description = document.createElement("textarea");
	description.className = `${STYLES.textarea} grow h-24`;
	description.name = settings.name || "autofill-description";
	if (settings.placeholder) description.placeholder = settings.placeholder;
	if (settings.rows) description.rows = settings.rows;
	return description;
};

const contextUpload = (settings: ContextUploadSettings = {}) => {
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

const dropzone = (options: DropzoneOptions) => {
	const { text = DEFAULT_DROPZONE_TEXT, element = null } = options;

	let dropzone: HTMLElement;
	let textElement: HTMLParagraphElement | undefined;
	if (!element) {
		dropzone = document.createElement("div");
		dropzone.dataset.role = "dropzone";
		dropzone.className = STYLES.upload.dropzone;
		textElement = dropzone.appendChild(document.createElement("p"));
		textElement.innerHTML = text || "";
	} else {
		dropzone = element;
	}

	let menu = dropzone.querySelector<HTMLElement>("[data-role='upload-menu']");
	if (!menu) {
		menu = menuButton(Boolean(element));
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
		setText: (newText: string) => {
			if (element) return;
			if (textElement) textElement.textContent = newText;
		},
		setContent: (...children: (Node | string)[]) => {
			textElement?.replaceChildren(...children);
		},
		hide: () => {
			dropzone.dataset.visible = "false";
		},
		show: () => {
			dropzone.dataset.visible = "true";
		},
	};
};

interface UploadActionItem {
	option: string;
	name: string;
	icon: string;
	kind: string;
	onClick: () => unknown;
}

export class UploadMenu {
	declare instance: UploadMenuHost;
	declare itemBuilders: Partial<Record<string, () => UploadActionItem | null>>;

	constructor(instance: UploadMenuHost) {
		this.instance = instance;
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
			.filter((item): item is UploadActionItem => item !== null);
	}

	create() {
		const container = this.button;
		if (!container) return;

		const chips = this.items.map((item) => {
			const chip = document.createElement("button");
			chip.type = "button";
			chip.className = STYLES.upload.chip;
			chip.dataset.kind = item.kind;
			chip.dataset.uploadAction = item.option;
			chip.append(createIcon(item.icon, "icon-xs text-kind-default"));
			const label = document.createElement("span");
			label.textContent = item.name;
			chip.append(label);
			chip.addEventListener("click", (e) => {
				e.preventDefault();
				e.stopPropagation();
				item.onClick();
			});
			return chip;
		});

		container.replaceChildren(...chips);
	}

	_buildRemove(): UploadActionItem | null {
		if (!this.instance.fileAttached) return null;
		return {
			option: "remove",
			name: "Remove",
			icon: "delete",
			kind: "delete",
			onClick: () => this.instance.removeFile(),
		};
	}

	_buildReplace(): UploadActionItem | null {
		if (!this.instance.fileAttached) return null;
		return {
			option: "replace",
			name: "Replace",
			icon: "replace",
			kind: "default",
			onClick: () => this.instance.replaceFile(),
		};
	}

	_buildGenerate(): UploadActionItem {
		return {
			option: "generate",
			name: "Generate",
			icon: "generate",
			kind: this.instance.kind || "default",
			onClick: () => this.instance.showGenerateForm?.(),
		};
	}

	_buildPaste(): UploadActionItem {
		return {
			option: "paste",
			name: "Paste",
			icon: "paste",
			kind: "default",
			onClick: () => this.instance.processPaste(),
		};
	}

	destroy() {
		this.button?.replaceChildren();
	}
}

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
