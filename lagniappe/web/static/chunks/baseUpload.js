/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bb55a6e4';
import { r as request } from './foundation.js?v=bb55a6e4';
import './connectivity.js?v=bb55a6e4';
import { c as createIcon } from './icons.js?v=bb55a6e4';
import { b as buttons } from './buttons.js?v=bb55a6e4';
import { Dropdown } from './dropdown.js?v=bb55a6e4';
import { p as primitives } from './primitives.js?v=bb55a6e4';
import { B as BaseForm } from './baseForm.js?v=bb55a6e4';

const DEFAULT_DROPZONE_TEXT =
	"Drop file here, click to upload, or tap to choose camera/files";
const DEFAULT_DIRECT_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024;
const DEFAULT_DIRECT_UPLOAD_RETRIES = 3;
const DEFAULT_DIRECT_UPLOAD_RETRY_DELAY_MS = 500;
const RESUMABLE_UPLOAD_INCOMPLETE = 308;
const RETRYABLE_DIRECT_UPLOAD_STATUSES = new Set([
	408, 429, 500, 502, 503, 504,
]);

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
const selectFile = () => {
	const section = document.createElement("div");
	section.dataset.role = "select-file";
	section.setAttribute("lp-select", "");
	const input = primitives.input({
		label: "Link to an existing file",
		name: "existing-file",
		kind: "file",
		data: {
			index: "file",
			placeholder: "search files...",
		},
	});
	section.appendChild(input);

	return {
		element: section,
		input: input,
		clear: () => {
			input.value = "";
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
 * @testable false
 * @covered-by src/script/elements/base/baseUpload.mjs::BaseUpload.prepareSubmit
 * @reason direct-upload route derivation is exercised through the base upload hook
 */
const directUploadRoute = (route) => {
	if (!route) return null;

	const url = new URL(route, window.location.origin);
	url.pathname = `${url.pathname.replace(/\/$/, "")}/direct-upload`;
	return `${url.pathname}${url.search}`;
};

/**
 * @testable false
 * @covered-by src/script/elements/base/baseUpload.mjs::BaseUpload.prepareSubmit
 * @reason session creation uses the shared request envelope and server auth
 */
const createDirectUploadSession = async ({ route, file, inputName }) => {
	const response = await request.post(directUploadRoute(route), {
		filename: file.name,
		content_type: file.type || "application/octet-stream",
		size: file.size,
		input_name: inputName,
	});
	if (!response?.ok) {
		throw new Error(response?.error || "Could not start direct upload");
	}
	return response;
};

/**
 * @testable false
 * @covered-by src/script/elements/upload.mjs::uploadDirectFile
 * @reason small timing helper is exercised through the retry contract
 */
const directUploadRetryDelay = (attempt, baseDelay) =>
	baseDelay * 2 ** Math.max(0, attempt - 1);

/**
 * @testable false
 * @covered-by src/script/elements/upload.mjs::uploadDirectFile
 * @reason sleep wrapper lets retry tests use a zero delay
 */
const wait = (delayMs) =>
	delayMs > 0
		? new Promise((resolve) => setTimeout(resolve, delayMs))
		: Promise.resolve();

/**
 * @testable false
 * @covered-by src/script/elements/upload.mjs::uploadDirectFile
 * @reason GCS resumable uploads report persisted bytes through Range headers
 */
const directUploadOffset = (response) => {
	const range = response.headers.get("Range") || "";
	const match = /^bytes=0-(\d+)$/i.exec(range.trim());
	return match ? Number.parseInt(match[1], 10) + 1 : 0;
};

/**
 * @testable false
 * @covered-by src/script/elements/upload.mjs::uploadDirectFile
 * @reason resumable upload status probing is part of retry recovery
 */
const directUploadStatusOffset = async ({ file, sessionUrl }) => {
	const response = await fetch(sessionUrl, {
		method: "PUT",
		headers: {
			"Content-Range": `bytes */${file.size}`,
		},
	});

	if (response.status === RESUMABLE_UPLOAD_INCOMPLETE) {
		return directUploadOffset(response);
	}

	if (response.ok) return file.size;

	const message = await response.text().catch(() => "");
	throw new Error(message || "Could not resume direct upload");
};

/**
 * @testable false
 * @covered-by src/script/elements/upload.mjs::uploadDirectFile
 * @reason retryability rules are shared by thrown fetch failures and storage 5xxs
 */
const shouldRetryDirectUpload = (response) =>
	RETRYABLE_DIRECT_UPLOAD_STATUSES.has(response.status);

/**
 * @testable false
 * @covered-by src/script/elements/upload.mjs::uploadDirectFile
 * @reason recovery needs to sync the browser offset with the storage session
 */
const resumeDirectUpload = async ({
	file,
	sessionUrl,
	attempt,
	retries,
	retryDelay,
	onProgress,
}) => {
	let statusAttempt = attempt;
	let lastError = null;

	while (statusAttempt <= retries) {
		await wait(directUploadRetryDelay(statusAttempt, retryDelay));
		try {
			const offset = await directUploadStatusOffset({ file, sessionUrl });
			onProgress(offset, file.size);
			return { attempt: statusAttempt, offset };
		} catch (error) {
			lastError = error;
			if (statusAttempt >= retries) break;
			statusAttempt += 1;
		}
	}

	throw lastError || new Error("Could not resume direct upload");
};

/**
 * @testable false
 * @covered-by src/script/elements/base/baseUpload.mjs::BaseUpload.prepareSubmit
 * @reason browser-to-GCS chunk PUT is provider I/O; wrapper owns retry contract
 */
const directUploadChunk = ({ file, sessionUrl, offset, end }) =>
	fetch(sessionUrl, {
		method: "PUT",
		headers: {
			"Content-Type": file.type || "application/octet-stream",
			"Content-Range": `bytes ${offset}-${end}/${file.size}`,
		},
		body: file.slice(offset, end + 1),
	});

/**
 * @testable true
 * @tests tests_js/test_014_direct_upload_retry.py::test_direct_upload_resumes_after_network_reset
 * @matrix direct-upload : resumable-range retry
 */
const uploadDirectFile = async ({
	file,
	sessionUrl,
	chunkSize = DEFAULT_DIRECT_UPLOAD_CHUNK_SIZE,
	retries = DEFAULT_DIRECT_UPLOAD_RETRIES,
	retryDelay = DEFAULT_DIRECT_UPLOAD_RETRY_DELAY_MS,
	onProgress = () => {},
}) => {
	if (!file.size) return {};

	let offset = 0;
	let retryAttempt = 0;
	while (offset < file.size) {
		const end = Math.min(offset + chunkSize, file.size) - 1;
		let response;

		try {
			response = await directUploadChunk({ file, sessionUrl, offset, end });
		} catch (error) {
			if (retryAttempt >= retries) throw error;
			retryAttempt += 1;
			const resume = await resumeDirectUpload({
				file,
				sessionUrl,
				attempt: retryAttempt,
				retries,
				retryDelay,
				onProgress,
			});
			retryAttempt = resume.attempt;
			offset = resume.offset;
			continue;
		}

		if (shouldRetryDirectUpload(response)) {
			if (retryAttempt >= retries) {
				const message = await response.text().catch(() => "");
				throw new Error(message || "Direct upload failed");
			}
			retryAttempt += 1;
			const resume = await resumeDirectUpload({
				file,
				sessionUrl,
				attempt: retryAttempt,
				retries,
				retryDelay,
				onProgress,
			});
			retryAttempt = resume.attempt;
			offset = resume.offset;
			continue;
		}

		if (response.status === RESUMABLE_UPLOAD_INCOMPLETE) {
			const nextOffset = directUploadOffset(response);
			if (nextOffset <= offset) {
				throw new Error("Direct upload did not advance");
			}
			offset = nextOffset;
			retryAttempt = 0;
			onProgress(offset, file.size);
			continue;
		}

		if (!response.ok) {
			const message = await response.text().catch(() => "");
			throw new Error(message || "Direct upload failed");
		}

		retryAttempt = 0;
		onProgress(file.size, file.size);
		const contentType = response.headers.get("content-type") || "";
		if (contentType.includes("application/json")) {
			return (await response.json()) || {};
		}
		return {};
	}

	return {};
};

const directUpload = {
	route: directUploadRoute,
	createSession: createDirectUploadSession,
	upload: uploadDirectFile,
};

/**
 * @testable infrastructure
 */
class UploadMenu {
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
const uploadElement = {
	dropzone,
	directUpload,
	contextDescription,
	hiddenFileInput,
	mimeType,
	access,
	processing,
	selectFile,
	menuButton,
	contextUpload,
	generateDocumentImage,
};

const PASTE_ERROR =
	"File detected in clipboard but not accessible. Try pressing Cmd+V (Mac) or Ctrl+V (Windows/Linux) to paste instead.";
const CLIPBOARD_ERROR = "Couldn't access clipboard.";
const CLIPBOARD_PERMISSION_ERROR = "Clipboard permission denied.";
const CLIPBOARD_ACCESS_NOT_AVAILABLE_ERROR = "Clipboard access not available.";
const CLIPBOARD_NO_FILE_ERROR = "No valid file found in clipboard.";
/**
 * @testable false
 * @covered-by src/script/elements/base/baseUpload.mjs::BaseUpload._processNewFile
 * @reason drop error message factory for the upload processing path
 */
const DROP_ERROR = (error) => `Error dropping file: ${error.message}`;
/**
 * @testable false
 * @covered-by src/script/elements/base/baseUpload.mjs::BaseUpload._processNewFile
 * @reason processing error message factory for the upload processing path
 */
const PROCESS_NEW_FILE_ERROR = (error) =>
	`Error processing file: ${error.message}`;
/**
 * @testable false
 * @covered-by src/script/elements/base/baseUpload.mjs::BaseUpload._processNewFile
 * @reason size error message factory for the upload processing path
 */
const FILE_TOO_LARGE_ERROR = (fileSizeMB, maxSizeMB) =>
	`File is too large (${fileSizeMB}MB). Maximum file size is ${maxSizeMB}MB.`;
/**
 * @testable false
 * @covered-by src/script/elements/base/baseUpload.mjs::BaseUpload._processImage
 * @reason image load error message factory for image processing
 */
const IMAGE_LOAD_ERROR = (error) => `Failed to load image: ${error.message}`;
const IMAGE_PROCESS_ERROR = `Failed to process image`;
const NOT_IMAGE_ERROR =
	"This upload only accepts images. Choose an image file (for example PNG, JPEG, or WebP).";
const DIRECT_UPLOAD_FALLBACK_LIMIT = 30 * 1024 * 1024;
const DIRECT_UPLOAD_FALLBACK_MAX_FILES = 5;
const DEFAULT_FILE_UPLOAD_LIMIT = 2 * 1024 * 1024 * 1024;
const DEFAULT_IMAGE_UPLOAD_LIMIT = 100 * 1024 * 1024;
const DIRECT_UPLOAD_REQUIRED_ERROR =
	"This file is too large for the compatibility upload path. Please try again.";
const INDIVIDUAL_FILES_ONLY_ERROR = "Only individual files are supported";

/**
 * @testable true
 * @tests tests_js/test_014_direct_upload_retry.py::test_directory_drop_is_rejected_before_file_processing
 * @matrix upload : directory-rejection drag-drop
 */
async function containsDroppedDirectory(dataTransfer) {
	const items = Array.from(dataTransfer?.items || []).filter(
		(item) => item.kind === "file",
	);
	for (const item of items) {
		const entry = item.webkitGetAsEntry?.();
		if (entry?.isDirectory) return true;

		if (!entry && typeof item.getAsFileSystemHandle === "function") {
			try {
				const handle = await item.getAsFileSystemHandle();
				if (handle?.kind === "directory") return true;
			} catch (_error) {
				// Fall through to the file metadata check below.
			}
		}
	}

	return Array.from(dataTransfer?.files || []).some(
		(file) => file.size === 0 && !file.type,
	);
}

/**
 * @testable false
 * @covered-by src/script/elements/base/baseUpload.mjs::BaseUpload._processNewFile
 * @reason image-file predicate is part of the upload validation contract
 */
function isLikelyImageFile(file) {
	if (file.type?.startsWith("image/")) return true;
	if (file.type && file.type !== "application/octet-stream") return false;
	const name = (file.name || "").toLowerCase();
	return /\.(png|jpe?g|gif|webp|bmp|svg|heic|heif|avif|ico|tiff?)$/.test(name);
}

/**
 * @testable false
 * @covered-by src/script/elements/base/baseUpload.mjs::defaultClipboardFilename
 * @reason extension normalization exists to build clipboard fallback filenames
 */
function mimeToExtension(mimeType) {
	if (!mimeType) return "bin";
	const map = {
		"image/png": "png",
		"image/jpeg": "jpg",
		"image/jpg": "jpg",
		"image/webp": "webp",
		"image/gif": "gif",
		"text/plain": "txt",
	};
	if (map[mimeType]) return map[mimeType];
	const [, sub] = mimeType.split("/");
	if (!sub) return "bin";
	const base = sub.split("+")[0];
	return base.replace(/[^a-z0-9]/gi, "") || "bin";
}

/**
 * Clipboard blobs often have no name; File.name must include an extension for
 * BaseUpload#filename.
 *
 * @testable false
 * @covered-by src/script/elements/base/baseUpload.mjs::BaseUpload.processPaste
 * @reason clipboard filename fallback is exercised through the paste path
 */
function defaultClipboardFilename(mimeType) {
	return `paste-${Date.now()}.${mimeToExtension(mimeType)}`;
}

/**
 * @testable false
 * @covered-by src/script/elements/base/baseUpload.mjs::BaseUpload.processPaste
 * @reason clipboard blob filename selection is part of paste processing
 */
function resolvedClipboardFileName(blob, typeHint) {
	const mime = blob.type || typeHint;
	const fromBlob =
		typeof blob.name === "string" && blob.name.trim().includes(".");
	return fromBlob ? blob.name.trim() : defaultClipboardFilename(mime);
}

/**
 * @testable infrastructure
 */
class BaseUpload {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.maxWidth = 1280;
		this.maxHeight = 720;
		this.destroyables = [];
		this.keyboardPaste = this._keyboardPaste.bind(this);
		this.windowFocus = this._windowFocus.bind(this);
		this.directUploads = [];
		this.directUploadSignature = null;
		this.directUploadSelectionSignature = null;
	}

	async init() {
		this.form = new BaseForm(this);
		await this.form.init();

		if (this.readonly) {
			this.dropzone?.menuButton?.remove();
			return;
		}

		this._initDropZone();
		this._initFileInput();
		if (this.uploadMenu) this.uploadMenu.create();

		window.addEventListener("focus", this.windowFocus);
		window.addEventListener("paste", this.keyboardPaste);
	}

	get formData() {
		const data =
			this.target instanceof HTMLFormElement
				? new FormData(this.target)
				: new FormData();
		return this.applyDirectUploads(data);
	}

	_windowFocus() {
		this.fileDialogOpen = false;
	}

	_initFileInput() {
		if (this.fileInput) return;

		this.fileInput = uploadElement.hiddenFileInput(this);
		this.form.target.appendChild(this.fileInput.element);
		this.mimeType = uploadElement.mimeType();
		this.form.target.appendChild(this.mimeType.element);

		this.fileInput.element.addEventListener("change", (event) => {
			const files = event.target.files;
			if (files && files.length > 0) {
				this._processNewFiles(files, {
					source: "select",
					preserveExisting: false,
				});
			}
			this.fileDialogOpen = false;
		});
	}

	/**
	 * @testable true
	 * @tests tests_e2e/004_projects/test_004e_document_forms.py::test_add_image
	 * @matrix editor : image-selection image-upload
	 */
	_processImage(file) {
		return new Promise((resolve, reject) => {
			const img = new Image();
			const objectUrl = URL.createObjectURL(file);

			img.onload = () => {
				URL.revokeObjectURL(objectUrl);

				const canvas = document.createElement("canvas");
				const ctx = canvas.getContext("2d");

				const scale = Math.min(
					this.maxWidth / img.width,
					this.maxHeight / img.height,
					1,
				);

				const width = Math.round(img.width * scale);
				const height = Math.round(img.height * scale);

				canvas.width = width;
				canvas.height = height;

				ctx.fillStyle = "#FFFFFF";
				ctx.fillRect(0, 0, width, height);

				ctx.drawImage(img, 0, 0, width, height);

				canvas.toBlob(
					(blob) => {
						if (!blob) {
							reject(new Error(IMAGE_PROCESS_ERROR));
							return;
						}
						resolve(
							new File([blob], file.name, {
								type: file.type,
								lastModified: Date.now(),
							}),
						);
					},
					file.type,
					0.92,
				);
			};

			img.onerror = (e) => {
				URL.revokeObjectURL(objectUrl);
				reject(new Error(IMAGE_LOAD_ERROR(e.message)));
			};

			img.src = objectUrl;
		});
	}

	get filename() {
		if (!this.fileInput.element.files.length) return "";
		const name = this.fileInput.element.files[0].name;
		const extensionIndex = name.lastIndexOf(".");
		return extensionIndex > 0 ? name.substring(0, extensionIndex) : name;
	}

	get textFileAttached() {
		return (
			this.fileInput.element.files.length > 0 &&
			this.fileInput.element.files[0].type.startsWith("text/")
		);
	}

	get fileAttached() {
		return this.fileInput?.element.files.length > 0;
	}

	get fileLabel() {
		const files = Array.from(this.fileInput?.element.files || []);
		if (files.length === 0) return "";
		if (files.length === 1) return this.filename;
		return `${files.length} files selected`;
	}

	onFileAccepted() {}

	shouldAutoUpload() {
		return typeof this.uploadImage === "function";
	}

	async autoUpload(file, context) {
		if (typeof this.uploadImage === "function") {
			return this.uploadImage(file, context);
		}
	}

	applyDefaultAttachUI(_file, context) {
		if (this.dropzone) {
			this.dropzone.setText(context.filename);
		}
		this.form?.showSubmitButton();
	}

	onFileAttached() {}

	get directUploadRoute() {
		return this.route || this.target?.dataset?.route || this.endpoints?.upload;
	}

	get uploadLimit() {
		if (this.maxFileSize) return this.maxFileSize;
		return this.uploadType === "image"
			? DEFAULT_IMAGE_UPLOAD_LIMIT
			: DEFAULT_FILE_UPLOAD_LIMIT;
	}

	get uploadLimitLabel() {
		return Math.round(this.uploadLimit / (1024 * 1024));
	}

	currentFileSignature() {
		return Array.from(this.fileInput?.element?.files || [])
			.map((file) =>
				[file.name, file.size, file.type, file.lastModified].join(":"),
			)
			.join("|");
	}

	applyDirectUploads(data) {
		if (!this.directUploads?.length) return data;

		data.delete(this.inputName);
		data.set(
			"direct_uploads",
			JSON.stringify(
				this.directUploads.map(({ _fileSignature, ...record }) => record),
			),
		);
		return data;
	}

	_canFallbackToMultipart(files) {
		return (
			files.length <= DIRECT_UPLOAD_FALLBACK_MAX_FILES &&
			files.reduce((total, file) => total + file.size, 0) <=
				DIRECT_UPLOAD_FALLBACK_LIMIT
		);
	}

	_directUploadFileSignature(file, index) {
		return [index, file.name, file.size, file.type, file.lastModified].join(
			":",
		);
	}

	_updateDirectUploadProgress(file, loaded, total) {
		const percent = total ? Math.round((loaded / total) * 100) : 0;
		const name = file.name || "file";
		this.dropzone?.setText(`Uploading ${name} - ${percent}%`);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_014_direct_upload_retry.py::test_single_file_keeps_compatibility_multipart_fallback
	 * @tests tests_js/test_014_direct_upload_retry.py::test_large_multi_file_retry_preserves_completed_direct_uploads
	 * @matrix direct-upload : aggregate-limit compatibility multipart-fallback partial-resume single-file
	 */
	async prepareSubmit({ route = null } = {}) {
		const files = Array.from(this.fileInput?.element?.files || []);
		if (!files.length) {
			this.directUploads = [];
			this.directUploadSignature = null;
			this.directUploadSelectionSignature = null;
			return true;
		}

		const signature = this.currentFileSignature();
		if (this.directUploadSignature === signature && this.directUploads.length) {
			return true;
		}

		const uploadRoute = route || this.directUploadRoute;
		if (!uploadRoute) {
			if (this._canFallbackToMultipart(files)) return true;
			this.showError(DIRECT_UPLOAD_REQUIRED_ERROR);
			return false;
		}

		const reusable =
			this.directUploadSelectionSignature === signature
				? new Map(
						this.directUploads.map((record) => [record._fileSignature, record]),
					)
				: new Map();
		const completed = [];
		let activeFile = null;
		try {
			for (const [index, file] of files.entries()) {
				if (!file.size) continue;
				activeFile = file;
				const fileSignature = this._directUploadFileSignature(file, index);
				const existing = reusable.get(fileSignature);
				if (existing) {
					completed.push(existing);
					continue;
				}
				const session = await uploadElement.directUpload.createSession({
					route: uploadRoute,
					file,
					inputName: this.inputName,
				});
				const metadata = await uploadElement.directUpload.upload({
					file,
					sessionUrl: session.session_url,
					chunkSize: session.chunk_size,
					onProgress: (loaded, total) => {
						this._updateDirectUploadProgress(file, loaded, total);
					},
				});
				completed.push({
					_fileSignature: fileSignature,
					token: session.token,
					input_name: this.inputName,
					filename: file.name,
					content_type: file.type || "application/octet-stream",
					size: file.size,
					generation: metadata.generation,
					path: metadata.name,
				});
			}
		} catch {
			this.directUploads = completed;
			this.directUploadSignature = null;
			this.directUploadSelectionSignature = signature;
			if (this._canFallbackToMultipart(files)) {
				this.directUploads = [];
				this.directUploadSelectionSignature = null;
				return true;
			}
			const filename = activeFile?.name || "one of the selected files";
			this.showError(
				`Could not upload ${filename}. Try again; completed uploads will be kept.`,
			);
			return false;
		}

		this.directUploads = completed;
		this.directUploadSignature = signature;
		this.directUploadSelectionSignature = signature;
		return true;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_file_input
	 * @tests tests_e2e/002_home/test_002g_home_import.py::test_import_csv_via_drag_drop
	 * @matrix ingress : drag-drop file-input upload-counts
	 */
	async _processNewFile(file, options = {}) {
		const context = { source: options.source || "unknown" };
		const maxFileSize = this.uploadLimit;
		if (file.size > maxFileSize) {
			const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
			this.showError(FILE_TOO_LARGE_ERROR(fileSizeMB, this.uploadLimitLabel));
			return;
		}
		if (this.uploadType === "image" && !isLikelyImageFile(file)) {
			this.showError(NOT_IMAGE_ERROR);
			this.fileInput?.clear();
			return;
		}
		let processed = file;
		if (this.uploadType === "image") {
			try {
				processed = await this._processImage(file);
			} catch (error) {
				this.showError(PROCESS_NEW_FILE_ERROR(error));
				return;
			}
		}

		const dataTransfer = new DataTransfer();
		if (this.multiple && options.preserveExisting !== false) {
			Array.from(this.fileInput.element.files || []).forEach((existing) => {
				dataTransfer.items.add(existing);
			});
		}
		dataTransfer.items.add(processed);
		this.fileInput.element.files = dataTransfer.files;
		this.directUploads = [];
		this.directUploadSignature = null;
		this.directUploadSelectionSignature = null;
		this.uploadMenu?.create();

		this.hideError();
		context.originalFile = file;
		context.file = processed;
		context.filename = this.multiple ? this.fileLabel : this.filename;
		context.isTextFile = this.textFileAttached;
		context.mimeType = file.type || "";
		this.mimeType.element.value = context.mimeType;

		this.onFileAccepted(processed, context);
		if (this.shouldAutoUpload(processed, context)) {
			await this.autoUpload(processed, context);
		} else {
			this.applyDefaultAttachUI(processed, context);
		}
		this.onFileAttached(processed, context);
	}

	async _processNewFiles(files, options = {}) {
		const selected = Array.from(files || []);
		if (!this.multiple) {
			if (selected[0]) await this._processNewFile(selected[0], options);
			return;
		}

		let preserveExisting = options.preserveExisting;
		for (const file of selected) {
			await this._processNewFile(file, {
				...options,
				preserveExisting: preserveExisting,
			});
			if (preserveExisting === false) preserveExisting = true;
		}
	}

	_initDropZone() {
		if (!this.dropzone) return;

		this.dropzone.element.addEventListener("dragover", (event) => {
			event.preventDefault();
			event.dataTransfer.dropEffect = "copy";
		});

		this.dropzone.element.addEventListener("drop", async (event) => {
			event.preventDefault();
			try {
				if (await containsDroppedDirectory(event.dataTransfer)) {
					this.showError(INDIVIDUAL_FILES_ONLY_ERROR);
					return;
				}
				const files = event.dataTransfer.files;
				if (files && files.length > 0) {
					await this._processNewFiles(files, { source: "drop" });
				}
			} catch (error) {
				this.showError(DROP_ERROR(error));
			}
		});

		this.dropzone.element.addEventListener("click", (e) => {
			if (
				this.fileDialogOpen ||
				e.target.closest("[data-role='upload-menu']")
			) {
				return;
			}

			if (e.target.closest('[data-role="dropzone"]')) {
				e.preventDefault();
				e.stopPropagation();
				this.fileDialogOpen = true;
				this.fileInput.element.click();
			}
		});
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005f_page_image.py::test_paste_image_on_page
	 * @pair pages:image-paste
	 */
	async processPaste() {
		const processFile = async (item, type) => {
			const blob = await item.getType(type);
			const fileName = resolvedClipboardFileName(blob, type);
			const file = new File([blob], fileName, { type: blob.type || type });
			await this._processNewFile(file, { source: "paste" });
		};

		try {
			const clipboardItems = await navigator.clipboard.read();
			if (clipboardItems.length > 0) {
				const imageTypes = ["image/png", "image/jpeg", "image/webp"];
				const item = clipboardItems[0];

				for (const type of imageTypes) {
					if (item.types.includes(type)) {
						await processFile(item, type);
						return;
					}
				}
				if (item.types && item.types.length > 0) {
					const type = item.types[0];
					await processFile(item, type);
				} else {
					this.showError(PASTE_ERROR);
				}
				this.pasteActive = true;
				setTimeout(() => {
					this.pasteActive = false;
				}, 3000);
			} else {
				this.showError(CLIPBOARD_NO_FILE_ERROR);
			}
		} catch (error) {
			if (error.name === "NotAllowedError") {
				this.showError(CLIPBOARD_PERMISSION_ERROR);
			} else if (error.name === "SecurityError") {
				this.showError(CLIPBOARD_ACCESS_NOT_AVAILABLE_ERROR);
			} else {
				this.showError(CLIPBOARD_ERROR);
			}
		}
	}

	_keyboardPaste(event) {
		if (!this.pasteActive) return;

		event.preventDefault();

		if (!event.clipboardData?.files?.length) {
			this.showError(CLIPBOARD_NO_FILE_ERROR);
			this.pasteActive = false;
			return;
		}

		const file = event.clipboardData.files[0];
		if (file) {
			const mime = file.type || "application/octet-stream";
			const nameOk =
				typeof file.name === "string" &&
				file.name.trim() &&
				file.name.includes(".");
			const toProcess = nameOk
				? file
				: new File([file], defaultClipboardFilename(mime), {
						type: file.type,
						lastModified: file.lastModified,
					});
			this._processNewFile(toProcess, { source: "keyboard-paste" });
		} else {
			this.showError(CLIPBOARD_NO_FILE_ERROR);
		}
		this.pasteActive = false;
	}

	replaceFile() {
		this.fileDialogOpen = true;
		this.fileInput.element.click();
	}

	reset() {
		this.directUploads = [];
		this.directUploadSignature = null;
		this.directUploadSelectionSignature = null;
		this.fileInput?.clear();
		this.mimeType?.clear();
		this.dropzone?.clear();
		this.form?.resetSubmitButton();
		this.form?.hideSubmitButton();
	}

	removeFile() {
		this.reset();
	}

	hideError() {
		this.form.hideError();
	}

	showError(message) {
		this.form.showError(message);
	}

	destroy() {
		this.uploadMenu?.destroy();
		this.form?.destroy();
		window.removeEventListener("focus", this.windowFocus);
		window.removeEventListener("paste", this.keyboardPaste);
		this.destroyables.forEach((destroyable) => {
			if (destroyable.destroy) destroyable.destroy();
		});
		this.destroyables = [];
	}
}

export { BaseUpload as B, UploadMenu as U, uploadElement as u };
