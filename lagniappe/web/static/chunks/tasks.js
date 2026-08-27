/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=b687b680';
import { BaseList } from './baseList.js?v=b687b680';
import { Dropdown } from './dropdown.js?v=b687b680';
import { w as withTransition, r as request } from './foundation.js?v=b687b680';
import './connectivity.js?v=b687b680';
import { s as setIcon } from './icons.js?v=b687b680';
import './combobox.js?v=b687b680';
import './primitives.js?v=b687b680';

/**
 * @testable false
 * @covered-by src/script/widgets/home/tasks.mjs::HomeTaskList
 * @reason internal date helper for home task due-date grouping
 */
function _toDateStr(offset = 0) {
	const d = new Date();
	d.setDate(d.getDate() + offset);
	return d.toLocaleDateString("sv-SE");
}
/**
 * @testable false
 * @covered-by src/script/widgets/home/tasks.mjs::HomeTaskList
 * @reason internal date helper for home task due-date grouping
 */
function _dateInfo(dateStr) {
	const today = _toDateStr();

	if (dateStr === today) return { label: "Today", due: "today" };
	if (dateStr === _toDateStr(1)) return { label: "Tomorrow", due: "future" };
	if (dateStr === _toDateStr(-1)) return { label: "Yesterday", due: "past" };

	const [year, month, day] = dateStr.split("-");
	const label = new Date(year, month - 1, day).toLocaleDateString(undefined, {
		day: "numeric",
		month: "short",
		year: "numeric",
	});
	return { label, due: dateStr < today ? "past" : "future" };
}

/**
 * @testable false
 * @covered-by src/script/widgets/home/tasks.mjs::HomeTaskList
 * @reason homepage offline mutation helper for deciding optimistic task visibility
 */
function _isWithinHomeTaskWindow(dueDate) {
	if (!dueDate) return false;

	const today = new Date();
	today.setHours(0, 0, 0, 0);
	const nextWeek = new Date(today);
	nextWeek.setDate(nextWeek.getDate() + 7);

	const due = new Date(`${dueDate}T00:00:00`);
	return due >= today && due <= nextWeek;
}

/**
 * @testable false
 * @covered-by src/script/widgets/home/tasks.mjs::HomeTaskList._postpone
 * @reason insertion helper exercised through home task creation and postpone flows
 */
function _insertSorted(target, task) {
	const dueDate = task.dataset.dueDate;

	for (const item of target.querySelectorAll("[lp-entity]")) {
		if (item.dataset.dueDate > dueDate) {
			item.before(task);
			return;
		}
	}
	target.append(task);
}

/**
 * @testable false
 * @covered-by src/script/widgets/home/tasks.mjs::HomeTaskList._postpone
 * @reason menu configuration helper for the tested postpone action
 */
const _postponeMenu = (button, postponeFn) => {
	let showingNextWeek = false;
	let showingThisWeek = false;
	let returnFocusIndex = 0;
	const weekdayNames = [
		"sunday",
		"monday",
		"tuesday",
		"wednesday",
		"thursday",
		"friday",
		"saturday",
	];
	const weekdayFormatter = new Intl.DateTimeFormat(undefined, {
		weekday: "long",
	});
	const dateFormatter = new Intl.DateTimeFormat(undefined, {
		day: "numeric",
		month: "short",
	});
	const hasDaysLeftThisWeek = new Date().getDay() !== 0;

	const primaryItems = [
		{
			name: "Tomorrow",
			icon: "tomorrow",
			kind: "task",
			onClick: () => postponeFn(button, "tomorrow"),
		},
		...(hasDaysLeftThisWeek
			? [
					{
						name: "This Week…",
						icon: "weekend",
						kind: "task",
						closeOnClick: false,
						onClick: () => {
							returnFocusIndex = 1;
							showThisWeek();
						},
					},
				]
			: []),
		{
			name: "Next Week…",
			icon: "nextWeek",
			kind: "task",
			closeOnClick: false,
			onClick: () => {
				returnFocusIndex = primaryItems.findIndex(
					(item) => item.name === "Next Week…",
				);
				showNextWeek();
			},
		},
		{
			name: "No Due Date",
			icon: "removeDueDate",
			kind: "task",
			onClick: () => postponeFn(button, null),
		},
	];

	/**
	 * @testable false
	 * @covered-by src/script/widgets/home/tasks.mjs::_postponeMenu
	 * @reason internal transition back to the primary postpone choices
	 */
	const showPrimary = () => {
		showingThisWeek = false;
		showingNextWeek = false;
		button._lp_combobox.updateOptions(primaryItems);
		button._lp_combobox.focusOption(returnFocusIndex);
	};

	/**
	 * @testable false
	 * @covered-by src/script/widgets/home/tasks.mjs::_postponeMenu
	 * @reason internal transition to the tested remaining dates this week
	 */
	const showThisWeek = () => {
		const today = new Date();
		today.setHours(12, 0, 0, 0);
		const daysUntilSunday = 7 - today.getDay();
		const items = [
			{
				name: "Back",
				icon: "back",
				kind: "task",
				closeOnClick: false,
				onClick: showPrimary,
			},
			...Array.from({ length: daysUntilSunday }, (_, index) => {
				const date = new Date(today);
				date.setDate(date.getDate() + index + 1);
				const weekday = weekdayNames[date.getDay()];
				return {
					name: `${weekdayFormatter.format(date)} · ${dateFormatter.format(date)}`,
					icon: "date",
					kind: "task",
					onClick: () => postponeFn(button, `this-week-${weekday}`),
				};
			}),
		];

		showingThisWeek = true;
		button._lp_combobox.updateOptions(items);
		button._lp_combobox.focusOption(0);
	};

	/**
	 * @testable false
	 * @covered-by src/script/widgets/home/tasks.mjs::_postponeMenu
	 * @reason internal transition to the tested next-week weekday choices
	 */
	const showNextWeek = () => {
		const monday = new Date();
		monday.setHours(12, 0, 0, 0);
		const daysUntilMonday = (8 - monday.getDay()) % 7 || 7;
		monday.setDate(monday.getDate() + daysUntilMonday);

		const weekdays = weekdayNames.slice(1, 6);
		const items = [
			{
				name: "Back",
				icon: "back",
				kind: "task",
				closeOnClick: false,
				onClick: showPrimary,
			},
			...weekdays.map((weekday, offset) => {
				const date = new Date(monday);
				date.setDate(date.getDate() + offset);
				return {
					name: `${weekdayFormatter.format(date)} · ${dateFormatter.format(date)}`,
					icon: "date",
					kind: "task",
					onClick: () => postponeFn(button, `next-week-${weekday}`),
				};
			}),
		];

		showingNextWeek = true;
		button._lp_combobox.updateOptions(items);
		button._lp_combobox.focusOption(0);
	};

	return {
		placement: "bottom-end",
		items: primaryItems,
		onHide: () => {
			if (!showingThisWeek && !showingNextWeek) return;
			showingThisWeek = false;
			showingNextWeek = false;
			button._lp_combobox.updateOptions(primaryItems);
		},
	};
};

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002a_home.py::test_tasks_prefetch
 * @matrix home : prefetch task-count task-list
 */
class HomeTaskList extends BaseList {
	constructor(attributes) {
		super(attributes);
		this.dropdowns = [];
		this._change = this._change.bind(this);
		this._listToggle = this.component.elt.querySelector(
			"[lp-show='tasks:HomeTaskList'][data-toggle]",
		);
	}

	init() {
		this.target.addEventListener("change", this._change);
	}

	handleOfflineQueue({ phase, queue, record }) {
		if (phase === "queued") return this._offlineQueued(record, queue);
		if (phase === "cancelled") return this._offlineCancelled(record);
		if (phase === "replayed" && record.kind === "task") {
			return withTransition(() => this._syncList(), {
				label: "home:task-replayed",
			});
		}
	}

	_offlineQueued(record, queue) {
		if (record.kind === "task" && record.action === "create") {
			this._updateUserTaskCountOffline(1);
			if (!this._offlineTaskVisible(record, queue)) {
				return { ok: true, removed: true };
			}
			return queue.response(this._renderOfflineTask(record, queue));
		}

		if (record.kind === "task" && record.action === "complete") {
			return withTransition(
				() => {
					this._removeTaskByKey(record.target_key);
					this._syncList();
					this._updateUserTaskCountOffline(-1);
				},
				{ label: "home:task-complete-offline" },
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
			{ label: "home:task-cancel-offline" },
		);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002d_home_tasks.py::test_complete_task_from_home_page
	 * @tests tests_e2e/002_home/test_002d_home_tasks.py::test_complete_recurring_task_from_home_page_reappears
	 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_task_complete_replays_after_reload
	 * @matrix tasks : complete offline-queue recurring
	 */
	async _change(e) {
		const toggle = e.target.closest("[data-role='complete']");
		if (!toggle) return;

		const elt = toggle.closest("[lp-entity]");
		elt.classList.add("opacity-50", "pointer-events-none");
		toggle.disabled = true;

		const data = new FormData();
		data.append("completed", toggle.checked);

		const route = this.endpoints.completeTask(elt.dataset.key);

		if (!this.view.online) {
			const queue =
				this.view.offlineQueue || (await this.view.ensureOfflineQueue?.());
			if (!queue) return;
			if (elt.dataset.key.startsWith("offline:")) {
				await queue.cancel({
					action: "create",
					client_key: elt.dataset.key,
				});
			} else {
				await queue.queue({
					id: `complete:${elt.dataset.key}`,
					kind: "task",
					action: "complete",
					method: "PUT",
					route,
					target_key: elt.dataset.key,
					data,
				});
			}
			return;
		}

		const response = await request.put(route, data);

		if (response.error) {
			elt.classList.remove("opacity-50", "pointer-events-none");
			toggle.disabled = false;
			toggle.checked = !toggle.checked;
			this._showNotification(elt, response.error);
			return;
		}

		await withTransition(() => this._commitTaskResponse(elt, response), {
			label: "home:task-complete",
		});
	}

	updated(response) {
		if (!response.html) return;
		this._replaceUserTaskCount(response.html);
		super.updated(response);
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

		this._listToggle.disabled = false;
		this._listToggle.removeAttribute("aria-busy");
		this._syncList();
		this.target.setAttribute("loaded", "");
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002d_home_tasks.py::test_postpone_task_due_date_to_tomorrow
	 * @tests tests_e2e/002_home/test_002d_home_tasks.py::test_postpone_task_due_date_to_this_week
	 * @tests tests_e2e/002_home/test_002d_home_tasks.py::test_postpone_task_due_date_to_next_week
	 * @tests tests_e2e/002_home/test_002d_home_tasks.py::test_postpone_task_due_date_to_no_due_date
	 * @matrix tasks : due-date postpone
	 */
	async _postpone(elt, button, value) {
		if (!this.view.online) {
			this._showNotification(elt, "Connect to postpone this task.");
			return;
		}

		elt.classList.add("opacity-50", "pointer-events-none");
		button.disabled = true;

		const data = new FormData();
		data.append("newDueDate", value);

		const route = this.endpoints.changeDueDate(elt.dataset.key);
		const response = await request.put(route, data);

		if (response.error) {
			elt.classList.remove("opacity-50", "pointer-events-none");
			button.disabled = false;
			this._showNotification(elt, response.error);
			return;
		}

		await withTransition(() => this._commitTaskResponse(elt, response), {
			label: "home:task-postpone",
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
			"[data-role='change-due-date']",
		)) {
			const menu = _postponeMenu(button, (btn, value) => {
				const elt = btn.closest("[lp-entity]");
				this._postpone(elt, btn, value);
			});
			const dropdown = new Dropdown(button);
			dropdown.init(menu);
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
		for (const item of this.target.querySelectorAll("[lp-entity]")) {
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
			"[data-role='task-count']",
		);
		const count = this.target.querySelectorAll("[lp-entity]").length;
		taskCount.textContent = count;
		taskCount.dataset.kind = count > 0 ? "task" : "success";
		taskCount.dataset.visible = "true";
	}

	_updateUserTaskCount(count) {
		if (count === undefined) return;
		const elt = document.querySelector("[data-role='user-task-count']");
		if (elt) elt.textContent = count;
	}

	_updateUserTaskCountOffline(delta) {
		const elt = document.querySelector("[data-role='user-task-count']");
		if (!elt) return;

		const count = Number.parseInt(elt.textContent || "0", 10);
		if (Number.isNaN(count)) return;

		elt.textContent = Math.max(0, count + delta);
	}

	_offlineTaskVisible(record, queue) {
		return _isWithinHomeTaskWindow(queue.field(record, "due-date"));
	}

	_renderOfflineTask(record, queue) {
		const name = queue.field(record, "name") || "Untitled task";
		const dueDate = queue.field(record, "due-date");

		const item = document.createElement("li");
		item.setAttribute("lp-entity", "");
		item.setAttribute("lp-link", "");
		item.dataset.key = record.client_key;
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
		return Array.from(root.querySelectorAll("[lp-entity][data-key]")).find(
			(item) => item.dataset.key === key,
		);
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
	}

	_showNotification(elt, message) {
		elt.querySelector("[data-role='notification']").textContent = message;
	}

	destroy() {
		for (const d of this.dropdowns) {
			d.destroy();
		}
		this.dropdowns = [];
	}
}

export { HomeTaskList };
