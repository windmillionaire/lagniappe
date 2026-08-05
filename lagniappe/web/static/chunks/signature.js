/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bb7cd952';
import { d as debounce, h as areEqual } from './foundation.js?v=bb7cd952';
import './connectivity.js?v=bb7cd952';
import { s as setIcon } from './icons.js?v=bb7cd952';
import { B as BaseElement } from './baseElement.js?v=bb7cd952';
import { p as primitives } from './primitives.js?v=bb7cd952';
import './notificationState.js?v=bb7cd952';

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_signature_submission_draw_save_reload_and_clear
 * @features signature
 * @dimensions file-input asset-lifecycle form-value editable readonly reload clear
 */
class SignatureElement extends BaseElement {
	get value() {
		return this.signatureInput?.value ?? null;
	}

	changed(value) {
		if (areEqual(this.value, value)) return false;
		return true;
	}

	get read() {
		if (this._read) return this._read;

		this._read = document.createElement("div");
		this._read.className = STYLES.signature.pad;

		const signature = this._read.appendChild(document.createElement("img"));
		signature.src = this.submission;
		signature.alt = "Signature";

		if (this.submission && this.signatureInput) {
			this.signatureInput.value = this.schema.id;
		}

		this._read.classList.add("group-data-[mode=edit]/element:hidden");

		return this._read;
	}

	get edit() {
		if (this._edit) return this._edit;

		this._edit = document.createElement("div");
		this._edit.className = "flex flex-col gap-2";
		if (this.label) {
			const label = primitives.label({
				label: this.label,
				tag: "h3",
			});
			this._edit.appendChild(label);
		}

		this.signatureInput = this._edit.appendChild(
			primitives.input({
				name: this.schema.id,
				type: "hidden",
			}),
		);
		if (this.submission) {
			this.signatureInput.value = this.schema.id;
		}

		const signatureContainer = this._edit.appendChild(
			document.createElement("div"),
		);
		signatureContainer.dataset.role = "signature";
		signatureContainer.className = STYLES.signature.pad;

		const reset = signatureContainer.appendChild(
			document.createElement("button"),
		);
		reset.className = STYLES.signature.reset;
		reset.id = "reset-button";

		const resetIcon = reset.appendChild(document.createElement("span"));
		setIcon(resetIcon, "reset");

		this.signature = new Signature(
			signatureContainer,
			this.submission,
			this.schema.id,
		);
		this.signature.init();
		this.destroyables.push(this.signature);

		reset.addEventListener("click", () => this.clear());

		this._edit.addEventListener("updated", () => {
			this.signatureInput.value = this.signature.inputName;
		});

		signatureContainer.classList.add("group-data-[mode=read]/element:hidden");

		return this._edit;
	}

	clear() {
		this.submission = null;
		if (this.signature) {
			this.signature.clear();
		}
		if (this.signatureInput) {
			this.signatureInput.value = "";
		}
	}
}

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_signature_submission_draw_save_reload_and_clear
 * @features signature
 * @dimensions file-input asset-lifecycle form-value editable readonly reload clear
 */
class Signature {
	constructor(container, imageUrl = null, inputName = "signature-image") {
		this.container = container;
		this.imageUrl = imageUrl;
		this.inputName = inputName;
		this.canvas = null;
		this.ctx = null;
		this.isDrawing = false;
		this.lastX = 0;
		this.lastY = 0;
		this.fileInput = null;
		this.resizeObserver = null;
		this.intersectionObserver = null;
		this.resetButton = null;
		this.boundHandlers = {};
		this.debouncedSave = debounce(() => this.saveSignature(), 300);
	}

	init() {
		this.canvas = this.container.appendChild(document.createElement("canvas"));
		this.canvas.className = `touch-none select-none cursor-crosshair`;

		this.fileInput = this.container.appendChild(
			document.createElement("input"),
		);
		this.fileInput.type = "file";
		this.fileInput.name = this.inputName;
		this.fileInput.accept = "image/png";
		this.fileInput.style.display = "none";

		this.ctx = this.canvas.getContext("2d", { willReadFrequently: false });

		this.setupCanvas();
		this.attachEventListeners();

		if (this.imageUrl) {
			this.loadSignature(this.imageUrl);
		}
	}

	setupCanvas() {
		// Use IntersectionObserver to set initial size when visible
		this.intersectionObserver = new IntersectionObserver(
			(entries, observer) => {
				for (const entry of entries) {
					if (entry.isIntersecting) {
						this.resizeCanvas();
						observer.disconnect();
					}
				}
			},
			{ threshold: 0.1 },
		);
		this.intersectionObserver.observe(this.container);

		// Watch for container size changes
		this.resizeObserver = new ResizeObserver(() => {
			this.resizeCanvas();
		});
		this.resizeObserver.observe(this.container);

		// Watch for window resize
		this.boundHandlers.resize = () => this.resizeCanvas();
		window.addEventListener("resize", this.boundHandlers.resize);
	}

	resizeCanvas() {
		const rect = this.container.getBoundingClientRect();

		// Skip resize when container is hidden (0 dimensions)
		if (rect.width === 0 || rect.height === 0) return;

		// Save current drawing
		const tempCanvas = document.createElement("canvas");
		const tempCtx = tempCanvas.getContext("2d");
		tempCanvas.width = this.canvas.width;
		tempCanvas.height = this.canvas.height;
		if (this.canvas.width > 0 && this.canvas.height > 0) {
			tempCtx.drawImage(this.canvas, 0, 0);
		}

		// Resize canvas to container
		this.canvas.width = rect.width;
		this.canvas.height = rect.height;

		// Restore drawing
		if (this.fileInput.files.length > 0) {
			this.loadSignatureFromFile(this.fileInput.files[0]);
		} else if (tempCanvas.width > 0 && tempCanvas.height > 0) {
			this.ctx.drawImage(tempCanvas, 0, 0);
		}
	}

	attachEventListeners() {
		this.boundHandlers.pointerDown = this.handlePointerDown.bind(this);
		this.boundHandlers.pointerMove = this.handlePointerMove.bind(this);
		this.boundHandlers.pointerUp = this.handlePointerUp.bind(this);
		this.boundHandlers.pointerLeave = this.handlePointerLeave.bind(this);

		this.canvas.addEventListener("pointerdown", this.boundHandlers.pointerDown);
		this.canvas.addEventListener("pointermove", this.boundHandlers.pointerMove);
		this.canvas.addEventListener("pointerup", this.boundHandlers.pointerUp);
		this.canvas.addEventListener(
			"pointerleave",
			this.boundHandlers.pointerLeave,
		);
	}

	handlePointerDown(e) {
		e.preventDefault();
		this.isDrawing = true;
		const rect = this.canvas.getBoundingClientRect();
		this.lastX = e.clientX - rect.left;
		this.lastY = e.clientY - rect.top;

		// Configure drawing style
		this.ctx.strokeStyle = "#000000";
		this.ctx.lineWidth = 2;
		this.ctx.lineCap = "round";
		this.ctx.lineJoin = "round";
	}

	handlePointerMove(e) {
		if (!this.isDrawing) return;

		e.preventDefault();
		const rect = this.canvas.getBoundingClientRect();
		const x = e.clientX - rect.left;
		const y = e.clientY - rect.top;

		this.ctx.beginPath();
		this.ctx.moveTo(this.lastX, this.lastY);
		this.ctx.lineTo(x, y);
		this.ctx.stroke();

		this.lastX = x;
		this.lastY = y;
	}

	handlePointerUp() {
		if (!this.isDrawing) return;
		this.isDrawing = false;
		this.debouncedSave();
	}

	handlePointerLeave() {
		if (!this.isDrawing) return;
		this.isDrawing = false;
		this.debouncedSave();
	}

	async saveSignature() {
		const blob = await new Promise((resolve) => {
			this.canvas.toBlob(resolve, "image/png", 1.0);
		});

		const file = new File([blob], "signature.png", {
			type: "image/png",
			lastModified: Date.now(),
		});

		const dataTransfer = new DataTransfer();
		dataTransfer.items.add(file);
		this.fileInput.files = dataTransfer.files;

		this.container.dispatchEvent(new CustomEvent("updated", { bubbles: true }));
	}

	async loadSignature(url) {
		return new Promise((resolve, reject) => {
			const img = new Image();
			img.crossOrigin = "anonymous";

			img.onload = () => {
				this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
				this.ctx.drawImage(img, 0, 0, this.canvas.width, this.canvas.height);
				resolve();
			};

			img.onerror = (error) => {
				console.error("Failed to load signature image:", error);
				reject(error);
			};

			img.src = url;
		});
	}

	loadSignatureFromFile(file) {
		const reader = new FileReader();
		reader.onload = (e) => {
			const img = new Image();
			img.onload = () => {
				this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
				this.ctx.drawImage(img, 0, 0, this.canvas.width, this.canvas.height);
			};
			img.src = e.target.result;
		};
		reader.readAsDataURL(file);
	}

	clear() {
		this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
		this.fileInput.value = "";
	}

	destroy() {
		// Disconnect observers
		if (this.resizeObserver) {
			this.resizeObserver.disconnect();
		}
		if (this.intersectionObserver) {
			this.intersectionObserver.disconnect();
		}

		// Remove event listeners
		if (this.boundHandlers.resize) {
			window.removeEventListener("resize", this.boundHandlers.resize);
		}

		if (this.canvas) {
			this.canvas.removeEventListener(
				"pointerdown",
				this.boundHandlers.pointerDown,
			);
			this.canvas.removeEventListener(
				"pointermove",
				this.boundHandlers.pointerMove,
			);
			this.canvas.removeEventListener(
				"pointerup",
				this.boundHandlers.pointerUp,
			);
			this.canvas.removeEventListener(
				"pointerleave",
				this.boundHandlers.pointerLeave,
			);
		}
	}
}

export { Signature, SignatureElement };
