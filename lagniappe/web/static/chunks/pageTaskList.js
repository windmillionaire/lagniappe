/*! Third-party licenses: /third-party-licenses.txt */
import { BaseList } from './baseList.js?v=b687b680';
import { w as withTransition } from './foundation.js?v=b687b680';
import './connectivity.js?v=b687b680';

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_page_task_viewer_sees_task_without_edit_controls
 * @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_assigned_user_can_work_their_assigned_task
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_task_update_preserves_open_widget_and_completed_readonly_state
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_while_another_task_is_open_keeps_rows_clear
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_update_page_task_settings_from_row
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_empty_page_task_list_shows_marker_only_after_create_closes
 * @tests tests_e2e/006_tasks/test_006d_task_permissions.py::test_completed_only_task_list_hides_empty_marker
 * @tests tests_js/test_028_form_state_split.py::test_task_list_refresh_preserves_rows_with_local_form_state
 * @tests tests_js/test_028_form_state_split.py::test_task_list_reconcile_deduplicates_created_row_already_added_by_refresh
 * @tests tests_js/test_028_form_state_split.py::test_task_list_initial_reconciliation_publishes_list_visibility
 * @tests tests_e2e/010_sync/test_010d_form_state_split.py::test_task_collection_refresh_preserves_active_form_for_revision_review
 * @tests tests_js/test_028_form_state_split.py::test_task_list_empty_marker_requires_closed_create_form_and_no_tasks
 * @tests tests_js/test_028_form_state_split.py::test_task_list_reconciliation_rejects_incomplete_structure
 * @matrix tasks : active-form-preservation completed-only create create-close dedupe detached-structure dirty-form-preservation empty-state refresh unsaved-marker
 * @matrix tasks : initial-render permission-gates readonly
 */
class PageTaskList extends BaseList {
	constructor(attributes) {
		super(attributes);
		this._change = this._change.bind(this);
		this._click = this._click.bind(this);
		this._setActiveTask = this._setActiveTask.bind(this);

		this._added = [];
		this._removed = [];
		this._replaced = [];
		this._updated = [];
	}

	init() {
		this.target.addEventListener("change", this._change);
		this.target.addEventListener("click", this._click);
		this.target.addEventListener("set-subcomponent", this._setActiveTask);
	}

	_change(e) {
		const widget = e.target.closest("[data-widget]")?.dataset.widget;
		if (!["TaskSettings", "TaskForm"].includes(widget)) {
			return;
		}
		const task = e.target.closest("li");
		const saved = task.querySelector("[data-saved]");
		if (saved) {
			saved.dataset.saved = "false";
			saved.dataset.visible = "true";
		}
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_complete_page_task
	 * @tests tests_js/test_028_form_state_split.py::test_task_completion_keeps_component_update_route_when_history_is_active
	 * @matrix tasks : active-widget complete route-override
	 */
	_click(e) {
		const submitter = e.target.closest(
			"[data-role='save-toggle'], [data-role='complete-toggle']",
		);
		const role = submitter?.dataset?.role;
		if (submitter && this.target.contains(submitter)) {
			const task = this.view.getComponent(submitter);
			const route = task.elt.dataset.route;
			task.disable();
			e.stopPropagation();
			e.preventDefault();

			if (!task.active && role === "complete-toggle") {
				const data = new FormData();
				data.append("role", role);
				this.view.update(task, data, route);
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
		if (completedHeader?.contains(e.target)) {
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

	_setActiveTask(e) {
		const activeTask = e.detail.subcomponent;
		this._moveTaskIfNecessary(activeTask.elt);
		this._setListVisibility();
	}

	_moveTaskIfNecessary(taskElt) {
		if (this._existingTask(taskElt)) return;

		const completed = taskElt.dataset.completed === "true";
		const list = completed ? this.completedTasks : this.activeTasks;
		if (!list.contains(taskElt)) {
			list.prepend(taskElt);
			this.view.addFlash(taskElt);
		}
	}

	_existingTask(taskElt) {
		const key = taskElt?.dataset?.key;
		const id = taskElt?.id;
		if (!key && !id) return null;

		return Array.from(
			this.target.querySelectorAll("li[lp-component][data-kind='task']"),
		).find((elt) => {
			return (
				elt !== taskElt &&
				((key && elt.dataset.key === key) || (id && elt.id === id))
			);
		});
	}

	async focusTask(taskId) {
		const taskElt = this.target.querySelector(`[data-key="${taskId}"]`);
		if (!taskElt) return false;

		const task = this.view.getComponent(taskElt);
		if (!task) return false;

		const revealCompleted = this.completedTasks.contains(taskElt);
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
		this.completedTasks.dataset.visible = "true";
		this.expandToggle.dataset.open = "true";
		this.expandToggle.setAttribute("aria-expanded", "true");
		this.expandToggle.setAttribute("aria-label", "Collapse");
		this.expandToggle.title = "Collapse";
	}

	_setListVisibility() {
		if (!this.target.hasAttribute("loaded")) return;
		const activeTasks = this.activeTasks;
		const completedTasks = this.completedTasks;
		const completedHeader = this.completedHeader;
		if (!activeTasks || !completedTasks || !completedHeader) return;

		const hasActive = this.activeCount > 0;
		const hasCompleted = this.completedCount > 0;
		const empty = activeTasks.querySelector("[data-role='empty']");
		const showEmpty =
			Boolean(empty) &&
			!hasActive &&
			!hasCompleted &&
			this.component.active === this;

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
		return this.target.querySelector("[data-role='active-tasks']");
	}

	get expandToggle() {
		return this.target.querySelector("[data-role='expand']");
	}

	get completedTasks() {
		return this.target.querySelector("[data-role='completed-tasks']");
	}

	get completedHeader() {
		return this.target.querySelector("[data-role='completed-header']");
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

	/**
	 * @testable infrastructure
	 * @covered-by src/script/views/base/core.mjs::Core._collectRefreshTargets
	 */
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
				this.target.querySelectorAll("li[lp-entity][data-kind='task']"),
				(task) => ({
					key: task.dataset.key,
					modified: task.dataset.modified || "",
				}),
			),
		};
	}

	_parseRefreshTask(html) {
		if (!html) return null;
		const template = document.createElement("template");
		template.innerHTML = html.trim();
		return template.content.querySelector("li[lp-component][data-kind='task']");
	}

	/**
	 * @testable infrastructure
	 * @covered-by src/script/views/base/core.mjs::Core._refreshCollectionComponents
	 */
	async prepareRefreshDelta(delta) {
		const existing = new Map(
			Array.from(
				this.target.querySelectorAll("li[lp-entity][data-kind='task']"),
				(task) => [task.dataset.key, task],
			),
		);
		this._removed = (delta.remove || [])
			.map((key) => existing.get(key))
			.filter(Boolean);
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
					this.target.querySelectorAll("li[lp-entity][data-kind='task']"),
					(task) => [task.dataset.key, task],
				),
			);
			for (const key of delta.order || []) {
				const task = refreshed.get(key);
				if (!task) {
					throw new Error("Page-task refresh order references a missing row");
				}
				const list =
					task.dataset.completed === "true"
						? this.completedTasks
						: this.activeTasks;
				list.append(task);
			}

			this.target.querySelectorAll("li[data-role='empty']").forEach((empty) => {
				empty.remove();
			});
			this._isEmpty = (delta.order || []).length === 0;
			if (this._isEmpty && delta.empty) {
				const template = document.createElement("template");
				template.innerHTML = delta.empty.trim();
				const empty = template.content.querySelector("li[data-role='empty']");
				if (empty) this.activeTasks.append(empty);
			}
			this._setListVisibility();
		};
	}

	async refreshDelta(delta) {
		const commit = await this.prepareRefreshDelta(delta);
		commit();
	}

	updated(response) {
		if (!response.html) return;

		const updated = [
			response.html.querySelector("[data-role='active-tasks']"),
			response.html.querySelector("[data-role='completed-header']"),
			response.html.querySelector("[data-role='completed-tasks']"),
		];
		if (updated.some((element) => !element)) {
			this._updated = [];
			return;
		}

		this._isEmpty = !response.html.querySelector("[data-key]");
		this._updated = updated;
	}
	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_task_update_preserves_open_widget_and_completed_readonly_state
	 * @matrix tasks : refresh update-state
	 */
	async prepareRefresh(response) {
		if (!this._queueRefresh(response)) return;
		await this.prereconcile();
		return () => this.postreconcile();
	}

	async refresh(response) {
		const commit = await this.prepareRefresh(response);
		commit?.();
	}

	_queueRefresh(response) {
		if (!response?.html) return;
		const existingTasks = new Map(
			Array.from(
				this.target.querySelectorAll("li[lp-component][data-kind='task']"),
			).map((elt) => [elt.id, elt]),
		);

		const newTasks = new Map(
			Array.from(
				response.html.querySelectorAll("li[lp-component][data-kind='task']"),
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
			if (existingTasks.has(id)) {
				const existingModified = existingTasks.get(id).dataset.modified;
				if (existingModified !== elt.dataset.modified) {
					this._replaced.push({ from: existingTasks.get(id), to: elt });
				}
			} else {
				this._added.push(elt);
			}
		});

		return true;
	}

	_restorableWidgetName(taskElt, open) {
		if (!open || open === "false") return null;

		const widget = open === "true" ? taskElt.dataset.default : open;
		if (!widget) return null;

		return taskElt.querySelector(`[data-widget='${widget}']`) ? widget : null;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_task_list_refresh_preserves_rows_with_local_form_state
	 * @matrix tasks : active-form-preservation dirty-form-preservation stale-widget
	 */
	_hasPendingLocalFormState(component, replacement = null) {
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
				component.active !== widget ||
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
			this.activeTasks.prepend(elt);
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
			const task = this.view.getComponent(elt);
			task?.closeOpenWidget?.();
		});
	}
}

export { PageTaskList };
