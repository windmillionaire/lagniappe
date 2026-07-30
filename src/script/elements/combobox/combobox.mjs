import {
	autoUpdate,
	computePosition,
	flip,
	offset,
	shift,
} from "@floating-ui/dom";
import { STYLES } from "styles";
import { generateElementId } from "../../shared";
import { primitives } from "../primitives";

/**
 * @testable true
 * @tests tests_js/test_016_combobox_frontend.py::test_combobox_positioning_uses_live_element_by_default_and_explicit_reference_when_configured
 * @tests tests_js/test_016_combobox_frontend.py::test_combobox_aria_and_keyboard_state_follow_the_open_panel
 * @tests tests_js/test_016_combobox_frontend.py::test_combobox_pointer_and_dismissal_events_preserve_trigger_focus
 * @tests tests_js/test_016_combobox_frontend.py::test_combobox_hides_empty_recent_panel_but_keeps_server_empty_result_row
 * @tests tests_js/test_016_combobox_frontend.py::test_combobox_copies_only_supported_dataset_configuration
 * @features combobox
 * @dimensions positioning aria keyboard pointer dismissal empty-results dataset-configuration
 */
export class Combobox {
	constructor(element) {
		this.parent = element;
		this.element = this.parent.querySelector("select, input") || element;
		this.mobile = window.matchMedia("(max-width: 768px)").matches;
		this.options = [];
		this.values = new Set();
		this.focusedIndex = -1;
		this.panel = null;
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

		this._panelPointerOver = this._panelPointerOver.bind(this);
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
			data.multiple === undefined ? undefined : JSON.parse(data.multiple);
		this.creatable = data.creatable;
		this.formType = data.formType;
		this.includeUsers = data.includeUsers;
		this.permission = data.permission;

		this.name = this.element?.name || this.element?.id || this.index;
		this.id = this.element?.id || generateElementId("combobox");
	}

	init() {
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

	_handleIntersection(entries) {
		entries.forEach((entry) => {
			if (!entry.isIntersecting && this.panelOpen) {
				this.hidePanel();
			}
		});
	}

	_addPanelHandlers() {
		if (this._panelHandlersAdded) return;

		this.panel.addEventListener("pointerover", this._panelPointerOver);
		this.panel.addEventListener("pointerdown", this._panelPointerDown);
		this.panel.addEventListener("click", this._optionClick);
		this._panelHandlersAdded = true;
	}

	_removePanelHandlers() {
		if (!this._panelHandlersAdded) return;

		this.panel.removeEventListener("pointerover", this._panelPointerOver);
		this.panel.removeEventListener("pointerdown", this._panelPointerDown);
		this.panel.removeEventListener("click", this._optionClick);
		this._panelHandlersAdded = false;
	}

	_createPanel() {
		if (this.panel) return;

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
		const reference = this.positionReference || this.element;

		this.cleanup = autoUpdate(reference, this.panel, () => {
			const middleware = [
				offset(4),
				shift({ padding: 5 }),
				flip({ padding: 5 }),
			];

			if (this.matchReferenceWidth) {
				const { width } = reference.getBoundingClientRect();
				this.panel.style.minWidth = `${Math.ceil(width)}px`;
			} else if (this.element.classList.contains("w-full")) {
				const { width } = this.element.getBoundingClientRect();
				this.panel.style.width = `${Math.round(width)}px`;
			}

			computePosition(reference, this.panel, {
				placement: this.placement,
				middleware: middleware,
			}).then(({ x, y, placement }) => {
				Object.assign(this.panel.style, {
					left: `${x}px`,
					top: `${y}px`,
				});
				this.placement = placement;
			});
		});
	}

	_cleanupAutoUpdate() {
		if (this.cleanup) {
			this.cleanup();
			this.cleanup = null;
		}
	}

	_addCheckbox(option) {
		const checkboxElement = primitives.checkbox({
			checked: this.values.has(option.dataset.id),
			kind: this.kind,
			label: false,
		});
		checkboxElement.dataset.role = "option-checkbox";

		option.appendChild(checkboxElement);
		option.className =
			`${option.className} ${STYLES.dropdown.option.multiple}`.trim();
		option._checkbox = checkboxElement.querySelector("input");
	}

	updatePanel(html) {
		if (!this.panel) this._createPanel();
		this.options = [];
		this.focusedIndex = -1;
		this.element.removeAttribute("aria-activedescendant");
		this.panel.innerHTML = html || "";
		if (!html) {
			this.hidePanel();
			return;
		}

		this.panel
			.querySelectorAll(`[role='${this.optionRole}']`)
			.forEach((optionElt, index) => {
				optionElt.dataset.index = index;
				if (!optionElt.id) optionElt.id = `${this.panel.id}-opt-${index}`;
				if (this.items) {
					this.items[index].id = optionElt.id;
					this.options.push(this.items[index]);
				} else {
					const option = {
						...optionElt.dataset,
						...JSON.parse(optionElt.dataset.details || "{}"),
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

	showPanel() {
		const renderedOptions =
			this.panel?.querySelectorAll(`[role='${this.optionRole}']`).length || 0;
		if (renderedOptions === 0) {
			this.hidePanel();
			return;
		}

		this.panelOpen = true;
		this.panel.classList.remove("hidden");
		this.panel.dataset.visible = "true";
		this.element.setAttribute("aria-expanded", "true");
		this.element.dataset.panel = "open";

		this._addPanelHandlers();
		this._addDocumentHandlers();
		this._startAutoUpdate();

		document.querySelectorAll("[data-combobox-id]").forEach((combobox) => {
			if (combobox._lp_combobox && combobox._lp_combobox !== this) {
				combobox._lp_combobox.hidePanel();
			}
		});
	}

	hidePanel() {
		const wasOpen = this.panelOpen;

		this.panelOpen = false;
		this.panel?.classList.add("hidden");
		if (this.panel) this.panel.dataset.visible = "false";
		this.element.setAttribute("aria-expanded", "false");
		this.element.dataset.panel = "closed";
		this.unfocusOption();
		this._removePanelHandlers();
		this._removeDocumentHandlers();
		this._cleanupAutoUpdate();

		if (wasOpen) return true;
	}

	elementClick(event, hidePanel = true) {
		event.stopPropagation();

		if (this.panelOpen && hidePanel) {
			this.hidePanel();
		}

		this.element.focus();
	}

	elementKeydown(event) {
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

	focusedOption() {
		if (this.focusedIndex < 0) return null;
		return this.panel.querySelector(`[data-index="${this.focusedIndex}"]`);
	}

	focusOption(index) {
		const currentOption = this.focusedOption();
		if (currentOption) {
			this.unfocusOption(currentOption);
		}
		const option = this.panel.querySelector(`[data-index="${index}"]`);
		option.setAttribute("aria-selected", "true");
		option.scrollIntoView({ block: "nearest" });
		this.focusedIndex = parseInt(option.dataset.index, 10);
		this.element.setAttribute("aria-activedescendant", option.id);
	}

	unfocusOption(option) {
		const currentOption = option || this.focusedOption();
		if (!currentOption) return;

		currentOption.setAttribute("aria-selected", "false");
		this.focusedIndex = -1;
		this.element.removeAttribute("aria-activedescendant");
	}

	_panelPointerDown(event) {
		// Keep DOM focus on the trigger so aria-activedescendant keeps working
		// and the input doesn't lose focus when the user clicks an option.
		event.preventDefault();
	}

	_documentClick(e) {
		if (
			this.panelOpen &&
			!this.element.contains(e.target) &&
			!this.panel.contains(e.target)
		) {
			this.deactivate();
		}
	}

	_documentKeydown(event) {
		if (this.panelOpen && event.key === "Escape") {
			this.deactivate();
		}
	}

	_panelPointerOver(event) {
		const option = event.target.closest(`[role="${this.optionRole}"]`);
		if (!option) return;

		const index = parseInt(option.dataset.index, 10);
		if (index === this.focusedIndex) return;

		this.focusOption(index);
	}

	_optionClick(event) {
		const option = event.target.closest(`[role="${this.optionRole}"]`);
		if (option) {
			event.stopPropagation();
			this.selectOption(option, event);
		}
	}

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
	}
}
