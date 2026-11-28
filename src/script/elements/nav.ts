interface NavComponent {
	elt: HTMLElement;
	view: { mobile?: boolean };
	active: NavElement | { target?: HTMLElement | null } | null;
}

export class NavElement {
	declare target?: never;
	declare component: NavComponent;
	declare active: boolean;
	declare modified: boolean;
	declare _widget: string | null;
	declare element: HTMLElement;
	declare name?: string;
	declare title: HTMLElement | null;
	declare nav: HTMLElement;
	declare standalone: boolean;
	declare persistent: boolean;
	declare componentToggles: Record<string, HTMLButtonElement>;
	declare widgetToggles: Record<string, HTMLButtonElement>;
	declare widgetControls: Record<string, HTMLButtonElement>;
	declare _hideNavContainer: Set<string>;
	declare _navContainer: HTMLElement;
	declare header: HTMLElement | null;
	declare controls: HTMLElement | null;
	declare navToggles: HTMLElement | null;

	constructor(component: NavComponent, elt: HTMLElement) {
		this.component = component;
		this.active = true;
		this.modified = false;
		this._widget = null;

		this.element = elt;
		this.name = elt.dataset.nav;

		this.title = elt.querySelector("[data-role='title']");

		this.nav =
			document.querySelector(`nav[data-nav="${this.name}"]`) ||
			this.component.elt.querySelector("nav") ||
			this.element;
		this.standalone = this.nav.dataset.standalone === "true";
		this.persistent = this.nav.dataset.persistent === "true";
		this.componentToggles = this._initNavToggles();

		if (this.nav.querySelector(".loader")) {
			this.nav.addEventListener("click", this._click.bind(this));
		}

		this._hideNavContainer = new Set();
		this._navContainer =
			this.element.querySelector<HTMLElement>("[data-flipped]") || this.nav;
		this.header = elt.querySelector("[data-role='header']");
		this.widgetToggles = this.header
			? this._initWidgetToggles(this.header)
			: {};

		this.controls = elt.querySelector("[data-role='controls']");
		this.widgetControls = this.controls
			? this._initControls(this.controls)
			: {};
		this.navToggles = elt.querySelector("[data-role='nav-toggles']");
	}

	_initNavToggles() {
		return Object.fromEntries(
			Array.from(
				this.nav.querySelectorAll<HTMLButtonElement>(
					"button[lp-show]:not([lp-control])",
				),
			).map((button) => {
				const [component, widget] = (
					button.getAttribute("lp-show") ?? ""
				).split(":");
				return [
					["active", "nav"].includes(widget) ? component : widget,
					button,
				];
			}),
		);
	}

	_initWidgetToggles(header: HTMLElement) {
		return Object.fromEntries(
			Array.from(
				header.querySelectorAll<HTMLButtonElement>(
					"button[lp-show]:not([lp-control])",
				),
			).map((button) => {
				const [component, widget] = (
					button.getAttribute("lp-show") ?? ""
				).split(":");
				if (widget) this._hideNavContainer.add(widget);
				return [component, button];
			}),
		);
	}

	_initControls(controls: HTMLElement) {
		return Object.fromEntries(
			Array.from(
				controls.querySelectorAll<HTMLButtonElement>("button[lp-control]"),
			).map((button) => [button.getAttribute("lp-control"), button]),
		);
	}

	_click(event: MouseEvent) {
		const target = event.target;
		if (
			!(target instanceof Element) ||
			!target.closest("[lp-show]:not([lp-control])")
		)
			return;

		Object.values(this.componentToggles).forEach((button) => {
			if (!button.classList.contains("loader")) return;

			const selected = button.contains(target);
			if (selected) {
				button.disabled = true;
			} else {
				button.classList.add("opacity-50");
			}
			this.modified = true;
		});
	}

	_setSubToggleVisibility(hideToggles: boolean, component?: string | null) {
		const controlsVisible = this.settings.controls === "true";
		const keepSubToggles = this.settings.subtoggles === "true";
		hideToggles = hideToggles || (controlsVisible && !keepSubToggles);

		Object.entries(this.widgetToggles).forEach(([name, toggle]) => {
			const hidden = hideToggles || name !== component;
			toggle.dataset.visible = hidden ? "false" : "true";
		});
	}

	_setComponentToggleVisibility(
		hideToggles: boolean,
		widget?: string | boolean | null,
		selected?: string | boolean | null,
	) {
		const mobile = this.component.view.mobile;

		if (
			typeof widget === "string" &&
			this._hideNavContainer.has(widget) &&
			hideToggles
		) {
			this._navContainer.dataset.visible = "false";
			return false;
		}
		if (this._navContainer) this._navContainer.dataset.visible = "true";

		Object.entries(this.componentToggles).forEach(([show, toggle]) => {
			if (hideToggles) {
				toggle.dataset.visible = "false";
			} else if (this.name === selected) {
				toggle.dataset.visible = "true";
			} else {
				toggle.dataset.selected = show === selected ? "true" : "false";
				toggle.dataset.visible = mobile ? toggle.dataset.selected : "true";
			}
		});

		return true;
	}

	_setNavVisibility(widget?: string | boolean | null) {
		const togglesVisible = widget ? this.settings.nav !== "false" : true;
		const visible =
			this.persistent || this.component.active === this || togglesVisible
				? "true"
				: "false";

		this.nav.dataset.visible = visible;
	}

	_updateLoadingToggles() {
		if (!this.modified) return;
		this.modified = false;

		this.nav
			.querySelectorAll<HTMLButtonElement>(".loader")
			.forEach((toggle) => {
				toggle.disabled = false;
				toggle.classList.remove("opacity-50");
			});
	}

	_setControlOptions(widget?: string | boolean | null) {
		if (!this.controls) return;
		const controlsVisible = widget ? this.settings.controls === "true" : false;
		this.controls.dataset.visible = controlsVisible ? "true" : "false";
		if (this.navToggles) {
			this.navToggles.dataset.visible = controlsVisible ? "false" : "true";
		}
		if (!controlsVisible) return;

		if ("flipped" in this._navContainer.dataset) {
			this._navContainer.dataset.flipped = "false";
			const flipper = this._navContainer.querySelector<HTMLButtonElement>(
				"[data-role='flipper']",
			);
			if (flipper) flipper.setAttribute("aria-expanded", "false");
		}

		Object.entries(this.widgetControls).forEach(([option, element]) => {
			this._setControlOption(option, element);
		});
	}

	_setTitle() {
		const title = this.settings.title || this.component.elt.dataset.title;
		if (this.title && title) this.title.textContent = title;
	}

	enable(component: NavComponent = this.component) {
		this.component = component;
		this.active = true;
	}

	disable() {
		this.active = false;
	}

	hide() {
		this.element.classList.add(
			"[&>*:not([data-role='error'])]:opacity-50",
			"pointer-events-none",
		);
	}

	show() {
		this.element.classList.remove(
			"[&>*:not([data-role='error'])]:opacity-50",
			"pointer-events-none",
		);
	}

	reconcile(widget?: string | boolean | null, component?: string | null) {
		const selected =
			widget && this.componentToggles[String(widget)] ? widget : component;
		const hideToggles = this.settings.nav === "false";
		this._setComponentToggleVisibility(hideToggles, widget, selected);
		this.element.dataset.visible = this.active ? "true" : "false";

		if (!this.active) return;

		this._setSubToggleVisibility(hideToggles, component);
		this._setNavVisibility(widget);
		this._updateLoadingToggles();
		this._setTitle();
		this._setControlOptions(widget);
	}

	get settings() {
		if (this.component.active === this) {
			return this.nav.dataset;
		}
		const active = this.component.active;
		return (active && "target" in active && active.target?.dataset) || {};
	}

	_setControlOption(option: string, element = this.widgetControls[option]) {
		if (!element) return;

		const settings = this.settings;
		const value = this.component.active
			? settings[option]
			: this.component.elt.dataset?.[option];

		if (option === "delete") {
			element.dataset.visible =
				settings.key && settings.delete !== "false" ? "true" : "false";
			return;
		} else if (!value) {
			element.dataset.visible = "false";
			return;
		}

		const controls = element.dataset.controls;
		if (controls) {
			element.setAttribute(`lp-${controls}`, value);
		}

		element.dataset.visible = "true";
	}
}
