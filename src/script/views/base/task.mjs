import ViewComponent from "./component";

const ISOLATED_TASK_ACTIONS = new Set(["TaskMove", "TaskCombine"]);

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_task_update_preserves_open_widget_and_completed_readonly_state
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_while_another_task_is_open_keeps_rows_clear
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_task_form_filters_compatible_tasks
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_tasks_migrates_history_and_reconciles_task_delta
 * @matrix task-combine : delta isolated-form lazy-reload linked-page no-reload view-page
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

	async updated(response) {
		if (response.task_delta) {
			this.deactivate(false);
			const parent = this.view.getComponent(this.parentComponent);
			await parent?.widgets?.PageTaskList?.refreshDelta(response.task_delta);
			return;
		}

		const update = response.html?.querySelector(`[id='${this.name}']`);

		if (update) {
			Object.assign(this.elt.dataset, update.dataset);
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
