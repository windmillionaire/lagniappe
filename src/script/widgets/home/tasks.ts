import {
	BaseList,
	type ListAttributes,
	listHtml,
} from "../../elements/base/baseList.ts";
import { Dropdown, type DropdownMenu } from "../../elements/combobox/index.ts";
import { STYLES } from "../../generated/styles.mjs";
import type { ENDPOINTS } from "../../shared/endpoints.ts";
import { setIcon } from "../../shared/icons.ts";
import { request } from "../../shared/index.ts";
import type {
	OfflineMutationRecord,
	OfflineQueue,
	QueueContext,
} from "../../shared/offlineQueue.ts";
import { withTransition } from "../../shared/transitions.ts";
import type { RequestResult } from "../../types/api.d.ts";
import type Core from "../../views/base/core.ts";

type TaskListAttributes = ListAttributes & {
	component: ListAttributes["component"] & { elt: HTMLElement };
	view: Pick<Core, "addFlash" | "offlineQueue" | "ensureOfflineQueue"> & {
		online: boolean;
		syncHomeSectionState?(component: TaskListAttributes["component"]): void;
	};
	endpoints: ReturnType<typeof ENDPOINTS.HomeTaskList>;
};

interface HomeTaskResult {
	count?: number;
	removed?: boolean;
	name?: string;
	scheduled?: boolean;
}

const WEEKDAY_NAMES = [
	"sunday",
	"monday",
	"tuesday",
	"wednesday",
	"thursday",
	"friday",
	"saturday",
] as const;
type Weekday = (typeof WEEKDAY_NAMES)[number];
type PostponeValue =
	| "tomorrow"
	| `this-week-${Weekday}`
	| `next-week-${Weekday}`
	| null;

function _toDateStr(offset = 0) {
	const d = new Date();
	d.setDate(d.getDate() + offset);
	return d.toLocaleDateString("sv-SE");
}
function _dateInfo(dateStr: string) {
	const today = _toDateStr();

	if (dateStr === today) return { label: "Today", due: "today" };
	if (dateStr === _toDateStr(1)) return { label: "Tomorrow", due: "future" };
	if (dateStr === _toDateStr(-1)) return { label: "Yesterday", due: "past" };

	const [year, month, day] = dateStr.split("-").map(Number);
	const currentYear = new Date().getFullYear();
	const label = new Date(year, month - 1, day).toLocaleDateString("en-US", {
		month: "short",
		day: "numeric",
		...(year === currentYear ? {} : { year: "numeric" }),
	});
	return { label, due: dateStr < today ? "past" : "future" };
}

function _isWithinHomeTaskWindow(dueDate: string) {
	if (!dueDate) return false;

	const today = new Date();
	today.setHours(0, 0, 0, 0);
	const nextWeek = new Date(today);
	nextWeek.setDate(nextWeek.getDate() + 7);

	const due = new Date(`${dueDate}T00:00:00`);
	return due >= today && due <= nextWeek;
}

function _insertSorted(target: HTMLElement, task: HTMLElement) {
	const dueDate = task.dataset.dueDate;

	for (const item of target.querySelectorAll<HTMLElement>("[lp-entity]")) {
		const itemDueDate = item.dataset.dueDate;
		if (
			itemDueDate !== undefined &&
			dueDate !== undefined &&
			itemDueDate > dueDate
		) {
			item.before(task);
			return;
		}
	}
	target.append(task);
}

const _postponeMenu = (
	dropdown: Dropdown,
	postpone: (value: PostponeValue) => void,
): DropdownMenu => {
	let showingNextWeek = false;
	let showingThisWeek = false;
	let returnFocusIndex = 0;
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
			onClick: () => postpone("tomorrow"),
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
			onClick: () => postpone(null),
		},
	];

	const showPrimary = () => {
		showingThisWeek = false;
		showingNextWeek = false;
		dropdown.updateOptions(primaryItems);
		dropdown.focusOption(returnFocusIndex);
	};

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
				const weekday = WEEKDAY_NAMES[date.getDay()];
				return {
					name: `${weekdayFormatter.format(date)} · ${dateFormatter.format(date)}`,
					icon: "date",
					kind: "task",
					onClick: () => postpone(`this-week-${weekday}`),
				};
			}),
		];

		showingThisWeek = true;
		dropdown.updateOptions(items);
		dropdown.focusOption(0);
	};

	const showNextWeek = () => {
		const monday = new Date();
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
				onClick: showPrimary,
			},
			...weekdays.map((weekday, offset) => {
				const date = new Date(monday);
				date.setDate(date.getDate() + offset);
				return {
					name: `${weekdayFormatter.format(date)} · ${dateFormatter.format(date)}`,
					icon: "date",
					kind: "task",
					onClick: () => postpone(`next-week-${weekday}`),
				};
			}),
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
		},
	};
};

export class HomeTaskList extends BaseList {
	declare component: TaskListAttributes["component"];
	declare view: TaskListAttributes["view"];
	declare endpoints: TaskListAttributes["endpoints"];
	declare dropdowns: Dropdown[];
	declare _listToggle: HTMLButtonElement | null;
	declare _pendingUserTaskCount: number | null;
	declare _pendingFeedback: string | null;

	constructor(attributes: TaskListAttributes) {
		super(attributes);
		this.dropdowns = [];
		this._change = this._change.bind(this);
		this._listToggle = this.component.elt.querySelector<HTMLButtonElement>(
			"[lp-show='tasks:HomeTaskList'][data-toggle]",
		);
		this._pendingUserTaskCount = null;
		this._pendingFeedback = null;
	}

	init() {
		this.target.addEventListener("change", this._change);
	}

	handleOfflineQueue({ phase, queue, record }: QueueContext) {
		if (phase === "queued") return this._offlineQueued(record, queue);
		if (phase === "cancelled") return this._offlineCancelled(record);
		if (phase === "replayed" && record.kind === "task") {
			return withTransition(() => this._syncList(), {
				label: "home:task-replayed",
			});
		}
	}

	_offlineQueued(record: OfflineMutationRecord, queue: OfflineQueue) {
		if (record.kind === "task" && record.action === "create") {
			const key = record.client_key;
			if (!key) return;
			this._updateUserTaskCountOffline(1);
			if (!this._offlineTaskVisible(record, queue)) {
				return {
					ok: true,
					removed: true,
					name: queue.field(record, "name") || "Untitled task",
					scheduled: Boolean(queue.field(record, "due-date")),
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
				{ label: "home:task-complete-offline" },
			);
		}
	}

	_offlineCancelled(record: OfflineMutationRecord) {
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

	async _change(e: Event) {
		if (!(e.target instanceof Element)) return;
		const toggle = e.target.closest<HTMLInputElement>("[data-role='complete']");
		if (!toggle) return;

		const elt = toggle.closest<HTMLElement>("[lp-entity]");
		const key = elt?.dataset.key;
		if (!elt || !key) return;
		elt.classList.add("opacity-50", "pointer-events-none");
		toggle.disabled = true;

		const data = new FormData();
		data.append("completed", String(toggle.checked));

		const route = this.endpoints.completeTask(key);

		if (!this.view.online) {
			const queue =
				this.view.offlineQueue || (await this.view.ensureOfflineQueue?.());
			if (!queue) return;
			if (key.startsWith("offline:")) {
				await queue.cancel({
					action: "create",
					client_key: key,
				});
			} else {
				await queue.queue({
					id: `complete:${key}`,
					kind: "task",
					action: "complete",
					method: "PUT",
					route,
					target_key: key,
					data,
				});
			}
			return;
		}

		const response = await request.put<HomeTaskResult>(route, data);
		if (!response) return;

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

	updated(response: unknown) {
		const html = listHtml(response);
		if (!html) return;
		this._replaceUserTaskCount(html);
		super.updated(response);
	}

	created(response: unknown) {
		super.created(response);
		if (!response || typeof response !== "object") return;
		const result = response as HomeTaskResult;
		if (typeof result.count === "number") {
			this._pendingUserTaskCount = result.count;
		}
		if (result.removed) {
			const name = typeof result.name === "string" ? result.name.trim() : "";
			const qualifier = result.scheduled
				? "scheduled beyond this week"
				: "unscheduled";
			this._pendingFeedback = name
				? `“${name}” saved to My Page (${qualifier}).`
				: `Task saved to My Page (${qualifier}).`;
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

	async _postpone(
		elt: HTMLElement,
		button: HTMLButtonElement,
		value: PostponeValue,
	) {
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
		const response = await request.put<HomeTaskResult>(route, data);
		if (!response) return;

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

	_commitTaskResponse(
		elt: HTMLElement,
		response: RequestResult<HomeTaskResult>,
	) {
		if (response.removed) {
			elt.remove();
		} else if (response.html) {
			const newTask = response.html.querySelector<HTMLElement>("[lp-entity]");
			if (newTask) {
				elt.remove();
				_insertSorted(this.target, newTask);
				this._initPostponeMenus(newTask);
			}
		}

		this._syncList();
		this._updateUserTaskCount(response.count);
	}

	_initPostponeMenus(root: HTMLElement) {
		for (const button of root.querySelectorAll<HTMLButtonElement>(
			"[data-role='change-due-date']",
		)) {
			const dropdown = new Dropdown(button);
			dropdown.init(
				_postponeMenu(dropdown, (value) => {
					const elt = button.closest<HTMLElement>("[lp-entity]");
					if (elt) void this._postpone(elt, button, value);
				}),
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
		for (const item of this.target.querySelectorAll<HTMLElement>(
			"[lp-entity]",
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
		const taskCount = this.component.elt.querySelector<HTMLElement>(
			"[data-role='task-count']",
		);
		const count = this.target.querySelectorAll("[lp-entity]").length;
		if (!taskCount) return;
		taskCount.textContent = String(count);
		taskCount.dataset.kind = count > 0 ? "task" : "success";
		taskCount.dataset.visible = "true";
	}

	_updateUserTaskCount(count?: number) {
		if (count === undefined) return;
		const elt = document.querySelector<HTMLElement>(
			"[data-role='user-task-count']",
		);
		if (!elt) return;
		const safeCount = Math.max(0, count);
		elt.textContent = String(safeCount);
		elt.dataset.visible = "true";
		elt.classList.add("font-bold", "ml-auto");
		elt.classList.toggle("text-task-default", safeCount > 0);
		elt.classList.toggle("text-project-default", safeCount === 0);
	}

	_updateUserTaskCountOffline(delta: number) {
		const elt = document.querySelector("[data-role='user-task-count']");
		if (!elt) return;

		const count = Number.parseInt(elt.textContent || "0", 10);
		if (Number.isNaN(count)) return;

		this._updateUserTaskCount(count + delta);
	}

	_setTaskFeedback(message: string) {
		const banner = this.component.elt.querySelector<HTMLElement>(
			"[data-role='task-feedback']",
		);
		if (!banner) return;
		const text = banner.querySelector<HTMLElement>(
			"[data-role='task-feedback-text']",
		);
		if (!message) {
			banner.dataset.visible = "false";
			if (text) text.textContent = "";
			return;
		}
		if (text) text.textContent = message;
		banner.dataset.visible = "true";
	}

	_offlineTaskVisible(record: OfflineMutationRecord, queue: OfflineQueue) {
		return _isWithinHomeTaskWindow(queue.field(record, "due-date"));
	}

	_renderOfflineTask(
		record: OfflineMutationRecord,
		queue: OfflineQueue,
		key: string,
	) {
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

	_taskByKey(root: HTMLElement | null, key?: string | null) {
		if (!root || !key) return null;
		return Array.from(
			root.querySelectorAll<HTMLElement>("[lp-entity][data-key]"),
		).find((item) => item.dataset.key === key);
	}

	_removeTaskByKey(key?: string | null) {
		this._taskByKey(this.target, key)?.remove();
	}

	_replaceUserTaskCount(html: Pick<ParentNode, "querySelector">) {
		const fresh = html.querySelector("[data-role='user-task-count']");
		const current = document.querySelector("[data-role='user-task-count']");
		if (current && fresh) current.replaceWith(fresh);
	}

	_updateVisibility() {
		const count = this.target.querySelectorAll("[lp-entity]").length;
		this.target.dataset.visible = count > 0 && this.visible ? "true" : "false";
		this.view.syncHomeSectionState?.(this.component);
	}

	_showNotification(elt: HTMLElement, message: string) {
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
