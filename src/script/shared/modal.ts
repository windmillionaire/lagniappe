import { STYLES } from "../generated/styles.mjs";
import { ENDPOINTS } from "./endpoints.ts";
import { captureError } from "./errors.ts";
import { request } from "./request.ts";
import { withTransition } from "./transitions.ts";

const HELP_TOPIC_PATH_RE = /^\/help\/([a-z][a-z0-9]*(?:_[a-z0-9]+)*)$/;

interface ModalView {
	_destroyed?: boolean;
	dataset?: DOMStringMap;
	reconcileChange?: (change: { type: "delete"; key: string | null }) => unknown;
}

type ModalElement = HTMLElement & { _lp_modal?: Modal };
type BeforeModalAttach = (modal: ModalElement) => unknown;
type ModalTrigger = HTMLElement & { disabled?: boolean };

type ComponentElement = HTMLElement & {
	_lp_component?: {
		active?: { target?: HTMLElement | null } | null;
		destroy(): void;
		help?: string;
	};
};

export class Modal {
	declare _destroyed: boolean;
	declare _listenersAttached: boolean;
	declare _scrollLocked: boolean;
	declare _modal: ModalElement | null;
	declare _previousFocus: HTMLElement | null;
	declare trigger: ModalTrigger | null | undefined;
	declare view: ModalView | null | undefined;
	declare keydown: (event: KeyboardEvent) => void;
	declare click: (event: MouseEvent) => void;
	declare key: string | null;

	constructor(view?: ModalView | null, trigger?: ModalTrigger | null) {
		this._destroyed = false;
		this._listenersAttached = false;
		this._scrollLocked = false;
		this._modal = null;
		this._previousFocus = null;
		this.trigger = trigger;
		this.view = view;
		this.keydown = this._keydown.bind(this);
		this.click = this._click.bind(this);
		this.key = null;
	}

	_lockScroll() {
		if (this._scrollLocked) return;
		const root = document.documentElement;
		const count = Number(root.dataset.modalLockCount || "0");
		if (count === 0) {
			root.dataset.modalPrevOverflow = root.style.overflow;
			root.style.overflow = "hidden";
			for (const el of document.querySelectorAll<HTMLElement>(
				'body > header, body > nav.main-nav, body > main, body > section[data-role="upstream-unavailable"]',
			)) {
				if (this._modal && el.contains(this._modal)) continue;
				const wasInert = Boolean(el.inert || el.hasAttribute("inert"));
				el.dataset.modalPrevInert = wasInert ? "true" : "false";
				el.inert = true;
				el.setAttribute("inert", "");
			}
		}
		root.dataset.modalLockCount = String(count + 1);
		this._scrollLocked = true;
	}

	_unlockScroll() {
		if (!this._scrollLocked) return;
		this._scrollLocked = false;
		const root = document.documentElement;
		const next = Math.max(0, Number(root.dataset.modalLockCount || "1") - 1);
		if (next === 0) {
			root.style.overflow = root.dataset.modalPrevOverflow ?? "";
			delete root.dataset.modalLockCount;
			delete root.dataset.modalPrevOverflow;
			for (const el of document.querySelectorAll<HTMLElement>(
				"[data-modal-prev-inert]",
			)) {
				const restoreInert = el.dataset.modalPrevInert === "true";
				el.inert = restoreInert;
				if (restoreInert) el.setAttribute("inert", "");
				else el.removeAttribute("inert");
				delete el.dataset.modalPrevInert;
			}
		} else {
			root.dataset.modalLockCount = String(next);
		}
	}

	_focusableElements(modal: HTMLElement): HTMLElement[] {
		const candidates = modal.querySelectorAll<HTMLElement>(
			'button:not([disabled]):not([hidden]), [href]:not([hidden]), input:not([disabled]):not([type="hidden"]):not([hidden]), select:not([disabled]):not([hidden]), textarea:not([disabled]):not([hidden]), [tabindex]:not([tabindex="-1"]):not([hidden])',
		);
		return Array.from(candidates).filter(
			(el) =>
				!el.hidden && !el.closest("[hidden]") && el.dataset.visible !== "false",
		);
	}

	_attachListeners() {
		if (this._destroyed || this._listenersAttached || !this.modal) return;
		document.addEventListener("keydown", this.keydown);
		document.addEventListener("click", this.click);
		this.modal._lp_modal = this;
		this._listenersAttached = true;
	}

	_detach(restoreFocus = true) {
		if (this._listenersAttached) {
			document.removeEventListener("keydown", this.keydown);
			document.removeEventListener("click", this.click);
			this._listenersAttached = false;
		}
		const modal = this._modal;
		if (modal?._lp_modal === this) delete modal._lp_modal;
		modal?.remove();
		this._modal = null;
		this._unlockScroll();
		if (this.trigger) this.trigger.disabled = false;
		if (restoreFocus) {
			const previousFocus = this._previousFocus?.isConnected
				? this._previousFocus
				: this.trigger?.isConnected
					? this.trigger
					: null;
			this._previousFocus = null;
			previousFocus?.focus({ preventScroll: true });
		}
	}

	destroy() {
		if (this._destroyed) return;
		this._destroyed = true;
		this._previousFocus = null;
		this._detach(false);
	}

	get modal() {
		return this._modal;
	}

	_keydown(event: KeyboardEvent) {
		const modal = this.modal;
		if (!modal) return;

		if (event.key === "Escape") {
			this.remove();
		} else if (
			event.key === "Enter" &&
			event.target instanceof HTMLElement &&
			event.target.tagName === "BUTTON"
		) {
			event.target.click();
		} else if (event.key === "Tab") {
			const focusable = this._focusableElements(modal);
			if (!focusable.length) return;

			const first = focusable[0];
			const last = focusable[focusable.length - 1];

			if (event.shiftKey) {
				if (
					document.activeElement === first ||
					!modal.contains(document.activeElement)
				) {
					event.preventDefault();
					last.focus();
				}
			} else {
				if (
					document.activeElement === last ||
					!modal.contains(document.activeElement)
				) {
					event.preventDefault();
					first.focus();
				}
			}
		}
	}

	_click(event: MouseEvent) {
		const modal = this.modal;
		const target = event.target;
		if (!(target instanceof Node)) return;

		if (this.trigger?.contains(target)) return;

		const content = modal?.querySelector("#modal-content");
		if (content && !content.contains(target)) {
			this.remove();
		} else if (
			target instanceof Element &&
			target.closest("[lp-control='close']")
		) {
			event.stopPropagation();
			this.remove();
		}
	}

	async remove() {
		if (!this.modal) return;
		await withTransition(
			() => {
				this._detach();
			},
			{ label: "modal:remove" },
		);
	}

	async load(route: string, beforeAttach?: BeforeModalAttach) {
		if (this._destroyed || this.view?._destroyed) return null;
		if (this.trigger) this.trigger.disabled = true;
		try {
			const modal = await request.get(route);
			if (this._destroyed || this.view?._destroyed) {
				if (this.trigger) this.trigger.disabled = false;
				return null;
			}
			if (!modal?.html) {
				captureError(new Error("No modal HTML provided"), this.trigger, {
					view: this.view?.dataset,
					route,
					modal,
				});
				if (this.trigger) this.trigger.disabled = false;
				return null;
			}
			const attached = await this.attach(modal.html, undefined, beforeAttach);
			if (this.trigger && !attached) this.trigger.disabled = false;
			return attached;
		} catch (error) {
			captureError(error, this.trigger, this.view?.dataset);
			if (this.trigger) this.trigger.disabled = false;
		}
	}

	async attach(
		html: Document | HTMLElement,
		component?: unknown,
		beforeAttach?: BeforeModalAttach,
	): Promise<ModalElement | null | undefined> {
		if (this._destroyed || this.view?._destroyed) return null;
		try {
			const modal =
				html.querySelector<ModalElement>("#modal") ||
				(html instanceof HTMLElement ? html : null);
			if (!modal) return null;
			if (beforeAttach?.(modal) === false) {
				if (this.trigger) this.trigger.disabled = false;
				return null;
			}
			if (
				!this._previousFocus &&
				document.activeElement instanceof HTMLElement &&
				!this._modal?.contains(document.activeElement)
			) {
				this._previousFocus = document.activeElement;
			}
			if (this.trigger) this.trigger.disabled = true;
			await withTransition(
				() => {
					if (this._destroyed || this.view?._destroyed) return;
					this._detach(false);
					this._modal = modal;
					this._lockScroll();
					document.body.appendChild(modal);
					this._attachListeners();
					if (!modal.contains(document.activeElement)) {
						const autofocusTarget = modal.querySelector<HTMLElement>(
							"[autofocus]:not([hidden])",
						);
						const focusTarget =
							(autofocusTarget &&
							!autofocusTarget.hidden &&
							!autofocusTarget.closest("[hidden]")
								? autofocusTarget
								: null) ||
							this._focusableElements(modal)[0] ||
							modal;
						if (focusTarget === modal && !modal.hasAttribute("tabindex")) {
							modal.tabIndex = -1;
						}
						focusTarget.focus({ preventScroll: true });
					}
				},
				{ label: "modal:attach" },
			);
			return this.modal;
		} catch (error) {
			captureError(error, component, this.view?.dataset);
			return null;
		}
	}
}

export class DeleteModal extends Modal {
	declare deleteButton: HTMLButtonElement | null | undefined;

	async init() {
		const trigger = this.trigger;
		if (!trigger) return;
		const entity =
			trigger.closest<HTMLElement>("[lp-entity]") ||
			trigger
				.closest<ComponentElement>("[lp-component]")
				?._lp_component?.active?.target?.closest<HTMLElement>("[lp-entity]");
		this.key =
			trigger.dataset.deleteKey || entity?.dataset?.key || entity?.id || null;

		if (!this.key || !this.view) {
			captureError(
				new Error("No key or view provided"),
				this.trigger,
				this.view?.dataset,
			);
			return;
		}

		let missingDeleteButton = false;
		await this.load(
			trigger.dataset.deleteModalRoute || ENDPOINTS.delete(this.key),
			(modalElt) => {
				const deleteButton = modalElt.querySelector<HTMLButtonElement>(
					"[data-role='delete']",
				);
				if (!deleteButton) {
					missingDeleteButton = true;
					return false;
				}
				this.deleteButton = deleteButton;
				this.deleteButton.addEventListener("click", this.delete.bind(this));
			},
		);

		if (missingDeleteButton) {
			captureError(
				new Error("Delete modal missing [data-role='delete']"),
				this.trigger,
				{ view: this.view?.dataset },
			);
			return;
		}

		const modal = this.modal;
		if (!modal) {
			if (this.trigger) this.trigger.disabled = false;
			return;
		}

		const closeBtn =
			modal.querySelector<HTMLElement>("[lp-control='close']") ??
			this.deleteButton;
		if (closeBtn) {
			closeBtn.focus();
			requestAnimationFrame(() => {
				if (this._destroyed || !modal.isConnected) return;
				if (!modal.contains(document.activeElement)) closeBtn.focus();
			});
		}
	}

	removeEntity(key: string) {
		document
			.querySelectorAll<ComponentElement>(`[data-key='${key}']`)
			.forEach((elt) => {
				if (elt._lp_component) elt._lp_component.destroy();
				elt.remove();
			});
	}

	async delete() {
		const { deleteButton, modal } = this;
		if (!deleteButton || !modal) return;
		const spinner = deleteButton.querySelector<HTMLElement>("#spinner");
		try {
			const route = deleteButton.dataset.route;
			if (!spinner || !route)
				throw new Error("Delete action is missing its spinner or route");
			deleteButton.disabled = true;
			spinner.dataset.visible = "true";
			const options = Array.from(
				modal.querySelectorAll<HTMLInputElement>("[data-delete-option][name]"),
			);
			const data = options.length
				? Object.fromEntries(
						options.map((option) => [option.name, option.checked]),
					)
				: null;

			const response = await request.delete(route, data);
			if (!response?.ok) {
				deleteButton.disabled = false;
				spinner.dataset.visible = "false";
				return;
			}

			await this.remove();
			const returnUrl = this.trigger?.dataset.returnUrl;
			if (returnUrl) {
				window.location.assign(returnUrl);
				return;
			}

			await this.view?.reconcileChange?.({ type: "delete", key: this.key });
		} catch (error) {
			deleteButton.disabled = false;
			if (spinner) spinner.dataset.visible = "false";
			captureError(error, deleteButton, this.view?.dataset);
		}
	}
}

export class HelpModal extends Modal {
	declare _currentTopic: string | null;
	declare _topicHistory: string[];
	declare _navigating: boolean;

	async init() {
		const trigger = this.trigger;
		if (!trigger) return;
		const section =
			trigger.closest<ComponentElement>("[lp-component]")?._lp_component
				?.help ||
			trigger.getAttribute("lp-help") ||
			trigger.closest("nav[lp-help]")?.getAttribute("lp-help");

		if (!section) {
			captureError(
				new Error("No section provided"),
				this.trigger,
				this.view?.dataset,
			);
			return;
		}

		this._topicHistory = [];
		this._navigating = false;
		await this.load(ENDPOINTS.help(section));
		if (this.modal) this._currentTopic = section;
	}

	_detach(restoreFocus = true) {
		this._topicHistory = [];
		this._currentTopic = null;
		this._navigating = false;
		super._detach(restoreFocus);
	}

	_click(event: MouseEvent) {
		const modal = this.modal;
		const target = event.target;
		if (modal && target instanceof Element && modal.contains(target)) {
			if (target.closest("[data-role='help-modal-back']")) {
				event.preventDefault();
				event.stopPropagation();
				void this._goBack();
				return;
			}
			if (
				event.button === 0 &&
				!event.metaKey &&
				!event.ctrlKey &&
				!event.shiftKey &&
				!event.altKey
			) {
				const link = target.closest<HTMLAnchorElement>("a[href]");
				if (link && !link.hasAttribute("data-help-index") && !link.target) {
					const rawHref = link.getAttribute("href");
					if (rawHref) {
						try {
							const url = new URL(rawHref, window.location.origin);
							if (url.origin === window.location.origin) {
								const match = HELP_TOPIC_PATH_RE.exec(url.pathname);
								if (match) {
									event.preventDefault();
									event.stopPropagation();
									void this._navigateTopic(match[1], { pushHistory: true });
									return;
								}
							}
						} catch {
							// Malformed hrefs fall through to default handling.
						}
					}
				}
			}
		}
		super._click(event);
	}

	async _goBack() {
		const previous = this._topicHistory.pop();
		if (!previous) return;
		await this._navigateTopic(previous, { pushHistory: false });
	}

	async _navigateTopic(topicId: string, options: { pushHistory: boolean }) {
		if (
			this._destroyed ||
			this.view?._destroyed ||
			!this.modal ||
			this._navigating ||
			topicId === this._currentTopic
		) {
			return;
		}
		this._navigating = true;
		try {
			const response = await request.get(ENDPOINTS.help(topicId));
			if (this._destroyed || this.view?._destroyed || !this.modal) return;
			const html =
				response?.html && typeof response.html !== "string"
					? response.html
					: null;
			const nextTitle = html
				?.querySelector("#modal-title")
				?.textContent?.trim();
			const nextBody = html?.querySelector("[data-role='help-modal-body']");
			if (!nextBody) {
				window.location.assign(`/help/${topicId}`);
				return;
			}
			const activeModal = this.modal;
			await withTransition(
				() => {
					if (this._destroyed || !activeModal.isConnected) return;
					if (options.pushHistory && this._currentTopic) {
						this._topicHistory.push(this._currentTopic);
					}
					this._currentTopic = topicId;
					const titleEl =
						activeModal.querySelector<HTMLElement>("#modal-title");
					if (titleEl && nextTitle) titleEl.textContent = nextTitle;
					const bodyEl = activeModal.querySelector<HTMLElement>(
						"[data-role='help-modal-body']",
					);
					if (bodyEl) {
						bodyEl.replaceChildren(...nextBody.childNodes);
						bodyEl.scrollTop = 0;
					}
					const backButton = activeModal.querySelector<HTMLButtonElement>(
						"[data-role='help-modal-back']",
					);
					if (backButton) {
						backButton.hidden = this._topicHistory.length === 0;
					}
					const focusTarget =
						backButton && !backButton.hidden
							? backButton
							: activeModal.querySelector<HTMLElement>("[lp-control='close']");
					focusTarget?.focus({ preventScroll: true });
				},
				{ label: "help-modal:navigate" },
			);
		} catch (error) {
			captureError(error, this.modal, this.view?.dataset);
		} finally {
			this._navigating = false;
		}
	}
}

export class OfflineModal extends Modal {
	declare _enabled: boolean;
	declare _triggerClick: () => void;

	constructor(view?: ModalView | null, trigger?: ModalTrigger | null) {
		super(view, trigger);
		this._enabled = false;
		this._triggerClick = () => {
			void this.attach();
		};
	}

	async attach() {
		if (this._destroyed || this.view?._destroyed || this.modal) {
			return this.modal;
		}
		const modal = document.createElement("div");
		modal.id = "modal";
		modal.className = STYLES.modal.wrapper;

		const content = modal.appendChild(document.createElement("div"));
		content.className = STYLES.modal.content;
		content.id = "modal-content";

		const header = content.appendChild(document.createElement("div"));
		header.className = STYLES.modal.header;
		const headerText = header.appendChild(document.createElement("h2"));
		headerText.textContent = "Offline";
		headerText.className = "text-lg font-bold text-base-dark";
		const close = header.appendChild(document.createElement("button"));
		close.textContent = "Close";
		close.className = `${STYLES.button.close}`;
		close.onclick = () => {
			void this.remove();
		};

		const body = content.appendChild(document.createElement("div"));
		body.className = "p-6 text-slate-600";
		const bodyText = body.appendChild(document.createElement("p"));
		bodyText.textContent =
			"You are offline (or the server is starting up). You will be able to view any pages that have been " +
			"cached, but search, documents and forms will be in read-only mode until you are online again.";

		await super.attach(modal);
		return undefined;
	}

	enable() {
		if (!this.trigger || this._destroyed || this._enabled) return;
		this.trigger.addEventListener("click", this._triggerClick);
		this._enabled = true;
	}

	disable() {
		if (!this.trigger || !this._enabled) return;
		this.trigger.removeEventListener("click", this._triggerClick);
		this._enabled = false;
	}

	destroy() {
		if (this._destroyed) return;
		this.disable();
		super.destroy();
	}
}
