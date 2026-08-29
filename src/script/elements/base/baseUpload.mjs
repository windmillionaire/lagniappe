import { uploadElement } from "../upload";
import { BaseForm } from "./baseForm";

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
export class BaseUpload {
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
