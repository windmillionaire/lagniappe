import { withTransition } from "../../shared/transitions";
import ViewComponent from "./component";

const ISOLATED_TASK_ACTIONS = new Set(["TaskMove", "TaskCombine"]);

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_task_update_preserves_open_widget_and_completed_readonly_state
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_while_another_task_is_open_keeps_rows_clear
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_uncomplete_from_loaded_task_history_closes_task
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_task_form_filters_compatible_tasks
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_tasks_migrates_history_and_reconciles_task_delta
 * @matrix task-combine : delta isolated-form lazy-reload linked-page no-reload view-page
 * @matrix tasks : active-widget history-refresh uncomplete
 * @matrix tasks : create list-state readonly refresh update-state while-open
 */
export class Task extends ViewComponent {
	async activate(show) {
		const existingCombine =
			show === "TaskCombine" ? this.widgets.TaskCombine : null;
		if (show === "TaskCombine" && this.view.key) {
			const target = this.elt.querySelector("[data-widget='TaskCombine']");
			if (target?.dataset.route) {
				const route = new URL(target.dataset.route, window.location.origin);
				route.searchParams.set("page", this.view.key);
				const scopedRoute = `${route.pathname}${route.search}`;
				target.dataset.route = scopedRoute;
				if (existingCombine) existingCombine.route = scopedRoute;
			}
		}
		const activated = await super.activate(show);
		if (activated && existingCombine) {
			const separator = existingCombine.route.includes("?") ? "&" : "?";
			await this.load(
				existingCombine,
				`${existingCombine.route}${separator}refresh=${Date.now()}`,
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
		if (ISOLATED_TASK_ACTIONS.has(this.active?.name)) {
			return this.active.formData;
		}

		const taskWidgets = Object.values(this.widgets).filter(
			(widget) =>
				!ISOLATED_TASK_ACTIONS.has(widget.name) &&
				(widget === this.active || widget.unsavedState === true) &&
				widget.target?.dataset.widget === widget.name &&
				this.elt.contains(widget.target),
		);
		const data = taskWidgets
			.map((widget) => {
				if (widget.formData instanceof FormData) return widget.formData;
				if (widget.target instanceof HTMLFormElement) {
					return new FormData(widget.target);
				}
				return null;
			})
			.filter(Boolean)
			.reduce((merged, current) => {
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

	/**
	 * @testable true
	 * @tests tests_js/test_032_task_settings_lifecycle.py::test_task_completion_replaces_closed_row_in_one_transition
	 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_reopening_discards_inactive_history_until_next_click
	 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_completion_waits_for_acceptance_and_moves_closed_task
	 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_uncomplete_from_loaded_task_history_closes_task
	 * @matrix tasks : active-widget complete history-refresh uncomplete update-state
	 */
	async updated(response) {
		if (response.task_delta) {
			this.deactivate(false);
			const parent = this.view.getComponent(this.parentComponent);
			await parent?.widgets?.PageTaskList?.refreshDelta(response.task_delta);
			return;
		}

		const update = response.html?.querySelector(`[id='${this.name}']`);
		if (update && this.completed !== (update.dataset.completed === "true")) {
			// Commit the closed row and its list move together, after server acceptance.
			// Widgets stay unloaded, including History, until the next explicit open.
			await withTransition(
				() => {
					if (this._destroyed || this.view._destroyed) return;
					const replacement = this.view.getComponent(update);
					update.dataset.open = "false";
					this.elt.replaceWith(update);
					this.destroy();
					this.view.components[replacement.name] = replacement;
					replacement.render(false);
				},
				{ label: `${this.name}:completion` },
			);
			return;
		}

		if (update) {
			// The server's closed-row default must not flash during preparation.
			Object.assign(this.elt.dataset, {
				...update.dataset,
				open: this.elt.dataset.open,
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

	/**
	 * @testable false
	 * @covered-by src/script/views/base/task.mjs::Task.updated
	 * @reason ordinary update widget cleanup belongs to the task response lifecycle
	 */
	_removeMissingWidgets(update) {
		this.elt.querySelectorAll("[data-widget]").forEach((elt) => {
			// Nested components own their widgets, including loaded history rows.
			if (elt.closest("[lp-component]") !== this.elt) return;
			const name = elt.dataset.widget;
			const target = update.querySelector(`[data-widget='${name}']`);
			if (target) return;

			elt.remove();
			if (this.active?.name === name) this.active = null;
			this.widgets[name]?.destroy?.();
			delete this.widgets[name];
		});
	}
}
