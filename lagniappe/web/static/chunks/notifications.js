/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=bd5baecd';
import { r as request, E as ENDPOINTS, w as withTransition, f as renderNotificationBadge } from './foundation.js?v=bd5baecd';
import './connectivity.js?v=bd5baecd';
import { c as createIcon } from './icons.js?v=bd5baecd';
import { Dropdown } from './dropdown.js?v=bd5baecd';
import './combobox.js?v=bd5baecd';
import './primitives.js?v=bd5baecd';

const CLEAR_ALL_KEY = "__clear_all_notifications__";

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_menu_renders_target_and_preserves_pending_state
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_menu_deletes_and_clears
 * @tests tests_js/test_042_messaging_frontend.py::test_notification_menu_keeps_authoritative_aggregate_count
 * @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_direct_message_lifecycle_is_private_and_restores_after_clear
 * @tests tests_e2e/012_messaging/test_012a_direct_messages.py::test_inbound_message_allows_reply_without_compose_permission
 * @pairs notifications:menu-open notifications:dropdown-refresh notifications:delete
 * @pairs notifications:clear-all notifications:long-text-wrap notifications:accessible-state
 * @pairs notifications:exact-count notifications:bounded-page
 */
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
			onShow: () => {
				this.menuOpen = true;
			},
			onHide: () => {
				this.menuOpen = false;
			},
			placement: "bottom-end",
			styles: {
				panel: `${STYLES.dropdown.panel} mt-2 w-80 max-w-[calc(100vw-1rem)] sm:w-96`,
			},
		});
		this._updateCount();
		window.addEventListener("notification-state", this._notificationState);
	}

	async _notificationState(event) {
		const next = event?.detail;
		if (!next || next.miss) return;
		const changed = Boolean(
			this.state &&
				(this.state.generation !== next.generation ||
					this.state.revision !== next.revision),
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

	/**
	 * @testable false
	 * @covered-by src/script/elements/notifications.mjs::Notifications
	 * @reason pending/completed replacement is covered through dropdown refresh
	 * @features notifications
	 * @dimensions upsert pending-complete
	 */
	upsertNotification(html) {
		if (!this.dropdown || !html) return;
		if (!this.loaded) {
			this.stale = true;
			return;
		}

		const option = this._notificationOption(html);
		const index = option.key
			? this.notifications.findIndex((item) => item.key === option.key)
			: -1;

		if (index >= 0) {
			this.notifications.splice(index, 1, option);
		} else {
			this.notifications.splice(0, 0, option);
		}
		this._updateDropdown();
	}

	async refresh() {
		if (!this.dropdown || !this.view.online) return false;

		const response = await request.get(ENDPOINTS.notifications);
		if (!response?.ok || !response.html) return false;

		this.notifications = this._optionsFromHtml(response.html);
		this.loaded = true;
		this.stale = false;
		this._updateDropdown();
		return true;
	}

	_optionsFromHtml(html) {
		return Array.from(html.querySelectorAll("[role='option']")).map(
			(option) => {
				return this._notificationOption(option.outerHTML, option.dataset.key);
			},
		);
	}

	_notificationOption(html, key = null) {
		const element = this._htmlOption(html);
		return {
			key: key || element?.dataset.key || null,
			action: element?.dataset.action || null,
			cursor: element?.dataset.cursor || null,
			html: element?.outerHTML || html,
			onClick: this._selectNotification,
			closeOnClick: this._closeOnNotificationClick,
		};
	}

	_dropdownItems() {
		if (!this.notifications.length) return [];
		const hasOrdinary = this.notifications.some(
			(item) => item.key && !item.key.startsWith("__"),
		);
		return hasOrdinary
			? [this._clearAllOption(), ...this.notifications]
			: this.notifications;
	}

	_clearAllOption() {
		return {
			key: CLEAR_ALL_KEY,
			html: `
				<button role="option"
					type="button"
					data-action="clear-notifications"
					class="${STYLES.dropdown.option.action} border-b border-base-light !rounded-none mb-1 pb-2 text-delete-default">
					${createIcon("trash.inactive", STYLES.dropdown.icon).outerHTML}
					<span>Clear all notifications</span>
				</button>
			`,
			onClick: this._clearNotifications,
			closeOnClick: false,
		};
	}

	/**
	 * @testable false
	 * @covered-by src/script/elements/notifications.mjs::Notifications
	 * @reason parsing is internal to notification option replacement
	 */
	_htmlOption(html) {
		const template = document.createElement("template");
		template.innerHTML = String(html || "").trim();
		return template.content.querySelector("[role='option']");
	}

	async _selectNotification(option, event) {
		const action = option?.dataset?.action;
		if (action === "message-user") {
			event?.preventDefault();
			const { ensureMessageComposer } = await import('./messageComposer.js?v=bd5baecd');
			ensureMessageComposer(this.view).open();
			return;
		}
		if (action === "load-notifications") {
			event?.preventDefault();
			await this._loadOlder(option.dataset.cursor);
			return;
		}
		const deleteButton = event?.target?.closest(
			"[data-action='delete-notification']",
		);
		if (deleteButton) {
			event.preventDefault();
			event.stopPropagation();
			await this._deleteNotification(deleteButton.dataset.key);
			return;
		}

		const link =
			event?.target?.closest("a[href]") || option.querySelector("a[href]");
		if (link) window.location.href = link.href;
	}

	_closeOnNotificationClick(_option, event) {
		return !event?.target?.closest("[data-action='delete-notification']");
	}

	async _clearNotifications() {
		if (
			!this.notifications.some((item) => item.key && !item.key.startsWith("__"))
		)
			return;

		this.localMutation = true;
		const response = await request
			.delete(ENDPOINTS.notifications)
			.finally(() => {
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
			(item) => item.key && !item.key.startsWith("__"),
		);
		const next = loaded.find((item) => item.action === "load-notifications");
		const existing = this.notifications.filter(
			(item) => item.action !== "load-notifications",
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
		const response = await request
			.delete(ENDPOINTS.activity(key))
			.finally(() => {
				this.localMutation = false;
			});
		if (!response?.ok) return;

		this.notifications = this.notifications.filter((item) => item.key !== key);
		this.stale = false;
		this._updateDropdown();
	}

	_updateDropdown() {
		if (!this.dropdown) return;

		const items = this._dropdownItems();
		this._updateCount();
		if (!this.menuOpen) {
			this.dropdown.items = items;
			return;
		}
		void withTransition(() => this.dropdown.updateOptions(items), {
			label: "notifications:update-open-menu",
		});
	}

	_updateCount() {
		const projected = Number(this.state?.count);
		const count = Number.isInteger(projected)
			? projected
			: this.loaded
				? this.notifications.filter(
						(item) => item.key && !item.key.startsWith("__"),
					).length
				: 0;
		renderNotificationBadge(count);
	}

	destroy() {
		window.removeEventListener("notification-state", this._notificationState);
		this.dropdown?.destroy?.();
		this.dropdown = null;
	}
}

export { Notifications };
