/*! Third-party licenses: /third-party-licenses.txt */
import { BaseList, listHtml } from './baseList.js?v=b8e0e957';
import { e as localStore, w as withTransition, r as request } from './foundation.js?v=b8e0e957';
import { S as STYLES, s as setIcon } from './ui-resources.js?v=b8e0e957';
import './connectivity.js?v=b8e0e957';
import { D as Dropdown } from './combobox.js?v=b8e0e957';

const REPORT_FILTERS = ["active", "executed", "answers"];
function isReportFilter(value) {
  return REPORT_FILTERS.some((filter) => filter === value);
}
function reportCategory(report) {
  if (report.outputKind === "answer") return "answers";
  return report.outputKind === "proposal" && report.status === "complete" ? "executed" : "active";
}
function _listToggle(component, widgetName) {
  return component.elt.querySelector(
    `[lp-show='${component.name}:${widgetName}'][data-toggle]`
  );
}
function _syncEmptyCount(toggle, widgetName, empty) {
  const indicator = toggle?.querySelector(
    `[data-indicator='${widgetName}']`
  );
  if (!indicator) return;
  const wasEmpty = indicator.dataset.empty === "true";
  indicator.dataset.empty = empty ? "true" : "false";
  indicator.classList.toggle("hidden", !empty);
  indicator.classList.toggle("font-bold", empty);
  if (empty) {
    indicator.textContent = "0";
  } else if (wasEmpty) {
    indicator.textContent = "";
  }
}
class LoadedHomeList extends BaseList {
  static unlockToggleWhenPopulated = false;
  static disableToggleWhenUnavailable = false;
  constructor(attributes) {
    super(attributes);
    this._listToggle = _listToggle(this.component, this.name);
  }
  _syncUnavailableToggle() {
    const ListClass = this.constructor;
    if (!ListClass.disableToggleWhenUnavailable || !this._listToggle) {
      return;
    }
    const unavailable = this.itemCount === 0 && !this.target.dataset.ifEmpty;
    this._listToggle.disabled = unavailable;
    this._listToggle.classList.toggle("opacity-50", unavailable);
    _syncEmptyCount(this._listToggle, this.name, unavailable);
  }
  postreconcile() {
    super.postreconcile();
    this._syncUnavailableToggle();
    const ListClass = this.constructor;
    if (ListClass.unlockToggleWhenPopulated && this.itemCount > 0 && this._listToggle) {
      this._listToggle.classList.remove("opacity-50", "pointer-events-none");
    }
    this.target.setAttribute("loaded", "");
  }
}
class HomeProjectList extends LoadedHomeList {
  static disableToggleWhenUnavailable = true;
}
class HomeCategoryList extends LoadedHomeList {
  static disableToggleWhenUnavailable = true;
}
class HomePageList extends LoadedHomeList {
  static unlockToggleWhenPopulated = true;
  static disableToggleWhenUnavailable = true;
}
class DirectoryList extends LoadedHomeList {
  static unlockToggleWhenPopulated = true;
}
class IngressList extends LoadedHomeList {
  static unlockToggleWhenPopulated = true;
}
class ToolReportList extends BaseList {
  constructor(attributes) {
    super(attributes);
    this._listToggle = _listToggle(this.component, this.name);
    this.storageKey = `home-report-filters:${this.component.elt.dataset.reportUser}`;
    const saved = localStore.getJSON(this.storageKey);
    this.filters = new Set(
      Array.isArray(saved) && saved.every(isReportFilter) ? saved : ["active", "answers"]
    );
    this._click = this._click.bind(this);
    this._deleteMessage = "";
  }
  init() {
    this.component.elt.addEventListener("click", this._click);
  }
  get reportItems() {
    return Array.from(
      this.target.querySelectorAll(
        "li[lp-entity][data-kind='report']"
      )
    );
  }
  get itemCount() {
    return this.reportItems.length;
  }
  get isPaginated() {
    return Boolean(
      this.target.querySelector?.(
        "[lp-control='next'], [lp-control='previous']"
      )
    );
  }
  created(response) {
    super.created(response);
    const items = listHtml(response)?.querySelectorAll(
      "li[lp-entity][data-kind='report']"
    ) || [];
    for (const item of items) this.filters.add(reportCategory(item.dataset));
    if (items.length) localStore.setJSON(this.storageKey, [...this.filters]);
  }
  _click(event) {
    if (!(event.target instanceof Element)) return;
    const filter = event.target.closest(
      "[data-role='report-filter']"
    );
    const value = filter?.dataset.filter;
    if (filter && this.target.contains(filter) && isReportFilter(value)) {
      if (this.filters.has(value)) this.filters.delete(value);
      else this.filters.add(value);
      localStore.setJSON(this.storageKey, [...this.filters]);
      void withTransition(() => this._renderFilters(), {
        label: "reports:filter"
      });
    }
    const clear = event.target.closest(
      "[data-role='delete-executed-reports']"
    );
    if (clear && this.target.contains(clear)) void this._openDelete(clear);
  }
  _renderFilters() {
    const counts = { active: 0, executed: 0, answers: 0 };
    let visible = 0;
    for (const item of this.reportItems) {
      const category = reportCategory(item.dataset);
      counts[category]++;
      item.hidden = !this.filters.has(category);
      if (!item.hidden) visible++;
    }
    for (const button of this.target.querySelectorAll(
      "[data-role='report-filter']"
    )) {
      const filter = button.dataset.filter;
      if (!isReportFilter(filter)) continue;
      const selected = this.filters.has(filter).toString();
      button.dataset.active = selected;
      button.setAttribute("aria-pressed", selected);
      const count = button.querySelector("[data-role='report-count']");
      if (count) count.textContent = String(counts[filter]);
    }
    const paginated = this.isPaginated;
    const empty = this.target.querySelector(
      "[data-role='report-empty']"
    );
    if (empty) {
      empty.hidden = visible > 0;
      const suffix = paginated ? " on this page." : ".";
      const [firstFilter] = this.filters;
      empty.textContent = !firstFilter ? "Select a report type to show." : this.filters.size === 1 ? `${{
        active: "No active proposals",
        executed: "No executed proposals",
        answers: "No answers"
      }[firstFilter]}${suffix}` : `No reports match the selected types${suffix}`;
    }
    const clear = this.target.querySelector(
      "[data-role='delete-executed-reports']"
    );
    if (clear) {
      clear.hidden = !(this.filters.size === 1 && this.filters.has("executed") && counts.executed > 0);
      clear.disabled = Boolean(this._deleting);
      const clearLabel = clear.querySelector?.(
        "[data-role='delete-executed-label']"
      );
      if (clearLabel) {
        clearLabel.textContent = paginated ? "Delete executed proposals on this page" : "Delete all executed proposals";
      }
    }
    const result = this.target.querySelector(
      "[data-role='report-delete-result']"
    );
    if (result) {
      result.textContent = this._deleteMessage;
      result.hidden = !this._deleteMessage;
    }
  }
  postreconcile() {
    const created = this._created;
    this._created = [];
    super.postreconcile();
    if (created.length) {
      this.target.querySelector("[data-role='report-items']")?.prepend(...created);
      for (const item of created) this.view.addFlash(item);
    }
    this.target.dataset.visible = Boolean(
      this.visible || this.component.active === this
    ).toString();
    this._renderFilters();
    void this.view.ensureDeferredOperations?.().then((manager) => manager?.scan(this.target));
    _syncEmptyCount(this._listToggle, this.name, this.itemCount === 0);
    if (this.itemCount > 0 && this._listToggle) {
      this._listToggle.classList.remove("opacity-50", "pointer-events-none");
    }
    this.target.setAttribute("loaded", "");
  }
  async _openDelete(trigger) {
    if (this._openingDelete || this._deleting || this._deleteModal?.modal)
      return;
    if (this.filters.size !== 1 || !this.filters.has("executed")) return;
    if (!this.view.online) {
      this._deleteMessage = "Connect to the server to delete reports.";
      this._renderFilters();
      return;
    }
    const keys = this.reportItems.filter((item) => reportCategory(item.dataset) === "executed").map((item) => item.dataset.key).filter((key) => Boolean(key));
    const route = trigger.dataset.route;
    if (!keys.length || !route) return;
    const element = this.target.querySelector(
      "[data-role='report-delete-template']"
    )?.content.querySelector("#modal")?.cloneNode(true);
    if (!(element instanceof HTMLElement)) return;
    const content = element.querySelector("#modal-content");
    const description = element.querySelector(
      "[data-role='report-delete-description']"
    );
    const confirm = element.querySelector(
      "[data-role='confirm-delete-reports']"
    );
    const confirmLabel = confirm?.querySelector("[data-role='text']");
    if (!content || !description || !confirm || !confirmLabel) return;
    this._openingDelete = true;
    try {
      const { Modal } = await import('./modal.js?v=b8e0e957');
      if (this._destroyed) return;
      this._deleteModal?.destroy();
      const modal = new Modal(this.view, trigger);
      this._deleteModal = modal;
      content.setAttribute("role", "dialog");
      content.setAttribute("aria-modal", "true");
      content.setAttribute("aria-labelledby", "report-delete-title");
      const noun = keys.length === 1 ? "proposal" : "proposals";
      description.textContent = `Delete ${keys.length} executed ${noun}? Their reports, undo history, and report-only uploads will be deleted. Pages, tasks, and other workspace changes will remain.`;
      confirmLabel.textContent = `Delete ${keys.length} ${noun}`;
      confirm.addEventListener("click", () => {
        void this._deleteExecuted(keys, route, modal);
      });
      await modal.attach(element);
      confirm.focus();
    } finally {
      this._openingDelete = false;
    }
  }
  async _deleteExecuted(keys, route, modal) {
    if (this._deleting) return;
    const confirm = modal.modal?.querySelector(
      "[data-role='confirm-delete-reports']"
    );
    const error = modal.modal?.querySelector(
      "[data-role='report-delete-error']"
    );
    const spinner = confirm?.querySelector("#spinner");
    if (!confirm || !error || !spinner) return;
    this._deleting = true;
    confirm.disabled = true;
    spinner.dataset.visible = "true";
    error.hidden = true;
    this._renderFilters();
    try {
      const { request } = await import('./foundation.js?v=b8e0e957').then(function (n) { return n.p; });
      const response = await request.delete(route, {
        keys
      });
      if (!response?.ok)
        throw new Error("Reports could not be deleted. Please try again.");
      const deleted = new Set(response.deleted || []);
      const skipped = response.skipped?.length || 0;
      const failed = response.failed?.length || 0;
      this._deleteMessage = [
        skipped ? `${skipped} no longer eligible or already deleted.` : "",
        failed ? `${failed} could not be deleted. Please try again.` : ""
      ].filter(Boolean).join(" ");
      await modal.remove();
      if (this._destroyed) return;
      await withTransition(
        () => {
          for (const item of this.reportItems) {
            const key = item.dataset.key;
            if (key && deleted.has(key)) item.remove();
          }
          this.postreconcile();
        },
        { label: "reports:delete-executed" }
      );
      await this.view._refreshHomeWidget(this.component, this);
    } catch {
      this._deleteMessage = "Reports could not be deleted. Please try again.";
      if (modal.modal) {
        error.textContent = this._deleteMessage;
        error.hidden = false;
        confirm.disabled = false;
      }
    } finally {
      spinner.dataset.visible = "false";
      this._deleting = false;
      if (!this._destroyed) this._renderFilters();
    }
  }
  destroy() {
    this._destroyed = true;
    this.component.elt.removeEventListener("click", this._click);
    this._deleteModal?.destroy();
  }
}
class StarredList extends BaseList {
  constructor(attributes) {
    super(attributes);
    this._listToggle = _listToggle(this.component, this.name);
  }
  get countElt() {
    return this.component.elt.querySelector("[data-role='starred-count']");
  }
  postreconcile() {
    super.postreconcile();
    const count = this.countElt;
    if (count) count.textContent = String(this.itemCount);
    this._listToggle?.classList.toggle("opacity-50", this.itemCount === 0);
    this._listToggle?.classList.toggle(
      "pointer-events-none",
      this.itemCount === 0
    );
    this.target.setAttribute("loaded", "");
  }
}

var lists = /*#__PURE__*/Object.freeze({
	__proto__: null,
	DirectoryList: DirectoryList,
	HomeCategoryList: HomeCategoryList,
	HomePageList: HomePageList,
	HomeProjectList: HomeProjectList,
	IngressList: IngressList,
	StarredList: StarredList,
	ToolReportList: ToolReportList
});

class HomeActivityList extends BaseList {
  constructor(attributes) {
    super(attributes);
    this._click = this._click.bind(this);
  }
  init() {
    this.target.addEventListener("click", this._click);
  }
  async _click(e) {
    if (!(e.target instanceof Element)) return;
    const button = e.target.closest(
      "[data-action='delete-activity']"
    );
    if (!button) return;
    await this.deleteActivity(button);
  }
  handleOfflineQueue({ phase, queue, record }) {
    if (phase === "queued") return this._offlineQueued(record, queue);
    if (phase === "cancelled") return this._offlineCancelled(record);
  }
  _offlineQueued(record, queue) {
    if (record.kind === "note" && record.action === "create") {
      const key = record.client_key;
      if (key) return queue.response(this._renderNote(record, queue, key));
    }
    if (record.action === "delete") return this._removeByKey(record.target_key);
  }
  _offlineCancelled(record) {
    if (record.action === "create") return this._removeByKey(record.client_key);
  }
  async deleteActivity(button) {
    const key = button.dataset.key;
    const item = button.closest(
      "li[data-key], [lp-entity][data-key]"
    );
    if (!key || !item) return;
    if (key.startsWith("offline:")) {
      const queue = this.view.offlineQueue || await this.view.ensureOfflineQueue?.();
      await queue?.cancel({
        action: "create",
        client_key: key
      });
      return;
    }
    if (item.dataset.kind === "note") return;
    const route = `/l/activity/${key}`;
    if (!this.view.online) {
      const queue = this.view.offlineQueue || await this.view.ensureOfflineQueue?.();
      await queue?.queue({
        id: `delete:${key}`,
        kind: item.dataset.kind || "activity",
        action: "delete",
        method: "DELETE",
        route,
        target_key: key
      });
      return;
    }
    button.disabled = true;
    const response = await request.delete(route);
    button.disabled = false;
    if (response?.ok) {
      await withTransition(() => this._commitRemoveItem(item), {
        label: "home:activity-delete"
      });
    }
  }
  _renderNote(record, queue, key) {
    const body = queue.field(record, "body");
    const visibility = queue.field(record, "visibility") || "private";
    const file = record.files?.[0]?.file;
    const item = document.createElement("li");
    item.dataset.key = key;
    item.dataset.kind = "note";
    item.dataset.offline = "true";
    item.className = [STYLES.note.item.home, "opacity-80"].join(" ");
    const content = document.createElement("div");
    content.className = STYLES.note.content;
    item.append(content);
    if (body) {
      const bodyElt = document.createElement("span");
      bodyElt.className = STYLES.note.body;
      bodyElt.textContent = body;
      content.append(bodyElt);
    }
    if (file) {
      const image = document.createElement("img");
      image.src = URL.createObjectURL(file);
      image.className = STYLES.note.photo.home;
      image.alt = "";
      content.append(image);
    }
    const meta = document.createElement("span");
    meta.className = STYLES.note.meta;
    meta.textContent = `Pending sync \xB7 ${visibility === "everyone" ? "Everyone" : "Private"}`;
    content.append(meta);
    const button = document.createElement("button");
    button.className = STYLES.note.discard;
    button.dataset.action = "delete-activity";
    button.dataset.key = key;
    button.type = "button";
    button.setAttribute("aria-label", "Discard pending note");
    button.title = "Discard pending note";
    item.append(button);
    const icon = document.createElement("span");
    setIcon(icon, "close");
    button.append(icon);
    return item;
  }
  _itemByKey(root, key) {
    if (!root || !key) return null;
    return Array.from(root.querySelectorAll("[data-key]")).find(
      (item) => item.dataset.key === key
    );
  }
  _removeByKey(key) {
    const item = this._itemByKey(this.target, key);
    if (!item) return void 0;
    return withTransition(() => this._commitRemoveItem(item), {
      label: "home:activity-offline-remove"
    });
  }
  ensureEmptyState(list = this.target) {
    if (!list) return false;
    if (list.querySelector("li:not([data-role='empty'])")) return false;
    if (list.querySelector("li[data-role='empty']")) return false;
    const empty = document.createElement("li");
    empty.dataset.role = "empty";
    empty.className = STYLES.note.empty;
    empty.textContent = "No notes yet \u2014 use + to add a quick note.";
    list.append(empty);
    return true;
  }
  _commitRemoveItem(item) {
    const list = item.closest("ul");
    item.remove();
    if (list && list.querySelectorAll("li:not([data-role='empty'])").length === 0) {
      this.ensureEmptyState(list);
      this.view.syncHomeSectionState?.(this.component);
    }
  }
  postreconcile() {
    const updated = this._updated;
    super.postreconcile();
    if (this.ensureEmptyState() && (this.visible || this.component.active === this)) {
      this.target.dataset.visible = "true";
    }
    if (updated) {
      this.destroy();
      this.init();
    }
    this.target.setAttribute("loaded", "");
  }
  destroy() {
    this.target.removeEventListener("click", this._click);
  }
}

var activity = /*#__PURE__*/Object.freeze({
	__proto__: null,
	HomeActivityList: HomeActivityList
});

const WEEKDAY_NAMES = [
  "sunday",
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday"
];
function _toDateStr(offset = 0) {
  const d = /* @__PURE__ */ new Date();
  d.setDate(d.getDate() + offset);
  return d.toLocaleDateString("sv-SE");
}
function _dateInfo(dateStr) {
  const today = _toDateStr();
  if (dateStr === today) return { label: "Today", due: "today" };
  if (dateStr === _toDateStr(1)) return { label: "Tomorrow", due: "future" };
  if (dateStr === _toDateStr(-1)) return { label: "Yesterday", due: "past" };
  const [year, month, day] = dateStr.split("-").map(Number);
  const label = new Date(year, month - 1, day).toLocaleDateString(void 0, {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
  return { label, due: dateStr < today ? "past" : "future" };
}
function _isWithinHomeTaskWindow(dueDate) {
  if (!dueDate) return false;
  const today = /* @__PURE__ */ new Date();
  today.setHours(0, 0, 0, 0);
  const nextWeek = new Date(today);
  nextWeek.setDate(nextWeek.getDate() + 7);
  const due = /* @__PURE__ */ new Date(`${dueDate}T00:00:00`);
  return due >= today && due <= nextWeek;
}
function _insertSorted(target, task) {
  const dueDate = task.dataset.dueDate;
  for (const item of target.querySelectorAll("[lp-entity]")) {
    const itemDueDate = item.dataset.dueDate;
    if (itemDueDate !== void 0 && dueDate !== void 0 && itemDueDate > dueDate) {
      item.before(task);
      return;
    }
  }
  target.append(task);
}
const _postponeMenu = (dropdown, postpone) => {
  let showingNextWeek = false;
  let showingThisWeek = false;
  let returnFocusIndex = 0;
  const weekdayFormatter = new Intl.DateTimeFormat(void 0, {
    weekday: "long"
  });
  const dateFormatter = new Intl.DateTimeFormat(void 0, {
    day: "numeric",
    month: "short"
  });
  const hasDaysLeftThisWeek = (/* @__PURE__ */ new Date()).getDay() !== 0;
  const primaryItems = [
    {
      name: "Tomorrow",
      icon: "tomorrow",
      kind: "task",
      onClick: () => postpone("tomorrow")
    },
    ...hasDaysLeftThisWeek ? [
      {
        name: "This Week\u2026",
        icon: "weekend",
        kind: "task",
        closeOnClick: false,
        onClick: () => {
          returnFocusIndex = 1;
          showThisWeek();
        }
      }
    ] : [],
    {
      name: "Next Week\u2026",
      icon: "nextWeek",
      kind: "task",
      closeOnClick: false,
      onClick: () => {
        returnFocusIndex = primaryItems.findIndex(
          (item) => item.name === "Next Week\u2026"
        );
        showNextWeek();
      }
    },
    {
      name: "No Due Date",
      icon: "removeDueDate",
      kind: "task",
      onClick: () => postpone(null)
    }
  ];
  const showPrimary = () => {
    showingThisWeek = false;
    showingNextWeek = false;
    dropdown.updateOptions(primaryItems);
    dropdown.focusOption(returnFocusIndex);
  };
  const showThisWeek = () => {
    const today = /* @__PURE__ */ new Date();
    today.setHours(12, 0, 0, 0);
    const daysUntilSunday = 7 - today.getDay();
    const items = [
      {
        name: "Back",
        icon: "back",
        kind: "task",
        closeOnClick: false,
        onClick: showPrimary
      },
      ...Array.from({ length: daysUntilSunday }, (_, index) => {
        const date = new Date(today);
        date.setDate(date.getDate() + index + 1);
        const weekday = WEEKDAY_NAMES[date.getDay()];
        return {
          name: `${weekdayFormatter.format(date)} \xB7 ${dateFormatter.format(date)}`,
          icon: "date",
          kind: "task",
          onClick: () => postpone(`this-week-${weekday}`)
        };
      })
    ];
    showingThisWeek = true;
    dropdown.updateOptions(items);
    dropdown.focusOption(0);
  };
  const showNextWeek = () => {
    const monday = /* @__PURE__ */ new Date();
    monday.setHours(12, 0, 0, 0);
    const daysUntilMonday = (8 - monday.getDay()) % 7 || 7;
    monday.setDate(monday.getDate() + daysUntilMonday);
    const weekdays = WEEKDAY_NAMES.slice(1, 6);
    const items = [
      {
        name: "Back",
        icon: "back",
        kind: "task",
        closeOnClick: false,
        onClick: showPrimary
      },
      ...weekdays.map((weekday, offset) => {
        const date = new Date(monday);
        date.setDate(date.getDate() + offset);
        return {
          name: `${weekdayFormatter.format(date)} \xB7 ${dateFormatter.format(date)}`,
          icon: "date",
          kind: "task",
          onClick: () => postpone(`next-week-${weekday}`)
        };
      })
    ];
    showingNextWeek = true;
    dropdown.updateOptions(items);
    dropdown.focusOption(0);
  };
  return {
    placement: "bottom-end",
    items: primaryItems,
    onHide: () => {
      if (!showingThisWeek && !showingNextWeek) return;
      showingThisWeek = false;
      showingNextWeek = false;
      dropdown.updateOptions(primaryItems);
    }
  };
};
class HomeTaskList extends BaseList {
  constructor(attributes) {
    super(attributes);
    this.dropdowns = [];
    this._change = this._change.bind(this);
    this._listToggle = this.component.elt.querySelector(
      "[lp-show='tasks:HomeTaskList'][data-toggle]"
    );
    this._pendingUserTaskCount = null;
    this._pendingFeedback = null;
  }
  init() {
    this.target.addEventListener("change", this._change);
  }
  handleOfflineQueue({ phase, queue, record }) {
    if (phase === "queued") return this._offlineQueued(record, queue);
    if (phase === "cancelled") return this._offlineCancelled(record);
    if (phase === "replayed" && record.kind === "task") {
      return withTransition(() => this._syncList(), {
        label: "home:task-replayed"
      });
    }
  }
  _offlineQueued(record, queue) {
    if (record.kind === "task" && record.action === "create") {
      const key = record.client_key;
      if (!key) return;
      this._updateUserTaskCountOffline(1);
      if (!this._offlineTaskVisible(record, queue)) {
        return {
          ok: true,
          removed: true,
          name: queue.field(record, "name") || "Untitled task",
          scheduled: Boolean(queue.field(record, "due-date"))
        };
      }
      return queue.response(this._renderOfflineTask(record, queue, key));
    }
    if (record.kind === "task" && record.action === "complete") {
      return withTransition(
        () => {
          this._removeTaskByKey(record.target_key);
          this._syncList();
          this._updateUserTaskCountOffline(-1);
        },
        { label: "home:task-complete-offline" }
      );
    }
  }
  _offlineCancelled(record) {
    if (record.kind !== "task" || record.action !== "create") return;
    return withTransition(
      () => {
        this._removeTaskByKey(record.client_key);
        this._syncList();
        this._updateUserTaskCountOffline(-1);
      },
      { label: "home:task-cancel-offline" }
    );
  }
  async _change(e) {
    if (!(e.target instanceof Element)) return;
    const toggle = e.target.closest("[data-role='complete']");
    if (!toggle) return;
    const elt = toggle.closest("[lp-entity]");
    const key = elt?.dataset.key;
    if (!elt || !key) return;
    elt.classList.add("opacity-50", "pointer-events-none");
    toggle.disabled = true;
    const data = new FormData();
    data.append("completed", String(toggle.checked));
    const route = this.endpoints.completeTask(key);
    if (!this.view.online) {
      const queue = this.view.offlineQueue || await this.view.ensureOfflineQueue?.();
      if (!queue) return;
      if (key.startsWith("offline:")) {
        await queue.cancel({
          action: "create",
          client_key: key
        });
      } else {
        await queue.queue({
          id: `complete:${key}`,
          kind: "task",
          action: "complete",
          method: "PUT",
          route,
          target_key: key,
          data
        });
      }
      return;
    }
    const response = await request.put(route, data);
    if (!response) return;
    if (response.error) {
      elt.classList.remove("opacity-50", "pointer-events-none");
      toggle.disabled = false;
      toggle.checked = !toggle.checked;
      this._showNotification(elt, response.error);
      return;
    }
    await withTransition(() => this._commitTaskResponse(elt, response), {
      label: "home:task-complete"
    });
  }
  updated(response) {
    const html = listHtml(response);
    if (!html) return;
    this._replaceUserTaskCount(html);
    super.updated(response);
  }
  created(response) {
    super.created(response);
    if (!response || typeof response !== "object") return;
    const result = response;
    if (typeof result.count === "number") {
      this._pendingUserTaskCount = result.count;
    }
    if (result.removed) {
      const name = typeof result.name === "string" ? result.name.trim() : "";
      const qualifier = result.scheduled ? "scheduled beyond this week" : "unscheduled";
      this._pendingFeedback = name ? `\u201C${name}\u201D saved to My Page (${qualifier}).` : `Task saved to My Page (${qualifier}).`;
    } else if (this._created.length > 0) {
      this._pendingFeedback = "";
    }
  }
  _insertNewTasks() {
    this._created.forEach((item) => {
      _insertSorted(this.target, item);
      this._initPostponeMenus(item);
      this.view.addFlash(item);
    });
    this._created = [];
  }
  postreconcile() {
    this.visible = this.target.dataset.visible === "true";
    if (this._updated) {
      this.updateTarget();
      this.destroy();
      this.init();
      this._initPostponeMenus(this.target);
    } else if (this._created.length > 0) {
      this._insertNewTasks();
    }
    if (typeof this._pendingUserTaskCount === "number") {
      this._updateUserTaskCount(this._pendingUserTaskCount);
      this._pendingUserTaskCount = null;
    }
    if (this._pendingFeedback !== null) {
      this._setTaskFeedback(this._pendingFeedback);
      this._pendingFeedback = null;
    }
    if (this._listToggle) {
      this._listToggle.disabled = false;
      this._listToggle.removeAttribute("aria-busy");
    }
    this._syncList();
    this.target.setAttribute("loaded", "");
  }
  async _postpone(elt, button, value) {
    if (!this.view.online) {
      this._showNotification(elt, "Connect to postpone this task.");
      return;
    }
    const key = elt.dataset.key;
    if (!key) return;
    elt.classList.add("opacity-50", "pointer-events-none");
    button.disabled = true;
    const data = new FormData();
    data.append("newDueDate", String(value));
    const route = this.endpoints.changeDueDate(key);
    const response = await request.put(route, data);
    if (!response) return;
    if (response.error) {
      elt.classList.remove("opacity-50", "pointer-events-none");
      button.disabled = false;
      this._showNotification(elt, response.error);
      return;
    }
    await withTransition(() => this._commitTaskResponse(elt, response), {
      label: "home:task-postpone"
    });
  }
  _commitTaskResponse(elt, response) {
    if (response.removed) {
      elt.remove();
    } else if (response.html) {
      const newTask = response.html.querySelector("[lp-entity]");
      if (newTask) {
        elt.remove();
        _insertSorted(this.target, newTask);
        this._initPostponeMenus(newTask);
      }
    }
    this._syncList();
    this._updateUserTaskCount(response.count);
  }
  _initPostponeMenus(root) {
    for (const button of root.querySelectorAll(
      "[data-role='change-due-date']"
    )) {
      const dropdown = new Dropdown(button);
      dropdown.init(
        _postponeMenu(dropdown, (value) => {
          const elt = button.closest("[lp-entity]");
          if (elt) void this._postpone(elt, button, value);
        })
      );
      this.dropdowns.push(dropdown);
    }
  }
  _syncList() {
    this._renderDateHeaders();
    this._updateTaskCount();
    this._updateVisibility();
  }
  _renderDateHeaders() {
    for (const h of this.target.querySelectorAll("[data-role='date-header']")) {
      h.remove();
    }
    let lastDate = null;
    for (const item of this.target.querySelectorAll(
      "[lp-entity]"
    )) {
      const dueDate = item.dataset.dueDate;
      if (dueDate && dueDate !== lastDate) {
        const { label, due } = _dateInfo(dueDate);
        const header = document.createElement("div");
        header.className = STYLES.task.home.group;
        header.dataset.role = "date-header";
        header.dataset.date = dueDate;
        header.dataset.due = due;
        header.textContent = label;
        item.before(header);
        lastDate = dueDate;
      }
    }
  }
  _updateTaskCount() {
    const taskCount = this.component.elt.querySelector(
      "[data-role='task-count']"
    );
    const count = this.target.querySelectorAll("[lp-entity]").length;
    if (!taskCount) return;
    taskCount.textContent = String(count);
    taskCount.dataset.kind = count > 0 ? "task" : "success";
    taskCount.dataset.visible = "true";
  }
  _updateUserTaskCount(count) {
    if (count === void 0) return;
    const elt = document.querySelector(
      "[data-role='user-task-count']"
    );
    if (!elt) return;
    const safeCount = Math.max(0, count);
    elt.textContent = String(safeCount);
    elt.dataset.visible = "true";
    elt.classList.add("font-bold", "ml-auto");
    elt.classList.toggle("text-task-default", safeCount > 0);
    elt.classList.toggle("text-project-default", safeCount === 0);
  }
  _updateUserTaskCountOffline(delta) {
    const elt = document.querySelector("[data-role='user-task-count']");
    if (!elt) return;
    const count = Number.parseInt(elt.textContent || "0", 10);
    if (Number.isNaN(count)) return;
    this._updateUserTaskCount(count + delta);
  }
  _setTaskFeedback(message) {
    const banner = this.component.elt.querySelector(
      "[data-role='task-feedback']"
    );
    if (!banner) return;
    const text = banner.querySelector(
      "[data-role='task-feedback-text']"
    );
    if (!message) {
      banner.dataset.visible = "false";
      if (text) text.textContent = "";
      return;
    }
    if (text) text.textContent = message;
    banner.dataset.visible = "true";
  }
  _offlineTaskVisible(record, queue) {
    return _isWithinHomeTaskWindow(queue.field(record, "due-date"));
  }
  _renderOfflineTask(record, queue, key) {
    const name = queue.field(record, "name") || "Untitled task";
    const dueDate = queue.field(record, "due-date");
    const item = document.createElement("li");
    item.setAttribute("lp-entity", "");
    item.setAttribute("lp-link", "");
    item.dataset.key = key;
    item.dataset.fingerprint = `offline:${record.id}`;
    item.dataset.name = name;
    item.dataset.dueDate = dueDate;
    item.dataset.offline = "true";
    item.className = [STYLES.task.home.item, "opacity-80"].join(" ");
    const header = document.createElement("div");
    header.className = STYLES.task.home.header;
    header.dataset.role = "header";
    item.append(header);
    const details = document.createElement("div");
    details.className = STYLES.task.home.details;
    details.dataset.role = "details";
    header.append(details);
    const title = document.createElement("div");
    title.className = STYLES.task.home.title;
    details.append(title);
    const complete = document.createElement("div");
    complete.className = STYLES.task.home.complete;
    title.append(complete);
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.dataset.role = "complete";
    checkbox.className = STYLES.checkbox.default;
    complete.append(checkbox);
    const checkIcon = document.createElement("span");
    setIcon(checkIcon, "check", STYLES.checkbox.icon);
    complete.append(checkIcon);
    title.append(document.createTextNode(name));
    const snooze = document.createElement("button");
    snooze.type = "button";
    snooze.disabled = true;
    snooze.dataset.role = "change-due-date";
    snooze.className = STYLES.task.home.snooze;
    details.append(snooze);
    const snoozeIcon = document.createElement("span");
    setIcon(snoozeIcon, "snooze");
    snooze.append(snoozeIcon);
    const notification = document.createElement("p");
    notification.className = STYLES.task.home.notification;
    notification.dataset.role = "notification";
    notification.textContent = "Pending sync";
    item.append(notification);
    return item;
  }
  _taskByKey(root, key) {
    if (!root || !key) return null;
    return Array.from(
      root.querySelectorAll("[lp-entity][data-key]")
    ).find((item) => item.dataset.key === key);
  }
  _removeTaskByKey(key) {
    this._taskByKey(this.target, key)?.remove();
  }
  _replaceUserTaskCount(html) {
    const fresh = html.querySelector("[data-role='user-task-count']");
    const current = document.querySelector("[data-role='user-task-count']");
    if (current && fresh) current.replaceWith(fresh);
  }
  _updateVisibility() {
    const count = this.target.querySelectorAll("[lp-entity]").length;
    this.target.dataset.visible = count > 0 && this.visible ? "true" : "false";
    this.view.syncHomeSectionState?.(this.component);
  }
  _showNotification(elt, message) {
    const notification = elt.querySelector("[data-role='notification']");
    if (notification) notification.textContent = message;
  }
  destroy() {
    for (const d of this.dropdowns) {
      d.destroy();
    }
    this.dropdowns = [];
  }
}

var tasks = /*#__PURE__*/Object.freeze({
	__proto__: null,
	HomeTaskList: HomeTaskList
});

export { activity as a, lists as l, tasks as t };
