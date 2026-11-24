import type {
	Dropdown,
	DropdownItem,
} from "../../elements/combobox/dropdown.ts";
import { withTransition } from "../../shared/transitions.ts";
import type { LoadedWidget } from "../../types/widgets";
import {
	type TableColumn,
	TableVisibilityState,
} from "../../widgets/tables/visibilityState.ts";
import Core from "./core.ts";
import type { ViewRoot } from "./shell.ts";

function isTableColumn(value: unknown): value is TableColumn {
	return Boolean(
		value &&
			typeof value === "object" &&
			"field" in value &&
			typeof value.field === "string" &&
			(!("title" in value) || typeof value.title === "string") &&
			(!("selected" in value) || typeof value.selected === "boolean"),
	);
}

export default class EntityIndex extends Core {
	declare dropdown: Dropdown | null;
	declare nav: null;
	declare toolsObserver: MutationObserver | null;
	declare TableVisibilityState?: TableVisibilityState | null;
	declare _indexMobileResize?: () => Promise<void>;
	declare _dropdownPromise?: Promise<Dropdown | null> | null;

	constructor(node: ViewRoot) {
		super(node);
		this.dropdown = null;
		this.nav = null;
		this.toolsObserver = null;
	}

	async init() {
		await super.init();

		const table = this.getComponent(this.elt.querySelector("#table"));
		if (!table) throw new Error("Entity index requires a table component");
		const tools = this.elt.querySelector<HTMLElement>("#tools");
		const mobileControls =
			this.elt.querySelector<HTMLElement>("#mobile-controls");
		let indexTable: LoadedWidget | null = null;

		if (this.mobile && tools) {
			await this._createDropdown();
			const toolsNav = document.querySelector<HTMLElement>(
				"nav[data-nav='tools']",
			);
			if (toolsNav) toolsNav.style.display = "none";
		}

		const selected = table.preload("selected");
		const columns = table.preload("columns");
		this.TableVisibilityState = new TableVisibilityState({
			component: table,
			view: this,
			selected: Array.isArray(selected)
				? selected.filter((field): field is string => typeof field === "string")
				: [],
			columns: Array.isArray(columns) ? columns.filter(isTableColumn) : [],
		}).init();

		if (!table.elt.hasAttribute("lp-prefetch")) {
			indexTable = await table.loadWidget("IndexTable");
		}
		await table.prepareRender(true);
		await withTransition(
			() => {
				table.render(true);
			},
			{ label: "index:initial-table" },
		);

		const continuation =
			indexTable?.target?.querySelector<HTMLTableRowElement>("tr[lp-load]");
		if (continuation && indexTable?.target) {
			const route = continuation.dataset.route;
			continuation.remove();
			indexTable.target.removeAttribute("loaded");
			indexTable.loaded = false;
			indexTable.loading = true;
			void table.load(indexTable, route);
		}

		this._indexMobileResize = async () => {
			const toolsNav = document.querySelector<HTMLElement>(
				"nav[data-nav='tools']",
			);
			if (this.mobile) await this._createDropdown();
			await withTransition(
				() => {
					if (!this.mobile) {
						if (mobileControls) mobileControls.dataset.visible = "false";
						this._setMobileControlsDropdownOpen(false);
						toolsNav?.removeAttribute("style");
					} else {
						if (tools) this.getComponent(tools)?.deactivate(false);
						if (toolsNav) toolsNav.style.display = "none";
					}
					table.widgets.TableSorting?.reset();
				},
				{ label: "index:mobile-resize" },
			);
		};
		this.elt.addEventListener("mobile-resize", this._indexMobileResize);

		if (!tools) {
			return;
		}

		const thead = table.elt.querySelector("thead");
		this.toolsObserver = new MutationObserver((mutations) => {
			for (const mutation of mutations) {
				if (mutation.attributeName === "data-visible") {
					const visible = tools?.dataset.visible === "true";
					thead?.classList.toggle("sticky", !visible);
				}
			}
		});
		this.toolsObserver.observe(tools, { attributes: true });
		await this._renderDefaultTool(tools);
	}

	_click(e: MouseEvent) {
		const { target } = e;
		if (!(target instanceof Element)) return;
		const toolsTrigger = target.closest("[data-role='tools-dropdown']");
		if (this.mobile && toolsTrigger && !this.dropdown) {
			e.preventDefault();
			e.stopPropagation();
			void this.runColdAction(
				toolsTrigger,
				() => this._createDropdown(),
				(dropdown) => dropdown?.showPanel?.(),
				toolsTrigger,
			);
			return;
		}

		const tableControls = target.closest(
			"button[lp-show='table:MobileTableControls']",
		);
		if (this.mobile && tableControls) {
			this.dropdown?.hidePanel();
			this._setMobileControlsDropdownOpen(false);

			const tools = this.elt.querySelector<HTMLElement>("#tools");
			if (tools?.dataset.visible === "true") {
				this.getComponent(tools)?.deactivate(false);
			}
		}

		super._click(e);
	}

	_defaultToolSlug() {
		return this.querySlug(this.queryParam("tool"));
	}

	_defaultToolTarget(
		tools: HTMLElement,
	): { componentId: string; widgetName?: string } | null {
		const tool = this._defaultToolSlug();
		if (!tool) return null;

		const buttons = tools.querySelectorAll(
			"nav[data-nav='tools'] button[lp-show]",
		);
		for (const button of buttons) {
			const attribute = button.getAttribute("lp-show");
			if (!attribute) continue;
			const [componentId, widgetName] = attribute.split(":");
			const candidates = [
				componentId,
				widgetName,
				attribute.replace(":", "-"),
				button.textContent,
			];

			if (candidates.some((candidate) => this.querySlug(candidate) === tool)) {
				return { componentId, widgetName };
			}
		}

		const widget = Array.from(
			tools.querySelectorAll<HTMLElement>("[data-widget]"),
		).find((elt) => this.querySlug(elt.dataset.widget) === tool);
		if (!widget) return null;

		return {
			componentId: widget.closest("[lp-component]")?.id || tools.id,
			widgetName: widget.dataset.widget,
		};
	}

	async _renderDefaultTool(tools: HTMLElement) {
		const target = this._defaultToolTarget(tools);
		if (!target) return;

		const component = this.getComponent(
			document.getElementById(target.componentId),
		);
		if (!component) return;

		const activated = await component.activate(target.widgetName || "default");
		await component.prepareRender(activated);
		await withTransition(
			() => {
				component.render(activated);
			},
			{ label: "index:default-tool" },
		);
	}

	_setMobileControlsDropdownOpen(open: boolean) {
		const mobileControls = this.elt.querySelector("#mobile-controls");
		if (!mobileControls) return;

		mobileControls.classList.toggle("opacity-50", open);
		mobileControls.classList.toggle("pointer-events-none", open);
	}

	async _createDropdown(): Promise<Dropdown | null | undefined> {
		if (this.dropdown) return;
		if (this._dropdownPromise) return this._dropdownPromise;

		const trigger = this.elt.querySelector<HTMLElement>(
			"[data-role='tools-dropdown']",
		);
		if (!trigger) return;
		this._dropdownPromise = Promise.all([
			import("../../elements/combobox/dropdown.ts"),
			import("../../generated/styles.mjs"),
		])
			.then(([{ Dropdown }, { STYLES }]) => {
				if (this._destroyed || !this.mobile) return null;

				const items: DropdownItem[] = [];

				const createOption = (button: HTMLButtonElement) => {
					const option = button.cloneNode(true) as HTMLButtonElement;
					option.setAttribute("role", "option");
					option.removeAttribute("data-selected");
					option.className = STYLES.index.tools.dropdown.toggle;
					return option.outerHTML;
				};

				document
					.querySelectorAll<HTMLButtonElement>("nav[data-nav='tools'] button")
					.forEach((button) => {
						if (button.dataset.visible === "false") return;
						items.push({
							html: createOption(button),
							onClick: () => {
								const mobileControls =
									this.elt.querySelector<HTMLElement>("#mobile-controls");
								const table = this.getComponent(
									this.elt.querySelector("#table"),
								);
								if (table?.active?.name === "MobileTableControls") {
									table.deactivate(false);
								} else if (mobileControls) {
									mobileControls.dataset.visible = "false";
								}
								this._setMobileControlsDropdownOpen(false);
								this.renderComponent(button);
							},
						});
					});

				this.dropdown = new Dropdown(trigger);

				this.dropdown.init({
					items,
					placement: "bottom-end",
					styles: {
						panel: STYLES.index.tools.dropdown.panel,
					},
					onShow: () => this._setMobileControlsDropdownOpen(true),
					onHide: () => this._setMobileControlsDropdownOpen(false),
				});
				return this.dropdown;
			})
			.catch((error) => {
				this.reportStartupError(error, trigger, "index-tools-dropdown");
				return null;
			})
			.finally(() => {
				this._dropdownPromise = null;
			});
		return this._dropdownPromise;
	}

	destroy() {
		if (this._indexMobileResize)
			this.elt.removeEventListener("mobile-resize", this._indexMobileResize);
		super.destroy();
		this._setMobileControlsDropdownOpen(false);
		this.dropdown?.destroy();
		this.dropdown = null;
		this.toolsObserver?.disconnect();
		this.toolsObserver = null;
		this.TableVisibilityState?.destroy();
		this.TableVisibilityState = null;
	}
}
