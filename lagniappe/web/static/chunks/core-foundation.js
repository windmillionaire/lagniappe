/*! Third-party licenses: /third-party-licenses.txt */
import { c as connectivity } from './connectivity.js?v=b74a2211';
import { c as captureError, E as ENDPOINTS, w as withTransition, a as clearRecentSearchResults, r as request, b as whenIdle, m as markPerformance, l as loadViewService, S as ShellView } from './foundation.js?v=b74a2211';

class NavElement {
  constructor(component, elt) {
    this.component = component;
    this.active = true;
    this.modified = false;
    this._widget = null;
    this.element = elt;
    this.name = elt.dataset.nav;
    this.title = elt.querySelector("[data-role='title']");
    this.nav = document.querySelector(`nav[data-nav="${this.name}"]`) || this.component.elt.querySelector("nav") || this.element;
    this.standalone = this.nav.dataset.standalone === "true";
    this.persistent = this.nav.dataset.persistent === "true";
    this.componentToggles = this._initNavToggles();
    if (this.nav.querySelector(".loader")) {
      this.nav.addEventListener("click", this._click.bind(this));
    }
    this._hideNavContainer = /* @__PURE__ */ new Set();
    this._navContainer = this.element.querySelector("[data-flipped]") || this.nav;
    this.header = elt.querySelector("[data-role='header']");
    this.widgetToggles = this.header ? this._initWidgetToggles(this.header) : {};
    this.controls = elt.querySelector("[data-role='controls']");
    this.widgetControls = this.controls ? this._initControls(this.controls) : {};
    this.navToggles = elt.querySelector("[data-role='nav-toggles']");
  }
  _initNavToggles() {
    return Object.fromEntries(
      Array.from(
        this.nav.querySelectorAll(
          "button[lp-show]:not([lp-control])"
        )
      ).map((button) => {
        const [component, widget] = (button.getAttribute("lp-show") ?? "").split(":");
        return [
          ["active", "nav"].includes(widget) ? component : widget,
          button
        ];
      })
    );
  }
  _initWidgetToggles(header) {
    return Object.fromEntries(
      Array.from(
        header.querySelectorAll(
          "button[lp-show]:not([lp-control])"
        )
      ).map((button) => {
        const [component, widget] = (button.getAttribute("lp-show") ?? "").split(":");
        if (widget) this._hideNavContainer.add(widget);
        return [component, button];
      })
    );
  }
  _initControls(controls) {
    return Object.fromEntries(
      Array.from(
        controls.querySelectorAll("button[lp-control]")
      ).map((button) => [button.getAttribute("lp-control"), button])
    );
  }
  _click(event) {
    const target = event.target;
    if (!(target instanceof Element) || !target.closest("[lp-show]:not([lp-control])"))
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
  _setSubToggleVisibility(hideToggles, component) {
    const controlsVisible = this.settings.controls === "true";
    const keepSubToggles = this.settings.subtoggles === "true";
    hideToggles = hideToggles || controlsVisible && !keepSubToggles;
    Object.entries(this.widgetToggles).forEach(([name, toggle]) => {
      const hidden = hideToggles || name !== component;
      toggle.dataset.visible = hidden ? "false" : "true";
    });
  }
  _setComponentToggleVisibility(hideToggles, widget, selected) {
    const mobile = this.component.view.mobile;
    if (typeof widget === "string" && this._hideNavContainer.has(widget) && hideToggles) {
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
    const visible = this.persistent || this.component.active === this || togglesVisible ? "true" : "false";
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
    if (!this.controls) return;
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
    if (this.title) this.title.textContent = title || "";
  }
  enable(component = this.component) {
    this.component = component;
    this.active = true;
  }
  disable() {
    this.active = false;
  }
  hide() {
    this.element.classList.add(
      "[&>*:not([data-role='error'])]:opacity-50",
      "pointer-events-none"
    );
  }
  show() {
    this.element.classList.remove(
      "[&>*:not([data-role='error'])]:opacity-50",
      "pointer-events-none"
    );
  }
  reconcile(widget, component) {
    const selected = widget && this.componentToggles[String(widget)] ? widget : component;
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
    return active && "target" in active && active.target?.dataset || {};
  }
  _setControlOption(option, element = this.widgetControls[option]) {
    if (!element) return;
    const settings = this.settings;
    const value = this.component.active ? settings[option] : this.component.elt.dataset?.[option];
    if (option === "delete") {
      element.dataset.visible = settings.key ? "true" : "false";
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

const WIDGETS = {
  BaseList: () => import('./baseList.js?v=b74a2211'),
  CategoryInfo: () => import('./category.js?v=b74a2211'),
  CollaborativeDocument: () => import('./document.js?v=b74a2211').then(function (n) { return n.b; }),
  CreateCategory: () => import('./category.js?v=b74a2211'),
  CreateForm: () => import('./forms.js?v=b74a2211').then(function (n) { return n.k; }),
  CreateModelTask: () => import('./project-tools.js?v=b74a2211').then(function (n) { return n.m; }),
  CreateNote: () => import('./page-tools.js?v=b74a2211').then(function (n) { return n.n; }),
  CreatePage: () => import('./page-tools.js?v=b74a2211').then(function (n) { return n.p; }),
  CreateProject: () => import('./project-tools.js?v=b74a2211').then(function (n) { return n.p; }),
  CreateToolReport: () => import('./uploads.js?v=b74a2211').then(function (n) { return n.t; }),
  CreateUserTask: () => import('./task-tools.js?v=b74a2211').then(function (n) { return n.t; }),
  CreateTask: () => import('./task-tools.js?v=b74a2211').then(function (n) { return n.t; }),
  CreateUser: () => import('./user-tools.js?v=b74a2211').then(function (n) { return n.u; }),
  CreateUserGroup: () => import('./user-tools.js?v=b74a2211').then(function (n) { return n.u; }),
  DirectoryList: () => import('./home-tools.js?v=b74a2211').then(function (n) { return n.l; }),
  DocumentSettings: () => import('./page-tools.js?v=b74a2211').then(function (n) { return n.d; }),
  FileInfo: () => import('./fileInfo.js?v=b74a2211'),
  PDFPreview: () => import('./filePdfPreview.js?v=b74a2211'),
  FileUpload: () => import('./uploads.js?v=b74a2211').then(function (n) { return n.a; }),
  Filters: () => import('./filters.js?v=b74a2211').then(function (n) { return n.f; }),
  FilterResults: () => import('./filters.js?v=b74a2211').then(function (n) { return n.a; }),
  GroupPermissions: () => import('./user-tools.js?v=b74a2211').then(function (n) { return n.a; }),
  HomeActivityList: () => import('./home-tools.js?v=b74a2211').then(function (n) { return n.a; }),
  HomePageList: () => import('./home-tools.js?v=b74a2211').then(function (n) { return n.l; }),
  HomeTaskList: () => import('./home-tools.js?v=b74a2211').then(function (n) { return n.t; }),
  HomeProjectList: () => import('./home-tools.js?v=b74a2211').then(function (n) { return n.l; }),
  HomeCategoryList: () => import('./home-tools.js?v=b74a2211').then(function (n) { return n.l; }),
  ImportData: () => import('./ingress.js?v=b74a2211'),
  IndexTable: () => import('./index-tools.js?v=b74a2211').then(function (n) { return n.i; }),
  IngressFileUpload: () => import('./uploads.js?v=b74a2211').then(function (n) { return n.i; }),
  IngressList: () => import('./home-tools.js?v=b74a2211').then(function (n) { return n.l; }),
  MobileTableControls: () => import('./index-tools.js?v=b74a2211').then(function (n) { return n.m; }),
  ModelTaskInfo: () => import('./project-tools.js?v=b74a2211').then(function (n) { return n.m; }),
  ModelTaskList: () => import('./project-tools.js?v=b74a2211').then(function (n) { return n.m; }),
  PageInfo: () => import('./page-tools.js?v=b74a2211').then(function (n) { return n.p; }),
  PagePermissions: () => import('./page-tools.js?v=b74a2211').then(function (n) { return n.a; }),
  PagePhoto: () => import('./page-tools.js?v=b74a2211').then(function (n) { return n.b; }),
  PageTaskList: () => import('./task-tools.js?v=b74a2211').then(function (n) { return n.p; }),
  ProjectInfo: () => import('./project-tools.js?v=b74a2211').then(function (n) { return n.p; }),
  PublicPermissions: () => import('./user-tools.js?v=b74a2211').then(function (n) { return n.a; }),
  SavedFilters: () => import('./filters.js?v=b74a2211').then(function (n) { return n.f; }),
  SiteAiModels: () => import('./admin-tools.js?v=b74a2211').then(function (n) { return n.a; }),
  SiteAdministrators: () => import('./admin-tools.js?v=b74a2211').then(function (n) { return n.b; }),
  SiteDeployment: () => import('./admin-tools.js?v=b74a2211').then(function (n) { return n.d; }),
  SiteInstallationAccess: () => import('./admin-tools.js?v=b74a2211').then(function (n) { return n.i; }),
  SiteImage: () => import('./admin-tools.js?v=b74a2211').then(function (n) { return n.c; }),
  SiteMaintenance: () => import('./admin-tools.js?v=b74a2211').then(function (n) { return n.m; }),
  SiteServiceProviders: () => import('./admin-tools.js?v=b74a2211').then(function (n) { return n.p; }),
  SiteSettings: () => import('./admin-tools.js?v=b74a2211').then(function (n) { return n.s; }),
  StarredList: () => import('./home-tools.js?v=b74a2211').then(function (n) { return n.l; }),
  TableEditor: () => import('./editor.js?v=b74a2211'),
  TableSorting: () => import('./index-tools.js?v=b74a2211').then(function (n) { return n.s; }),
  TableVisibility: () => import('./index-tools.js?v=b74a2211').then(function (n) { return n.v; }),
  TaskForm: () => import('./task-tools.js?v=b74a2211').then(function (n) { return n.a; }),
  TaskHistory: () => import('./task-tools.js?v=b74a2211').then(function (n) { return n.b; }),
  TaskCombine: () => import('./task-tools.js?v=b74a2211').then(function (n) { return n.t; }),
  TaskMove: () => import('./task-tools.js?v=b74a2211').then(function (n) { return n.t; }),
  ToolReportList: () => import('./home-tools.js?v=b74a2211').then(function (n) { return n.l; }),
  TaskSettings: () => import('./task-tools.js?v=b74a2211').then(function (n) { return n.t; }),
  UserSettings: () => import('./userSettings.js?v=b74a2211')
};
const JSON_ATTRIBUTES = [
  "attributes",
  "submission",
  "schema",
  "conditions",
  "columns",
  "selected",
  "preload",
  "options"
];
const _attributes = (component, show) => {
  const settings = {
    component,
    view: component.view,
    name: show,
    visible: false,
    modified: false
  };
  const target = component.elt.querySelector(
    `[data-widget="${show}"]`
  );
  if (target) {
    settings.target = target;
    settings.key = target.dataset.key || component.key || settings.view.key;
    settings.kind = target.dataset.kind || component.kind || "default";
    settings.persistent = target.dataset.persistent === "true";
    settings.visible = target.dataset.visible === "true";
    settings.loaded = target.hasAttribute("loaded");
  }
  settings.route = target?.dataset.route || component.elt.dataset.route;
  for (const attribute of JSON_ATTRIBUTES) {
    const value = target?.dataset[attribute];
    if (value) settings[attribute] = JSON.parse(value);
  }
  if (show in ENDPOINTS) {
    const endpoint = ENDPOINTS[show];
    settings.endpoints = endpoint(settings);
  }
  return settings;
};
const _defineReadonly = (widget, component) => {
  Object.defineProperty(widget, "readonly", {
    configurable: true,
    enumerable: true,
    get() {
      return component.readonly || this.target?.dataset.readonly === "true";
    }
  });
};
class DefaultWidget {
  constructor(attributes) {
    Object.assign(this, attributes);
    this.DEFAULT = true;
  }
}
async function loadWidget(component, show, extraAttributes = {}) {
  let widget;
  const attributes = { ..._attributes(component, show), ...extraAttributes };
  const name = show.split("/")[0];
  if (name in WIDGETS) {
    const module = await WIDGETS[name]();
    const Widget = module[name];
    widget = new Widget(attributes);
  } else {
    widget = new DefaultWidget(attributes);
  }
  _defineReadonly(widget, component);
  if (widget.init) await widget.init();
  widget.enable = () => {
    widget.modified = widget.modified || widget.visible !== true;
    widget.visible = true;
  };
  widget.disable = (force = false) => {
    widget.modified = force || widget.visible !== false;
    widget.visible = false;
  };
  widget.prepareReconcile = async (silent = false) => {
    if (!widget.modified || silent) return;
    await widget.prereconcile?.();
  };
  widget.reconcile = (silent = false) => {
    if (widget.target && !widget.persistent) {
      widget.target.dataset.visible = widget.visible ? "true" : "false";
    }
    if (!widget.modified) return;
    widget.modified = false;
    if (widget.postreconcile && !silent) {
      const result = widget.postreconcile();
      if (result && typeof result === "object" && "then" in result && result.then) {
        captureError(
          new TypeError(
            `${widget.name}.postreconcile() must commit synchronously. Move awaited work to prereconcile().`
          ),
          widget.target
        );
        void result.catch(captureError);
      }
    }
  };
  if (widget.target) {
    const target = widget.target;
    target._lp_widget = widget;
  }
  return widget;
}

class ViewComponent {
  constructor(node, view) {
    this.view = view;
    this.elt = node;
    this.key = node.closest("[data-key]")?.dataset.key;
    this.name = node.id;
    this.kind = node.dataset.kind || view.kind;
    this.widgets = {};
    this.widgetLoads = /* @__PURE__ */ new Map();
    this.active = null;
    this.attributes = {};
    this._nav = null;
    this._activeSubComponent = null;
    this._creating = false;
    this._destroyed = false;
    this.reconcile = null;
  }
  get readonly() {
    return this.view.readonly || this.elt.dataset.readonly === "true";
  }
  get default() {
    return this.elt.dataset.default;
  }
  get navElt() {
    return this.elt.querySelector(
      `[lp-nav][data-nav="${this.name}"]`
    );
  }
  get nav() {
    if (this._nav) return this._nav;
    const nav = this.elt.dataset.parentNav;
    const navElt = nav ? document.getElementById(nav) : null;
    if (navElt && !this.elt.contains(navElt)) {
      this._nav = this.view.getComponent(navElt)?.nav ?? null;
    } else {
      this._nav = this.navElt ? new NavElement(this, this.navElt) : null;
      if (this.navElt) this.navElt.dataset.visible = "true";
    }
    return this._nav;
  }
  set nav(newNav) {
    this._nav = newNav;
    if (this.navElt) this.navElt.dataset.visible = newNav ? "false" : "true";
  }
  get activeWidget() {
    return this.active instanceof NavElement ? null : this.active;
  }
  get subComponents() {
    const filtered = Array.from(
      this.elt.querySelectorAll(":scope [lp-component]")
    ).filter((component) => {
      return component.parentElement?.closest("[lp-component]") === this.elt;
    });
    return filtered;
  }
  get parentComponent() {
    return this.elt.parentElement?.closest("[lp-component]") ?? null;
  }
  get persistent() {
    return this.elt.dataset.persistent === "true";
  }
  set persistent(value) {
    this.elt.dataset.persistent = value ? "true" : "false";
  }
  get visible() {
    return this.elt.dataset.visible === "true";
  }
  set visible(value) {
    this.elt.dataset.visible = value ? "true" : "false";
  }
  get error() {
    return this.elt.querySelector("[data-role='error']");
  }
  async activate(show) {
    if (this._destroyed) return false;
    this.view?.DeferredOperations?.suspendTaskForm?.(this.activeWidget?.target);
    this.active?.disable();
    if (!show) {
      this.active = null;
      this.nav?.reconcile(null, this.name);
      return false;
    } else if (["default", "active"].includes(show)) {
      show = this.default;
      if (!show) {
        this.active = null;
        return true;
      }
    } else if (show === "nav" && this.nav?.standalone) {
      this.active = this.nav;
      return true;
    }
    this.active = await this.loadWidget(show);
    if (this._destroyed) {
      this.active?.destroy?.();
      this.active = null;
      return false;
    }
    const createForm = this.active?.ifEmpty;
    if (createForm && !this._creating) {
      const createTarget = Array.from(
        this.elt.querySelectorAll("[data-widget]")
      ).some((target) => target.dataset.widget === createForm);
      if (createTarget) return await this.activate(createForm);
    }
    this.active?.enable();
    this.view?.DeferredOperations?.resumeTaskForm?.(this.active?.target);
    return true;
  }
  async prefetch() {
    const widgets = this.elt.querySelectorAll(
      "[data-widget][lp-prefetch]"
    );
    await Promise.all(
      Array.from(widgets).map(async (elt) => {
        await this.loadWidget(elt.dataset.widget);
      })
    );
  }
  async prepareCollectionRefresh(skip = /* @__PURE__ */ new Set()) {
    const widgets = Object.values(this.widgets);
    const commits = await Promise.all(
      widgets.map(async (widget) => {
        if (skip.has(widget)) return null;
        if (widget.refreshScope !== "collection") return null;
        if (!widget.refresh) return null;
        if (widget.unsavedState === true || widget.form?._queued === true || widget.target?.querySelector?.(
          "[lp-edited-marker][data-visible='true']"
        ))
          return null;
        const response = await this.view.load(this, widget.route);
        if (!response || response.updated === false) return null;
        if (widget.prepareRefresh) {
          return await widget.prepareRefresh(response);
        }
        return () => {
          const result = widget.refresh?.(response);
          if (result instanceof Promise) void result.catch(captureError);
        };
      })
    );
    return commits.filter((commit) => commit != null);
  }
  async refreshCollections(skip = /* @__PURE__ */ new Set()) {
    const commits = await this.prepareCollectionRefresh(skip);
    commits.forEach((commit) => {
      commit();
    });
  }
  async loadWidget(name) {
    if (!name || this._destroyed) return null;
    if (this.widgets[name]) return this.widgets[name];
    const existing = this.widgetLoads.get(name);
    if (existing) return existing;
    const pending = (async () => {
      const widget = await loadWidget(this, name);
      if (!widget || this._destroyed) {
        widget?.destroy?.();
        return null;
      }
      this.widgets[name] = widget;
      if (widget.loading || widget.loaded) return widget;
      widget.loading = true;
      const shouldLoad = widget.target?.hasAttribute("lp-load") || widget.target?.hasAttribute("lp-prefetch");
      if (shouldLoad) await this.load(widget);
      return widget;
    })();
    this.widgetLoads.set(name, pending);
    try {
      return await pending;
    } finally {
      if (this.widgetLoads.get(name) === pending) {
        this.widgetLoads.delete(name);
      }
    }
  }
  // this is called when a widget needs to be loaded/reloaded in response to an event
  async load(widget = this.activeWidget, route) {
    if (!widget || widget?.loaded) return null;
    route = route || widget.route;
    const response = await this.view.load(this, route);
    widget.modified = true;
    if (!response) {
      widget.loading = false;
      return null;
    }
    if (response.updated === false && widget.initialized) return null;
    const html = response.html || null;
    const responseTarget = html?.querySelector(
      `[data-widget='${widget.name}']`
    );
    if (responseTarget && response.pollChannel) {
      responseTarget.dataset.pollChannel = response.pollChannel;
    }
    if (responseTarget && response.pollRevision) {
      responseTarget.dataset.pollRevision = response.pollRevision;
    }
    const append = await widget.updated?.(response);
    if (append) void this.load(widget, append.dataset.route);
    if (widget !== this.active) {
      await widget.prepareReconcile();
      await withTransition(() => widget.reconcile(), {
        label: `${this.name}:${widget.name}:load`
      });
    }
  }
  // triggered by a submit event, called by the core class's update() method
  // any loaded widgets that have targets in the server response will be updated
  // if the widget hasn't been loaded yet, its target will be replaced with the new html
  // otherwise the widget's updated() method will be called with the response
  async updated(response) {
    const updates = {
      replace: [],
      append: []
    };
    const widgetUpdates = [];
    const targets = response.html ? response.html.querySelectorAll("[data-widget]") : [];
    targets.forEach((elt) => {
      const name = elt.dataset.widget;
      if (!name) return;
      const widget = this.widgets[name];
      const target = this.elt.querySelector(`[data-widget='${name}']`);
      if (widget?.updated) {
        widgetUpdates.push(widget.updated(response));
        widget.modified = true;
      } else if (target) {
        updates.replace.push({ target, elt });
      } else {
        updates.append.push(elt);
      }
    });
    await Promise.all(widgetUpdates);
    await this.prepareRender(true);
    await withTransition(
      () => {
        updates.replace.forEach(({ target, elt }) => {
          target.replaceWith(elt);
        });
        this.elt.append(...updates.append);
        this.activeWidget?.success?.();
        this.render(true);
      },
      { label: `${this.name}:update` }
    );
  }
  disable() {
    this.nav?.hide();
  }
  enable() {
    this.nav?.show();
  }
  // triggered by a submit event, called by the core class's create() method
  // this.active is the form that triggered the event
  // if it needs to be reset or modified, that should happen in its postreconcile() method
  // receiver is the widget that will receive the new html, this will be activated
  // it may be the same component or a different component, both components will be rendered
  async created(response) {
    const originator = this.activeWidget;
    if (!originator) return;
    this._creating = true;
    originator.modified = true;
    const destination = originator.target?.dataset.destination;
    if (destination === void 0)
      throw new Error("Create widget requires data-destination");
    const [componentId, widgetName] = destination.split(":");
    await originator.created?.(response);
    let component;
    if (widgetName) {
      if (componentId === this.name) {
        component = this;
        await this.activate(widgetName);
      } else {
        component = this.view.getComponent(
          document.getElementById(componentId)
        );
        await component?.activate(widgetName);
      }
      if (component?.active) {
        await component.activeWidget?.created?.(response);
        component.active.modified = true;
      }
    } else {
      component = null;
    }
    await this.prepareRender(true);
    if (component && this !== component) await component.prepareRender(true);
    await withTransition(
      () => {
        this.render(true);
        if (component && this !== component) component.render(true);
      },
      { label: `${this.name}:create` }
    );
    this._creating = false;
  }
  preload(property) {
    const data = this.elt.dataset.preload;
    const attributes = data ? JSON.parse(data) : {};
    this.attributes = attributes && typeof attributes === "object" && !Array.isArray(attributes) ? attributes : {};
    return this.attributes[property] ?? null;
  }
  showError(message) {
    this.enable();
    const active = this.activeWidget;
    if (this.open !== "false" && active?.showError) {
      active.showError(message);
    } else {
      const errorElt = this.error;
      if (!errorElt) return;
      const error = document.createElement("span");
      error.textContent = message;
      void withTransition(
        () => {
          errorElt.replaceChildren(error);
          errorElt.dataset.visible = "true";
        },
        { label: `${this.name}:error` }
      );
      active?.enable();
    }
  }
  // if widgets return data, it must be a FormData object
  // this FormData will have the data-role of the submitter added to it
  get formData() {
    return this.activeWidget?.formData;
  }
  get open() {
    return this.elt.dataset.open;
  }
  get route() {
    return this.activeWidget?.route || this.activeWidget?.target?.dataset.route || this.elt.dataset.route;
  }
  deactivate(visible = true, originator = null) {
    const active = this.active;
    if (active) {
      this.view?.DeferredOperations?.suspendTaskForm?.(
        this.activeWidget?.target
      );
      if (active instanceof NavElement) active.disable();
      else active.disable(true);
      active.reconcile(true);
      this.nav?.reconcile(null, this.name);
    }
    if (!visible) {
      this.elt.dataset.visible = this.persistent ? "true" : "false";
      this.elt.dataset.open = "false";
    }
    if (originator) {
      this.nav?.disable();
      this.nav?.reconcile(originator.active?.name, originator.name);
    }
  }
  _setParentComponent() {
    const parentElt = this.parentComponent;
    const parent = parentElt ? this.view.getComponent(parentElt) : null;
    const subComponents = parent ? parent.subComponents : this.subComponents;
    subComponents.forEach((elt) => {
      const subComponent = this.view.getComponent(elt);
      if (subComponent && subComponent !== this) subComponent.deactivate(false);
    });
    if (!parent) return;
    if (!this.nav && parent.nav) {
      this.nav = parent.nav;
    } else if (this.nav !== parent.nav && this.nav?.standalone) {
      parent.deactivate(true, this);
      parent.elt.dataset.visible = "true";
    }
    parent._setSubComponent(this);
  }
  _setSubComponent(subComponent) {
    const activeSubComponent = this._activeSubComponent;
    if (activeSubComponent && activeSubComponent !== subComponent) {
      const visible = activeSubComponent.persistent ? "true" : "false";
      activeSubComponent.elt.dataset.visible = visible;
    }
    this._activeSubComponent = subComponent;
    const event = new CustomEvent("set-subcomponent", {
      detail: {
        subcomponent: subComponent
      },
      bubbles: true
    });
    subComponent.elt.dispatchEvent(event);
  }
  async prepareRender(_visible) {
    await Promise.all(
      Object.values(this.widgets).map((widget) => {
        return widget.prepareReconcile();
      })
    );
  }
  // User actions and initial entity enhancement call this within a transition.
  // Connected-DOM manipulation in widgets belongs in postreconcile().
  render(visible) {
    const open = visible ? this.active?.name || "true" : false;
    this.elt.dataset.visible = this.persistent || visible ? "true" : "false";
    this._setParentComponent();
    Object.values(this.widgets).forEach((widget) => {
      widget.reconcile();
    });
    if (this.nav) {
      this.nav.enable(this);
      this.nav.reconcile(this.active?.name, this.name);
    }
    this.elt.dataset.open = open || "false";
    this.view.onComponentRendered?.(this);
    void this.view.schedulePollingReconciliation?.();
  }
  destroy() {
    this._destroyed = true;
    Object.values(this.widgets).forEach((widget) => {
      widget.destroy?.();
    });
    this.widgetLoads.clear();
    if (this.key !== void 0) delete this.view.components[this.key];
  }
}

function isCollectionWidget(widget) {
  return widget.refreshScope === "collection" && "refreshDescriptor" in widget && typeof widget.refreshDescriptor === "function" && "refreshDelta" in widget && typeof widget.refreshDelta === "function";
}
function isStringList(value) {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}
function isRefreshDelta(value) {
  if (value === null || typeof value !== "object" || !("id" in value) || typeof value.id !== "string")
    return false;
  if ("fallback" in value && value.fallback !== false) return false;
  if ("remove" in value && !isStringList(value.remove)) return false;
  if ("order" in value && !isStringList(value.order)) return false;
  if ("empty" in value && value.empty !== null && typeof value.empty !== "string")
    return false;
  return !("upsert" in value) || Array.isArray(value.upsert) && value.upsert.every(
    (row) => row !== null && typeof row === "object" && "key" in row && typeof row.key === "string" && "html" in row && typeof row.html === "string"
  );
}
const COLLECTION_ONLY_CHANGE_TYPES = /* @__PURE__ */ new Set(["delete", "star", "unstar"]);
const FORM_ALREADY_RECONCILED_CHANGE_TYPES = /* @__PURE__ */ new Set([
  ...COLLECTION_ONLY_CHANGE_TYPES,
  "entity-poll"
]);
const loadChangeDestination = async (view, destination) => {
  if (!destination) return null;
  const [componentId, widgetName] = destination.split(":");
  if (!componentId || !widgetName) return null;
  const component = view.getComponent(document.getElementById(componentId));
  return component ? await component.loadWidget(widgetName) : null;
};
const loadMountedCollectionOwners = async (view, keys) => {
  const requested = new Set(keys);
  const targets = /* @__PURE__ */ new Set();
  for (const entity of view.elt.querySelectorAll(
    "[lp-entity][data-key]"
  )) {
    if (!entity.dataset.key || !requested.has(entity.dataset.key)) continue;
    const target = entity.parentElement?.closest?.("[data-widget]");
    if (target?.dataset.widget && !target.matches?.("form"))
      targets.add(target);
  }
  await Promise.all(
    Array.from(targets, async (target) => {
      await view.getComponent(target)?.loadWidget(target.dataset.widget);
    })
  );
};
const removeDeletedEntity = (view, key) => {
  for (const element of view.elt.querySelectorAll(
    "[data-key]"
  )) {
    if (element.dataset.key !== key) continue;
    element._lp_component?.destroy?.();
    element.remove();
  }
};
const reconcileChange = (view, change = {}) => {
  view._pendingChanges.push({ ...change });
  if (view._reconcilePromise) return view._reconcilePromise;
  view._reconcilePromise = (async () => {
    try {
      do {
        const changes = view._pendingChanges.splice(0);
        const fingerprint = view.elt.dataset.fingerprint || null;
        const destinationKeys = [];
        for (const item of changes) {
          if (item.type === "delete") clearRecentSearchResults();
          if (item.type === "star" || item.type === "unstar") {
            view._applyStarState(item);
          }
          const destination = await loadChangeDestination(
            view,
            item.destination
          );
          if (destination?.key && !COLLECTION_ONLY_CHANGE_TYPES.has(item.type ?? "")) {
            destinationKeys.push(destination.key);
          }
        }
        const keys = [
          ...new Set(changes.flatMap(({ key }) => key ? [key] : []))
        ];
        if (keys.length) await loadMountedCollectionOwners(view, keys);
        const deletedKeys = changes.flatMap(
          ({ key, type }) => type === "delete" && key ? [key] : []
        );
        const formKeys = [
          .../* @__PURE__ */ new Set([
            ...changes.filter(
              ({ type }) => !FORM_ALREADY_RECONCILED_CHANGE_TYPES.has(type ?? "")
            ).flatMap(({ key }) => key ? [key] : []),
            ...destinationKeys
          ])
        ];
        if (formKeys.length) {
          const watcher = await view.ensureEditWatcher();
          if (view.PollingCoordinator?.activePoll) watcher?.enqueue(formKeys);
          else await watcher?.invalidate(formKeys);
        }
        await view.refreshCollections(false, {
          fingerprint,
          beforeCommit: () => {
            deletedKeys.forEach((key) => {
              removeDeletedEntity(view, key);
            });
          }
        });
        await view.refreshSupplementalCollections(changes);
        for (const item of changes) await view.afterReconcileChange(item);
      } while (view._pendingChanges.length);
    } finally {
      view._reconcilePromise = null;
    }
  })();
  return view._reconcilePromise;
};
const collectRefreshTargets = (_view, components) => {
  const targets = /* @__PURE__ */ new Map();
  for (const component of components) {
    if (component.elt && !component.elt.isConnected) continue;
    for (const widget of Object.values(component.widgets)) {
      if (!isCollectionWidget(widget)) continue;
      try {
        const descriptor = widget.refreshDescriptor();
        if (!descriptor) continue;
        const id = component.name;
        if (!id || targets.has(id)) continue;
        targets.set(id, { descriptor: { ...descriptor, id }, widget });
      } catch (error) {
        captureError(error);
      }
    }
  }
  return targets;
};
const refreshCollectionComponents = async (view, components, {
  fingerprint = view.elt.dataset.fingerprint || null,
  deferCommit = false
} = {}) => {
  const targets = collectRefreshTargets(view, components);
  const reconciled = /* @__PURE__ */ new Set();
  const commits = [];
  let refreshedFingerprint = null;
  let refreshedAuthorization = null;
  let collectionRevision = null;
  if (targets.size) {
    const response = await request.post(
      "/l/refresh",
      {
        view: {
          key: view.key || null,
          hash: view.hash || null,
          index: view.elt.dataset.index || null,
          mode: view.elt.dataset.userMode || null,
          fingerprint,
          authorization: view.elt.dataset.authorization || null,
          collection_revision: view.elt.dataset.collectionRevision || null
        },
        targets: Array.from(targets.values(), ({ descriptor }) => descriptor)
      }
    );
    if (response?.reload) {
      window.location.reload();
      return;
    }
    if (response?.ok && Array.isArray(response.targets)) {
      refreshedFingerprint = response.fingerprint || null;
      refreshedAuthorization = response.authorization || null;
      collectionRevision = response.collection_revision || null;
      if (!response.targets.length && refreshedFingerprint) {
        for (const { widget } of targets.values()) reconciled.add(widget);
      }
      const results = new Map(
        response.targets.filter(isRefreshDelta).map((target) => [target.id, target])
      );
      for (const [id, { widget }] of targets) {
        const result = results.get(id);
        if (!result || result.fallback) continue;
        try {
          if (deferCommit && widget.prepareRefreshDelta) {
            commits.push(await widget.prepareRefreshDelta(result));
          } else if (deferCommit) {
            commits.push(() => {
              const pending = widget.refreshDelta(result);
              if (pending instanceof Promise) void pending.catch(captureError);
            });
          } else {
            await widget.refreshDelta(result);
          }
          reconciled.add(widget);
        } catch (error) {
          captureError(error);
        }
      }
    }
  }
  if (deferCommit) {
    const prepared = await Promise.all(
      components.map(async (component) => {
        if (component.elt && !component.elt.isConnected) return [];
        return await component.prepareCollectionRefresh(reconciled);
      })
    );
    commits.push(...prepared.flat());
    return () => {
      commits.filter((commit) => commit != null).forEach((commit) => {
        commit();
      });
      if (refreshedFingerprint) {
        view.elt.dataset.fingerprint = refreshedFingerprint;
      }
      if (refreshedAuthorization)
        view.elt.dataset.authorization = refreshedAuthorization;
      if (collectionRevision)
        view.elt.dataset.collectionRevision = collectionRevision;
    };
  }
  await Promise.all(
    components.map(async (component) => {
      if (component.elt && !component.elt.isConnected) return;
      await component.refreshCollections(reconciled);
    })
  );
  if (refreshedFingerprint) view.elt.dataset.fingerprint = refreshedFingerprint;
  if (refreshedAuthorization)
    view.elt.dataset.authorization = refreshedAuthorization;
  if (collectionRevision)
    view.elt.dataset.collectionRevision = collectionRevision;
  return null;
};

const ensureOfflineQueue = (view) => loadViewService(view, "_offlineQueuePromise", "offlineQueue", async () => {
  const { OfflineQueue } = await import('./offline-replay.js?v=b74a2211').then(function (n) { return n.o; });
  if (view._destroyed) return null;
  const queue = new OfflineQueue(view);
  await queue.init();
  return queue;
});
const ensurePollingCoordinator = (view) => loadViewService(view, "_pollingPromise", "PollingCoordinator", async () => {
  const { PollingCoordinator } = await import('./polling.js?v=b74a2211');
  if (view._destroyed) return null;
  const coordinator = new PollingCoordinator(view).init();
  view.PollingCoordinator = coordinator;
  view._initPollingSubscription();
  void view.schedulePollingReconciliation();
  return coordinator;
});
const ensureSyncManager = (view) => loadViewService(view, "_syncPromise", "SyncManager", async () => {
  await ensurePollingCoordinator(view);
  const { SyncManager } = await import('./sync.js?v=b74a2211');
  if (view._destroyed) return null;
  const manager = new SyncManager(view);
  manager.init();
  return manager;
});
const ensureEditWatcher = (view) => loadViewService(view, "_editWatcherPromise", "EditWatcher", async () => {
  await ensurePollingCoordinator(view);
  const { EditWatcher } = await import('./watcher.js?v=b74a2211');
  if (view._destroyed) return null;
  const watcher = new EditWatcher(view);
  watcher.init();
  return watcher;
});
const ensureDeferredOperations = (view) => loadViewService(
  view,
  "_deferredOperationsPromise",
  "DeferredOperations",
  async () => {
    await ensurePollingCoordinator(view);
    const { DeferredOperationManager } = await import('./deferredOperations.js?v=b74a2211');
    if (view._destroyed) return null;
    return new DeferredOperationManager(view).init();
  }
);
const ensureNotifications = (view) => loadViewService(view, "_notificationsPromise", "Notifications", async () => {
  if (!document.querySelector("[data-role='notifications']")) return null;
  const { Notifications } = await import('./notifications.js?v=b74a2211');
  if (view._destroyed) return null;
  const notifications = new Notifications(view);
  notifications.init();
  return notifications;
});
const ensureSearchBox = (view) => loadViewService(view, "_searchPromise", "SearchBox", async () => {
  const search = document.querySelector("[lp-search]");
  if (!search) return null;
  const { SearchBox } = await import('./combobox.js?v=b74a2211').then(function (n) { return n.d; });
  if (view._destroyed) return null;
  const box = new SearchBox(search);
  await box.init();
  return box;
});
const ensureEntityMenu = (view) => loadViewService(view, "_entityMenuPromise", "EntityMenu", async () => {
  const { EntityMenu } = await import('./combobox.js?v=b74a2211').then(function (n) { return n.g; });
  if (view._destroyed) return null;
  return new EntityMenu(view);
});
const ensureSubmissionManager = (view) => loadViewService(view, "_submissionPromise", "SubmissionManager", async () => {
  const { SubmissionManager } = await import('./submission.js?v=b74a2211');
  if (view._destroyed) return null;
  return new SubmissionManager(view);
});
const ensureOfflineModal = (view) => loadViewService(view, "_offlineModalPromise", "offlineModal", async () => {
  if (!view.offlineIndicator) return null;
  const { OfflineModal } = await import('./modal.js?v=b74a2211');
  if (view._destroyed) return null;
  const modal = new OfflineModal(view, view.offlineIndicator);
  modal.enable();
  return modal;
});
const ensureModalClasses = (view) => loadViewService(view, "_modalClassesPromise", "ModalClasses", async () => {
  const { DeleteModal, HelpModal, Modal } = await import('./modal.js?v=b74a2211');
  if (view._destroyed) return null;
  return { DeleteModal, HelpModal, Modal };
});
const hasSyncCapability = (view) => Boolean(view.elt.querySelector("[lp-sync]"));
const settleServices = async (view, promises, context) => {
  const results = await Promise.allSettled(promises);
  for (const result of results) {
    if (result.status === "rejected") {
      view.reportStartupError(result.reason, view.elt, context);
    }
  }
  return results;
};
const initializeCoreServices = (view) => {
  if (view._servicesInitialized) return view.servicesReady;
  view._servicesInitialized = true;
  const start = view._publishedReady.then(() => view);
  view._serviceStart = start;
  const idle = start.then(() => whenIdle());
  const offlineWork = idle.then(async () => {
    const { inspectOfflineWork } = await import('./offlineWork.js?v=b74a2211');
    return inspectOfflineWork(view);
  });
  view.offlineQueueReady = offlineWork.then(
    ({ mutations }) => mutations ? ensureOfflineQueue(view) : null
  );
  view.syncReady = hasSyncCapability(view) ? start.then(() => ensureSyncManager(view)) : offlineWork.then(({ sync }) => sync ? ensureSyncManager(view) : null);
  view.initialReplayReady = view.offlineQueueReady.then(async (queue) => {
    if (!queue) return 0;
    const { replayOfflineQueue } = await import('./offline-replay.js?v=b74a2211').then(function (n) { return n.a; });
    return replayOfflineQueue(view, queue);
  });
  const essential = start.then(
    async () => {
      if (view._destroyed) return [];
      view._setOfflineIndicator();
      return await settleServices(
        view,
        [
          ensurePollingCoordinator(view),
          // Server-backed widgets are the visible page. Start them directly;
          // IndexedDB hydration and replay must never gate their first render.
          view.prefetch()
        ],
        "essential-service-startup"
      );
    }
  );
  const optional = idle.then(
    async () => {
      if (view._destroyed) return [];
      const warmers = [];
      if (document.querySelector("[data-role='notifications']")) {
        warmers.push(ensureNotifications(view));
      }
      if (view.elt.matches("[data-operation]") || view.elt.querySelector("[data-operation]")) {
        warmers.push(ensureDeferredOperations(view));
      }
      if (view.elt.querySelector("[lp-edited-marker]")) {
        warmers.push(ensureEditWatcher(view));
      }
      return await settleServices(view, warmers, "optional-service-startup");
    }
  );
  view.servicesReady = Promise.all([
    essential,
    optional,
    view.offlineQueueReady,
    view.syncReady,
    view.initialReplayReady
  ]).catch((error) => {
    view.reportStartupError(error, view.elt, "service-startup");
    return [];
  }).then(async (result) => {
    await view._publishedReady;
    if (!view._destroyed) markPerformance("lagniappe:services-ready");
    return result;
  });
  return view.servicesReady;
};

const ISOLATED_TASK_ACTIONS = /* @__PURE__ */ new Set(["TaskMove", "TaskCombine"]);
class Task extends ViewComponent {
  async activate(show) {
    const existingCombine = show === "TaskCombine" ? this.widgets.TaskCombine : null;
    if (show === "TaskCombine" && this.view.key) {
      const target = this.elt.querySelector(
        "[data-widget='TaskCombine']"
      );
      if (target?.dataset.route) {
        const route = new URL(target.dataset.route, window.location.origin);
        route.searchParams.set("page", this.view.key);
        const scopedRoute = `${route.pathname}${route.search}`;
        target.dataset.route = scopedRoute;
        if (existingCombine) existingCombine.route = scopedRoute;
      }
    }
    const activated = await super.activate(show);
    if (activated && existingCombine?.route) {
      const separator = existingCombine.route.includes("?") ? "&" : "?";
      await this.load(
        existingCombine,
        `${existingCombine.route}${separator}refresh=${Date.now()}`
      );
    }
    return activated;
  }
  closeOpenWidget() {
    if (!this.open || this.open === "false") return false;
    this.deactivate(false);
    return true;
  }
  get completed() {
    return this.elt.dataset.completed === "true";
  }
  get showEmptyFields() {
    return this.readonly && !this.completed;
  }
  get formData() {
    const active = this.activeWidget;
    if (active && ISOLATED_TASK_ACTIONS.has(active.name)) {
      return active.formData;
    }
    const taskWidgets = Object.values(this.widgets).filter(
      (widget) => !ISOLATED_TASK_ACTIONS.has(widget.name) && (widget === this.active || widget.unsavedState === true) && widget.target?.dataset.widget === widget.name && this.elt.contains(widget.target)
    );
    const data = taskWidgets.map((widget) => {
      if (widget.formData instanceof FormData) return widget.formData;
      if (widget.target instanceof HTMLFormElement) {
        return new FormData(widget.target);
      }
      return null;
    }).filter((form) => form !== null).reduce((merged, current) => {
      for (const [key, value] of current.entries()) {
        merged.append(key, value);
      }
      return merged;
    }, new FormData());
    taskWidgets.forEach((widget) => {
      data.append("active", widget.name);
    });
    return data;
  }
  async updated(response) {
    if (response.task_delta) {
      this.deactivate(false);
      const parent = this.view.getComponent(this.parentComponent);
      await parent?.widgets?.PageTaskList?.refreshDelta(response.task_delta);
      return;
    }
    const html = response.html || null;
    const update = html?.querySelector(`[id='${this.name}']`);
    if (update && this.completed !== (update.dataset.completed === "true")) {
      await withTransition(
        () => {
          if (this._destroyed || this.view._destroyed) return;
          const replacement = this.view.getComponent(update);
          if (!replacement)
            throw new Error("Task response requires a replacement component");
          update.dataset.open = "false";
          this.elt.replaceWith(update);
          this.destroy();
          this.view.components[replacement.name] = replacement;
          replacement.render(false);
        },
        { label: `${this.name}:completion` }
      );
      return;
    }
    if (update) {
      Object.assign(this.elt.dataset, {
        ...update.dataset,
        open: this.elt.dataset.open
      });
      this._replaceNav(update);
      this._removeMissingWidgets(update);
    }
    await super.updated(response);
  }
  _replaceNav(update) {
    const elt = update.querySelector("[lp-nav]");
    const target = this.nav?.element;
    if (!elt || !target) return;
    target.replaceWith(elt);
    this._nav = null;
  }
  _removeMissingWidgets(update) {
    this.elt.querySelectorAll("[data-widget]").forEach((elt) => {
      if (elt.closest("[lp-component]") !== this.elt) return;
      const name = elt.dataset.widget;
      if (!name) return;
      const target = update.querySelector(`[data-widget='${name}']`);
      if (target) return;
      elt.remove();
      if (this.active?.name === name) this.active = null;
      this.widgets[name]?.destroy?.();
      delete this.widgets[name];
    });
  }
}

const ROOT_COLLECTION_CHANNELS = /* @__PURE__ */ new Set([
  "categories",
  "projects",
  "pages",
  "tasks",
  "forms",
  "users",
  "ingress",
  "home"
]);
const isRootCollectionChannel = (channel) => Boolean(channel && ROOT_COLLECTION_CHANNELS.has(channel));
class Core extends ShellView {
  constructor(node) {
    super(node);
    this.hasDeferredServices = true;
    this.offlineIndicator = document.querySelector(
      '[data-role="offline"]'
    );
    this.offlineModal = null;
    this.Notifications = null;
    this.offlineQueue = null;
    this.PollingCoordinator = null;
    this.DeferredOperations = null;
    this.SyncManager = null;
    this.EditWatcher = null;
    this.SubmissionManager = null;
    this.SearchBox = null;
    this.EntityMenu = null;
    this.ModalClasses = null;
    this.offlineQueueReady = Promise.resolve(null);
    this.syncReady = Promise.resolve(null);
    this.initialReplayReady = Promise.resolve(0);
    this.replayReady = Promise.resolve(0);
    this.connectivityGeneration = 0;
    this._pendingChanges = [];
    this._reconcilePromise = null;
    this._componentActions = /* @__PURE__ */ new Map();
    this._pollingReconcileTask = null;
    this._pollingReconcileRequested = false;
    this._offlineReplayTask = null;
    this._coldControlListener = null;
    this.blurred = false;
    this.blurredAt = null;
  }
  queryParam(name) {
    const value = new URLSearchParams(window.location.search).get(name);
    return value?.trim() || null;
  }
  querySlug(value) {
    return value?.trim().replace(/([a-z0-9])([A-Z])/g, "$1-$2").replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase();
  }
  operationId() {
    return globalThis.crypto?.randomUUID?.() || `operation-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
  async init() {
    await super.init();
    initializeCoreServices(this);
    return this;
  }
  reportStartupError(error, element = this.elt, context = "lazy-control") {
    captureError(error, element, { context });
  }
  ensureOfflineQueue() {
    return ensureOfflineQueue(this);
  }
  ensurePollingCoordinator() {
    return ensurePollingCoordinator(this);
  }
  ensureSyncManager() {
    return ensureSyncManager(this);
  }
  ensureEditWatcher() {
    return ensureEditWatcher(this);
  }
  ensureDeferredOperations() {
    return ensureDeferredOperations(this);
  }
  ensureNotifications() {
    return ensureNotifications(this);
  }
  ensureSearchBox() {
    return ensureSearchBox(this);
  }
  ensureEntityMenu() {
    return ensureEntityMenu(this);
  }
  ensureSubmissionManager() {
    return ensureSubmissionManager(this);
  }
  ensureOfflineModal() {
    return ensureOfflineModal(this);
  }
  ensureModalClasses() {
    return ensureModalClasses(this);
  }
  /**
   * Subscribe the root view to its durable entity or collection revision.
   *
   */
  _initPollingSubscription() {
    if (!this.PollingCoordinator) return;
    const pollChannel = this.elt.dataset.pollChannel;
    const entityRevision = this.elt.dataset.pollEntityRevision;
    if (pollChannel) {
      this.PollingCoordinator.subscribe(
        {
          id: `view:channel:${pollChannel}`,
          type: "channel",
          channel: pollChannel,
          revision: this.elt.dataset.pollRevision ?? null
        },
        {
          mode: entityRevision ? "periodic" : "foreground",
          initial: "scheduled",
          onResult: async (result) => {
            if (result.status === "changed") await this.refresh();
          }
        }
      );
      if (!entityRevision) return;
    }
    const key = this.key;
    if (key) {
      const id = `view:entity:${key}`;
      this.PollingCoordinator.subscribe(
        {
          id,
          type: "entity",
          key,
          revision: entityRevision ?? this.elt.dataset.fingerprint ?? null
        },
        {
          mode: "periodic",
          initial: "scheduled",
          onResult: async (result) => {
            const watcher = this.elt.querySelector("[lp-edited-marker]") ? await this.ensureEditWatcher() : this.EditWatcher;
            await watcher?.receiveEntityResult?.(key, result);
            if (result.status === "unavailable") {
              await this.reconcileChange({ type: "delete", key });
              return;
            }
            if (result.status !== "changed") return;
            await this.reconcileChange({
              type: "entity-poll",
              key
            });
          }
        }
      );
      return;
    }
    const channel = this.elt.dataset.index || this.kind;
    if (!isRootCollectionChannel(channel)) return;
    this.PollingCoordinator.subscribe(
      {
        id: `view:channel:${channel}`,
        type: "channel",
        channel,
        revision: this.elt.dataset.fingerprint ?? null
      },
      {
        mode: "foreground",
        initial: "scheduled",
        onResult: async (result) => {
          if (result.status === "changed") await this.refresh();
        }
      }
    );
  }
  /**
   * Reconcile committed server invalidations without treating poll payloads as
   * authoritative replacement data. Concurrent invalidations share one pass
   * and any invalidations received mid-pass are
   * handled by the next iteration.
   *
   */
  reconcileChange(change = {}) {
    return reconcileChange(this, change);
  }
  async refreshSupplementalCollections(_changes) {
  }
  afterReconcileChange(_change) {
    return Promise.resolve();
  }
  onComponentRendered(_component) {
  }
  _applyStarState({ key, starred, type } = {}) {
    if (!key) return;
    const active = starred ?? type === "star";
    const buttons = /* @__PURE__ */ new Set([
      ...this.elt.querySelectorAll(
        `[data-key="${key}"] [lp-control="star"]`
      ),
      ...document.querySelectorAll(
        `[data-entity-key="${key}"][lp-control="star"]`
      )
    ]);
    for (const button of buttons) {
      button.dataset.active = active ? "true" : "false";
      const label = active ? "Unstar" : "Star";
      button.setAttribute("aria-label", label);
      button.title = label;
      const text = button.querySelector('[data-role="star-label"]');
      if (text) text.textContent = label;
    }
  }
  _adjustStarredCount(_delta) {
  }
  _setStarredCount(_count) {
  }
  async _toggleStar(button) {
    if (!this.online) return;
    const entity = button.closest("[lp-entity]") || button.closest("[data-key]");
    const key = entity?.id || entity?.dataset.key;
    if (!key) return;
    const active = button.dataset.active === "true";
    button.disabled = true;
    this._applyStarState({ key, starred: !active });
    this._adjustStarredCount(!active ? 1 : -1);
    try {
      const response = await request.patch(ENDPOINTS.toggleStar(key));
      if (!response?.ok) throw new Error("Unable to update star");
      if (typeof response.count === "number") {
        this._setStarredCount(response.count);
      }
      button.disabled = false;
      await this.reconcileChange({
        type: response.starred ? "star" : "unstar",
        key,
        starred: response.starred
      });
    } catch (error) {
      captureError(error, button);
      this._applyStarState({ key, starred: active });
      this._adjustStarredCount(active ? 1 : -1);
    } finally {
      button.disabled = false;
    }
  }
  _setOfflineIndicator() {
    this.offline = !this.online;
  }
  get offline() {
    return !this.online;
  }
  set offline(offline) {
    if (this.offlineIndicator) {
      this.offlineIndicator.dataset.visible = offline ? "true" : "false";
      this.offlineIndicator.setAttribute(
        "aria-hidden",
        offline ? "false" : "true"
      );
    }
    this.elt.dispatchEvent(
      new CustomEvent("offline-status", {
        detail: { offline: Boolean(offline) }
      })
    );
  }
  async sync({
    hidden = document.hidden,
    blurred = false,
    blurredAt = null,
    force = false
  } = {}) {
    const online = connectivity.online;
    const visibleBlur = Boolean(hidden && blurred);
    const wasInactive = this.hidden || !this.online || force;
    const changed = force || hidden !== this.hidden || visibleBlur !== this.blurred || online !== this.online;
    if (!changed) {
      return;
    }
    if (visibleBlur && !this.blurred) this.blurredAt = blurredAt ?? Date.now();
    else if (!visibleBlur) this.blurredAt = null;
    if (online && !this.online) this.connectivityGeneration += 1;
    this.hidden = hidden;
    this.blurred = visibleBlur;
    this.online = online;
    this.offline = !online;
    if (!online || hidden) {
      this.EditWatcher?.pause();
      if (visibleBlur)
        this.PollingCoordinator?.blur(this.blurredAt ?? void 0);
      else this.PollingCoordinator?.pause();
      await this.SyncManager?.deregister();
    } else {
      await Promise.all([
        this.ensurePollingCoordinator(),
        this.SyncManager || this.elt.querySelector("[lp-sync]") ? this.ensureSyncManager() : null,
        this.elt.querySelector("[lp-edited-marker]") ? this.ensureEditWatcher() : null
      ]);
      if (wasInactive && !hidden) {
        this.scheduleOfflineReplay();
        await this.EditWatcher?.resume();
      } else {
        await this.EditWatcher?.resume();
      }
      await this.SyncManager?.register();
      await this.reconcilePollingSubscriptions();
      if (wasInactive && !hidden) {
        await this.PollingCoordinator?.catchUp();
      } else {
        await this.PollingCoordinator?.resume();
      }
    }
  }
  /**
   * Replay is background reconciliation, never a prerequisite for restoring
   * polling, sync, EditWatcher, or the visible server render. OfflineQueue
   * itself polls mounted updated forms as each replay succeeds.
   *
   */
  scheduleOfflineReplay() {
    if (this._offlineReplayTask) return this._offlineReplayTask;
    const replay = import('./offline-replay.js?v=b74a2211').then(function (n) { return n.a; }).then(
      ({ replayOfflineQueue }) => replayOfflineQueue(this)
    );
    this._offlineReplayTask = replay;
    this.replayReady = replay;
    const complete = () => {
      if (this._offlineReplayTask === replay) this._offlineReplayTask = null;
    };
    void replay.then(complete, complete);
    return replay;
  }
  /**
   * Reconcile widget-owned polling after a component activation or a return
   * to the foreground. Managers retain state for hidden widgets, but only the
   * active visible widget may own recurring form, document, or ingress work.
   *
   */
  async reconcilePollingSubscriptions() {
    if (this._destroyed || this.hidden || !this.online) return;
    await this.EditWatcher?.reconcileSubscriptions?.();
    await this.SyncManager?.reconcileSubscriptions?.();
    await Promise.all(
      Object.values(this.components).flatMap(
        (component) => Object.values(component.widgets).map(
          (widget) => widget?.syncPollingSubscription?.()
        )
      )
    );
  }
  /**
   * Schedule subscription ownership reconciliation without making component
   * rendering wait for manager or network work. Repeated renders coalesce and
   * request at most one follow-up pass if ownership changes while a pass runs.
   *
   */
  schedulePollingReconciliation() {
    if (this._destroyed || this.hidden || !this.online) {
      return Promise.resolve();
    }
    this._pollingReconcileRequested = true;
    if (this._pollingReconcileTask) return this._pollingReconcileTask;
    const pending = Promise.resolve().then(async () => {
      while (this._pollingReconcileRequested && !this._destroyed) {
        this._pollingReconcileRequested = false;
        await this.reconcilePollingSubscriptions();
      }
    }).catch((error) => {
      this.reportStartupError(
        error,
        this.elt,
        "polling-subscription-reconciliation"
      );
    }).finally(() => {
      if (this._pollingReconcileTask === pending) {
        this._pollingReconcileTask = null;
      }
    });
    this._pollingReconcileTask = pending;
    return pending;
  }
  async prefetch() {
    const prefetch = this.elt.querySelectorAll("[lp-component][lp-prefetch]");
    await Promise.all(
      Array.from(prefetch).map(async (elt) => {
        const component = this.getComponent(elt);
        if (!component) return;
        await component.prefetch();
      })
    );
  }
  _collectRefreshTargets(components) {
    return collectRefreshTargets(this, components);
  }
  async _refreshCollectionComponents(components, options = {}) {
    return refreshCollectionComponents(this, components, options);
  }
  async refreshCollections(navigation = false, options = {}) {
    const components = Object.values(this.components);
    const { beforeCommit = null, ...refreshOptions } = options;
    const commit = await this._refreshCollectionComponents(components, {
      ...refreshOptions,
      deferCommit: true
    });
    if (!commit) return;
    const commitRefresh = () => {
      beforeCommit?.();
      commit();
    };
    if (navigation) {
      commitRefresh();
    } else {
      await withTransition(commitRefresh, { label: "collections:refresh" });
    }
  }
  async refresh(navigation = false, options = {}) {
    return this.refreshCollections(navigation, options);
  }
  async notify(message) {
    const notifications = await this.ensureNotifications();
    await notifications?.notify?.(message);
  }
  _installColdControlListeners() {
    this._coldControlListener = this._coldControlEvent.bind(this);
    for (const type of ["input", "click"]) {
      document.addEventListener(type, this._coldControlListener, true);
    }
  }
  _removeColdControlListeners() {
    if (!this._coldControlListener) return;
    for (const type of ["input", "click"]) {
      document.removeEventListener(type, this._coldControlListener, true);
    }
    this._coldControlListener = null;
  }
  _coldControlEvent(event) {
    const { target } = event;
    if (!(target instanceof Element)) return;
    const search = target.closest("[lp-search]");
    if (search && !this.SearchBox) {
      this.runColdAction(
        search,
        () => this.ensureSearchBox(),
        (box) => this._activateSearchBox(box),
        search
      );
      return;
    }
    const offline = target.closest("[data-role='offline']");
    if (offline && !this.offlineModal && event.type === "click") {
      event.preventDefault();
      event.stopImmediatePropagation?.();
      this.runColdAction(
        offline,
        () => this.ensureOfflineModal(),
        (modal) => modal?.attach?.(),
        offline
      );
      return;
    }
    const notifications = target.closest("[data-role='notifications']");
    if (!notifications || this.Notifications) return;
    if (event.type === "click") {
      event.preventDefault();
      event.stopImmediatePropagation?.();
    }
    this.runColdAction(
      notifications,
      () => this.ensureNotifications(),
      (manager) => manager?.dropdown?.showPanel?.(),
      notifications
    );
  }
  _click(e) {
    const target = e?.target;
    if (!e || !(target instanceof Element)) return;
    const menuTrigger = target.closest("[data-role='menu-trigger']");
    const menu = menuTrigger?.closest("[lp-menu]");
    if (menu && this.elt.contains(menu)) {
      e.preventDefault();
      e.stopPropagation();
      this.runColdAction(
        menu,
        () => this.ensureEntityMenu(),
        (manager) => manager?.toggle(menu),
        menuTrigger
      );
      return;
    }
    const button = target.closest("button");
    const control = button?.getAttribute("lp-control");
    if (button?.matches("[data-role='flipper']")) {
      e.preventDefault();
      const flip = button.closest("[data-flipped]");
      if (!flip) return;
      const flipped = flip.dataset.flipped === "false";
      flip.dataset.flipped = flipped ? "true" : "false";
      return;
    } else if (button && control === "help") {
      e.preventDefault();
      e.stopPropagation();
      void this._showHelpModal(button);
      return;
    } else if (button && control === "star") {
      e.preventDefault();
      void this._toggleStar(button);
      return;
    } else if (button && control === "delete") {
      e.preventDefault();
      e.stopPropagation();
      void this._showDeleteModal(button);
      return;
    } else if (button && (control === "previous" || control === "next")) {
      e.preventDefault();
      if (!this.online) return;
      const widget = target.closest("[data-widget]");
      const widgetName = widget?.dataset.widget;
      const route = button.dataset.route;
      if (!widgetName || !route) return;
      const component = this.getComponent(widget);
      void request.get(route).then((response) => {
        component?.widgets[widgetName]?.refresh?.(response);
      });
      return;
    } else if (control || button?.hasAttribute("lp-show")) {
      e.preventDefault();
      void this.renderComponent(button);
      return;
    }
    if (target.closest("form") || target.closest("a") || target.closest("input") || target.closest("button")) {
      return;
    }
    const toggle = target.closest("[lp-show]");
    if (toggle) {
      e.preventDefault();
      void this.renderComponent(toggle);
      return;
    }
    const link = target.closest("[lp-link]");
    if (link) {
      const title = link.matches("tr[lp-entity]") ? "td[data-column='name'] [data-role='title']" : "[data-role='title']";
      link.querySelector(title)?.click();
      return;
    }
  }
  async _showDeleteModal(button) {
    return this.runColdAction(
      button,
      () => this.ensureModalClasses(),
      async (classes) => {
        if (!classes?.DeleteModal) return;
        const modal = new classes.DeleteModal(this, button);
        await modal.init();
      }
    );
  }
  async _showHelpModal(button) {
    return this.runColdAction(
      button,
      () => this.ensureModalClasses(),
      async (classes) => {
        if (!classes?.HelpModal) return;
        const modal = new classes.HelpModal(this, button);
        await modal.init();
      }
    );
  }
  getComponent(itemElt) {
    const target = itemElt?.closest("[lp-component]");
    if (target?._lp_component) return target._lp_component;
    const id = target?.id || target?.dataset?.key;
    if (id && target?.hasAttribute("lp-component")) {
      const ComponentClass = target.matches(
        "li[lp-component][data-kind='task']"
      ) ? Task : ViewComponent;
      const component = new ComponentClass(target, this);
      this.components[id] = component;
      target._lp_component = component;
      target.setAttribute("initialized", "");
      return component;
    }
    return null;
  }
  successfulResponse(response, component) {
    if (!response) return false;
    if (response.reload) {
      window.location.reload();
      return false;
    }
    if (response.error) {
      component?.showError?.(response.error);
      return false;
    }
    const { modal } = response;
    if (modal) {
      void this.ensureModalClasses().then((classes) => {
        if (this._destroyed || !classes?.Modal) return;
        if (typeof modal === "string") {
          captureError(
            new TypeError("Modal markup must be parsed before attachment"),
            component
          );
          return;
        }
        void new classes.Modal(this).attach(modal, component);
      });
      return false;
    }
    return true;
  }
  async update(component, data, route = component.route) {
    const manager = await this.ensureSubmissionManager();
    return manager?.update(component, data, route);
  }
  async create(component, data, route = component.route) {
    const manager = await this.ensureSubmissionManager();
    return manager?.create(component, data, route);
  }
  async load(component, route) {
    if (!route) return null;
    const response = await request.get(route);
    if (!response || !this.successfulResponse(response, component)) return null;
    return response;
  }
  _setLoadingTrigger(trigger, component, widgetName) {
    const target = component.elt.querySelector(`[data-widget="${widgetName}"]`);
    if (!target || target.hasAttribute("loaded")) return null;
    const loadsAsync = target?.hasAttribute("lp-load") || target?.hasAttribute("lp-prefetch");
    trigger.setAttribute("aria-busy", "true");
    if (loadsAsync) trigger.dataset.loading = "true";
    return trigger;
  }
  _clearLoadingTrigger(trigger) {
    if (!trigger) return;
    delete trigger.dataset.loading;
    trigger.removeAttribute("aria-busy");
  }
  renderComponent(trigger) {
    if (!trigger) return;
    if (this._componentActions.has(trigger)) {
      return this._componentActions.get(trigger);
    }
    const attribute = trigger.getAttribute("lp-show") || trigger.getAttribute("lp-close") || "";
    const [componentId, requestedWidget] = attribute.split(":");
    if (!componentId) {
      captureError(new Error("No component ID found"), trigger);
      return;
    }
    const targetElt = document.getElementById(componentId);
    const component = this.getComponent(targetElt);
    if (!component) {
      captureError(new Error("No component found"), trigger, { componentId });
      return;
    }
    const activeWidget = component.active?.name;
    let widgetName = requestedWidget === "active" && activeWidget ? activeWidget : requestedWidget;
    const toggleWidget = trigger.dataset.toggle === "true" && activeWidget === widgetName;
    const toggleComponent = component.visible && widgetName === "default";
    const showActiveWidget = widgetName === "active" && component.active;
    if (toggleWidget || toggleComponent) {
      const active = component.active;
      widgetName = active && "visible" in active && active.visible ? null : activeWidget;
    } else if (showActiveWidget) {
      widgetName = activeWidget;
    }
    const loadingTrigger = widgetName ? this._setLoadingTrigger(trigger, component, widgetName) : null;
    const pending = component.activate(widgetName).then(async (activated) => {
      if (this._destroyed || trigger.isConnected === false) return null;
      await component.prepareRender(activated);
      const committed = await withTransition(
        () => {
          if (this._destroyed) return;
          component.render(activated);
        },
        { label: `${component.name}:activate` }
      );
      if (activated && committed !== false && !this._destroyed && trigger.isConnected && component.elt.isConnected) {
        component.elt.dispatchEvent(
          new CustomEvent("component-opened", {
            bubbles: true,
            detail: { component, trigger }
          })
        );
      }
      return committed;
    }).catch((error) => {
      this.reportStartupError(error, trigger, "component-activation");
      return null;
    }).finally(() => {
      this._clearLoadingTrigger(loadingTrigger);
      if (this._componentActions.get(trigger) === pending) {
        this._componentActions.delete(trigger);
      }
    });
    this._componentActions.set(trigger, pending);
    return pending;
  }
  addFlash(node) {
    if (!node || node.classList.contains("flash")) return;
    node.classList.add("flash");
    node.addEventListener(
      "animationend",
      () => {
        node.classList.remove("flash");
      },
      { once: true }
    );
  }
  destroy() {
    super.destroy();
    this._pollingReconcileRequested = false;
    this.SubmissionManager?.destroy();
    this.SyncManager?.destroy();
    this.DeferredOperations?.destroy();
    this.EntityMenu?.destroy();
    this.EditWatcher?.destroy();
    this.Notifications?.destroy?.();
    this.PollingCoordinator?.destroy();
    this.SearchBox?.destroy?.();
    this.offlineModal?.destroy?.();
    this._componentActions.clear();
    Object.values(this.components).forEach((component) => {
      if (component.destroy) component.destroy();
    });
    this.components = {};
  }
}

export { Core as C, NavElement as N, loadWidget as l };
