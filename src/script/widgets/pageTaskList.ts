import { BaseList, type ListAttributes } from "../elements/base/baseList.ts";
import { withTransition } from "../shared/transitions.ts";
import type { RequestResult } from "../types/api";
import type ViewComponent from "../views/base/component.ts";
import type Core from "../views/base/core.ts";
import type { Task } from "../views/base/task.ts";

export interface PageTaskDelta {
	remove?: string[];
	upsert?: { key: string; html: string }[];
	order?: string[];
	empty?: string | null;
}

type TaskRowUpdate = { from: HTMLLIElement; to: HTMLLIElement };
type StagedReplacement = TaskRowUpdate & {
	current: ViewComponent | null;
	replacement: ViewComponent | null;
};
type StagedCreation = {
	hasForm: boolean;
	newTask: ViewComponent;
	elt: HTMLLIElement;
};
type TaskListView = Pick<
	Core,
	"key" | "getComponent" | "addFlash" | "update" | "load" | "components"
>;
type TaskListResponse = { html?: Document | HTMLElement | "" | null };
type TaskListSettings = ListAttributes & {
	component: ViewComponent;
	view: TaskListView;
};

export class PageTaskList extends BaseList {
	declare component: ViewComponent;
	declare view: TaskListView;
	declare route?: string;
	declare _added: HTMLLIElement[];
	declare _removed: HTMLLIElement[];
	declare _replaced: TaskRowUpdate[];
	declare _updated: HTMLElement[];
	declare _replaceAll?: HTMLElement[] | null;
	declare _preparedReplacements?: StagedReplacement[];
	declare _preparedCreated?: StagedCreation[];

	constructor(attributes: TaskListSettings) {
		super(attributes);
		this._change = this._change.bind(this);
		this._click = this._click.bind(this);
		this._setActiveTask = this._setActiveTask.bind(this);
		this._scrollOpenedTask = this._scrollOpenedTask.bind(this);

		this._added = [];
		this._removed = [];
		this._replaced = [];
		this._updated = [];
	}

	init() {
		this.target.addEventListener("change", this._change);
		this.target.addEventListener("click", this._click);
		this.target.addEventListener("set-subcomponent", this._setActiveTask);
		this.target.addEventListener("component-opened", this._scrollOpenedTask);
	}

	_change(e: Event) {
		const target = e.target as Element | null;
		if (!target?.closest) return;
		const widget = target.closest<HTMLElement>("[data-widget]")?.dataset.widget;
		if (widget !== "TaskSettings" && widget !== "TaskForm") {
			return;
		}
		const task = target.closest("li");
		const saved = task?.querySelector<HTMLElement>("[data-saved]");
		if (saved) {
			saved.dataset.saved = "false";
			saved.dataset.visible = "true";
		}
	}

	_click(e: MouseEvent) {
		const target = e.target as Element | null;
		if (!target?.closest) return;
		const submitter = target.closest<HTMLElement>(
			"[data-role='save-toggle'], [data-role='complete-toggle']",
		);
		const role = submitter?.dataset?.role;
		if (submitter && this.target.contains(submitter)) {
			const task = this.view.getComponent(submitter);
			if (!task) return;
			const route = task.elt.dataset.route;
			task.disable();
			e.stopPropagation();
			e.preventDefault();

			if (
				role === "complete-toggle" &&
				(!task.active || task.elt.dataset.completed === "true")
			) {
				const data = new FormData();
				data.append("role", role);
				if (task.elt.dataset.completed === "true") {
					const choice = task.elt.querySelector<HTMLInputElement>(
						"[data-role='completion-submission-choice']:checked",
					);
					data.append("completion_submission", choice?.value || "modified");
				}
				void this.view.update(task, data, route);
				return;
			}

			submitter.dispatchEvent(
				new CustomEvent("submit", {
					bubbles: true,
					detail: { update: true, role, route },
				}),
			);
			return;
		}

		const completedHeader = this.completedHeader;
		if (completedHeader?.contains(target)) {
			const expandToggle = this.expandToggle;
			const completedTasks = this.completedTasks;
			if (!expandToggle || !completedTasks) return;

			const open = expandToggle.dataset.open !== "true";
			expandToggle.dataset.open = open ? "true" : "false";
			expandToggle.setAttribute("aria-expanded", open ? "true" : "false");
			expandToggle.setAttribute("aria-label", open ? "Collapse" : "Expand");
			expandToggle.title = open ? "Collapse" : "Expand";
			completedTasks.dataset.visible = open ? "true" : "false";
		}
	}

	_setActiveTask(e: Event) {
		const { subcomponent } = (e as CustomEvent<{ subcomponent: ViewComponent }>)
			.detail;
		this._moveTaskIfNecessary(subcomponent.elt as HTMLLIElement);
		this._setListVisibility();
	}

	_scrollOpenedTask(e: Event) {
		const { component, trigger } =
			(
				e as CustomEvent<{
					component?: ViewComponent;
					trigger?: Element | null;
				}>
			).detail || {};
		const task = component?.elt;
		if (
			e.target !== task ||
			!task?.matches("li[lp-component][data-kind='task']") ||
			!this.target.contains(task) ||
			trigger !== task.querySelector(":scope > [lp-nav][lp-show]")
		)
			return;

		if (
			!component?.active ||
			!("target" in component.active) ||
			!component.active.target
		)
			return;
		const { top, bottom } = task.getBoundingClientRect();
		const viewportTop = 80;
		const viewportBottom =
			window.innerHeight || document.documentElement.clientHeight;
		const viewportHeight = viewportBottom - viewportTop;
		const taskHeight = bottom - top;
		const usableHeight = Math.min(taskHeight, viewportHeight);
		const visibleHeight =
			Math.min(bottom, viewportBottom) - Math.max(top, viewportTop);
		// Leave a comfortably visible task under the pointer, even if it is tall.
		if (usableHeight <= 0 || visibleHeight >= usableHeight / 2) return;
		task.classList.add("scroll-mt-20");
		task.scrollIntoView({
			behavior: "auto",
			block: taskHeight <= viewportHeight ? "nearest" : "start",
		});
	}

	_moveTaskIfNecessary(taskElt: HTMLLIElement) {
		if (this._existingTask(taskElt)) return;

		const completed = taskElt.dataset.completed === "true";
		const list = completed ? this.completedTasks : this.activeTasks;
		if (list && !list.contains(taskElt)) {
			const moving =
				this.activeTasks?.contains(taskElt) ||
				this.completedTasks?.contains(taskElt);
			list.prepend(taskElt);
			if (!moving) this.view.addFlash(taskElt);
		}
	}

	_existingTask(taskElt: HTMLLIElement) {
		const key = taskElt?.dataset?.key;
		const id = taskElt?.id;
		if (!key && !id) return null;

		return Array.from(
			this.target.querySelectorAll<HTMLLIElement>(
				"li[lp-component][data-kind='task']",
			),
		).find((elt) => {
			return (
				elt !== taskElt &&
				((key && elt.dataset.key === key) || (id && elt.id === id))
			);
		});
	}

	async focusTask(taskId: string) {
		const taskElt = this.target.querySelector(`[data-key="${taskId}"]`);
		if (!taskElt) return false;

		const task = this.view.getComponent(taskElt);
		if (!task) return false;

		const revealCompleted = this.completedTasks?.contains(taskElt);
		await task.activate("default");
		await task.prepareRender(true);
		await withTransition(
			() => {
				if (revealCompleted) this._openCompletedTasks();
				task.render(true);
			},
			{ label: "page-tasks:focus" },
		);
		taskElt.scrollIntoView({ behavior: "auto", block: "start" });
		return true;
	}

	_openCompletedTasks() {
		const completed = this.completedTasks;
		const toggle = this.expandToggle;
		if (!completed || !toggle) return;
		completed.dataset.visible = "true";
		toggle.dataset.open = "true";
		toggle.setAttribute("aria-expanded", "true");
		toggle.setAttribute("aria-label", "Collapse");
		toggle.title = "Collapse";
	}

	_setListVisibility() {
		if (!this.target.hasAttribute("loaded")) return;
		const activeTasks = this.activeTasks;
		const completedTasks = this.completedTasks;
		const completedHeader = this.completedHeader;
		if (!activeTasks || !completedTasks || !completedHeader) return;

		const hasActive = this.activeCount > 0;
		const hasCompleted = this.completedCount > 0;
		const empty = activeTasks.querySelector<HTMLElement>("[data-role='empty']");
		const showEmpty =
			Boolean(empty) &&
			!hasActive &&
			!hasCompleted &&
			Object.is(this.component.active, this);

		if (empty) empty.dataset.visible = showEmpty ? "true" : "false";
		activeTasks.dataset.visible = hasActive || showEmpty ? "true" : "false";
		completedHeader.dataset.visible = hasCompleted ? "true" : "false";
	}

	get ifEmpty() {
		const createTask = this.component.widgets.CreateTask;
		const createTaskClosing =
			createTask?.visible === false &&
			createTask.target?.dataset.visible === "true";

		return this._isEmpty && this._created.length === 0 && !createTaskClosing
			? this.target.dataset.ifEmpty
			: false;
	}

	get activeTasks() {
		return this.target.querySelector<HTMLElement>("[data-role='active-tasks']");
	}

	get expandToggle() {
		return this.target.querySelector<HTMLElement>("[data-role='expand']");
	}

	get completedTasks() {
		return this.target.querySelector<HTMLElement>(
			"[data-role='completed-tasks']",
		);
	}

	get completedHeader() {
		return this.target.querySelector<HTMLElement>(
			"[data-role='completed-header']",
		);
	}

	get activeCount() {
		if (!this.activeTasks) return 0;
		return this.activeTasks.querySelectorAll(
			"li[lp-component][data-kind='task']",
		).length;
	}

	get completedCount() {
		if (!this.completedTasks) return 0;
		return this.completedTasks.querySelectorAll(
			"li[lp-component][data-kind='task']",
		).length;
	}

	refreshDescriptor() {
		if (
			this.component.name !== "tasks" ||
			!this.view.key ||
			!this.target.hasAttribute("loaded")
		) {
			return null;
		}
		return {
			rows: Array.from(
				this.target.querySelectorAll<HTMLLIElement>(
					"li[lp-entity][data-kind='task']",
				),
				(task) => ({
					key: task.dataset.key,
					hash: task.dataset.hash || "",
					fingerprint: task.dataset.fingerprint || "",
				}),
			),
		};
	}

	_parseRefreshTask(html: string) {
		if (!html) return null;
		const template = document.createElement("template");
		template.innerHTML = html.trim();
		return template.content.querySelector<HTMLLIElement>(
			"li[lp-component][data-kind='task']",
		);
	}

	async prepareRefreshDelta(delta: PageTaskDelta) {
		const existing = new Map(
			Array.from(
				this.target.querySelectorAll<HTMLLIElement>(
					"li[lp-entity][data-kind='task']",
				),
				(task) => [task.dataset.key, task],
			),
		);
		const known = new Set(existing.keys());
		for (const key of delta.remove || []) known.delete(key);
		for (const { key } of delta.upsert || []) known.add(key);
		if ((delta.order || []).some((key) => !known.has(key))) {
			// Mutation deltas contain only the affected rows. Another client may
			// have added a task since this list loaded; reconcile the full list
			// through the usual draft-preserving path before applying anything.
			const response = await this.view.load(this.component, this.route);
			return this.prepareRefresh(response ?? undefined);
		}
		this._removed = (delta.remove || [])
			.map((key) => existing.get(key))
			.filter((task) => task !== undefined);
		this._replaced = [];
		this._added = [];

		for (const update of delta.upsert || []) {
			const task = this._parseRefreshTask(update.html);
			if (!task || task.dataset.key !== update.key) {
				throw new Error("Invalid page-task refresh row");
			}
			const current = existing.get(update.key);
			if (current) this._replaced.push({ from: current, to: task });
			else this._added.push(task);
		}

		await this.prereconcile();
		return () => {
			this.postreconcile();

			const refreshed = new Map(
				Array.from(
					this.target.querySelectorAll<HTMLLIElement>(
						"li[lp-entity][data-kind='task']",
					),
					(task) => [task.dataset.key, task],
				),
			);
			// Keep a viewed task at its current scroll position while its form is
			// being reconciled. Saving it changes its modified timestamp and would
			// otherwise move an open row to the top of the list.
			const preserveActiveOrder = Boolean(
				this.activeTasks?.querySelector(
					"li[lp-entity][data-kind='task'][data-open]:not([data-open='false'])",
				),
			);
			const preserveCompletedOrder = Boolean(
				this.completedTasks?.querySelector(
					"li[lp-entity][data-kind='task'][data-open]:not([data-open='false'])",
				),
			);
			const activeOrder: HTMLLIElement[] = [];
			const completedOrder: HTMLLIElement[] = [];
			for (const key of delta.order || []) {
				const task = refreshed.get(key);
				if (!task) {
					throw new Error("Page-task refresh order references a missing row");
				}
				const list =
					task.dataset.completed === "true"
						? this.completedTasks
						: this.activeTasks;
				const preserveOrder =
					task.dataset.completed === "true"
						? preserveCompletedOrder
						: preserveActiveOrder;
				if (preserveOrder) {
					if (list && !list.contains(task)) list.append(task);
				} else {
					(task.dataset.completed === "true"
						? completedOrder
						: activeOrder
					).push(task);
				}
			}
			for (const [list, desired] of [
				[this.activeTasks, activeOrder],
				[this.completedTasks, completedOrder],
			] as const) {
				if (!list || !desired.length) continue;
				const current = Array.from(list.children).filter((child) =>
					child.matches("li[lp-entity][data-kind='task']"),
				);
				if (
					current.length !== desired.length ||
					current.some((task, index) => task !== desired[index])
				) {
					list.append(...desired);
				}
			}

			this.target.querySelectorAll("li[data-role='empty']").forEach((empty) => {
				empty.remove();
			});
			this._isEmpty = (delta.order || []).length === 0;
			if (this._isEmpty && delta.empty) {
				const template = document.createElement("template");
				template.innerHTML = delta.empty.trim();
				const empty = template.content.querySelector("li[data-role='empty']");
				if (empty) this.activeTasks?.append(empty);
			}
			this._setListVisibility();
		};
	}

	async refreshDelta(delta: PageTaskDelta) {
		const commit = await this.prepareRefreshDelta(delta);
		commit?.();
	}

	updated(response: RequestResult) {
		if (!response.html) return;

		const updated = [
			response.html.querySelector<HTMLElement>("[data-role='active-tasks']"),
			response.html.querySelector<HTMLElement>(
				"[data-role='completed-header']",
			),
			response.html.querySelector<HTMLElement>("[data-role='completed-tasks']"),
		];
		if (updated.some((element) => !element)) {
			this._updated = [];
			return;
		}

		this._isEmpty = !response.html.querySelector("[data-key]");
		this._updated = updated.filter((element) => element !== null);
	}
	async prepareRefresh(response: TaskListResponse | undefined) {
		if (!this._queueRefresh(response)) return;
		await this.prereconcile();
		return () => this.postreconcile();
	}

	async refresh(response: RequestResult | undefined) {
		const commit = await this.prepareRefresh(response);
		commit?.();
	}

	_queueRefresh(response: TaskListResponse | undefined) {
		if (!response?.html) return;
		const existingTasks = new Map(
			Array.from(
				this.target.querySelectorAll<HTMLLIElement>(
					"li[lp-component][data-kind='task']",
				),
			).map((elt) => [elt.id, elt]),
		);

		const newTasks = new Map(
			Array.from(
				response.html.querySelectorAll<HTMLLIElement>(
					"li[lp-component][data-kind='task']",
				),
			).map((elt) => [elt.id, elt]),
		);

		this._added = [];
		this._removed = [];
		this._replaced = [];

		existingTasks.forEach((elt, id) => {
			if (!newTasks.has(id)) {
				this._removed.push(elt);
			}
		});

		newTasks.forEach((elt, id) => {
			const existing = existingTasks.get(id);
			if (existing) {
				if (existing.dataset.fingerprint !== elt.dataset.fingerprint) {
					this._replaced.push({ from: existing, to: elt });
				}
			} else {
				this._added.push(elt);
			}
		});

		return true;
	}

	_restorableWidgetName(taskElt: HTMLLIElement, open?: string) {
		if (!open || open === "false") return null;

		const widget = open === "true" ? taskElt.dataset.default : open;
		if (!widget) return null;

		return taskElt.querySelector(`[data-widget='${widget}']`) ? widget : null;
	}

	_hasPendingLocalFormState(
		component: ViewComponent | null,
		replacement: HTMLLIElement | null = null,
	) {
		return Object.values(component?.widgets ?? {}).some((widget) => {
			if (
				widget.unsavedState === true ||
				widget.form?._queued === true ||
				widget.target?.querySelector?.(
					"[lp-edited-marker][data-visible='true']",
				)
			) {
				return true;
			}

			if (
				component?.active !== widget ||
				widget.visible !== true ||
				!widget.name
			) {
				return false;
			}

			return Boolean(
				replacement?.querySelector?.(`[data-widget='${widget.name}']`),
			);
		});
	}

	async prereconcile() {
		const needsRefresh = this.activeCount > 0 || this.completedCount > 0;
		const hasUpdated = this._updated.length > 0;
		if (hasUpdated) {
			if (needsRefresh) {
				const html = document.createElement("div");
				html.append(...this._updated);
				this._queueRefresh({ html });
			} else {
				this._replaceAll = [...this._updated];
			}
		}
		this._updated = [];

		this._removed = this._removed.filter((elt) => {
			const component = this.view.getComponent(elt);
			return !this._hasPendingLocalFormState(component);
		});

		this._preparedReplacements = [];
		for (const { from, to } of this._replaced) {
			const current = this.view.getComponent(from);
			if (this._hasPendingLocalFormState(current, to)) continue;
			const open = this._restorableWidgetName(to, current?.open);
			const replacement = this.view.getComponent(to);
			if (current?.key) this.view.components[current.key] = current;
			if (replacement && open) {
				await replacement.activate(open);
				await replacement.prepareRender(true);
			}
			this._preparedReplacements.push({
				current,
				from,
				replacement,
				to,
			});
		}
		this._replaced = [];

		this._preparedCreated = [];
		for (const elt of this._created) {
			const pendingAdded = this._added.some((added) => {
				return (
					(elt.dataset.key && added.dataset.key === elt.dataset.key) ||
					(elt.id && added.id === elt.id)
				);
			});
			if (pendingAdded || this._existingTask(elt)) continue;

			const newTask = this.view.getComponent(elt);
			if (!newTask) continue;
			const hasForm = newTask.elt.dataset.default === "TaskForm";
			if (hasForm) {
				await newTask.activate("TaskForm");
				await newTask.prepareRender(true);
			}
			this._preparedCreated.push({ hasForm, newTask, elt });
		}
		this._created = [];
	}

	postreconcile() {
		if (this.component.active?.name === "CreateTask") {
			this._closeOpenTasks();
		}

		if (this._replaceAll) {
			this.target.replaceChildren(...this._replaceAll);
			this._replaceAll = null;
		}

		for (const elt of this._removed) {
			const component = this.view.getComponent(elt);
			component?.destroy?.();
			elt.remove();
		}
		this._removed = [];

		for (const { current, from, replacement, to } of this
			._preparedReplacements || []) {
			from.replaceWith(to);
			current?.destroy?.();
			if (replacement) {
				if (replacement.key)
					this.view.components[replacement.key] = replacement;
				if (replacement.active) replacement.render(true);
			}
			this._moveTaskIfNecessary(to);
		}
		this._preparedReplacements = [];

		for (const elt of this._added) {
			this._moveTaskIfNecessary(elt);
		}
		this._added = [];

		for (const { hasForm, newTask, elt } of this._preparedCreated || []) {
			this.activeTasks?.prepend(elt);
			this.view.addFlash(elt);
			if (hasForm) newTask.render(true);
		}
		this._preparedCreated = [];

		this.target.setAttribute("loaded", "");
		this._setListVisibility();
	}

	_closeOpenTasks() {
		const openTasks = this.target.querySelectorAll(
			"li[lp-component][data-kind='task'][data-open]:not([data-open='false'])",
		);
		openTasks.forEach((elt) => {
			const task = this.view.getComponent(elt) as Task | null;
			task?.closeOpenWidget?.();
		});
	}
}
