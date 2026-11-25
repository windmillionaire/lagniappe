/*! Third-party licenses: /third-party-licenses.txt */
import { S as STYLES, c as createIcon } from './ui-resources.js?v=b438e48a';
import { r as request, E as ENDPOINTS, w as withTransition, k as renderNotificationBadge } from './foundation.js?v=b438e48a';
import './connectivity.js?v=b438e48a';
import { D as Dropdown } from './combobox.js?v=b438e48a';
import './upstreamUnavailable.js?v=b438e48a';
import './ui-controls.js?v=b438e48a';

const CLEAR_ALL_KEY = "__clear_all_notifications__";
function clickTarget(event) {
  const target = event?.target;
  return target && "closest" in target && typeof target.closest === "function" ? target : null;
}
class Notifications {
  constructor(view) {
    this.view = view;
    this.dropdown = null;
    this.button = document.querySelector("[data-role='notifications']");
    this.count = document.querySelector("[data-role='notification-count']");
    this.notifications = [];
    this.loaded = false;
    this.stale = false;
    this.menuOpen = false;
    this.state = null;
    this.localMutation = false;
    this._selectNotification = this._selectNotification.bind(this);
    this._clearNotifications = this._clearNotifications.bind(this);
    this._closeOnNotificationClick = this._closeOnNotificationClick.bind(this);
    this._notificationState = this._notificationState.bind(this);
  }
  get visible() {
    return this.button?.dataset.visible === "true";
  }
  set visible(value) {
    if (!this.button) return;
    const visible = Boolean(value);
    this.button.dataset.visible = visible ? "true" : "false";
    this.button.setAttribute("aria-hidden", visible ? "false" : "true");
    this.button.tabIndex = visible ? 0 : -1;
  }
  init(notifications = []) {
    if (!this.button) return;
    this.notifications = this.notifications.concat(notifications);
    this.loaded = notifications.length > 0;
    this.state = window.__NOTIFICATION_STATE__ || null;
    this.dropdown = new Dropdown(this.button).init({
      items: [],
      loadOptions: async () => {
        await this._ensureLoaded();
        return this._dropdownItems();
      },
      emptyHtml: () => this._emptyNoticeHtml(),
      onShow: () => {
        this.menuOpen = true;
      },
      onHide: () => {
        this.menuOpen = false;
      },
      placement: "bottom-end",
      styles: {
        panel: `${STYLES.dropdown.panel} mt-2 w-80 max-w-[calc(100vw-1rem)] sm:w-96`
      }
    });
    this._updateCount();
    window.addEventListener("notification-state", this._notificationState);
  }
  async _notificationState(event) {
    const next = event?.detail;
    if (!next || next.miss) return;
    const changed = Boolean(
      this.state && (this.state.generation !== next.generation || this.state.revision !== next.revision)
    );
    this.state = { ...next };
    if (changed && this.loaded && !this.localMutation) this.stale = true;
    this._updateCount();
    if (this.stale && this.menuOpen) await this.refresh();
  }
  async _ensureLoaded() {
    if (this.loaded && !this.stale) return true;
    return await this.refresh();
  }
  upsertNotification(html) {
    if (!this.dropdown || !html) return;
    if (!this.loaded) {
      this.stale = true;
      return;
    }
    const option = this._notificationOption(html);
    const index = option.key ? this.notifications.findIndex((item) => item.key === option.key) : -1;
    if (index >= 0) {
      this.notifications.splice(index, 1, option);
    } else {
      this.notifications.splice(0, 0, option);
    }
    this._updateDropdown();
  }
  async refresh() {
    if (!this.dropdown) return false;
    if (!this.view.online) await window.__CONNECTIVITY_READY__;
    if (!this.dropdown || !this.view.online) return false;
    const response = await request.get(ENDPOINTS.notifications);
    if (!response?.ok || response.html == null) return false;
    this.notifications = typeof response.html === "string" ? [] : this._optionsFromHtml(response.html);
    this.loaded = true;
    this.stale = false;
    this._updateDropdown();
    return true;
  }
  _hasNotificationContent() {
    return this.notifications.some(
      (item) => item.key && !item.key.startsWith("__") || item.action === "open-messages"
    );
  }
  _emptyNoticeHtml() {
    if (this._hasNotificationContent()) return "";
    const hasAction = this.notifications.some(
      (item) => item.action === "message-user"
    );
    const className = hasAction ? STYLES.dropdown.emptyWithAction || "" : STYLES.dropdown.empty || "";
    return `<div role="status" data-role="empty" class="${className}">No unread notifications</div>`;
  }
  _optionsFromHtml(html) {
    return Array.from(
      html.querySelectorAll("[role='option']")
    ).map((option) => {
      return this._notificationOption(option.outerHTML, option.dataset.key);
    });
  }
  _notificationOption(html, key = null) {
    const element = this._htmlOption(html);
    return {
      key: key || element?.dataset.key || null,
      action: element?.dataset.action || null,
      cursor: element?.dataset.cursor || null,
      html: element?.outerHTML || html,
      onClick: this._selectNotification,
      closeOnClick: this._closeOnNotificationClick
    };
  }
  _dropdownItems() {
    if (!this.notifications.length) return [];
    const messageUser = this.notifications.find(
      (item) => item.action === "message-user"
    );
    const messageAggregate = this.notifications.find(
      (item) => item.action === "open-messages"
    );
    const leading = [messageUser, messageAggregate].filter(
      (item) => item !== void 0
    );
    const remaining = this.notifications.filter(
      (item) => !leading.includes(item)
    );
    const hasOrdinary = this.notifications.some(
      (item) => item.key && !item.key.startsWith("__")
    );
    if (!hasOrdinary) return [...leading, ...remaining];
    return [...leading, this._clearAllOption(), ...remaining];
  }
  _clearAllOption() {
    return {
      key: CLEAR_ALL_KEY,
      html: `
				<button role="option"
					type="button"
					data-action="clear-notifications"
					class="${STYLES.dropdown.option.action} border-y border-base-light !rounded-none bg-base-bg text-delete-default">
					${createIcon("trash.inactive", STYLES.dropdown.icon).outerHTML}
					<span>Clear all notifications</span>
				</button>
			`,
      onClick: this._clearNotifications,
      closeOnClick: false
    };
  }
  _htmlOption(html) {
    const template = document.createElement("template");
    template.innerHTML = String(html || "").trim();
    return template.content.querySelector("[role='option']");
  }
  async _selectNotification(option, event) {
    const target = clickTarget(event);
    const action = option?.dataset?.action;
    if (action === "message-user") {
      event?.preventDefault();
      const { ensureMessageComposer } = await import('./messageComposer.js?v=b438e48a');
      ensureMessageComposer(this.view).open();
      return;
    }
    if (action === "load-notifications") {
      event?.preventDefault();
      await this._loadOlder(option.dataset.cursor);
      return;
    }
    const deleteButton = target?.closest(
      "[data-action='delete-notification']"
    );
    if (deleteButton) {
      event?.preventDefault();
      event?.stopPropagation();
      await this._deleteNotification(deleteButton.dataset.key);
      return;
    }
    const link = target?.closest("a[href]") || option.querySelector("a[href]");
    if (link) window.location.href = link.href;
  }
  _closeOnNotificationClick(_option, event) {
    return !clickTarget(event)?.closest("[data-action='delete-notification']");
  }
  async _clearNotifications() {
    if (!this.notifications.some((item) => item.key && !item.key.startsWith("__")))
      return;
    this.localMutation = true;
    const response = await request.delete(ENDPOINTS.notifications).finally(() => {
      this.localMutation = false;
    });
    if (!response?.ok) return;
    await this.refresh();
  }
  async _loadOlder(cursor) {
    if (!cursor || !this.view.online) return;
    const response = await request.get(ENDPOINTS.notifications, { cursor });
    if (!response?.ok || !response.html) return;
    const loaded = this._optionsFromHtml(response.html);
    const older = loaded.filter(
      (item) => item.key && !item.key.startsWith("__")
    );
    const next = loaded.find((item) => item.action === "load-notifications");
    const existing = this.notifications.filter(
      (item) => item.action !== "load-notifications"
    );
    const keys = new Set(existing.map((item) => item.key));
    for (const item of older) {
      if (!keys.has(item.key)) existing.push(item);
    }
    if (next) existing.push(next);
    this.notifications = existing;
    this._updateDropdown();
  }
  async _deleteNotification(key) {
    if (!key) return;
    this.localMutation = true;
    const response = await request.delete(ENDPOINTS.activity(key)).finally(() => {
      this.localMutation = false;
    });
    if (!response?.ok) return;
    this.notifications = this.notifications.filter((item) => item.key !== key);
    this.stale = false;
    this._updateDropdown();
  }
  _updateDropdown() {
    const { dropdown } = this;
    if (!dropdown) return;
    const items = this._dropdownItems();
    this._updateCount();
    if (!this.menuOpen) {
      dropdown.items = items;
      return;
    }
    void withTransition(() => dropdown.updateOptions(items), {
      label: "notifications:update-open-menu"
    });
  }
  _updateCount() {
    const projected = Number(this.state?.count);
    const count = Number.isInteger(projected) ? projected : this.loaded ? this.notifications.filter(
      (item) => item.key && !item.key.startsWith("__")
    ).length : 0;
    renderNotificationBadge(count);
  }
  destroy() {
    window.removeEventListener("notification-state", this._notificationState);
    this.dropdown?.destroy?.();
    this.dropdown = null;
  }
}

export { Notifications };
