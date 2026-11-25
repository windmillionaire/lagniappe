/*! Third-party licenses: /third-party-licenses.txt */
import { w as withTransition, r as request } from '../foundation.js?v=b8c49d0d';
import { E as EntityIndex } from '../index-foundation.js?v=b8c49d0d';
import '../upstreamUnavailable.js?v=b8c49d0d';
import '../connectivity.js?v=b8c49d0d';
import '../core-foundation.js?v=b8c49d0d';

class Users extends EntityIndex {
  constructor(node) {
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
  _click(e) {
    const target = e.target;
    const groupLink = target?.closest?.(
      "a[data-kind='group'][href]"
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
    const closeTools = target?.closest?.("button[lp-close='tools']");
    if (closeTools && this.elt.contains(closeTools)) this._replaceGroupUrl();
    super._click(e);
  }
  _groupSelector(groupKey) {
    if (!groupKey) return null;
    return Array.from(
      this.elt.querySelectorAll(
        "#user-groups button[data-key][lp-show^='user-groups:GroupPermissions/']"
      )
    ).find((button) => button.dataset.key === groupKey);
  }
  _groupPanelChange(event) {
    const component = event.detail?.subcomponent;
    if (component?.name !== "user-groups") return;
    const active = component.active;
    this._replaceGroupUrl(
      active && "target" in active ? active.target?.dataset.key : null
    );
  }
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
  _defaultToolTarget(tools) {
    const selector = this._groupSelector(this.queryParam("group"));
    const action = selector?.getAttribute("lp-show");
    if (action) {
      const [componentId, widgetName] = action.split(":");
      return { componentId, widgetName };
    }
    return super._defaultToolTarget(tools);
  }
  async refreshCollections(navigation = false, options = {}) {
    this._syncUserModeRoute();
    await super.refreshCollections(navigation, options);
  }
  async refreshSupplementalCollections(changes = []) {
    const groupsElt = this.elt?.querySelector("[id='user-groups']");
    const groups = groupsElt ? this.getComponent(groupsElt) : null;
    const active = groups?.active;
    const activeGroupKey = active && "target" in active ? active.target?.dataset.key : void 0;
    if (activeGroupKey && changes.some(
      ({ type, key }) => type === "delete" && key === activeGroupKey
    )) {
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
      { label: "users:refresh-groups" }
    );
  }
  async _publicModeClick(e) {
    const button = e.target?.closest?.(
      "[data-role='public-users-toggle']"
    );
    if (!button || !this.elt.contains(button)) return;
    e.preventDefault();
    e.stopPropagation();
    if (this._loadingPublicMode || !this.online) return;
    const nextMode = this.elt.dataset.userMode === "public" ? "regular" : "public";
    await this._loadUserMode(nextMode, button);
  }
  async _loadUserMode(mode, button) {
    const table = this.getComponent(this.elt.querySelector("#table"));
    const route = this._userModeRoute(mode, button);
    if (!table || !route) return;
    this._setPublicModeLoading(true);
    try {
      const response = await request.get(route);
      if (!this.successfulResponse(response, table)) return;
      const html = response?.html;
      if (!html) return;
      const body = html.querySelector(
        "tbody[data-widget='IndexTable']"
      );
      if (!body) return;
      let continuation = body.querySelector("tr[lp-load]");
      while (continuation) {
        const nextRoute = continuation.dataset.route;
        if (!nextRoute) return;
        const next = await request.get(nextRoute);
        if (!this.successfulResponse(next, table)) return;
        const nextHtml = next?.html;
        if (!nextHtml) return;
        const nextBody = nextHtml.querySelector(
          "tbody[data-widget='IndexTable']"
        );
        if (!nextBody) return;
        continuation.replaceWith(...nextBody.children);
        continuation = body.querySelector("tr[lp-load]");
      }
      await withTransition(
        () => {
          this.elt.dataset.userMode = mode;
          this._replaceUserRows(table, body, route);
          this._syncPublicModeControls();
          this._setCreateUserAvailability();
          table.render(true);
        },
        { label: "users:change-index-mode" }
      );
    } finally {
      this._setPublicModeLoading(false);
    }
  }
  _replaceUserRows(table, body, route = null) {
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
  _userModeRoute(mode = this.elt.dataset.userMode, button = null) {
    const toggle = button || this.elt.querySelector(
      "[data-role='public-users-toggle']"
    );
    if (!toggle) return null;
    return mode === "public" ? toggle.dataset.routePublic : toggle.dataset.routeRegular;
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
    this.elt.querySelectorAll("[data-role='public-users-toggle']").forEach((button) => {
      button.dataset.active = publicMode ? "true" : "false";
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
    });
  }
  _setCreateUserAvailability() {
    const publicMode = this.elt.dataset.userMode === "public";
    this.elt.querySelectorAll("[data-role='create-user-toggle']").forEach((button) => {
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
  _setPublicModeLoading(loading) {
    this._loadingPublicMode = loading;
    this.elt.querySelectorAll("[data-role='public-users-toggle']").forEach((button) => {
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
