import { localStore } from "../shared/storage.ts";
import { withTransition } from "../shared/transitions.ts";
import type { LoadedWidget } from "../types/widgets.d.ts";
import type ViewComponent from "./base/component.ts";
import Core, { type ReconcileChange } from "./base/core.ts";

const HOME_CHANNELS = Object.freeze({
	HomeActivityList: "home-notes",
	HomeTaskList: "tasks",
	StarredList: "starred",
	HomePageList: "pages",
	HomeProjectList: "projects",
	HomeCategoryList: "categories",
	IngressList: "ingress",
	ToolReportList: "tool-reports",
} as const);

const HOME_SECTIONS = Object.freeze({
	pages: "HomePageList",
	notes: "HomeActivityList",
	tasks: "HomeTaskList",
	projects: "HomeProjectList",
	categories: "HomeCategoryList",
	starred: "StarredList",
	directory: "DirectoryList",
	tools: "ToolReportList",
} as const);

type HomeSectionId = keyof typeof HOME_SECTIONS;

function isHomeSectionId(value: unknown): value is HomeSectionId {
	return typeof value === "string" && value in HOME_SECTIONS;
}

export default class Home extends Core {
	declare _homePollUnsubscribers: Map<string, () => void>;
	declare _openSections: Set<HomeSectionId>;
	declare _restoringSections: Set<HomeSectionId>;
	declare _interactedSections: Set<HomeSectionId>;
	declare _suppressSectionPersist: boolean;

	constructor(elt: HTMLElement) {
		super(elt);
		this.hash = "home";
		this._homePollUnsubscribers = new Map();
		this._openSections = new Set();
		this._restoringSections = new Set();
		this._interactedSections = new Set();
		this._suppressSectionPersist = false;
	}

	get _sectionStorageKey() {
		const user = this.elt?.dataset?.user;
		return user ? `home-open-sections:${user}` : "home-open-sections";
	}

	_initPollingSubscription() {}

	async prefetch() {
		await Promise.all([super.prefetch(), this._restoreOpenSections()]);
		this._syncHomePollingSubscriptions();
	}

	_savedOpenSections(): HomeSectionId[] | null {
		const saved = localStore.getJSON(this._sectionStorageKey);
		if (!Array.isArray(saved)) return null;
		const unique = new Set<HomeSectionId>();
		for (const item of saved) {
			if (isHomeSectionId(item)) unique.add(item);
		}
		return [...unique];
	}

	_defaultOpenSections(): HomeSectionId[] {
		const defaults: HomeSectionId[] = ["tasks"];
		const starredCountText = this.elt
			?.querySelector?.("[data-role='starred-count']")
			?.textContent?.trim();
		const starredCount = Number.parseInt(starredCountText || "0", 10);
		if (!Number.isNaN(starredCount) && starredCount > 0) {
			defaults.push("starred");
		}
		return defaults;
	}

	_sectionElement(sectionId: HomeSectionId) {
		return (
			this.elt?.querySelector?.<HTMLElement>(`#${sectionId}[lp-component]`) ??
			null
		);
	}

	_sectionToggle(sectionId: HomeSectionId, component?: ViewComponent | null) {
		const widgetName = HOME_SECTIONS[sectionId];
		const root = component?.elt ?? this._sectionElement(sectionId);
		return (
			root?.querySelector?.<HTMLButtonElement>(
				`button[lp-show='${sectionId}:${widgetName}'][data-toggle]`,
			) ?? null
		);
	}

	_isSectionListOpen(
		sectionId: HomeSectionId,
		component?: ViewComponent | null,
	) {
		const widgetName = HOME_SECTIONS[sectionId];
		const resolved = component ?? this.components[sectionId] ?? null;
		if (!resolved || resolved.active?.name !== widgetName) return false;
		const target =
			resolved.activeWidget?.target ??
			resolved.elt?.querySelector?.<HTMLElement>(
				`[data-widget='${widgetName}']`,
			);
		return target?.dataset?.visible === "true";
	}

	_canRestoreWidget(sectionId: HomeSectionId, widget: LoadedWidget) {
		if (sectionId === "tools") return true;
		const list = widget as LoadedWidget & { itemCount?: number };
		if (typeof list.itemCount === "number") return list.itemCount > 0;
		return Boolean(widget.target?.querySelector?.("li"));
	}

	_persistOpenSections() {
		const ordered = new Set<HomeSectionId>([
			...this._openSections,
			...this._restoringSections,
		]);
		localStore.setJSON(this._sectionStorageKey, [...ordered]);
	}

	async _restoreOpenSections() {
		const saved = this._savedOpenSections();
		const sections = saved !== null ? saved : this._defaultOpenSections();
		if (sections.length === 0) return;

		await Promise.all(
			sections.map((sectionId) => this._restoreSection(sectionId)),
		);
	}

	async _restoreSection(sectionId: HomeSectionId) {
		if (this._destroyed || this._interactedSections.has(sectionId)) return;
		const elt = this._sectionElement(sectionId);
		const component = this.getComponent(elt);
		if (!component || component.active) return;

		const widgetName = HOME_SECTIONS[sectionId];
		const toggle = this._sectionToggle(sectionId, component);
		const target = component.elt.querySelector<HTMLElement>(
			`[data-widget='${widgetName}']`,
		);
		const loadingTrigger =
			toggle && target?.hasAttribute("lp-load")
				? this._setLoadingTrigger(toggle, component, widgetName)
				: null;

		this._restoringSections.add(sectionId);
		try {
			const widget = await component.loadWidget(widgetName);
			if (
				!widget ||
				this._destroyed ||
				!this._restoringSections.has(sectionId) ||
				this._interactedSections.has(sectionId) ||
				component.active ||
				!this._canRestoreWidget(sectionId, widget)
			) {
				return;
			}

			await widget.prereconcile?.();
			await component.prepareRender(true);
			if (
				this._destroyed ||
				!this._restoringSections.has(sectionId) ||
				this._interactedSections.has(sectionId) ||
				component.active
			) {
				return;
			}

			await withTransition(
				() => {
					if (
						this._destroyed ||
						!this._restoringSections.has(sectionId) ||
						this._interactedSections.has(sectionId) ||
						component.active
					) {
						return;
					}
					this._suppressSectionPersist = true;
					try {
						component.active = widget;
						widget.enable();
						component.render(true);
					} finally {
						this._suppressSectionPersist = false;
					}
				},
				{ label: `home:restore-${sectionId}` },
			);
		} finally {
			this._restoringSections.delete(sectionId);
			this._clearLoadingTrigger(loadingTrigger);
		}
	}

	renderComponent(trigger?: HTMLElement | null) {
		const attribute =
			trigger?.getAttribute("lp-show") ||
			trigger?.getAttribute("lp-close") ||
			"";
		const [componentId] = attribute.split(":");
		if (isHomeSectionId(componentId)) {
			this._interactedSections.add(componentId);
			this._restoringSections.delete(componentId);
		}
		return super.renderComponent(trigger);
	}

	syncHomeSectionState(
		component?: { elt?: HTMLElement; name?: string } | null,
	) {
		const sectionId = component?.name || component?.elt?.id;
		if (!isHomeSectionId(sectionId)) return;
		const resolved =
			(component && "active" in component
				? (component as ViewComponent)
				: null) ??
			this.components[sectionId] ??
			null;
		const isOpen = this._isSectionListOpen(sectionId, resolved);
		const toggle = this._sectionToggle(sectionId, resolved);
		toggle?.setAttribute("aria-expanded", isOpen ? "true" : "false");
		if (isOpen) this._openSections.add(sectionId);
		else this._openSections.delete(sectionId);
	}

	_click(e?: MouseEvent) {
		const target = e?.target;
		if (
			e &&
			target instanceof Element &&
			target.closest("[data-role='dismiss-task-feedback']")
		) {
			e.preventDefault();
			const feedback = this.elt?.querySelector?.<HTMLElement>(
				"[data-role='task-feedback']",
			);
			if (feedback) {
				void withTransition(
					() => {
						feedback.dataset.visible = "false";
					},
					{ label: "home:dismiss-task-feedback" },
				);
			}
			return;
		}
		super._click(e);
	}

	_setStarredCount(count: number) {
		const safeCount = Math.max(0, count);
		const countElt = this.elt?.querySelector?.<HTMLElement>(
			"[data-role='starred-count']",
		);
		if (countElt) countElt.textContent = String(safeCount);

		const toggle = this._sectionToggle("starred");
		if (toggle) {
			toggle.classList.toggle("opacity-50", safeCount === 0);
			toggle.classList.toggle("pointer-events-none", safeCount === 0);
		}
		if (safeCount === 0) {
			const list = this._sectionElement(
				"starred",
			)?.querySelector?.<HTMLElement>("[data-widget='StarredList']");
			if (list) list.dataset.visible = "false";
			this.syncHomeSectionState(this.components.starred);
		}
	}

	_adjustStarredCount(delta: number) {
		const countElt = this.elt?.querySelector?.<HTMLElement>(
			"[data-role='starred-count']",
		);
		if (!countElt) return;
		const current = Number.parseInt(countElt.textContent?.trim() || "0", 10);
		if (Number.isNaN(current)) return;
		this._setStarredCount(current + delta);
	}

	onComponentRendered(component: ViewComponent) {
		const sectionId = component.name;
		if (!isHomeSectionId(sectionId)) return;

		if (sectionId === "tasks" && component.active?.name === "CreateUserTask") {
			const feedback = component.elt.querySelector<HTMLElement>(
				"[data-role='task-feedback']",
			);
			if (feedback) feedback.dataset.visible = "false";
		}

		const wasOpen = this._openSections.has(sectionId);
		this.syncHomeSectionState(component);
		const isOpen = this._openSections.has(sectionId);

		if (!this._suppressSectionPersist && isOpen !== wasOpen) {
			this._persistOpenSections();
		}
	}

	async reconcilePollingSubscriptions() {
		await super.reconcilePollingSubscriptions();
		this._syncHomePollingSubscriptions();
	}

	_syncHomePollingSubscriptions() {
		if (!this.PollingCoordinator) return;
		const loaded = new Set<string>();
		for (const component of Object.values(this.components)) {
			for (const widget of Object.values(component.widgets)) {
				const channel =
					widget && HOME_CHANNELS[widget.name as keyof typeof HOME_CHANNELS];
				if (!widget?.loaded || !channel) continue;
				const id = `home:channel:${channel}`;
				loaded.add(id);
				if (this._homePollUnsubscribers.has(id)) continue;
				const unsubscribe = this.PollingCoordinator.subscribe(
					{
						id,
						type: "channel",
						channel,
						revision: widget.target?.dataset.pollRevision ?? null,
					},
					{
						mode: "foreground",
						initial: "scheduled",
						onResult: async (result) => {
							if (result.status !== "changed") return;
							return await this._refreshHomeWidget(component, widget);
						},
					},
				);
				this._homePollUnsubscribers.set(id, unsubscribe);
			}
		}
		for (const [id, unsubscribe] of this._homePollUnsubscribers) {
			if (loaded.has(id)) continue;
			unsubscribe?.();
			this._homePollUnsubscribers.delete(id);
		}
	}

	async _prepareHomeWidgetRefresh(
		component: ViewComponent,
		widget: LoadedWidget,
	) {
		if (!widget?.loaded || !widget.route) return null;
		const response = await this.load(component, widget.route);
		if (!response || response.updated === false) return null;
		const commit = widget.prepareRefresh
			? await widget.prepareRefresh(response)
			: () => widget.refresh?.(response);
		return () => {
			if (typeof commit === "function") commit();
			if (response.pollChannel && widget.target) {
				widget.target.dataset.pollChannel = response.pollChannel;
			}
			if (response.pollRevision && widget.target) {
				widget.target.dataset.pollRevision = response.pollRevision;
			}
		};
	}

	async _refreshHomeWidget(component: ViewComponent, widget: LoadedWidget) {
		const commit = await this._prepareHomeWidgetRefresh(component, widget);
		if (!commit) return false;
		await withTransition(commit, { label: `home:refresh-${widget.name}` });
		return true;
	}

	async refreshSupplementalCollections(changes: ReconcileChange[] = []) {
		if (changes.some(({ type }) => type === "star" || type === "unstar")) {
			await this._refreshStarred();
		}
		if (changes.some(({ type }) => type === "delete")) this._hideEmptyLists();
	}

	async _refreshStarred() {
		const starredComponent = this.getComponent(
			document.getElementById("starred"),
		);
		if (!starredComponent) return;

		const existingWidget = starredComponent.widgets.StarredList;
		const widget =
			existingWidget || (await starredComponent.loadWidget("StarredList"));
		if (!widget) return;

		const commit = existingWidget
			? await this._prepareHomeWidgetRefresh(starredComponent, widget)
			: null;
		await starredComponent.prepareRender(true);
		await withTransition(
			() => {
				if (commit) commit();
				if (starredComponent.active === widget) {
					this._suppressSectionPersist = true;
					try {
						starredComponent.render(true);
					} finally {
						this._suppressSectionPersist = false;
					}
				}
			},
			{ label: "home:refresh-starred" },
		);
		this._syncHomePollingSubscriptions();
	}

	_hideEmptyLists() {
		for (const component of Object.values(this.components)) {
			let hidAny = false;
			for (const widget of Object.values(component.widgets)) {
				const target = widget?.target;
				if (target?.tagName === "UL" && target.children.length === 0) {
					if (
						widget.name === "HomeActivityList" &&
						"ensureEmptyState" in widget &&
						typeof widget.ensureEmptyState === "function"
					) {
						widget.ensureEmptyState();
						continue;
					}
					target.dataset.visible = "false";
					hidAny = true;
				}
			}
			if (hidAny) this.syncHomeSectionState(component);
		}
	}

	destroy() {
		for (const unsubscribe of this._homePollUnsubscribers.values()) {
			unsubscribe?.();
		}
		this._homePollUnsubscribers.clear();
		this._openSections.clear();
		this._restoringSections.clear();
		this._interactedSections.clear();
		super.destroy();
	}
}
