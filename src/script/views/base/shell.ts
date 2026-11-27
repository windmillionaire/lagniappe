import type { SearchBox } from "../../elements/combobox/search.ts";
import type { Notifications } from "../../elements/notifications.ts";
import { connectivity } from "../../shared/connectivity.ts";
import type { PollingCoordinator } from "../../shared/polling.ts";
import type Builder from "../builder/builder.ts";
import type ViewComponent from "./component.ts";
import type { SubmissionManager, ViewSubmitEvent } from "./submission.ts";

const MOBILE_QUERY = "(max-width: 640px)";

export interface ViewRoot extends HTMLElement {
	_lp_view?: ShellView | Builder;
}

export interface ViewSyncOptions {
	hidden?: boolean;
	blurred?: boolean;
	blurredAt?: number | null;
	force?: boolean;
}

function hasClosest(target: EventTarget | null): target is Element {
	return Boolean(
		target && "closest" in target && typeof target.closest === "function",
	);
}

export const markPerformance = (name: string) => {
	if (typeof performance === "undefined" || !performance.mark) return;
	if (performance.getEntriesByName?.(name, "mark")?.length) return;
	performance.mark(name);
};

export const whenIdle = () =>
	new Promise<IdleDeadline | undefined>((resolve) => {
		if (typeof globalThis.requestIdleCallback === "function") {
			globalThis.requestIdleCallback(resolve, { timeout: 1000 });
			return;
		}
		setTimeout(resolve, 0);
	});

export const loadViewService = <
	Handle extends string,
	Slot extends string,
	Manager extends object,
>(
	view: { _destroyed: boolean } & Record<Handle, NoInfer<Manager> | null> &
		Partial<Record<Slot, Promise<NoInfer<Manager> | null> | null>>,
	promiseKey: Slot,
	handleKey: Handle,
	loader: () => Promise<Manager | null>,
): Promise<Manager | null> => {
	const handles: Record<Handle, Manager | null> = view;
	const promises: Partial<Record<Slot, Promise<Manager | null> | null>> = view;
	const handle = handles[handleKey];
	if (handle) return Promise.resolve(handle);
	const existing = promises[promiseKey];
	if (existing) return existing;

	const pending = Promise.resolve()
		.then(loader)
		.then((manager) => {
			if (view._destroyed) {
				if (
					manager &&
					"destroy" in manager &&
					typeof manager.destroy === "function"
				)
					manager.destroy();
				return null;
			}
			if (manager) handles[handleKey] = manager;
			return manager || null;
		})
		.catch((error) => {
			if (promises[promiseKey] === pending) promises[promiseKey] = null;
			throw error;
		});
	promises[promiseKey] = pending;
	return pending;
};

/**
 * Lightweight page shell. It owns only interaction interception, viewport
 * publication, pointer tracking, and the final ready markers shared by every
 * view. Feature managers belong to Core's deferred service layer.
 *
 */
export default class ShellView {
	declare elt: ViewRoot;
	declare kind: string | undefined;
	declare hash: string | undefined;
	declare key: string | undefined;
	declare readonly: boolean;
	declare mobile: boolean;
	declare online: boolean;
	declare hidden: boolean;
	declare components: Record<string, ViewComponent>;
	declare SearchBox: SearchBox | null;
	declare Notifications: Notifications | null;
	declare PollingCoordinator: PollingCoordinator | null;
	declare hasDeferredServices: boolean;
	declare isDragging: boolean;
	declare _destroyed: boolean;
	declare _publishedReady: Promise<this>;
	declare servicesReady: Promise<unknown>;
	ensureSubmissionManager?(): Promise<SubmissionManager | null>;
	declare _searchPromise?: Promise<SearchBox | null> | null;
	declare _notificationsPromise?: Promise<Notifications | null> | null;
	declare _pollingPromise?: Promise<PollingCoordinator | null> | null;

	declare private _interactive: boolean;
	declare private _published: boolean;
	declare private _ownsShellServices?: boolean;
	declare private _coldActions: Map<Element, Promise<unknown>>;
	declare private copyResetTimers: Map<HTMLButtonElement, number>;
	declare private _pointer: { id: number; x: number; y: number } | null;
	declare private _mobileQuery?: MediaQueryList;
	declare private _resolvePublished?: (view: this) => void;
	declare private _shellColdControl?: EventListener | null;

	constructor(node: ViewRoot) {
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

	init(): Promise<this | undefined> | Promise<void>;
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

	ensurePollingCoordinator() {
		return loadViewService(
			this,
			"_pollingPromise",
			"PollingCoordinator",
			async () => {
				const { PollingCoordinator } = await import("../../shared/polling.ts");
				return this._destroyed ? null : new PollingCoordinator(this).init();
			},
		);
	}

	ensureSearchBox() {
		return loadViewService(this, "_searchPromise", "SearchBox", async () => {
			const search = document.querySelector<HTMLElement>("[lp-search]");
			if (!search) return null;
			const { SearchBox } = await import("../../elements/combobox/search.ts");
			if (this._destroyed) return null;
			const box = new SearchBox(search);
			await box.init();
			return box;
		});
	}

	ensureNotifications() {
		return loadViewService(
			this,
			"_notificationsPromise",
			"Notifications",
			async () => {
				if (!document.querySelector("[data-role='notifications']")) return null;
				await this.ensurePollingCoordinator();
				const { Notifications } = await import(
					"../../elements/notifications.ts"
				);
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
				const warmers: Promise<SearchBox | Notifications | null>[] = [];
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

	reportStartupError(
		error: unknown,
		element: Element | null = this.elt,
		context = "lazy-control",
	) {
		void import("../../shared/errors.ts")
			.then(({ captureError }) => {
				captureError(error, element, { context });
			})
			.catch(() => {});
	}

	_installColdControlListeners() {
		this._shellColdControl = (event) => {
			const { target } = event;
			if (!hasClosest(target)) return;
			const search = target.closest("[lp-search]");
			if (search && !this.SearchBox) {
				const clearBtn = target.closest<HTMLButtonElement>(
					"[data-role='search-clear']",
				);
				if (clearBtn && event.type === "click") {
					event.preventDefault();
					const input =
						search.querySelector<HTMLInputElement>("input[name='q']");
					if (input) {
						input.value = "";
						input.focus();
					}
					clearBtn.dataset.visible = "false";
					this.runColdAction(
						search,
						() => this.ensureSearchBox(),
						(box) => box?.clearSearch(),
						search,
					);
					return;
				}
				this.runColdAction(
					search,
					() => this.ensureSearchBox(),
					(box) => this._activateSearchBox(box),
					search,
				);
				return;
			}
			const notifications = target.closest("[data-role='notifications']");
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

	_activateSearchBox(box: SearchBox | null) {
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

	async sync({ hidden = document.hidden }: ViewSyncOptions = {}) {
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

	_mobileChanged(event: MediaQueryListEvent) {
		this.mobile = event.matches;
		this.elt.dispatchEvent(new CustomEvent("mobile-resize"));
	}

	_pointerDown(event: PointerEvent) {
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

	_pointerMove(event: PointerEvent) {
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

	_handleClick(event: MouseEvent) {
		if (this.isDragging) {
			this.isDragging = false;
			return;
		}
		const { target } = event;
		const copyButton = hasClosest(target)
			? target.closest<HTMLButtonElement>("[data-role='manual-command-copy']")
			: null;
		if (copyButton) {
			event.preventDefault();
			void this.copyCommand(copyButton);
			return;
		}
		this._click(event);
	}

	_click(_event: MouseEvent) {}

	async copyCommand(button: HTMLButtonElement) {
		const command = button
			.closest("[data-role='manual-command-shell']")
			?.querySelector("[data-role='manual-command'] code")?.textContent;
		if (!command) return;

		let copied = false;
		if (navigator.clipboard?.writeText) {
			let timeoutId: ReturnType<typeof setTimeout> | undefined;
			try {
				copied = await Promise.race([
					navigator.clipboard.writeText(command).then(() => true),
					new Promise<boolean>((resolve) => {
						timeoutId = setTimeout(() => resolve(false), 250);
					}),
				]);
			} catch {
				copied = false;
			} finally {
				if (timeoutId !== undefined) clearTimeout(timeoutId);
			}
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

	_handleSubmit(event: ViewSubmitEvent) {
		if (!this.ensureSubmissionManager || event.defaultPrevented) return;
		const form = event.target;
		if (!hasClosest(form) || !form.closest("[lp-component]")) return;

		event.preventDefault();
		event.stopPropagation();
		const submitter =
			"submitter" in event && event.submitter && "disabled" in event.submitter
				? event.submitter
				: null;
		if (submitter) submitter.disabled = true;
		let handedOff = false;
		this.runColdAction(
			form,
			() => this.ensureSubmissionManager?.(),
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

	runColdAction<Loaded>(
		owner: Element | null | undefined,
		load: () => Loaded | PromiseLike<Loaded>,
		activate: (value: Loaded) => unknown,
		busyOwner = owner,
	): Promise<unknown> {
		if (!owner || this._destroyed) return Promise.resolve(null);
		const existing = this._coldActions.get(owner);
		if (existing) return existing;

		busyOwner?.setAttribute?.("aria-busy", "true");
		const dataset =
			busyOwner && "dataset" in busyOwner
				? (busyOwner as HTMLElement | SVGElement).dataset
				: undefined;
		if (dataset) dataset.loading = "true";
		const pending = Promise.resolve()
			.then<Loaded>(load)
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
				if (dataset) delete dataset.loading;
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
