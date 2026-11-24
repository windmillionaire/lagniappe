import { FormController } from "../../forms/controller.ts";
import { directUpload } from "../../shared/directUpload.ts";
import { uploadElement } from "../upload.ts";

const PASTE_ERROR =
	"File detected in clipboard but not accessible. Try pressing Cmd+V (Mac) or Ctrl+V (Windows/Linux) to paste instead.";
const CLIPBOARD_ERROR = "Couldn't access clipboard.";
const CLIPBOARD_PERMISSION_ERROR = "Clipboard permission denied.";
const CLIPBOARD_ACCESS_NOT_AVAILABLE_ERROR = "Clipboard access not available.";
const CLIPBOARD_NO_FILE_ERROR = "No valid file found in clipboard.";
const DROP_ERROR = (error: unknown) =>
	`Error dropping file: ${errorMessage(error)}`;
const PROCESS_NEW_FILE_ERROR = (error: unknown) =>
	`Error processing file: ${errorMessage(error)}`;
const FILE_TOO_LARGE_ERROR = (fileSizeMB: string, maxSizeMB: number) =>
	`File is too large (${fileSizeMB}MB). Maximum file size is ${maxSizeMB}MB.`;
const IMAGE_LOAD_ERROR = (error: unknown) =>
	`Failed to load image: ${errorMessage(error)}`;
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

type UploadInput = ReturnType<typeof uploadElement.hiddenFileInput>;
type UploadMenu = { create(): void; destroy(): void };
type Dropzone = {
	element: HTMLElement;
	menuButton?: HTMLElement | null;
	clear(): void;
	setText(text: string): void;
};

interface UploadAttributes {
	[key: string]: unknown;
	target?: HTMLElement;
	readonly?: boolean;
	dropzone?: Dropzone | null;
	uploadMenu?: UploadMenu | null;
	inputName?: string;
	uploadType?: string;
	multiple?: boolean;
	route?: string | null;
	endpoints?: { upload?: string | null } & Record<string, unknown>;
	maxFileSize?: number;
}

interface FileSelectionOptions {
	source?: string;
	preserveExisting?: boolean;
}

interface UploadContext {
	source: string;
	originalFile: File;
	file: File;
	filename: string;
	isTextFile: boolean;
	mimeType: string;
}

interface DirectUploadRecord {
	_fileSignature: string;
	token: string;
	input_name: string;
	filename: string;
	content_type: string;
	size: number;
	generation: string | number | undefined;
	path: string | undefined;
}

function errorMessage(error: unknown) {
	return typeof error === "object" && error !== null && "message" in error
		? error.message
		: undefined;
}

async function containsDroppedDirectory(
	dataTransfer: DataTransfer | null,
	files = Array.from(dataTransfer?.files || []),
) {
	const items = Array.from(dataTransfer?.items || []).filter(
		(item) => item.kind === "file",
	);
	for (const item of items) {
		const entry = item.webkitGetAsEntry?.();
		if (entry?.isDirectory) return true;

		if (
			!entry &&
			"getAsFileSystemHandle" in item &&
			typeof item.getAsFileSystemHandle === "function"
		) {
			try {
				const handle: unknown = await item.getAsFileSystemHandle();
				if (
					handle &&
					typeof handle === "object" &&
					"kind" in handle &&
					handle.kind === "directory"
				) {
					return true;
				}
			} catch (_error) {
				// Fall through to the file metadata check below.
			}
		}
	}

	return files.some((file) => file.size === 0 && !file.type);
}

function isLikelyImageFile(file: File) {
	if (file.type?.startsWith("image/")) return true;
	if (file.type && file.type !== "application/octet-stream") return false;
	const name = (file.name || "").toLowerCase();
	return /\.(png|jpe?g|gif|webp|bmp|svg|heic|heif|avif|ico|tiff?)$/.test(name);
}

function mimeToExtension(mimeType: string) {
	if (!mimeType) return "bin";
	const map: Record<string, string | undefined> = {
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
 */
function defaultClipboardFilename(mimeType: string) {
	return `paste-${Date.now()}.${mimeToExtension(mimeType)}`;
}

function resolvedClipboardFileName(blob: Blob, typeHint: string) {
	const mime = blob.type || typeHint;
	if ("name" in blob && typeof blob.name === "string") {
		const name = blob.name.trim();
		if (name.includes(".")) return name;
	}
	return defaultClipboardFilename(mime);
}

export class BaseUpload {
	// Standalone subclasses can supply these attributes before init().
	declare target: HTMLElement;
	declare inputName: string;
	declare readonly?: boolean;
	declare dropzone?: UploadAttributes["dropzone"];
	declare uploadMenu?: UploadAttributes["uploadMenu"];
	declare uploadType?: string;
	declare multiple?: boolean;
	declare route?: UploadAttributes["route"];
	declare endpoints?: UploadAttributes["endpoints"];
	declare maxFileSize?: number;
	uploadImage?(file: File, context: UploadContext): unknown;

	// Created by init() on the interactive upload path.
	declare form: FormController;
	declare fileInput: UploadInput;
	declare mimeType: UploadInput;
	declare fileDialogOpen?: boolean;
	declare pasteActive?: boolean;
	declare maxWidth: number;
	declare maxHeight: number;
	declare keyboardPaste: (event: ClipboardEvent) => void;
	declare windowFocus: () => void;
	declare destroyables: { destroy?(): void }[];
	declare directUploads: DirectUploadRecord[];
	declare directUploadSignature: string | null;
	declare directUploadSelectionSignature: string | null;

	constructor(attributes?: UploadAttributes) {
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
		this.form = new FormController(this);
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

		const input = this.fileInput.element;
		input.addEventListener("change", () => {
			const files = input.files;
			if (files && files.length > 0) {
				this._processNewFiles(files, {
					source: "select",
					preserveExisting: false,
				});
			}
			this.fileDialogOpen = false;
		});
	}

	_processImage(file: File) {
		return new Promise<File>((resolve, reject) => {
			const img = new Image();
			const objectUrl = URL.createObjectURL(file);

			img.onload = () => {
				URL.revokeObjectURL(objectUrl);

				const canvas = document.createElement("canvas");
				const ctx = canvas.getContext("2d");
				if (!ctx) {
					reject(new Error(IMAGE_PROCESS_ERROR));
					return;
				}

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

			img.onerror = (event) => {
				URL.revokeObjectURL(objectUrl);
				reject(new Error(IMAGE_LOAD_ERROR(errorMessage(event))));
			};

			img.src = objectUrl;
		});
	}

	get filename() {
		const file = this.fileInput.element.files?.[0];
		if (!file) return "";
		const name = file.name;
		const extensionIndex = name.lastIndexOf(".");
		return extensionIndex > 0 ? name.substring(0, extensionIndex) : name;
	}

	get textFileAttached() {
		return this.fileInput.element.files?.[0]?.type.startsWith("text/") ?? false;
	}

	get fileAttached() {
		return (this.fileInput?.element.files?.length ?? 0) > 0;
	}

	get fileLabel() {
		const files = Array.from(this.fileInput?.element.files || []);
		if (files.length === 0) return "";
		if (files.length === 1) return this.filename;
		return `${files.length} files selected`;
	}

	onFileAccepted(_file: File, _context: UploadContext) {}

	shouldAutoUpload(_file: File, _context: UploadContext) {
		return typeof this.uploadImage === "function";
	}

	async autoUpload(file: File, context: UploadContext) {
		if (typeof this.uploadImage === "function") {
			return this.uploadImage(file, context);
		}
	}

	applyDefaultAttachUI(_file: File, context: UploadContext) {
		if (this.dropzone) {
			this.dropzone.setText(context.filename);
		}
		this.form?.showSubmitButton();
	}

	onFileAttached(_file: File, _context: UploadContext) {}

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

	applyDirectUploads<T extends Pick<FormData, "delete" | "set">>(data: T): T {
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

	_canFallbackToMultipart(files: File[]) {
		return (
			files.length <= DIRECT_UPLOAD_FALLBACK_MAX_FILES &&
			files.reduce((total, file) => total + file.size, 0) <=
				DIRECT_UPLOAD_FALLBACK_LIMIT
		);
	}

	_directUploadFileSignature(file: File, index: number) {
		return [index, file.name, file.size, file.type, file.lastModified].join(
			":",
		);
	}

	_updateDirectUploadProgress(file: File, loaded: number, total: number) {
		const percent = total ? Math.round((loaded / total) * 100) : 0;
		const name = file.name || "file";
		this.dropzone?.setText(`Uploading ${name} - ${percent}%`);
	}

	async prepareSubmit({ route = null }: { route?: string | null } = {}) {
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
				: new Map<string, DirectUploadRecord>();
		const completed: DirectUploadRecord[] = [];
		let activeFile: File | null = null;
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
				const session = await directUpload.createSession({
					route: uploadRoute,
					file,
					inputName: this.inputName,
				});
				const metadata = await directUpload.upload({
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

	async _processNewFile(file: File, options: FileSelectionOptions = {}) {
		const source = options.source || "unknown";
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
		const context: UploadContext = {
			source,
			originalFile: file,
			file: processed,
			filename: this.multiple ? this.fileLabel : this.filename,
			isTextFile: this.textFileAttached,
			mimeType: file.type || "",
		};
		this.mimeType.element.value = context.mimeType;

		this.onFileAccepted(processed, context);
		if (this.shouldAutoUpload(processed, context)) {
			await this.autoUpload(processed, context);
		} else {
			this.applyDefaultAttachUI(processed, context);
		}
		this.onFileAttached(processed, context);
	}

	async _processNewFiles(
		files: Iterable<File> | ArrayLike<File> | null | undefined,
		options: FileSelectionOptions = {},
	) {
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
			if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
		});

		this.dropzone.element.addEventListener("drop", async (event) => {
			event.preventDefault();
			try {
				// DataTransfer.files is only guaranteed during the drop event. Copy it
				// before the asynchronous directory check yields to the browser.
				const files = Array.from(event.dataTransfer?.files || []);
				if (await containsDroppedDirectory(event.dataTransfer, files)) {
					this.showError(INDIVIDUAL_FILES_ONLY_ERROR);
					return;
				}
				if (files.length > 0) {
					await this._processNewFiles(files, { source: "drop" });
				}
			} catch (error) {
				this.showError(DROP_ERROR(error));
			}
		});

		this.dropzone.element.addEventListener("click", (e) => {
			const target = e.target;
			if (
				this.fileDialogOpen ||
				!target ||
				!("closest" in target) ||
				typeof target.closest !== "function" ||
				target.closest("[data-role='upload-menu']")
			) {
				return;
			}

			if (target.closest('[data-role="dropzone"]')) {
				e.preventDefault();
				e.stopPropagation();
				this.fileDialogOpen = true;
				this.fileInput.element.click();
			}
		});
	}

	async processPaste() {
		const processFile = async (item: ClipboardItem, type: string) => {
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
			const name =
				error && typeof error === "object" && "name" in error
					? error.name
					: undefined;
			if (name === "NotAllowedError") {
				this.showError(CLIPBOARD_PERMISSION_ERROR);
			} else if (name === "SecurityError") {
				this.showError(CLIPBOARD_ACCESS_NOT_AVAILABLE_ERROR);
			} else {
				this.showError(CLIPBOARD_ERROR);
			}
		}
	}

	_keyboardPaste(event: ClipboardEvent) {
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

	showError(message: string) {
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
