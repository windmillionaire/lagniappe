import * as pdfjs from "pdfjs-dist";
import { STYLES } from "styles";
import { primitives } from "../elements/primitives";
import { setIcon } from "../shared/icons";

const MAX_DEVICE_SCALE = 2;
const MAX_PAGE_WIDTH = 896;
const RENDER_MARGIN = "800px 0px";
const RESIZE_DELAY_MS = 150;
const RERENDER_THRESHOLD_PX = 24;
const ACTIVE_PAGE_THRESHOLDS = [0, 0.25, 0.5, 0.75, 1];
const LOAD_RETRY_DELAYS_MS = [500, 1500];
const WIDTH_WAIT_FRAMES = 8;
const RANGE_CHUNK_SIZE = 1024 * 1024;

/**
 * @testable false
 * @covered-by src/script/widgets/filePdfPreview.mjs::PDFPreview
 * @reason range transport behavior is exercised through the PDF preview widget
 */
class PDFRangeTransport extends pdfjs.PDFDataRangeTransport {
	constructor({ url, length, filename }) {
		super(length, null, true, filename);
		this.url = url;
		this.controllers = new Set();
	}

	requestDataRange(begin, end) {
		const controller = new AbortController();
		this.controllers.add(controller);
		fetch(this.url, {
			headers: {
				Range: `bytes=${begin}-${end - 1}`,
			},
			signal: controller.signal,
		})
			.then(async (response) => {
				if (!response.ok && response.status !== 206) {
					throw new Error(`PDF range request failed: ${response.status}`);
				}
				this.onDataRange(begin, new Uint8Array(await response.arrayBuffer()));
			})
			.catch((error) => {
				if (error.name !== "AbortError") {
					console.error("Unable to load PDF range", error);
				}
			})
			.finally(() => {
				this.controllers.delete(controller);
			});
	}

	abort() {
		this.controllers.forEach((controller) => {
			controller.abort();
		});
		this.controllers.clear();
	}
}

/**
 * @testable true
 * @tests tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_pdf_renders_pdf_preview_widget
 * @tests tests_e2e/011_files/test_011a_file_tabs.py::test_pdf_preview_loading_state_paints_before_document_render
 * @tests tests_e2e/011_files/test_011a_file_tabs.py::test_page_uploaded_pdf_toolbar_navigates_pages
 * @tests tests_e2e/011_files/test_011a_file_tabs.py::test_file_mobile_pdf_preview_renders_canvas
 * @tests tests_js/test_025_pdf_preview.py::test_pdf_preview_loading_does_not_block_widget_reconciliation
 * @tests tests_js/test_025_pdf_preview.py::test_pdf_preview_revisit_does_not_await_pending_rasterization
 * @features file
 * @dimensions pdf-preview pdf-toolbar loading-state view-transition revisit
 */
export class PDFPreview {
	constructor(attributes) {
		Object.assign(this, attributes);
		this._started = false;
		this._pdf = null;
		this._pages = new Map();
		this._intersections = new Map();
		this._rendering = new Map();
		this._resizeTimer = null;
		this._loadRetryTimer = null;
		this._loadRetryResolve = null;
		this._renderObserver = null;
		this._activeObserver = null;
		this._resizeObserver = null;
		this._loadingTask = null;
		this._renderQueue = Promise.resolve();
		this._currentPage = 1;
		this._numPages = 0;
		this._destroyed = false;
		this._onToolbarClick = this._onToolbarClick.bind(this);
		this._onToolbarChange = this._onToolbarChange.bind(this);
		this._onToolbarKeydown = this._onToolbarKeydown.bind(this);
	}

	get url() {
		return this.target.dataset.url;
	}

	get size() {
		const size = Number.parseInt(this.target.dataset.size || "", 10);
		return Number.isFinite(size) && size > 0 ? size : null;
	}

	get workerSrc() {
		return document.querySelector("meta[name='pdf-worker-src']")?.content;
	}

	get wasmUrl() {
		return document.querySelector("meta[name='pdf-wasm-url']")?.content;
	}

	get status() {
		return this.target.querySelector("[data-role='pdf-status']");
	}

	get pages() {
		return this.target.querySelector("[data-role='pdf-pages']");
	}

	get fallback() {
		return this.target.querySelector("[data-role='pdf-fallback']");
	}

	get toolbar() {
		return this.target.querySelector("[data-role='toolbar']");
	}

	get pageInput() {
		return this.target.querySelector("[data-role='pdf-page-input']");
	}

	get pageCount() {
		return this.target.querySelector("[data-role='pdf-page-count']");
	}

	get previousButton() {
		return this.target.querySelector("[data-action='previous-page']");
	}

	get nextButton() {
		return this.target.querySelector("[data-action='next-page']");
	}

	get fullscreenButton() {
		return this.target.querySelector("[data-action='toggle-fullscreen']");
	}

	init() {
		if (!this.target.dataset.fullscreen)
			this.target.dataset.fullscreen = "false";
		this._createToolbar();
		this.target.addEventListener("click", this._onToolbarClick);
		this.target.addEventListener("change", this._onToolbarChange);
		this.target.addEventListener("keydown", this._onToolbarKeydown);
	}

	postreconcile() {
		if (!this.visible) return;

		if (this._started) {
			void this._renderPage(this._currentPage);
			return;
		}

		this._started = true;
		void this._renderPreview();
	}

	_setStatus(text) {
		const status = this.status;
		if (!status) return;

		status.replaceChildren();
		status.dataset.visible = text ? "true" : "false";
		if (text) {
			status.setAttribute("aria-label", text);
			this.target.setAttribute("aria-busy", "true");
			status.appendChild(primitives.loading());
		} else {
			status.removeAttribute("aria-label");
			this.target.removeAttribute("aria-busy");
		}
	}

	_showFallback() {
		this._setStatus("");
		if (this.toolbar) this.toolbar.dataset.visible = "false";
		if (this.pages) this.pages.dataset.visible = "false";
		const fallback = this.fallback;
		if (fallback) fallback.dataset.visible = "true";
	}

	_createToolbar() {
		if (this.toolbar) return;

		const toolbar = document.createElement("div");
		toolbar.dataset.role = "toolbar";
		toolbar.dataset.visible = "false";
		toolbar.className =
			"group/toolbar z-40 border-b sm:border-t border-base-light/50 bg-base-bg p-4 sm:px-6";

		const tools = document.createElement("div");
		tools.className = STYLES.editor.toolbar.tools;

		const pageTools = document.createElement("div");
		pageTools.className = STYLES.editor.toolbar.section;
		pageTools.append(
			this._toolbarButton("previous-page", "back", "Previous Page"),
			this._pageControl(),
			this._toolbarButton("next-page", "next", "Next Page"),
		);

		const viewTools = document.createElement("div");
		viewTools.className = `${STYLES.editor.toolbar.section} ml-auto`;
		viewTools.append(
			this._toolbarButton("toggle-fullscreen", "maximize", "Toggle Focus", {
				pressed: false,
			}),
		);

		tools.append(pageTools, viewTools);
		toolbar.append(tools);
		this.target.prepend(toolbar);
	}

	_toolbarButton(action, icon, title, { pressed = null } = {}) {
		const button = document.createElement("button");
		button.type = "button";
		button.dataset.action = action;
		button.title = title;
		button.setAttribute("aria-label", title);
		if (pressed !== null) button.setAttribute("aria-pressed", String(pressed));
		button.className = `${STYLES.editor.toolbar.tool} disabled:pointer-events-none disabled:opacity-40`;
		this._setButtonIcon(button, icon);
		return button;
	}

	_setButtonIcon(button, icon) {
		const iconElement = document.createElement("span");
		setIcon(iconElement, icon);
		button.replaceChildren(iconElement);
	}

	_pageControl() {
		const label = document.createElement("label");
		label.className =
			"flex min-h-8 items-center gap-1 rounded-md bg-white px-2 py-1 text-sm font-semibold text-base-default shadow-sm outline outline-base-light/50";

		const screenReaderLabel = document.createElement("span");
		screenReaderLabel.className = "sr-only";
		screenReaderLabel.textContent = "Page";

		const input = document.createElement("input");
		input.type = "number";
		input.min = "1";
		input.step = "1";
		input.value = "1";
		input.dataset.role = "pdf-page-input";
		input.setAttribute("aria-label", "Page");
		input.className =
			"h-6 w-12 rounded-sm border border-base-light/50 bg-base-bg px-1 text-center text-sm font-semibold text-base-dark focus-visible:outline-2 focus-visible:outline-kind-default";

		const count = document.createElement("span");
		count.dataset.role = "pdf-page-count";
		count.className = "min-w-8 whitespace-nowrap text-base-medium";
		count.textContent = "/ -";

		label.append(screenReaderLabel, input, count);
		return label;
	}

	async _renderPreview() {
		const workerSrc = this.workerSrc;
		if (workerSrc) pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;

		try {
			this._setStatus("Loading preview");
			this._pdf = await this._loadDocument();
			await this._preparePages();
			this._observePages();
			this._observeResize();
		} catch (error) {
			console.error("Unable to render PDF preview", error);
			this._showFallback();
		}
	}

	async _loadDocument() {
		let lastError = null;

		for (
			let attempt = 0;
			attempt <= LOAD_RETRY_DELAYS_MS.length;
			attempt += 1
		) {
			try {
				const options = await this._loadOptions();
				this._loadingTask = pdfjs.getDocument(options);
				return await this._loadingTask.promise;
			} catch (error) {
				lastError = error;
				if (this._destroyed || attempt >= LOAD_RETRY_DELAYS_MS.length) break;
				await this._delay(LOAD_RETRY_DELAYS_MS[attempt]);
			}
		}

		throw lastError;
	}

	async _loadOptions() {
		const options = {};
		if (this.wasmUrl) options.wasmUrl = this.wasmUrl;

		const size = this.size || (await this._loadSize());
		if (size) {
			options.range = new PDFRangeTransport({
				url: this.url,
				length: size,
				filename: this.target.dataset.filename,
			});
			options.rangeChunkSize = RANGE_CHUNK_SIZE;
			options.disableStream = true;
			options.disableAutoFetch = true;
			return options;
		}

		options.url = this.url;
		options.disableStream = true;
		return options;
	}

	async _loadSize() {
		const response = await fetch(this.url, { method: "HEAD" });
		if (!response.ok) return null;

		const size = Number.parseInt(
			response.headers.get("content-length") || "",
			10,
		);
		if (!Number.isFinite(size) || size <= 0) return null;

		this.target.dataset.size = String(size);
		return size;
	}

	_delay(ms) {
		return new Promise((resolve) => {
			this._loadRetryResolve = resolve;
			this._loadRetryTimer = setTimeout(() => {
				this._loadRetryTimer = null;
				this._loadRetryResolve = null;
				resolve();
			}, ms);
		});
	}

	async _preparePages() {
		const pages = this.pages;
		if (!pages || !this._pdf) return;

		const firstPage = await this._pdf.getPage(1);
		const firstViewport = firstPage.getViewport({ scale: 1 });
		const fragment = document.createDocumentFragment();
		this._numPages = this._pdf.numPages;

		for (let number = 1; number <= this._pdf.numPages; number += 1) {
			const wrapper = document.createElement("div");
			wrapper.dataset.page = String(number);
			wrapper.dataset.loaded = number === 1 ? "true" : "false";
			wrapper.dataset.rendered = "false";
			wrapper.className =
				"mx-auto mb-4 overflow-hidden rounded bg-white shadow-sm ring-1 ring-base-light/50 last:mb-0";
			wrapper.style.aspectRatio = `${firstViewport.width} / ${firstViewport.height}`;
			wrapper.style.maxWidth = `${MAX_PAGE_WIDTH}px`;
			wrapper.style.width = "100%";

			const canvas = document.createElement("canvas");
			canvas.className = "block h-full w-full";
			canvas.setAttribute("aria-label", `Page ${number}`);
			wrapper.appendChild(canvas);

			this._pages.set(number, {
				canvas,
				page: number === 1 ? firstPage : null,
				renderedWidth: 0,
				viewport: firstViewport,
				wrapper,
			});
			fragment.appendChild(wrapper);
		}

		pages.appendChild(fragment);
		pages.dataset.visible = "true";
		await this._nextFrame();
		this._setCurrentPage(1);
		this._updateToolbar();
		await this._renderPage(1);
	}

	_nextFrame() {
		return new Promise((resolve) => requestAnimationFrame(resolve));
	}

	_observePages() {
		const root = this.pages;
		if (!("IntersectionObserver" in window)) {
			this._pages.forEach((_entry, number) => {
				this._renderPage(number);
			});
			return;
		}

		this._renderObserver = new IntersectionObserver(
			(entries) => {
				entries.forEach((entry) => {
					if (!entry.isIntersecting) return;
					this._renderPage(Number(entry.target.dataset.page));
				});
			},
			{ root, rootMargin: RENDER_MARGIN },
		);

		this._activeObserver = new IntersectionObserver(
			(entries) => this._updateActivePage(entries),
			{ root, threshold: ACTIVE_PAGE_THRESHOLDS },
		);

		this._pages.forEach((entry) => {
			this._renderObserver.observe(entry.wrapper);
			this._activeObserver.observe(entry.wrapper);
		});
	}

	_observeResize() {
		if (!("ResizeObserver" in window)) return;

		this._resizeObserver = new ResizeObserver(() => {
			clearTimeout(this._resizeTimer);
			this._resizeTimer = setTimeout(() => {
				this._pages.forEach((entry, number) => {
					if (!entry.renderedWidth && entry.wrapper.clientWidth) {
						if (
							number === this._currentPage ||
							this._intersections.has(number)
						) {
							this._renderPage(number);
						}
						return;
					}
					if (!entry.renderedWidth) return;

					const width = entry.wrapper.clientWidth;
					if (Math.abs(width - entry.renderedWidth) < RERENDER_THRESHOLD_PX) {
						return;
					}
					this._renderPage(number, { force: true });
				});
			}, RESIZE_DELAY_MS);
		});
		this._resizeObserver.observe(this.target);
	}

	_updateActivePage(entries) {
		entries.forEach((entry) => {
			const number = Number(entry.target.dataset.page);
			if (entry.isIntersecting) {
				this._intersections.set(number, entry);
			} else {
				this._intersections.delete(number);
			}
		});

		let activeNumber = this._currentPage;
		let activeDistance = Number.POSITIVE_INFINITY;
		const root = this.pages;
		const rootRect = root?.getBoundingClientRect();
		const viewportCenter = rootRect
			? rootRect.top + rootRect.height / 2
			: window.innerHeight / 2;
		this._intersections.forEach((entry, number) => {
			const rect = entry.boundingClientRect;
			const distance = Math.abs(rect.top + rect.height / 2 - viewportCenter);
			if (distance < activeDistance) {
				activeDistance = distance;
				activeNumber = number;
			}
		});
		this._setCurrentPage(activeNumber);
	}

	_onToolbarClick(event) {
		const button = event.target.closest("button[data-action]");
		if (!button || !this.target.contains(button) || button.disabled) return;

		const action = button.dataset.action;
		if (action === "previous-page") {
			this._goToPage(this._currentPage - 1);
		} else if (action === "next-page") {
			this._goToPage(this._currentPage + 1);
		} else if (action === "toggle-fullscreen") {
			this._toggleFullscreen();
		}
	}

	_onToolbarChange(event) {
		if (!event.target.matches("[data-role='pdf-page-input']")) return;
		this._goToPage(event.target.value);
	}

	_onToolbarKeydown(event) {
		if (!event.target.matches("[data-role='pdf-page-input']")) return;

		if (event.key === "Enter") {
			event.preventDefault();
			this._goToPage(event.target.value);
		} else if (event.key === "Escape") {
			event.preventDefault();
			event.target.value = String(this._currentPage);
			event.target.blur();
		}
	}

	async _goToPage(value) {
		const number = this._clampPage(value);
		if (!number) {
			this._setCurrentPage(this._currentPage);
			return;
		}

		this._setCurrentPage(number);
		this._scrollPageIntoView(number);
		await this._renderPage(number);
	}

	_scrollPageIntoView(number) {
		const pages = this.pages;
		const wrapper = this._pages.get(number)?.wrapper;
		if (!pages || !wrapper) return;

		if (pages.scrollTo) {
			const paddingTop = Number.parseFloat(getComputedStyle(pages).paddingTop);
			pages.scrollTo({
				top: Math.max(wrapper.offsetTop - paddingTop, 0),
				behavior: "auto",
			});
		} else {
			wrapper.scrollIntoView({ behavior: "auto", block: "start" });
		}
	}

	_clampPage(value) {
		const number = Number.parseInt(value, 10);
		if (!Number.isFinite(number) || number < 1 || !this._numPages) return null;
		return Math.min(number, this._numPages);
	}

	_setCurrentPage(number) {
		const next = this._clampPage(number) ?? 1;
		this._currentPage = next;
		this._updateToolbar();
	}

	_updateToolbar() {
		const ready = this._numPages > 0;
		const toolbar = this.toolbar;
		if (toolbar) toolbar.dataset.visible = ready ? "true" : "false";

		if (this.pageInput) {
			this.pageInput.disabled = !ready;
			this.pageInput.max = ready ? String(this._numPages) : "";
			this.pageInput.value = String(this._currentPage);
		}
		if (this.pageCount) {
			this.pageCount.textContent = ready ? `/ ${this._numPages}` : "/ -";
		}
		if (this.previousButton) {
			this.previousButton.disabled = !ready || this._currentPage <= 1;
		}
		if (this.nextButton) {
			this.nextButton.disabled = !ready || this._currentPage >= this._numPages;
		}
		if (this.fullscreenButton) {
			this.fullscreenButton.disabled = !ready;
		}
	}

	_toggleFullscreen() {
		const active = this.target.dataset.fullscreen === "true";
		this.target.dataset.fullscreen = active ? "false" : "true";
		this._updateFullscreenButton();
		requestAnimationFrame(() => {
			this._renderPage(this._currentPage, { force: true });
		});
	}

	_updateFullscreenButton() {
		const button = this.fullscreenButton;
		if (!button) return;

		const active = this.target.dataset.fullscreen === "true";
		button.setAttribute("aria-pressed", String(active));
		button.title = active ? "Exit Focus" : "Toggle Focus";
		button.setAttribute("aria-label", button.title);
		this._setButtonIcon(button, active ? "minimize" : "maximize");
	}

	async _renderPage(number, { force = false } = {}) {
		const entry = this._pages.get(number);
		if (!entry) return null;
		if (!force && entry.renderedWidth) return null;
		if (this._rendering.has(number)) return this._rendering.get(number);

		const render = this._renderQueue.then(() => {
			return this._renderPageTask(number, entry, force);
		});
		this._renderQueue = render.catch(() => null);
		const task = render
			.catch((error) => {
				console.error(`Unable to render PDF page ${number}`, error);
				if (number === 1 && !entry.renderedWidth) this._showFallback();
				return null;
			})
			.finally(() => {
				this._rendering.delete(number);
			});
		this._rendering.set(number, task);
		return task;
	}

	async _renderPageTask(number, entry, force) {
		await this._loadPage(number, entry);

		const cssWidth = await this._renderWidth(entry);
		const context = entry.canvas.getContext("2d");
		if (!cssWidth || !context) return;

		if (force) {
			context.clearRect(0, 0, entry.canvas.width, entry.canvas.height);
		}

		const viewport = entry.viewport;
		const scale = cssWidth / viewport.width;
		const deviceScale = Math.min(
			window.devicePixelRatio || 1,
			MAX_DEVICE_SCALE,
		);
		const renderViewport = entry.page.getViewport({
			scale: scale * deviceScale,
		});

		entry.canvas.width = Math.floor(renderViewport.width);
		entry.canvas.height = Math.floor(renderViewport.height);
		entry.wrapper.style.aspectRatio = `${viewport.width} / ${viewport.height}`;

		await entry.page.render({
			canvasContext: context,
			viewport: renderViewport,
		}).promise;

		entry.renderedWidth = cssWidth;
		entry.wrapper.dataset.rendered = "true";
		if (number === 1) this._setStatus("");
	}

	async _renderWidth(entry) {
		for (let attempt = 0; attempt < WIDTH_WAIT_FRAMES; attempt += 1) {
			const width = entry.wrapper.clientWidth || this.target.clientWidth;
			if (width) return width;
			await this._nextFrame();
		}
		return entry.wrapper.clientWidth || this.target.clientWidth;
	}

	async _loadPage(number, entry) {
		if (entry.page) return;

		entry.page = await this._pdf.getPage(number);
		entry.viewport = entry.page.getViewport({ scale: 1 });
		entry.wrapper.style.aspectRatio = `${entry.viewport.width} / ${entry.viewport.height}`;
		entry.wrapper.dataset.loaded = "true";
	}

	destroy() {
		this._destroyed = true;
		clearTimeout(this._resizeTimer);
		clearTimeout(this._loadRetryTimer);
		this._loadRetryResolve?.();
		this._loadRetryTimer = null;
		this._loadRetryResolve = null;
		this.target.removeEventListener("click", this._onToolbarClick);
		this.target.removeEventListener("change", this._onToolbarChange);
		this.target.removeEventListener("keydown", this._onToolbarKeydown);
		this._renderObserver?.disconnect();
		this._activeObserver?.disconnect();
		this._resizeObserver?.disconnect();
		this._loadingTask?.destroy?.();
		this._pdf?.destroy?.();
	}
}
