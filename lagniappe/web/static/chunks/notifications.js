/*! Third-party licenses: /third-party-licenses.txt */
import { S as STYLES } from './styles.js?v=b549327e';
import { r as request } from './request.js?v=b549327e';
import './connectivity.js?v=b549327e';
import { c as createIcon } from './icons.js?v=b549327e';
import { E as ENDPOINTS } from './endpoints.js?v=b549327e';
import './utilities.js?v=b549327e';
import { Dropdown } from './dropdown.js?v=b549327e';
import './errors.js?v=b549327e';
import './combobox.js?v=b549327e';
import './primitives.js?v=b549327e';

const CLEAR_ALL_KEY = "__clear_all_notifications__";

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_menu_renders_target_and_preserves_pending_state
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_menu_deletes_and_clears
 * @features notifications
 * @dimensions menu-open dropdown-refresh delete clear-all long-text-wrap
 */
class Notifications {
	constructor(view) {
		this.view = view;
		this.dropdown = null;
		this.button = document.querySelector("[data-role='notifications']");
		this.count = document.querySelector("[data-role='notification-count']");
		this.notifications = [];

		this._selectNotification = this._selectNotification.bind(this);
		this._clearNotifications = this._clearNotifications.bind(this);
		this._closeOnNotificationClick = this._closeOnNotificationClick.bind(this);
	}

	get visible() {
		return this.button?.dataset.visible === "true";
	}

	set visible(value) {
		if (!this.button) return;
		this.button.dataset.visible = value ? "true" : "false";
	}

	init(notifications = []) {
		if (!this.button) return;

		this.notifications = this.notifications.concat(notifications);
		this.dropdown = new Dropdown(this.button).init({
			items: this._dropdownItems(),
			placement: "bottom-end",
			styles: {
				panel: `${STYLES.dropdown.panel} mt-2 w-80 max-w-[calc(100vw-1rem)] sm:w-96`,
			},
		});
		this._updateCount();
		this._unsubscribe = this.view.PollingCoordinator?.subscribe(
			{
				id: "personal:notifications",
				type: "channel",
				channel: "notifications",
				revision: null,
			},
			{
				onResult: async (result) => {
					if (result.status !== "changed") return;
					if (!(await this.refresh())) return false;
					return true;
				},
			},
		);
	}

	/**
	 * @testable false
	 * @manual true
	 * @reason pending/completed replacement is covered through dropdown refresh
	 * @features notifications
	 * @dimensions upsert pending-complete
	 */
	upsertNotification(html) {
		if (!this.dropdown || !html) return;

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
			html: element?.outerHTML || html,
			onClick: this._selectNotification,
			closeOnClick: this._closeOnNotificationClick,
		};
	}

	_dropdownItems() {
		if (!this.notifications.length) return [];
		return [this._clearAllOption(), ...this.notifications];
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
		if (!this.notifications.length) return;

		const response = await request.delete(ENDPOINTS.notifications);
		if (!response?.ok) return;

		this.notifications = [];
		this._updateDropdown();
	}

	async _deleteNotification(key) {
		if (!key) return;

		const response = await request.delete(ENDPOINTS.activity(key));
		if (!response?.ok) return;

		this.notifications = this.notifications.filter((item) => item.key !== key);
		this._updateDropdown();
	}

	_updateDropdown() {
		if (!this.dropdown) return;

		this.dropdown.updateOptions(this._dropdownItems());
		this._updateCount();
	}

	_updateCount() {
		const count = this.notifications.length;
		if (this.count) this.count.textContent = count;
		if (this.button) {
			this.button.setAttribute("aria-label", `Notifications: ${count}`);
		}
		this.visible = count > 0;
	}

	destroy() {
		this._unsubscribe?.();
		this._unsubscribe = null;
		this.dropdown?.destroy?.();
		this.dropdown = null;
	}
}

export { Notifications };
