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

export const INDEX_LOADING_DELAY_MS = 200;

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
	declare _tableLoadingTimer?: ReturnType<typeof setTimeout> | null;
	declare _tableLoadingTarget?: HTMLTableSectionElement | null;
	declare _tableLoadingToken: number;
	declare _tableScrollObserver?: ResizeObserver | null;
	declare _tableScrollSyncFrame?: number | null;
	declare _onTableVisibilityToggle?: () => void;

	constructor(node: ViewRoot) {
		super(node);
		this.dropdown = null;
		this.nav = null;
		this.toolsObserver = null;
		this._tableLoadingTimer = null;
		this._tableLoadingTarget = null;
		this._tableLoadingToken = 0;
		this._tableScrollObserver = null;
		this._tableScrollSyncFrame = null;
	}

	async init() {
		await super.init();

		const table = this.getComponent(this.elt.querySelector("#table"));
		if (!table) throw new Error("Entity index requires a table component");
		const tools = this.elt.querySelector<HTMLElement>("#tools");
		const filterBar = this.elt.querySelector<HTMLElement>("#filter-bar");
		const mobileControls =
			this.elt.querySelector<HTMLElement>("#mobile-controls");
		let indexTable: LoadedWidget | null = null;

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

		if (this.mobile && tools) {
			await this._createDropdown();
			const toolsNav = document.querySelector<HTMLElement>(
				"nav[data-nav='tools']",
			);
			if (toolsNav) toolsNav.style.display = "none";
		}

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
		this._syncTableScrollOverflow(table.elt);

		if (table.elt.hasAttribute("lp-prefetch")) {
			this._scheduleTableLoading(table.elt);
		}

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
						if (table.active?.name === "MobileTableControls") {
							table.deactivate(false);
						} else if (mobileControls) {
							mobileControls.dataset.visible = "false";
						}
						this._setMobileControlsDropdownOpen(false);
						toolsNav?.removeAttribute("style");
					} else {
						if (
							table.active?.name === "TableVisibility" ||
							table.active?.name === "TableSorting"
						) {
							table.deactivate(false);
						}
						if (tools) this.getComponent(tools)?.deactivate(false);
						if (toolsNav) toolsNav.style.display = "none";
					}
					table.widgets.TableSorting?.reset();
					if (this.mobile) {
						const mobileWidget = table.widgets.MobileTableControls as
							| (LoadedWidget & { sync?: () => void })
							| undefined;
						mobileWidget?.sync?.();
					}
				},
				{ label: "index:mobile-resize" },
			);
			if (!this._destroyed) this._syncTableScrollOverflow(table.elt);
		};
		this.elt.addEventListener("mobile-resize", this._indexMobileResize);
		this._onTableVisibilityToggle = () => {
			this._scheduleTableScrollOverflow(table.elt);
		};
		this.elt.addEventListener(
			"toggle-column-visibility",
			this._onTableVisibilityToggle,
		);
		if (typeof ResizeObserver !== "undefined") {
			const wrapper = table.elt.closest<HTMLElement>(
				"[data-role='table-scroll']",
			);
			this._tableScrollObserver = new ResizeObserver(() => {
				if (!this._destroyed) this._scheduleTableScrollOverflow(table.elt);
			});
			if (wrapper) this._tableScrollObserver.observe(wrapper);
			this._tableScrollObserver.observe(table.elt);
		}

		if (tools) {
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

		if (filterBar && this._defaultToolSlug() === "filters") {
			const bar = await this._ensureFilterBar(filterBar);
			bar?.openAddPopover?.();
		}
	}

	async _ensureFilterBar(filterBarEl: HTMLElement) {
		const component = this.getComponent(filterBarEl);
		if (!component) return null;
		const existing = component.widgets.FilterBar as
			| {
					openAddPopover?: () => void;
					toggleAddPopover?: () => void;
					toggleSavedPopover?: () => Promise<void>;
			  }
			| undefined;
		if (existing) return existing;
		return (await component.loadWidget("FilterBar")) as {
			openAddPopover?: () => void;
			toggleAddPopover?: () => void;
			toggleSavedPopover?: () => Promise<void>;
		} | null;
	}

	_handleCategoryHeaderClick(target: Element, e: MouseEvent): boolean {
		const categoryAction = target.closest<HTMLElement>(
			"[data-category-action]",
		);
		if (
			categoryAction?.dataset.categoryAction &&
			this.elt.contains(categoryAction)
		) {
			const action = categoryAction.dataset.categoryAction;
			e.preventDefault();
			e.stopPropagation();
			void import("../../widgets/categoryHeader.ts").then((mod) => {
				if (this._destroyed) return;
				if (action === "rename") mod.startCategoryRename(this);
				else if (action === "description")
					mod.startCategoryDescriptionEdit(this);
				else if (action === "default-form")
					mod.startCategoryDefaultFormEdit(this);
			});
			return true;
		}

		const editableDescription = target.closest<HTMLElement>(
			"[data-role='description'][data-editable='true']",
		);
		if (
			editableDescription &&
			this.elt.contains(editableDescription) &&
			!target.closest("a, button, input, textarea, form")
		) {
			e.preventDefault();
			e.stopPropagation();
			void import("../../widgets/categoryHeader.ts").then((mod) => {
				if (!this._destroyed) mod.startCategoryDescriptionEdit(this);
			});
			return true;
		}

		return false;
	}

	_click(e: MouseEvent) {
		const { target } = e;
		if (!(target instanceof Element)) return;

		if (this._handleCategoryHeaderClick(target, e)) return;

		const filterBarTrigger = target.closest<HTMLElement>(
			"#filter-bar [data-role='add-trigger'], #filter-bar [data-role='saved-trigger']",
		);
		if (filterBarTrigger && this.elt.contains(filterBarTrigger)) {
			const filterBarEl = filterBarTrigger.closest<HTMLElement>("#filter-bar");
			const component = filterBarEl ? this.getComponent(filterBarEl) : null;
			if (filterBarEl && component && !component.widgets.FilterBar) {
				e.preventDefault();
				e.stopPropagation();
				const role = filterBarTrigger.dataset.role;
				void this.runColdAction(
					filterBarTrigger,
					() => this._ensureFilterBar(filterBarEl),
					(bar) => {
						if (role === "saved-trigger") {
							void bar?.toggleSavedPopover?.();
						} else {
							bar?.toggleAddPopover?.();
						}
					},
					filterBarTrigger,
				);
				return;
			}
		}

		const headerToolBtn = target.closest(
			"button[lp-show^='tools:'], button[lp-show='user-groups:nav']",
		);
		if (this.mobile && headerToolBtn) {
			const mobileControls =
				this.elt.querySelector<HTMLElement>("#mobile-controls");
			const table = this.getComponent(this.elt.querySelector("#table"));
			if (table?.active?.name === "MobileTableControls") {
				table.deactivate(false);
			} else if (mobileControls) {
				mobileControls.dataset.visible = "false";
			}
		}
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

	_matchesToolSlug(candidate: string | null | undefined, target: string) {
		const slug = this.querySlug(candidate);
		if (!slug) return false;
		return (
			slug === target || slug.replace(/-/g, "") === target.replace(/-/g, "")
		);
	}

	_defaultToolTarget(
		tools: HTMLElement,
	): { componentId: string; widgetName?: string } | null {
		const tool = this._defaultToolSlug();
		if (!tool) return null;

		const buttons = this.elt.querySelectorAll(
			"nav[data-nav='tools'] button[lp-show], nav[data-nav='view'] button[lp-show]",
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
				button.getAttribute("aria-label"),
			];

			if (
				candidates.some((candidate) => this._matchesToolSlug(candidate, tool))
			) {
				return { componentId, widgetName };
			}
		}

		const widget = Array.from(
			tools.querySelectorAll<HTMLElement>("[data-widget]"),
		).find((elt) => this._matchesToolSlug(elt.dataset.widget, tool));
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

	async prefetch() {
		let table: ReturnType<EntityIndex["getComponent"]> = null;
		try {
			await super.prefetch();
		} finally {
			table = this.getComponent(this.elt.querySelector("#table"));
			const indexTable = table?.widgets?.IndexTable;
			if (!indexTable?.loading || indexTable.loaded) {
				this.clearTableLoading();
			}
			if (table && !this._destroyed) this._syncTableScrollOverflow(table.elt);
		}
	}

	_scheduleTableScrollOverflow(tableElt: HTMLElement) {
		if (this._tableScrollSyncFrame != null) return;
		this._tableScrollSyncFrame = requestAnimationFrame(() => {
			this._tableScrollSyncFrame = null;
			if (!this._destroyed) this._syncTableScrollOverflow(tableElt);
		});
	}

	_syncTableScrollOverflow(tableElt: HTMLElement) {
		const wrapper = tableElt.closest<HTMLElement>("[data-role='table-scroll']");
		if (!wrapper) return;
		const next = this.mobile
			? "false"
			: tableElt.scrollWidth > wrapper.clientWidth + 1
				? "true"
				: "false";
		if (wrapper.dataset.overflowX !== next) {
			wrapper.dataset.overflowX = next;
		}
	}

	_scheduleTableLoading(tableElt: HTMLElement) {
		const tbody = tableElt.querySelector<HTMLTableSectionElement>(
			"tbody[data-widget='IndexTable']",
		);
		if (
			!tbody ||
			tbody.hasAttribute("loaded") ||
			tbody.querySelector("tr[lp-entity]")
		) {
			return;
		}
		this.clearTableLoading();
		this._tableLoadingTarget = tbody;
		const token = ++this._tableLoadingToken;
		this._tableLoadingTimer = setTimeout(() => {
			this._tableLoadingTimer = null;
			void this._showTableLoading(tableElt, tbody, token);
		}, INDEX_LOADING_DELAY_MS);
	}

	async _showTableLoading(
		tableElt: HTMLElement,
		tbody: HTMLTableSectionElement,
		token: number,
	) {
		if (
			this._destroyed ||
			token !== this._tableLoadingToken ||
			!tbody.isConnected ||
			tbody.hasAttribute("loaded") ||
			tbody.querySelector("tr[lp-entity]") ||
			tbody.querySelector("tr[data-role='loading']")
		) {
			return;
		}
		const { STYLES } = await import("../../generated/styles.mjs");
		if (
			this._destroyed ||
			token !== this._tableLoadingToken ||
			!tbody.isConnected ||
			tbody.hasAttribute("loaded") ||
			tbody.querySelector("tr[lp-entity]") ||
			tbody.querySelector("tr[data-role='loading']")
		) {
			return;
		}

		const colCount = Math.max(
			1,
			tableElt.querySelectorAll("thead > tr:first-child > th").length,
		);
		const row = document.createElement("tr");
		row.dataset.role = "loading";
		row.dataset.visible = "true";
		row.setAttribute("aria-live", "polite");

		const cell = document.createElement("td");
		cell.colSpan = colCount;
		cell.setAttribute("role", "status");
		cell.className = STYLES.table.loading.cell;
		cell.textContent = "Loading…";
		row.append(cell);

		tbody.setAttribute("aria-busy", "true");
		tbody.prepend(row);
	}

	clearTableLoading() {
		this._tableLoadingToken += 1;
		if (
			this._tableLoadingTimer !== null &&
			this._tableLoadingTimer !== undefined
		) {
			clearTimeout(this._tableLoadingTimer);
			this._tableLoadingTimer = null;
		}
		const tbody =
			this._tableLoadingTarget ||
			this.elt.querySelector<HTMLTableSectionElement>(
				"#table tbody[data-widget='IndexTable']",
			);
		this._tableLoadingTarget = null;
		if (!tbody) return;
		tbody.removeAttribute("aria-busy");
		for (const row of tbody.querySelectorAll("tr[data-role='loading']")) {
			row.remove();
		}
	}

	destroy() {
		this.clearTableLoading();
		if (this._indexMobileResize)
			this.elt.removeEventListener("mobile-resize", this._indexMobileResize);
		if (this._onTableVisibilityToggle) {
			this.elt.removeEventListener(
				"toggle-column-visibility",
				this._onTableVisibilityToggle,
			);
			this._onTableVisibilityToggle = undefined;
		}
		this._tableScrollObserver?.disconnect();
		this._tableScrollObserver = null;
		if (this._tableScrollSyncFrame != null) {
			cancelAnimationFrame(this._tableScrollSyncFrame);
			this._tableScrollSyncFrame = null;
		}
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
