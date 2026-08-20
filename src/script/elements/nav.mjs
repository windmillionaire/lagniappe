/**
 * @testable infrastructure
 */
export class NavElement {
	constructor(component, elt) {
		this.component = component;
		this.active = true;
		this.modified = false;
		this._widget = null;

		this.element = elt;
		this.name = elt.dataset.nav;

		this.title = elt.querySelector("[data-role='title']");

		this.nav =
			document.querySelector(`nav[data-nav="${this.name}"]`) ||
			this.component.elt.querySelector("nav");
		this.standalone = this.nav.dataset.standalone === "true";
		this.persistent = this.nav.dataset.persistent === "true";
		this.componentToggles = this._initNavToggles();

		if (this.nav.querySelector(".loader")) {
			this.nav.addEventListener("click", this._click.bind(this));
		}

		this._hideNavContainer = new Set();
		this._navContainer =
			this.element.querySelector("[data-flipped]") || this.nav;
		this.header = elt.querySelector("[data-role='header']");
		this.widgetToggles = this.header
			? this._initWidgetToggles(this.header)
			: {};

		this.controls = elt.querySelector("[data-role='controls']");
		this.widgetControls = this.controls ? this._initControls() : {};
		this.navToggles = elt.querySelector("[data-role='nav-toggles']");
	}

	_initNavToggles() {
		return Object.fromEntries(
			Array.from(
				this.nav.querySelectorAll("button[lp-show]:not([lp-control])"),
			).map((button) => {
				const [component, widget] = button.getAttribute("lp-show").split(":");
				return [
					["active", "nav"].includes(widget) ? component : widget,
					button,
				];
			}),
		);
	}

	_initWidgetToggles() {
		return Object.fromEntries(
			Array.from(
				this.header.querySelectorAll("button[lp-show]:not([lp-control])"),
			).map((button) => {
				const [component, widget] = button.getAttribute("lp-show").split(":");
				this._hideNavContainer.add(widget);
				return [component, button];
			}),
		);
	}

	_initControls() {
		return Object.fromEntries(
			Array.from(this.controls.querySelectorAll("button[lp-control]")).map(
				(button) => [button.getAttribute("lp-control"), button],
			),
		);
	}

	_click(event) {
		if (!event.target.closest("[lp-show]:not([lp-control])")) return;

		Object.values(this.componentToggles).forEach((button) => {
			if (!button.classList.contains("loader")) return;

			const selected = button.contains(event.target);
			if (selected) {
				button.disabled = true;
			} else {
				button.classList.add("opacity-50");
			}
			this.modified = true;
		});
	}

	_setSubToggleVisibility(hideToggles, component) {
		const controlsVisible = this.settings.controls === "true";
		const keepSubToggles = this.settings.subtoggles === "true";
		hideToggles = hideToggles || (controlsVisible && !keepSubToggles);

		Object.entries(this.widgetToggles).forEach(([name, toggle]) => {
			const hidden = hideToggles || name !== component;
			toggle.dataset.visible = hidden ? "false" : "true";
		});
	}

	_setComponentToggleVisibility(hideToggles, widget, selected) {
		const mobile = this.component.view.mobile;

		if (this._hideNavContainer.has(widget) && hideToggles) {
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

	_setNavVisibility(widget) {
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

		this.nav.querySelectorAll(".loader").forEach((toggle) => {
			toggle.disabled = false;
			toggle.classList.remove("opacity-50");
		});
	}

	_setControlOptions(widget) {
		const controlsVisible = widget ? this.settings.controls === "true" : false;
		this.controls.dataset.visible = controlsVisible ? "true" : "false";
		if (this.navToggles) {
			this.navToggles.dataset.visible = controlsVisible ? "false" : "true";
		}
		if (!controlsVisible) return;

		if ("flipped" in this._navContainer.dataset) {
			this._navContainer.dataset.flipped = "false";
		}

		Object.entries(this.widgetControls).forEach(([option, element]) => {
			this._setControlOption(option, element);
		});
	}

	_setTitle() {
		const title = this.settings.title || this.component.elt.dataset.title;
		this.title.textContent = title || "";
	}

	enable(component) {
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

	reconcile(widget, component) {
		const selected = this.componentToggles[widget] ? widget : component;
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
		return this.component.active?.target?.dataset || {};
	}

	_setControlOption(option, element = this.widgetControls[option]) {
		if (!element) return;

		const settings = this.settings;
		const value = this.component.active
			? settings[option]
			: this.component.elt.dataset?.[option];

		if (option === "delete") {
			element.dataset.visible = settings.key ? "true" : "false";
			return;
		} else if (!value && element) {
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
