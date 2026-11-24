import {
	autoUpdate,
	computePosition,
	flip,
	offset,
	type Placement,
	type ReferenceElement,
	shift,
} from "@floating-ui/dom";
import { STYLES } from "../../generated/styles.mjs";
import { captureError } from "../../shared/errors.ts";
import { generateElementId } from "../../shared/utilities.ts";
import { primitives } from "../primitives.mjs";

export interface ComboboxOption {
	id?: string;
	name?: string;
	kind?: string;
	hash?: string;
	[key: string]: unknown;
}

export interface ComboboxOptionElement extends HTMLElement {
	_checkbox?: HTMLInputElement | null;
}

export interface ComboboxTrigger extends HTMLElement {
	autocomplete?: string;
	name?: string;
	placeholder?: string;
	value?: string;
}

interface ComboboxHost extends HTMLElement {
	_lp_combobox?: Combobox<unknown[]>;
}

export abstract class Combobox<InitArguments extends unknown[] = []> {
	declare _destroyed: boolean;
	declare parent: ComboboxHost;
	declare element: ComboboxTrigger;
	declare mobile: boolean;
	declare options: ComboboxOption[];
	declare items?: ComboboxOption[];
	declare values: Set<string>;
	declare focusedIndex: number;
	declare panel: HTMLDivElement | null;
	declare panelOpen: boolean;
	declare panelReady: Promise<boolean>;
	declare popupRole: string;
	declare optionRole: string;
	declare triggerRole: string | null | undefined;
	declare positionReference: ReferenceElement | null | undefined;
	declare matchReferenceWidth: boolean;
	declare placement: Placement;
	declare styles: { panel: string };
	declare index?: string;
	declare kind: string;
	declare placeholder?: string;
	declare preload?: string;
	declare multiple?: boolean;
	declare creatable?: string;
	declare formType?: string;
	declare includeUsers?: string;
	declare permission?: string;
	declare name?: string;
	declare id: string;
	declare cleanup?: (() => void) | null;
	declare _elementHandlersAdded?: boolean;
	declare _documentHandlersAdded?: boolean;
	declare _panelHandlersAdded?: boolean;
	declare _observer?: IntersectionObserver | null;

	constructor(element: HTMLElement) {
		this._destroyed = false;
		this.parent = element;
		this.element =
			this.parent.querySelector<HTMLInputElement | HTMLSelectElement>(
				"select, input",
			) || element;
		this.mobile = window.matchMedia("(max-width: 768px)").matches;
		this.options = [];
		this.values = new Set();
		this.focusedIndex = -1;
		this.panel = null;
		this.panelOpen = false;
		this.panelReady = Promise.resolve(false);
		this.popupRole = "listbox";
		this.optionRole = "option";
		this.triggerRole = "combobox";
		// Resolve the default at positioning time because some adapters replace
		// the constructor element during init(). Only menus that deliberately float
		// from another element should configure an explicit reference.
		this.positionReference = null;
		this.matchReferenceWidth = false;

		this.elementKeydown = this.elementKeydown.bind(this);
		this.elementClick = this.elementClick.bind(this);
		this._documentClick = this._documentClick.bind(this);
		this._documentKeydown = this._documentKeydown.bind(this);

		this._panelPointerMove = this._panelPointerMove.bind(this);
		this._panelPointerDown = this._panelPointerDown.bind(this);
		this._optionClick = this._optionClick.bind(this);
		this._handleIntersection = this._handleIntersection.bind(this);

		this.placement = this.placement || "bottom-start";
		this.styles = { panel: STYLES.dropdown.panel };

		const data = { ...this.parent.dataset, ...this.element?.dataset };
		this.index = data.index;
		this.kind = data.kind || this.index || "default";
		this.placeholder = data.placeholder;
		this.preload = data.preload;
		this.multiple =
			data.multiple === undefined
				? undefined
				: (JSON.parse(data.multiple) as boolean);
		this.creatable = data.creatable;
		this.formType = data.formType;
		this.includeUsers = data.includeUsers;
		this.permission = data.permission;

		this.name = this.element?.name || this.element?.id || this.index;
		this.id = this.element?.id || generateElementId("combobox");
	}

	// Derived controls can require configuration before the shared DOM setup.
	init(...args: InitArguments): void;
	init() {
		if (this._destroyed) return;
		if (!this.element) throw new Error("Element not found");

		this.element.autocomplete = "off";
		this.element.setAttribute("data-1p-ignore", "");
		this.element.setAttribute("aria-expanded", "false");
		this.element.setAttribute("aria-haspopup", this.popupRole);
		if (this.triggerRole) {
			this.element.setAttribute("role", this.triggerRole);
		} else {
			this.element.removeAttribute("role");
		}
		this.element.setAttribute("spellcheck", "false");
		if (this.placeholder && !this.element.placeholder) {
			this.element.placeholder = this.placeholder;
		}

		// Element handlers live on a specific element and must be attached
		// synchronously so the first click after init() always reaches
		// elementClick. The IntersectionObserver is only used to dismiss an
		// already-open panel if the trigger scrolls out of view.
		this._addElementHandlers();
		this._initElementObserver();
		this.parent.setAttribute("data-combobox-id", this.id);
		this.parent._lp_combobox = this;
		this.element.id = this.id;
	}

	_addElementHandlers() {
		if (this._elementHandlersAdded) return;

		this.element.addEventListener("keydown", this.elementKeydown);
		this.element.addEventListener("click", this.elementClick);
		this._elementHandlersAdded = true;
	}

	_removeElementHandlers() {
		if (!this._elementHandlersAdded) return;

		this.element.removeEventListener("keydown", this.elementKeydown);
		this.element.removeEventListener("click", this.elementClick);
		this._elementHandlersAdded = false;
	}

	_addDocumentHandlers() {
		if (this._documentHandlersAdded) return;

		document.addEventListener("click", this._documentClick, { capture: true });
		document.addEventListener("keydown", this._documentKeydown, {
			capture: true,
		});
		this._documentHandlersAdded = true;
	}

	_removeDocumentHandlers() {
		if (!this._documentHandlersAdded) return;

		document.removeEventListener("click", this._documentClick, {
			capture: true,
		});
		document.removeEventListener("keydown", this._documentKeydown, {
			capture: true,
		});
		this._documentHandlersAdded = false;
	}

	_initElementObserver() {
		this._observer = new IntersectionObserver(this._handleIntersection, {
			threshold: 0,
		});
		this._observer.observe(this.element);
	}

	_handleIntersection(entries: IntersectionObserverEntry[]) {
		entries.forEach((entry) => {
			if (!entry.isIntersecting && this.panelOpen) {
				this.hidePanel();
			}
		});
	}

	_addPanelHandlers() {
		if (this._panelHandlersAdded || !this.panel) return;

		this.panel.addEventListener("pointermove", this._panelPointerMove);
		this.panel.addEventListener("pointerdown", this._panelPointerDown);
		this.panel.addEventListener("click", this._optionClick);
		this._panelHandlersAdded = true;
	}

	_removePanelHandlers() {
		if (!this._panelHandlersAdded) return;

		this.panel?.removeEventListener("pointermove", this._panelPointerMove);
		this.panel?.removeEventListener("pointerdown", this._panelPointerDown);
		this.panel?.removeEventListener("click", this._optionClick);
		this._panelHandlersAdded = false;
	}

	_createPanel() {
		if (this._destroyed || this.panel) return;

		this.panel = document.createElement("div");
		this.panel.id = `${this.id}-panel`;
		this.panel.setAttribute("role", this.popupRole);
		this.panel.setAttribute("aria-labelledby", this.id);
		this.panel.className = this.styles.panel;
		this.panel.dataset.kind = this.kind;
		this.panel.dataset.visible = "false";

		this.element.setAttribute("aria-controls", this.panel.id);

		document.body.appendChild(this.panel);
	}

	_startAutoUpdate() {
		this._cleanupAutoUpdate();
		if (this._destroyed) return Promise.resolve(false);
		const reference = this.positionReference || this.element;
		const panel = this.panel;
		if (!panel) return Promise.resolve(false);
		let active = true;
		let positionRequest = 0;
		let readySettled = false;
		let resolveReady: (positioned: boolean) => void;
		let rejectReady: (error: unknown) => void;
		const ready = new Promise<boolean>((resolve, reject) => {
			resolveReady = resolve;
			rejectReady = reject;
		});
		const settleReady = (positioned: boolean, error: unknown = null) => {
			if (readySettled) {
				if (error) captureError(error, panel);
				return;
			}
			readySettled = true;
			if (error) rejectReady(error);
			else resolveReady(positioned);
		};
		const cleanup = autoUpdate(reference, panel, () => {
			if (!active || this._destroyed || this.panel !== panel) return;
			const request = ++positionRequest;
			const middleware = [
				offset(4),
				// Try the opposite alignment before shifting away from the anchor.
				flip({ padding: 5 }),
				shift({ padding: 5 }),
			];

			if (this.matchReferenceWidth) {
				const { width } = reference.getBoundingClientRect();
				panel.style.minWidth = `${Math.ceil(width)}px`;
			} else if (this.element.classList.contains("w-full")) {
				const { width } = this.element.getBoundingClientRect();
				panel.style.width = `${Math.round(width)}px`;
			}

			computePosition(reference, panel, {
				// Reconsider the preferred placement after each resize or move.
				placement: this.placement,
				middleware: middleware,
			})
				.then(({ x, y }) => {
					if (!active || this._destroyed || this.panel !== panel) {
						settleReady(false);
						return;
					}
					if (request !== positionRequest) return;
					Object.assign(panel.style, {
						left: `${x}px`,
						top: `${y}px`,
					});
					settleReady(true);
				})
				.catch((error: unknown) => {
					if (!active || this._destroyed || this.panel !== panel) {
						settleReady(false);
						return;
					}
					if (request !== positionRequest) return;
					settleReady(false, error);
				});
		});
		this.cleanup = () => {
			active = false;
			cleanup();
			settleReady(false);
		};
		return ready;
	}

	_cleanupAutoUpdate() {
		if (this.cleanup) {
			this.cleanup();
			this.cleanup = null;
		}
	}

	_addCheckbox(option: ComboboxOptionElement) {
		const id = option.dataset.id;
		const checkboxElement = primitives.checkbox({
			checked: id !== undefined && this.values.has(id),
			kind: this.kind,
			label: false,
		});
		checkboxElement.dataset.role = "option-checkbox";

		option.appendChild(checkboxElement);
		option.className =
			`${option.className} ${STYLES.dropdown.option.multiple}`.trim();
		option._checkbox = checkboxElement.querySelector("input");
	}

	updatePanel(html: string | null | undefined) {
		if (this._destroyed) return false;
		if (!this.panel) this._createPanel();
		const panel = this.panel;
		if (!panel) return false;
		this.options = [];
		this.focusedIndex = -1;
		this.element.removeAttribute("aria-activedescendant");
		panel.innerHTML = html || "";
		if (!html) {
			this.hidePanel();
			return;
		}

		panel
			.querySelectorAll<ComboboxOptionElement>(`[role='${this.optionRole}']`)
			.forEach((optionElt, index) => {
				optionElt.dataset.index = String(index);
				if (!optionElt.id) optionElt.id = `${panel.id}-opt-${index}`;
				if (this.items) {
					this.items[index].id = optionElt.id;
					this.options.push(this.items[index]);
				} else {
					// Server-rendered rows serialize their option details in this attribute.
					const details = JSON.parse(
						optionElt.dataset.details || "{}",
					) as ComboboxOption;
					const option = {
						...optionElt.dataset,
						...details,
					};
					this.options.push(option);
				}
				if (this.multiple && optionElt.dataset.id) {
					this._addCheckbox(optionElt);
				}
			});

		if (this.options.length === 0) {
			this.hidePanel();
		}
	}

	showPanel(): Promise<boolean> {
		if (this._destroyed) return Promise.resolve(false);
		const panel = this.panel;
		if (!panel?.querySelector(`[role='${this.optionRole}']`)) {
			this.hidePanel();
			return Promise.resolve(false);
		}
		if (this.panelOpen) return this.panelReady;

		this.panelOpen = true;
		panel.classList.remove("hidden");
		panel.dataset.visible = "true";
		panel.dataset.positioned = "false";
		this.element.setAttribute("aria-expanded", "true");
		this.element.dataset.panel = "open";

		this._addPanelHandlers();
		this._addDocumentHandlers();

		const panelReady = Promise.resolve(this._startAutoUpdate())
			.then((positioned) => {
				if (
					positioned === false ||
					this.panelReady !== panelReady ||
					this.panel !== panel ||
					!this.panelOpen
				) {
					return false;
				}

				panel.dataset.positioned = "true";

				document
					.querySelectorAll<ComboboxHost>("[data-combobox-id]")
					.forEach((combobox) => {
						if (combobox._lp_combobox && combobox._lp_combobox !== this) {
							combobox._lp_combobox.hidePanel();
						}
					});
				return true;
			})
			.catch((error: unknown) => {
				if (this.panelReady === panelReady && this.panel === panel) {
					this.hidePanel();
				}
				captureError(error, panel);
				return false;
			});
		this.panelReady = panelReady;
		return panelReady;
	}

	hidePanel(): boolean | undefined {
		const wasOpen = this.panelOpen;

		this.panelOpen = false;
		this.panelReady = Promise.resolve(false);
		this.panel?.classList.add("hidden");
		if (this.panel) {
			this.panel.dataset.visible = "false";
			this.panel.dataset.positioned = "false";
		}
		this.element.setAttribute("aria-expanded", "false");
		this.element.dataset.panel = "closed";
		this.unfocusOption();
		this._removePanelHandlers();
		this._removeDocumentHandlers();
		this._cleanupAutoUpdate();

		if (wasOpen) return true;
	}

	elementClick(event: MouseEvent, hidePanel = true) {
		event.stopPropagation();

		if (this.panelOpen && hidePanel) {
			this.hidePanel();
		}

		this.element.focus();
	}

	elementKeydown(event: KeyboardEvent) {
		const count = this.options.length;
		const next = () =>
			this.focusedIndex >= count - 1 ? 0 : this.focusedIndex + 1;
		const prev = () =>
			this.focusedIndex <= 0 ? count - 1 : this.focusedIndex - 1;

		switch (event.key) {
			case "ArrowDown":
				if (this.panelOpen && count > 0) {
					event.stopPropagation();
					event.preventDefault();
					this.focusOption(next());
				}
				break;
			case "ArrowUp":
				if (this.panelOpen && count > 0) {
					event.stopPropagation();
					event.preventDefault();
					this.focusOption(prev());
				}
				break;
			case "Enter": {
				if (this.panelOpen && this.focusedIndex >= 0) {
					event.stopPropagation();
					event.preventDefault();
					const option = this.focusedOption();
					if (option) this.selectOption(option);
				}
				break;
			}
			case "Tab":
				if (this.panelOpen) this.hidePanel();
				break;
		}
	}

	focusedOption(): ComboboxOptionElement | null {
		if (this.focusedIndex < 0) return null;
		return (
			this.panel?.querySelector<ComboboxOptionElement>(
				`[data-index="${this.focusedIndex}"]`,
			) ?? null
		);
	}

	focusOption(index: number) {
		const currentOption = this.focusedOption();
		if (currentOption) {
			this.unfocusOption(currentOption);
		}
		const option = this.panel?.querySelector<ComboboxOptionElement>(
			`[data-index="${index}"]`,
		);
		if (!option) return;
		option.setAttribute("aria-selected", "true");
		option.scrollIntoView({ block: "nearest" });
		this.focusedIndex = Number.parseInt(option.dataset.index ?? "", 10);
		this.element.setAttribute("aria-activedescendant", option.id);
	}

	unfocusOption(option?: ComboboxOptionElement | null) {
		const currentOption = option || this.focusedOption();
		if (!currentOption) return;

		currentOption.setAttribute("aria-selected", "false");
		this.focusedIndex = -1;
		this.element.removeAttribute("aria-activedescendant");
	}

	_panelPointerDown(event: PointerEvent) {
		// Keep DOM focus on the trigger so aria-activedescendant keeps working
		// and the input doesn't lose focus when the user clicks an option.
		event.preventDefault();
	}

	_documentClick(event: MouseEvent) {
		if (
			this.panelOpen &&
			event.target instanceof Node &&
			!this.element.contains(event.target) &&
			!this.panel?.contains(event.target)
		) {
			this.deactivate();
		}
	}

	_documentKeydown(event: KeyboardEvent) {
		if (this.panelOpen && event.key === "Escape") {
			this.deactivate();
		}
	}

	_panelPointerMove(event: PointerEvent) {
		if (!(event.target instanceof Element)) return;
		const option = event.target.closest<ComboboxOptionElement>(
			`[role="${this.optionRole}"]`,
		);
		if (!option) return;

		const index = Number.parseInt(option.dataset.index ?? "", 10);
		if (index === this.focusedIndex) return;

		this.focusOption(index);
	}

	_optionClick(event: MouseEvent) {
		if (!(event.target instanceof Element)) return;
		const option = event.target.closest<ComboboxOptionElement>(
			`[role="${this.optionRole}"]`,
		);
		if (option) {
			event.stopPropagation();
			this.selectOption(option, event);
		}
	}

	abstract selectOption(
		option: ComboboxOptionElement,
		event?: MouseEvent | null,
	): void;

	show() {
		this.element.focus();
	}

	hide() {
		if (this.panelOpen) {
			this.hidePanel();
		}
	}

	deactivate() {
		this.hidePanel();
		this.element.dispatchEvent(new Event("deactivate", { bubbles: true }));
	}

	destroy() {
		if (this._destroyed) return;
		this._destroyed = true;
		this._removeElementHandlers();
		this._removePanelHandlers();
		this._removeDocumentHandlers();
		this._cleanupAutoUpdate();
		if (this._observer) {
			this._observer.disconnect();
			this._observer = null;
		}
		this.hidePanel();
		if (this.panel) this.panel.remove();
		this.panel = null;
		this.element.removeAttribute("aria-controls");
		this.parent.removeAttribute("data-combobox-id");
		if (this.parent._lp_combobox === this) {
			delete this.parent._lp_combobox;
		}
	}
}
