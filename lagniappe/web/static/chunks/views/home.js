/*! Third-party licenses: /third-party-licenses.txt */
import { C as Core } from '../core-foundation.js?v=bfd37afb';
import '../connectivity.js?v=bfd37afb';
import '../foundation.js?v=bfd37afb';
import '../notificationState.js?v=bfd37afb';

const HOME_CHANNELS = Object.freeze({
	HomeActivityList: "home-notes",
	HomeTaskList: "tasks",
	StarredList: "starred",
	HomePageList: "pages",
	HomeProjectList: "projects",
	HomeCategoryList: "categories",
	IngressList: "ingress",
	ToolReportList: "tool-reports",
});

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002a_home.py::test_home_mobile_dashboard_smoke
 * @tests tests_js/test_040_home_polling.py::test_home_polling_subscribes_loaded_widgets_and_refreshes_only_owner
 * @features home
 * @dimensions load layout mobile
 * @pairs home:foreground home:mounted-scope home:targeted-refresh home:lazy-widget
 * @pairs polling:foreground polling:mounted-scope polling:targeted-refresh polling:lazy-widget
 */
class Home extends Core {
	constructor(elt) {
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
		const loaded = new Set();
		for (const component of Object.values(this.components)) {
			for (const widget of Object.values(component.widgets)) {
				const channel = HOME_CHANNELS[widget.name];
				if (!channel || !widget.loaded) continue;
				const id = `home:channel:${channel}`;
				loaded.add(id);
				if (this._homePollUnsubscribers.has(id)) continue;
				const unsubscribe = this.PollingCoordinator.subscribe(
					{
						id,
						type: "channel",
						channel,
						revision: widget.target?.dataset.pollRevision || null,
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

	async _refreshHomeWidget(component, widget) {
		if (!widget?.loaded || !widget.route) return false;
		const response = await this.load(component, widget.route);
		if (!response || response.updated === false) return false;
		await widget.refresh?.(response);
		if (response.pollChannel) {
			widget.target.dataset.pollChannel = response.pollChannel;
		}
		if (response.pollRevision) {
			widget.target.dataset.pollRevision = response.pollRevision;
		}
		return true;
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/home.mjs::Home._refreshStarred
	 * @covered-by src/script/views/home.mjs::Home._hideEmptyLists
	 * @reason polling reconciliation delegates collection work to focused home handlers
	 */
	async refreshSupplementalCollections(changes = []) {
		if (changes.some(({ type }) => ["star", "unstar"].includes(type))) {
			await this._refreshStarred();
		}
		if (changes.some(({ type }) => type === "delete")) this._hideEmptyLists();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_category
	 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_project
	 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_page
	 * @features starred
	 * @dimensions category project page
	 */
	async _refreshStarred() {
		const starredComponent = this.getComponent(
			document.getElementById("starred"),
		);
		if (!starredComponent) return;

		const existingWidget = starredComponent.widgets.StarredList;
		const widget =
			existingWidget || (await starredComponent.loadWidget("StarredList"));
		if (!widget) return;

		if (existingWidget) await this._refreshHomeWidget(starredComponent, widget);
		if (starredComponent.active === widget) await starredComponent.render(true);
		this._syncHomePollingSubscriptions();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_reload_uses_server_state_until_replay
	 * @features offline
	 * @dimensions server-first reload
	 */
	_hideEmptyLists() {
		for (const component of Object.values(this.components)) {
			for (const widget of Object.values(component.widgets)) {
				const target = widget.target;
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

export { Home as default };
