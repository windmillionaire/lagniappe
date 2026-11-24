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

export default class Home extends Core {
	declare _homePollUnsubscribers: Map<string, () => void>;

	constructor(elt: HTMLElement) {
		super(elt);
		this.hash = "home";
		this._homePollUnsubscribers = new Map();
	}

	_initPollingSubscription() {}

	async prefetch() {
		await super.prefetch();
		this._syncHomePollingSubscriptions();
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
				if (starredComponent.active === widget) starredComponent.render(true);
			},
			{ label: "home:refresh-starred" },
		);
		this._syncHomePollingSubscriptions();
	}

	_hideEmptyLists() {
		for (const component of Object.values(this.components)) {
			for (const widget of Object.values(component.widgets)) {
				const target = widget?.target;
				if (target?.tagName === "UL" && target.children.length === 0) {
					target.dataset.visible = "false";
				}
			}
		}
	}

	destroy() {
		for (const unsubscribe of this._homePollUnsubscribers.values()) {
			unsubscribe?.();
		}
		this._homePollUnsubscribers.clear();
		super.destroy();
	}
}
