import { withTransition } from "../../shared/transitions.mjs";
import ViewComponent from "./component.mjs";

const ISOLATED_TASK_ACTIONS = new Set(["TaskMove", "TaskCombine"]);

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
