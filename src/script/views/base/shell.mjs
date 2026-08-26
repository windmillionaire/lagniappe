import { connectivity } from "../../shared/connectivity";

const MOBILE_QUERY = "(max-width: 640px)";

/**
 * @testable false
 * @covered-by src/script/views/base/shell.mjs::ShellView
 */
export const markPerformance = (name) => {
	if (typeof performance === "undefined" || !performance.mark) return;
	if (performance.getEntriesByName?.(name, "mark")?.length) return;
	performance.mark(name);
};

/**
 * @testable false
 * @covered-by src/script/views/base/services.mjs::initializeCoreServices
 * @reason idle scheduling is an implementation detail of deferred service startup
 */
export const whenIdle = () =>
	new Promise((resolve) => {
		if (typeof globalThis.requestIdleCallback === "function") {
			globalThis.requestIdleCallback(resolve, { timeout: 1000 });
			return;
		}
		setTimeout(resolve, 0);
	});

/**
 * Lightweight page shell. It owns only interaction interception, viewport
 * publication, pointer tracking, and the final ready markers shared by every
 * view. Feature managers belong to Core's deferred service layer.
 *
 * @testable infrastructure
 */
export default class ShellView {
	constructor(node) {
		this.elt = node;
		this.kind = node.dataset.kind;
		this.hash = node.dataset.hash || node.dataset.index;
		this.key = node.dataset.key;
		this.readonly = node.dataset.readonly === "true";
		this.mobile = window.matchMedia(MOBILE_QUERY).matches;
		this.online = connectivity.online;
		this.hidden = connectivity.hidden;
		this.components = {};
		this.SearchBox = null;
		this.Notifications = null;
		this.PollingCoordinator = null;

		this._destroyed = false;
		this._interactive = false;
		this._published = false;
		this.hasDeferredServices = false;
		this._coldActions = new Map();
		this.copyResetTimers = new Map();
		this._pointer = null;
		this.isDragging = false;

		this._handleClick = this._handleClick.bind(this);
		this._handleSubmit = this._handleSubmit.bind(this);
		this._pointerDown = this._pointerDown.bind(this);
		this._pointerMove = this._pointerMove.bind(this);
		this._pointerUp = this._pointerUp.bind(this);
		this._mobileChanged = this._mobileChanged.bind(this);

		this._publishedReady = new Promise((resolve) => {
			this._resolvePublished = resolve;
		});
		this.servicesReady = Promise.resolve(this);
	}

	async init() {
		if (this._interactive) return this;
		this._interactive = true;
		this.elt.addEventListener("click", this._handleClick);
		this.elt.addEventListener("submit", this._handleSubmit);
		this.elt.addEventListener("pointerdown", this._pointerDown);

		this._mobileQuery = window.matchMedia(MOBILE_QUERY);
		this._mobileQuery.addEventListener("change", this._mobileChanged);
		const mode = document
			.querySelector("meta[name='mode']")
			?.getAttribute("content");
		if (mode !== "public") this._installColdControlListeners?.();

		this.elt.dataset.interactive = "true";
		markPerformance("lagniappe:interaction-ready");
		if (!this.hasDeferredServices && mode !== "public") {
			this.hasDeferredServices = true;
			this._ownsShellServices = true;
			this._initializeShellServices();
		}
		return this;
	}

	_loadShellManager(promiseKey, handleKey, loader) {
		if (this[handleKey]) return Promise.resolve(this[handleKey]);
		if (this[promiseKey]) return this[promiseKey];
		const pending = Promise.resolve()
			.then(loader)
			.then((manager) => {
				if (this._destroyed) {
					manager?.destroy?.();
					return null;
				}
				if (manager) this[handleKey] = manager;
				return manager || null;
			})
			.catch((error) => {
				if (this[promiseKey] === pending) this[promiseKey] = null;
				throw error;
			});
		this[promiseKey] = pending;
		return pending;
	}

	ensurePollingCoordinator() {
		return this._loadShellManager(
			"_pollingPromise",
			"PollingCoordinator",
			async () => {
				const { PollingCoordinator } = await import("../../shared/polling");
				return this._destroyed ? null : new PollingCoordinator(this).init();
			},
		);
	}

	ensureSearchBox() {
		return this._loadShellManager("_searchPromise", "SearchBox", async () => {
			const search = document.querySelector("[lp-search]");
			if (!search) return null;
			const { SearchBox } = await import("../../elements/combobox/search");
			if (this._destroyed) return null;
			const box = new SearchBox(search);
			await box.init();
			return box;
		});
	}

	ensureNotifications() {
		return this._loadShellManager(
			"_notificationsPromise",
			"Notifications",
			async () => {
				if (!document.querySelector("[data-role='notifications']")) return null;
				await this.ensurePollingCoordinator();
				const { Notifications } = await import("../../elements/notifications");
				if (this._destroyed) return null;
				const notifications = new Notifications(this);
				notifications.init();
				return notifications;
			},
		);
	}

	_initializeShellServices() {
		this.servicesReady = this._publishedReady
			.then(() => whenIdle())
			.then(async () => {
				const warmers = [];
				if (document.querySelector("[lp-search]")) {
					warmers.push(this.ensureSearchBox());
				}
				if (document.querySelector("[data-role='notifications']")) {
					warmers.push(this.ensureNotifications());
				}
				const results = await Promise.allSettled(warmers);
				for (const result of results) {
					if (result.status === "rejected") {
						this.reportStartupError(
							result.reason,
							this.elt,
							"shell-service-startup",
						);
					}
				}
				return results;
			})
			.catch((error) => {
				this.reportStartupError(error, this.elt, "shell-service-startup");
				return [];
			})
			.then(async (result) => {
				await this._publishedReady;
				if (!this._destroyed) markPerformance("lagniappe:services-ready");
				return result;
			});
	}

	reportStartupError(error, element = this.elt, context = "lazy-control") {
		void import("../../shared/errors")
			.then(({ captureError }) => {
				captureError(error, element, { context });
			})
			.catch(() => {});
	}

	_installColdControlListeners() {
		this._shellColdControl = (event) => {
			const search = event.target?.closest?.("[lp-search]");
			if (search && !this.SearchBox) {
				this.runColdAction(
					search,
					() => this.ensureSearchBox(),
					(box) => this._activateSearchBox(box),
					search,
				);
				return;
			}
			const notifications = event.target?.closest?.(
				"[data-role='notifications']",
			);
			if (!notifications || this.Notifications) return;
			if (event.type === "click") {
				event.preventDefault();
				event.stopImmediatePropagation?.();
			}
			this.runColdAction(
				notifications,
				() => this.ensureNotifications(),
				(manager) => manager?.dropdown?.showPanel?.(),
				notifications,
			);
		};
		for (const type of ["input", "click"]) {
			document.addEventListener(type, this._shellColdControl, true);
		}
	}

	/**
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_lazy_search_replays_the_latest_live_input_after_loading
	 * @matrix startup : first-interaction single-flight
	 * @pair search:navbar-results
	 */
	_activateSearchBox(box) {
		if (!box) return;
		const input = box.element;
		if (input?.value?.trim()) box._input({ target: input });
		else box.showPanel?.();
	}

	_removeColdControlListeners() {
		if (!this._shellColdControl) return;
		for (const type of ["input", "click"]) {
			document.removeEventListener(type, this._shellColdControl, true);
		}
		this._shellColdControl = null;
	}

	async sync({ hidden = document.hidden } = {}) {
		this.hidden = hidden;
		this.online = connectivity.online;
		if (hidden || !this.online) this.PollingCoordinator?.pause();
		else await this.PollingCoordinator?.resume();
	}

	publish() {
		if (this._destroyed || this._published) return this;
		this._published = true;
		this.elt.setAttribute("initialized", "");
		this.elt._lp_view = this;
		markPerformance("lagniappe:view-ready");
		this._resolvePublished?.(this);
		if (!this.hasDeferredServices) {
			queueMicrotask(() => {
				if (!this._destroyed) markPerformance("lagniappe:services-ready");
			});
		}
		return this;
	}

	_mobileChanged(event) {
		this.mobile = event.matches;
		this.elt.dispatchEvent(new CustomEvent("mobile-resize"));
	}

	_pointerDown(event) {
		if (event.button !== undefined && event.button !== 0) return;
		this.isDragging = false;
		this._pointer = {
			id: event.pointerId,
			x: event.clientX,
			y: event.clientY,
		};
		window.addEventListener("pointermove", this._pointerMove);
		window.addEventListener("pointerup", this._pointerUp);
		window.addEventListener("pointercancel", this._pointerUp);
	}

	_pointerMove(event) {
		if (!this._pointer) return;
		if (
			this._pointer.id !== undefined &&
			event.pointerId !== undefined &&
			event.pointerId !== this._pointer.id
		)
			return;
		const deltaX = Math.abs(event.clientX - this._pointer.x);
		const deltaY = Math.abs(event.clientY - this._pointer.y);
		if (deltaX > 5 || deltaY > 5) this.isDragging = true;
	}

	_pointerUp() {
		this._pointer = null;
		window.removeEventListener("pointermove", this._pointerMove);
		window.removeEventListener("pointerup", this._pointerUp);
		window.removeEventListener("pointercancel", this._pointerUp);
	}

	_handleClick(event) {
		if (this.isDragging) {
			this.isDragging = false;
			return;
		}
		const copyButton = event.target?.closest?.(
			"[data-role='manual-command-copy']",
		);
		if (copyButton) {
			event.preventDefault();
			void this.copyCommand(copyButton);
			return;
		}
		this._click(event);
	}

	_click() {}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002f_home_directory.py::test_manual_installation_commands_are_copyable_and_scroll_on_mobile
	 * @tests tests_e2e/008_users/test_008d_admin_data_protection.py::test_backups_tab_reveals_static_status_panel
	 * @tests tests_js/test_038_startup_specializations.py::test_command_copy_falls_back_when_clipboard_is_unavailable
	 * @matrix manual admin : clipboard-fallback command-copy
	 */
	async copyCommand(button) {
		const command = button
			.closest("[data-role='manual-command-shell']")
			?.querySelector("[data-role='manual-command'] code")?.textContent;
		if (!command) return;

		let copied = false;
		try {
			if (navigator.clipboard?.writeText) {
				await navigator.clipboard.writeText(command);
				copied = true;
			}
		} catch {
			copied = false;
		}

		if (!copied) {
			const textarea = document.createElement("textarea");
			textarea.value = command;
			textarea.setAttribute("readonly", "");
			textarea.style.position = "fixed";
			textarea.style.opacity = "0";
			document.body.append(textarea);
			textarea.select();
			try {
				copied = document.execCommand("copy");
			} catch {
				copied = false;
			}
			textarea.remove();
			button.focus();
		}

		const resetTimer = this.copyResetTimers.get(button);
		if (resetTimer) clearTimeout(resetTimer);
		button.textContent = copied ? "Copied!" : "Copy failed";
		button.setAttribute(
			"aria-label",
			copied ? "Command copied" : "Command could not be copied",
		);
		this.copyResetTimers.set(
			button,
			setTimeout(() => {
				if (button.isConnected) {
					button.textContent = "Copy";
					button.setAttribute("aria-label", "Copy command");
				}
				this.copyResetTimers.delete(button);
			}, 2000),
		);
	}

	_handleSubmit(event) {
		if (!this.ensureSubmissionManager || event.defaultPrevented) return;
		const form = event.target;
		if (!form?.closest?.("[lp-component]")) return;

		event.preventDefault();
		event.stopPropagation();
		const submitter = event.submitter;
		if (submitter) submitter.disabled = true;
		let handedOff = false;
		this.runColdAction(
			form,
			() => this.ensureSubmissionManager(),
			(manager) => {
				if (this._destroyed || !form.isConnected || !manager) return;
				handedOff = true;
				return manager.submit(event);
			},
			submitter,
		).finally(() => {
			if (submitter && !handedOff) submitter.disabled = false;
		});
	}

	runColdAction(owner, load, activate, busyOwner = owner) {
		if (!owner || this._destroyed) return Promise.resolve(null);
		if (this._coldActions.has(owner)) return this._coldActions.get(owner);

		busyOwner?.setAttribute?.("aria-busy", "true");
		if (busyOwner?.dataset) busyOwner.dataset.loading = "true";
		const pending = Promise.resolve()
			.then(load)
			.then((value) => {
				if (this._destroyed) return null;
				return activate(value);
			})
			.catch((error) => {
				this.reportStartupError?.(error, owner);
				return null;
			})
			.finally(() => {
				busyOwner?.removeAttribute?.("aria-busy");
				if (busyOwner?.dataset) delete busyOwner.dataset.loading;
				if (this._coldActions.get(owner) === pending) {
					this._coldActions.delete(owner);
				}
			});
		this._coldActions.set(owner, pending);
		return pending;
	}

	destroy() {
		this._destroyed = true;
		for (const timer of this.copyResetTimers.values()) clearTimeout(timer);
		this.copyResetTimers.clear();
		this._pointerUp();
		this.elt.removeEventListener("click", this._handleClick);
		this.elt.removeEventListener("submit", this._handleSubmit);
		this.elt.removeEventListener("pointerdown", this._pointerDown);
		this._mobileQuery?.removeEventListener("change", this._mobileChanged);
		this._removeColdControlListeners?.();
		this._coldActions.clear();
		if (this._ownsShellServices) {
			this.Notifications?.destroy?.();
			this.PollingCoordinator?.destroy?.();
			this.SearchBox?.destroy?.();
		}
		if (this.elt._lp_view === this) delete this.elt._lp_view;
	}
}
