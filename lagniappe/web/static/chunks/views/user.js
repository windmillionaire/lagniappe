/*! Third-party licenses: /third-party-licenses.txt */
import { r as request } from '../request.js?v=b19dd33c';
import { withTransition } from '../utilities.js?v=b19dd33c';
import EntityIndex from './index.js?v=b19dd33c';
import '../errors.js?v=b19dd33c';
import '../styles.js?v=b19dd33c';
import '../tableVisibilityState.js?v=b19dd33c';
import '../core.js?v=b19dd33c';
import '../connectivity.js?v=b19dd33c';
import '../endpoints.js?v=b19dd33c';
import '../shell.js?v=b19dd33c';

/**
 * @testable true
 * @tests tests_e2e/008_users/test_008a_user_index.py::test_create_user_from_index
 * @features users
 * @dimensions create-form create-submit created-row
 */
class Users extends EntityIndex {
	constructor(node) {
		super(node);
		this._publicModeClick = this._publicModeClick.bind(this);
		this._groupPanelChange = this._groupPanelChange.bind(this);
		this._loadingPublicMode = false;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008a_user_index.py::test_users_index_public_toggle_hidden_when_public_users_disabled
	 * @tests tests_e2e/008_users/test_008a_user_index.py::test_users_index_public_toggle_shows_public_users
	 * @features users
	 * @dimensions index-mode-toggle table-row disabled
	 */
	async init() {
		await super.init();
		this.elt.addEventListener("click", this._publicModeClick);
		this.elt.addEventListener("set-subcomponent", this._groupPanelChange);
		this._syncUserModeRoute();
		this._syncPublicModeControls();
		this._setCreateUserAvailability();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_group_column_link_opens_group_tools_and_tracks_url
	 * @features user-groups
	 * @dimensions column-link query-route same-page-navigation
	 */
	_click(e) {
		const groupLink = e.target.closest("a[data-kind='group'][href]");
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

		const closeTools = e.target.closest("button[lp-close='tools']");
		if (closeTools && this.elt.contains(closeTools)) this._replaceGroupUrl();

		super._click(e);
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/user.mjs::Users._click
	 * @reason initial query resolution and link interception share the same DOM lookup
	 */
	_groupSelector(groupKey) {
		if (!groupKey) return null;
		return Array.from(
			this.elt.querySelectorAll(
				"#user-groups button[data-key][lp-show^='user-groups:GroupPermissions/']",
			),
		).find((button) => button.dataset.key === groupKey);
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/user.mjs::Users._click
	 * @reason component activation emits the event exercised by the group-link E2E flow
	 */
	_groupPanelChange(event) {
		const component = event.detail?.subcomponent;
		if (component?.name !== "user-groups") return;

		this._replaceGroupUrl(component.active?.target?.dataset.key);
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/user.mjs::Users._click
	 * @reason URL synchronization is observed through navigation and reload behavior
	 */
	_replaceGroupUrl(groupKey = null) {
		const route = new URL(window.location.href);
		if (groupKey) {
			route.searchParams.set("group", groupKey);
			route.searchParams.delete("tool");
		} else {
			route.searchParams.delete("group");
		}

		window.history.replaceState(window.history.state, "", route);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_group_column_link_opens_group_tools_and_tracks_url
	 * @features user-groups
	 * @dimensions query-route reload
	 */
	_defaultToolTarget(tools) {
		const selector = this._groupSelector(this.queryParam("group"));
		if (selector) {
			const [componentId, widgetName] = selector
				.getAttribute("lp-show")
				.split(":");
			return { componentId, widgetName };
		}

		return super._defaultToolTarget(tools);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008a_user_index.py::test_users_index_public_toggle_shows_public_users
	 * @features users
	 * @dimensions index-mode-toggle table-row refresh
	 */
	async refreshCollections(navigation = false, options = {}) {
		this._syncUserModeRoute();
		await super.refreshCollections(navigation, options);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_delete_group_refreshes_group_navigation
	 * @features user-groups
	 * @dimensions group-delete nav-refresh polling
	 */
	async refreshSupplementalCollections(changes = []) {
		if (changes.some(({ type }) => type === "delete")) {
			await this._refreshGroups();
		}
	}

	async _refreshGroups() {
		const groupsElt = this.elt?.querySelector("[id='user-groups']");
		if (!groupsElt) return;
		const groups = this.getComponent(groupsElt);
		if (!groups) return;

		await withTransition(async () => {
			await groups.activate("nav");
			Object.entries(groups.widgets).forEach(([key, widget]) => {
				if (!groups.elt.contains(widget.target)) {
					widget.destroy();
					delete groups.widgets[key];
				}
			});
			groups.render(true);
		});
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/user.mjs::Users.init
	 * @reason delegated click handler is exercised through public-users index E2E
	 */
	async _publicModeClick(e) {
		const button = e.target.closest("[data-role='public-users-toggle']");
		if (!button || !this.elt.contains(button)) return;

		e.preventDefault();
		e.stopPropagation();
		if (this._loadingPublicMode || !this.online) return;

		const nextMode =
			this.elt.dataset.userMode === "public" ? "regular" : "public";
		await this._loadUserMode(nextMode, button);
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/user.mjs::Users.init
	 * @reason request/reconcile flow is browser-only and covered by public-users index E2E
	 */
	async _loadUserMode(mode, button) {
		const table = this.getComponent(this.elt.querySelector("#table"));
		const route = this._userModeRoute(mode, button);
		if (!table || !route) return;

		this._setPublicModeLoading(true);
		let response;
		try {
			response = await request.get(route);
		} finally {
			this._setPublicModeLoading(false);
		}
		if (!this.successfulResponse(response, table)) return;

		const body = response.html?.querySelector(
			"tbody[data-widget='IndexTable']",
		);
		if (!body) return;

		await withTransition(async () => {
			this.elt.dataset.userMode = mode;
			this._replaceUserRows(table, body, route);
			this._syncPublicModeControls();
			this._setCreateUserAvailability();
			await table.render(true);
		});
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/user.mjs::Users.init
	 * @reason DOM replacement details are verified through the public-users toggle flow
	 */
	_replaceUserRows(table, body, route = null) {
		const refreshRoute = route || body.dataset.route;
		if (refreshRoute) body.dataset.route = refreshRoute;

		const oldBody = table.elt.querySelector("tbody[data-widget='IndexTable']");
		oldBody?.replaceWith(body);

		const indexTable = table.widgets.IndexTable;
		if (indexTable) {
			indexTable.target = body;
			if (refreshRoute) indexTable.route = refreshRoute;
			indexTable.target._lp_widget = indexTable;
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

	/**
	 * @testable false
	 * @covered-by src/script/views/user.mjs::Users.refreshCollections
	 * @reason helper maps the active public-users mode to the widget refresh route
	 */
	_userModeRoute(mode = this.elt.dataset.userMode, button = null) {
		const toggle =
			button || this.elt.querySelector("[data-role='public-users-toggle']");
		if (!toggle) return null;

		return mode === "public"
			? toggle.dataset.routePublic
			: toggle.dataset.routeRegular;
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/user.mjs::Users.refreshCollections
	 * @reason keeps inherited component refresh requests aligned with the current list mode
	 */
	_syncUserModeRoute() {
		const table = this.getComponent(this.elt.querySelector("#table"));
		const indexTable = table?.widgets.IndexTable;
		const route = this._userModeRoute();
		if (!indexTable || !route) return;

		indexTable.route = route;
		if (indexTable.target) indexTable.target.dataset.route = route;
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/user.mjs::Users.init
	 * @reason control state mirrors the browser-only mode transition
	 */
	_syncPublicModeControls() {
		const publicMode = this.elt.dataset.userMode === "public";
		const label = publicMode ? "Show regular users" : "Show public users";
		const title = this.elt.querySelector("[data-role='title']");
		if (title)
			title.textContent = publicMode ? "Public User Index" : "User Index";

		this.elt
			.querySelectorAll("[data-role='public-users-toggle']")
			.forEach((button) => {
				button.dataset.active = publicMode ? "true" : "false";
				button.setAttribute("aria-label", label);
				button.setAttribute("title", label);
			});
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/user.mjs::Users.init
	 * @reason create-tool visibility is coupled to the browser mode toggle
	 */
	_setCreateUserAvailability() {
		const publicMode = this.elt.dataset.userMode === "public";
		this.elt
			.querySelectorAll("[data-role='create-user-toggle']")
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

	/**
	 * @testable false
	 * @covered-by src/script/views/user.mjs::Users.init
	 * @reason dropdown item filtering depends on runtime viewport state
	 */
	_refreshMobileToolsDropdown() {
		if (!this.mobile || !this.dropdown) return;
		this.dropdown.destroy();
		this.dropdown = null;
		this._createDropdown();
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/user.mjs::Users.init
	 * @reason loading state is a small visual guard around the mode request
	 */
	_setPublicModeLoading(loading) {
		this._loadingPublicMode = loading;
		this.elt
			.querySelectorAll("[data-role='public-users-toggle']")
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

export { Users as default };
