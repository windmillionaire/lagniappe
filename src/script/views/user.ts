import { request } from "../shared/request.ts";
import { withTransition } from "../shared/transitions.ts";
import type { LoadedWidget } from "../types/widgets.d.ts";
import type ViewComponent from "./base/component.ts";
import type { SubcomponentEvent } from "./base/component.ts";
import type { ReconcileChange, RefreshOptions } from "./base/core.ts";
import EntityIndex from "./base/index.ts";

type UserMode = "public" | "regular";

export default class Users extends EntityIndex {
	declare _loadingPublicMode: boolean;

	constructor(node: HTMLElement) {
		super(node);
		this._publicModeClick = this._publicModeClick.bind(this);
		this._groupPanelChange = this._groupPanelChange.bind(this);
		this._loadingPublicMode = false;
	}

	async init() {
		await super.init();
		this.elt.addEventListener("click", this._publicModeClick);
		this.elt.addEventListener("set-subcomponent", this._groupPanelChange);
		this._syncUserModeRoute();
		this._syncPublicModeControls();
		this._setCreateUserAvailability();
	}

	_click(e: MouseEvent) {
		const target = e.target as Element | null;
		const groupLink = target?.closest?.<HTMLAnchorElement>(
			"a[data-kind='group'][href]",
		);
		if (groupLink && this.elt.contains(groupLink)) {
			const route = new URL(groupLink.href, window.location.href);
			const groupKey = route.searchParams.get("group");
			const selector = this._groupSelector(groupKey);
			if (selector) {
				e.preventDefault();
				selector.click();
				return;
			}
		}

		const groupsToggle = target?.closest?.<HTMLElement>(
			"button[data-role='user-groups-toggle']",
		);
		if (groupsToggle && this.elt.contains(groupsToggle)) {
			const toolsElt = this.elt.querySelector<HTMLElement>("#tools");
			const groupsElt = this.elt.querySelector<HTMLElement>("#user-groups");
			if (
				toolsElt?.dataset.visible === "true" &&
				groupsElt?.dataset.visible === "true"
			) {
				e.preventDefault();
				e.stopPropagation();
				this._replaceGroupUrl();
				this.getComponent(toolsElt)?.deactivate(false);
				return;
			}
		}

		const closeTools = target?.closest?.("button[lp-close='tools']");
		if (closeTools && this.elt.contains(closeTools)) this._replaceGroupUrl();

		super._click(e);
	}

	_groupSelector(groupKey: string | null) {
		if (!groupKey) return null;
		return Array.from(
			this.elt.querySelectorAll<HTMLButtonElement>(
				"#user-groups button[data-key][lp-show^='user-groups:GroupPermissions/']",
			),
		).find((button) => button.dataset.key === groupKey);
	}

	_groupPanelChange(event: SubcomponentEvent) {
		const component = event.detail?.subcomponent;
		if (component?.name !== "user-groups") return;

		const active = component.active;
		this._replaceGroupUrl(
			active && "target" in active ? active.target?.dataset.key : null,
		);
	}

	_replaceGroupUrl(groupKey: string | null = null) {
		const route = new URL(window.location.href);
		if (groupKey) {
			route.searchParams.set("group", groupKey);
			route.searchParams.delete("tool");
		} else {
			route.searchParams.delete("group");
		}

		window.history.replaceState(window.history.state, "", route);
	}

	_defaultToolTarget(tools: HTMLElement) {
		const selector = this._groupSelector(this.queryParam("group"));
		const action = selector?.getAttribute("lp-show");
		if (action) {
			const [componentId, widgetName] = action.split(":");
			return { componentId, widgetName };
		}

		return super._defaultToolTarget(tools);
	}

	async refreshCollections(navigation = false, options: RefreshOptions = {}) {
		this._syncUserModeRoute();
		await super.refreshCollections(navigation, options);
	}

	async refreshSupplementalCollections(changes: ReconcileChange[] = []) {
		const groupsElt = this.elt?.querySelector("[id='user-groups']");
		const groups = groupsElt ? this.getComponent(groupsElt) : null;
		const active = groups?.active;
		const activeGroupKey =
			active && "target" in active ? active.target?.dataset.key : undefined;
		if (
			activeGroupKey &&
			changes.some(
				({ type, key }) => type === "delete" && key === activeGroupKey,
			)
		) {
			await this._refreshGroups();
		}
	}

	async _refreshGroups() {
		const groupsElt = this.elt?.querySelector("[id='user-groups']");
		if (!groupsElt) return;
		const groups = this.getComponent(groupsElt);
		if (!groups) return;

		await groups.activate("nav");
		await groups.prepareRender(true);
		await withTransition(
			() => {
				Object.entries(groups.widgets).forEach(([key, widget]) => {
					if (!groups.elt.contains(widget.target ?? null)) {
						widget.destroy?.();
						delete groups.widgets[key];
					}
				});
				groups.render(true);
			},
			{ label: "users:refresh-groups" },
		);
	}

	async _publicModeClick(e: MouseEvent) {
		const button = (e.target as Element | null)?.closest?.<HTMLButtonElement>(
			"[data-role='public-users-toggle']",
		);
		if (!button || !this.elt.contains(button)) return;

		e.preventDefault();
		e.stopPropagation();
		if (this._loadingPublicMode || !this.online) return;

		const nextMode =
			this.elt.dataset.userMode === "public" ? "regular" : "public";
		await this._loadUserMode(nextMode, button);
	}

	async _loadUserMode(mode: UserMode, button: HTMLButtonElement) {
		const table = this.getComponent(this.elt.querySelector("#table"));
		const route = this._userModeRoute(mode, button);
		if (!table || !route) return;

		this._setPublicModeLoading(true);
		try {
			const response = await request.get(route);
			if (!this.successfulResponse(response, table)) return;

			const html = response?.html;
			if (!html) return;
			const body = html.querySelector<HTMLTableSectionElement>(
				"tbody[data-widget='IndexTable']",
			);
			if (!body) return;

			// Mode replacement is atomic: collect every cursor page before
			// marking the new table loaded, retaining the old mode on failure.
			let continuation = body.querySelector<HTMLTableRowElement>("tr[lp-load]");
			while (continuation) {
				const nextRoute = continuation.dataset.route;
				if (!nextRoute) return;
				const next = await request.get(nextRoute);
				if (!this.successfulResponse(next, table)) return;
				const nextHtml = next?.html;
				if (!nextHtml) return;
				const nextBody = nextHtml.querySelector(
					"tbody[data-widget='IndexTable']",
				);
				if (!nextBody) return;
				continuation.replaceWith(...nextBody.children);
				continuation = body.querySelector<HTMLTableRowElement>("tr[lp-load]");
			}

			await withTransition(
				() => {
					this.elt.dataset.userMode = mode;
					this._replaceUserRows(table, body, route);
					this._syncPublicModeControls();
					this._setCreateUserAvailability();
					table.render(true);
				},
				{ label: "users:change-index-mode" },
			);
		} finally {
			this._setPublicModeLoading(false);
		}
	}

	_replaceUserRows(
		table: ViewComponent,
		body: HTMLTableSectionElement & { _lp_widget?: LoadedWidget },
		route: string | null = null,
	) {
		const refreshRoute = route || body.dataset.route;
		if (refreshRoute) body.dataset.route = refreshRoute;
		body.setAttribute("loaded", "");

		const oldBody = table.elt.querySelector("tbody[data-widget='IndexTable']");
		oldBody?.replaceWith(body);

		const indexTable = table.widgets.IndexTable;
		if (indexTable) {
			indexTable.target = body;
			if (refreshRoute) indexTable.route = refreshRoute;
			body._lp_widget = indexTable;
			indexTable.loaded = true;
			indexTable.loading = false;
			indexTable._created = [];
			indexTable._updated = [];
			indexTable.visible = true;
			indexTable.modified = true;
			table.active = indexTable;
		}

		const sorting = table.widgets.TableSorting;
		if (sorting) {
			sorting.disable(true);
			sorting.reset();
		}
	}

	_userModeRoute(
		mode = this.elt.dataset.userMode,
		button: HTMLButtonElement | null = null,
	) {
		const toggle =
			button ||
			this.elt.querySelector<HTMLButtonElement>(
				"[data-role='public-users-toggle']",
			);
		if (!toggle) return null;

		return mode === "public"
			? toggle.dataset.routePublic
			: toggle.dataset.routeRegular;
	}

	_syncUserModeRoute() {
		const table = this.getComponent(this.elt.querySelector("#table"));
		const indexTable = table?.widgets.IndexTable;
		const route = this._userModeRoute();
		if (!indexTable || !route) return;

		indexTable.route = route;
		if (indexTable.target) indexTable.target.dataset.route = route;
	}

	_syncPublicModeControls() {
		const publicMode = this.elt.dataset.userMode === "public";
		const label = publicMode ? "Show regular users" : "Show public users";
		const title = this.elt.querySelector("[data-role='title']");
		if (title)
			title.textContent = publicMode ? "Public User Index" : "User Index";

		this.elt
			.querySelectorAll<HTMLButtonElement>("[data-role='public-users-toggle']")
			.forEach((button) => {
				button.dataset.active = publicMode ? "true" : "false";
				button.setAttribute("aria-label", label);
				button.setAttribute("title", label);
			});
	}

	_setCreateUserAvailability() {
		const publicMode = this.elt.dataset.userMode === "public";
		this.elt
			.querySelectorAll<HTMLButtonElement>("[data-role='create-user-toggle']")
			.forEach((button) => {
				button.dataset.visible = publicMode ? "false" : "true";
			});

		const toolsElt = this.elt.querySelector("#tools");
		const tools = toolsElt ? this.getComponent(toolsElt) : null;
		if (publicMode && tools?.active?.name === "CreateUser") {
			tools.deactivate(false);
		}

		this._refreshMobileToolsDropdown();
	}

	_refreshMobileToolsDropdown() {
		if (!this.mobile || !this.dropdown) return;
		this.dropdown.destroy();
		this.dropdown = null;
		this._createDropdown();
	}

	_setPublicModeLoading(loading: boolean) {
		this._loadingPublicMode = loading;
		this.elt
			.querySelectorAll<HTMLButtonElement>("[data-role='public-users-toggle']")
			.forEach((button) => {
				button.disabled = loading;
			});
	}

	destroy() {
		this.elt.removeEventListener("click", this._publicModeClick);
		this.elt.removeEventListener("set-subcomponent", this._groupPanelChange);
		super.destroy();
	}
}
