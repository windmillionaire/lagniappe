import { BaseList } from "../../elements/base/baseList.ts";
import { localStore } from "../../shared/storage.ts";
import { withTransition } from "../../shared/transitions.ts";

const REPORT_FILTERS = ["active", "executed", "answers"];

function reportCategory(report) {
	if (report.outputKind === "answer") return "answers";
	return report.outputKind === "proposal" && report.status === "complete"
		? "executed"
		: "active";
}

function _listToggle(component, widgetName) {
	return component.elt.querySelector(
		`[lp-show='${component.name}:${widgetName}'][data-toggle]`,
	);
}

function _syncEmptyCount(toggle, widgetName, empty) {
	const indicator = toggle?.querySelector(`[data-indicator='${widgetName}']`);
	if (!indicator) return;

	const wasEmpty = indicator.dataset.empty === "true";
	indicator.dataset.empty = empty ? "true" : "false";
	indicator.classList.toggle("hidden", !empty);
	indicator.classList.toggle("font-bold", empty);
	if (empty) {
		indicator.textContent = "0";
	} else if (wasEmpty) {
		indicator.textContent = "";
	}
}

/**
 * Shared loading lifecycle for simple home collection lists.
 *
 */
class LoadedHomeList extends BaseList {
	static unlockToggleWhenPopulated = false;
	static disableToggleWhenUnavailable = false;

	constructor(attributes) {
		super(attributes);
		this._listToggle = _listToggle(this.component, this.name);
	}

	_syncUnavailableToggle() {
		if (!this.constructor.disableToggleWhenUnavailable || !this._listToggle) {
			return;
		}

		const unavailable = this.itemCount === 0 && !this.target.dataset.ifEmpty;
		this._listToggle.disabled = unavailable;
		this._listToggle.classList.toggle("opacity-50", unavailable);
		_syncEmptyCount(this._listToggle, this.name, unavailable);
	}

	postreconcile() {
		super.postreconcile();
		this._syncUnavailableToggle();
		if (
			this.constructor.unlockToggleWhenPopulated &&
			this.itemCount > 0 &&
			this._listToggle
		) {
			this._listToggle.classList.remove("opacity-50", "pointer-events-none");
		}
		this.target.setAttribute("loaded", "");
	}
}

export class HomeProjectList extends LoadedHomeList {
	static disableToggleWhenUnavailable = true;
}

export class HomeCategoryList extends LoadedHomeList {
	static disableToggleWhenUnavailable = true;
}

export class HomePageList extends LoadedHomeList {
	static unlockToggleWhenPopulated = true;
	static disableToggleWhenUnavailable = true;
}

export class DirectoryList extends LoadedHomeList {
	static unlockToggleWhenPopulated = true;
}

export class IngressList extends LoadedHomeList {
	static unlockToggleWhenPopulated = true;
}

export class ToolReportList extends BaseList {
	constructor(attributes) {
		super(attributes);
		this._listToggle = _listToggle(this.component, this.name);
		this.storageKey = `home-report-filters:${this.component.elt.dataset.reportUser}`;
		const saved = localStore.getJSON(this.storageKey);
		this.filters = new Set(
			Array.isArray(saved) &&
				saved.every((value) => REPORT_FILTERS.includes(value))
				? saved
				: ["active", "answers"],
		);
		this._click = this._click.bind(this);
		this._deleteMessage = "";
	}

	init() {
		this.component.elt.addEventListener("click", this._click);
	}

	get reportItems() {
		return Array.from(
			this.target.querySelectorAll("li[lp-entity][data-kind='report']"),
		);
	}

	get itemCount() {
		return this.reportItems.length;
	}

	get isPaginated() {
		return Boolean(
			this.target.querySelector?.(
				"[lp-control='next'], [lp-control='previous']",
			),
		);
	}

	created(response) {
		super.created(response);
		const items =
			response.html?.querySelectorAll("li[lp-entity][data-kind='report']") ||
			[];
		for (const item of items) this.filters.add(reportCategory(item.dataset));
		if (items.length) localStore.setJSON(this.storageKey, [...this.filters]);
	}

	_click(event) {
		const filter = event.target.closest("[data-role='report-filter']");
		if (filter && this.target.contains(filter)) {
			const value = filter.dataset.filter;
			if (this.filters.has(value)) this.filters.delete(value);
			else this.filters.add(value);
			localStore.setJSON(this.storageKey, [...this.filters]);
			void withTransition(() => this._renderFilters(), {
				label: "reports:filter",
			});
		}
		const clear = event.target.closest("[data-role='delete-executed-reports']");
		if (clear && this.target.contains(clear)) void this._openDelete(clear);
	}

	_renderFilters() {
		const counts = { active: 0, executed: 0, answers: 0 };
		let visible = 0;
		for (const item of this.reportItems) {
			const category = reportCategory(item.dataset);
			counts[category]++;
			item.hidden = !this.filters.has(category);
			if (!item.hidden) visible++;
		}
		for (const button of this.target.querySelectorAll(
			"[data-role='report-filter']",
		)) {
			const selected = this.filters.has(button.dataset.filter).toString();
			button.dataset.active = selected;
			button.setAttribute("aria-pressed", selected);
			button.querySelector("[data-role='report-count']").textContent =
				counts[button.dataset.filter];
		}
		const paginated = this.isPaginated;
		const empty = this.target.querySelector("[data-role='report-empty']");
		if (empty) {
			empty.hidden = visible > 0;
			const suffix = paginated ? " on this page." : ".";
			empty.textContent = !this.filters.size
				? "Select a report type to show."
				: this.filters.size === 1
					? `${
							{
								active: "No active proposals",
								executed: "No executed proposals",
								answers: "No answers",
							}[[...this.filters][0]]
						}${suffix}`
					: `No reports match the selected types${suffix}`;
		}
		const clear = this.target.querySelector(
			"[data-role='delete-executed-reports']",
		);
		if (clear) {
			clear.hidden = !(
				this.filters.size === 1 &&
				this.filters.has("executed") &&
				counts.executed > 0
			);
			clear.disabled = Boolean(this._deleting);
			const clearLabel = clear.querySelector?.(
				"[data-role='delete-executed-label']",
			);
			if (clearLabel) {
				clearLabel.textContent = paginated
					? "Delete executed proposals on this page"
					: "Delete all executed proposals";
			}
		}
		const result = this.target.querySelector(
			"[data-role='report-delete-result']",
		);
		if (result) {
			result.textContent = this._deleteMessage;
			result.hidden = !this._deleteMessage;
		}
	}

	postreconcile() {
		const created = this._created;
		this._created = [];
		super.postreconcile();
		if (created.length) {
			this.target
				.querySelector("[data-role='report-items']")
				?.prepend(...created);
			this.view.addFlash(...created);
		}
		this.target.dataset.visible = Boolean(
			this.visible || this.component.active === this,
		).toString();
		this._renderFilters();
		void this.view
			.ensureDeferredOperations?.()
			.then((manager) => manager?.scan(this.target));
		_syncEmptyCount(this._listToggle, this.name, this.itemCount === 0);
		if (this.itemCount > 0 && this._listToggle) {
			this._listToggle.classList.remove("opacity-50", "pointer-events-none");
		}
		this.target.setAttribute("loaded", "");
	}

	async _openDelete(trigger) {
		if (this._openingDelete || this._deleting || this._deleteModal?.modal)
			return;
		if (this.filters.size !== 1 || !this.filters.has("executed")) return;
		if (!this.view.online) {
			this._deleteMessage = "Connect to the server to delete reports.";
			this._renderFilters();
			return;
		}
		const keys = this.reportItems
			.filter((item) => reportCategory(item.dataset) === "executed")
			.map((item) => item.dataset.key);
		if (!keys.length) return;
		const element = this.target
			.querySelector("[data-role='report-delete-template']")
			?.content.querySelector("#modal")
			?.cloneNode(true);
		if (!element) return;
		this._openingDelete = true;
		try {
			const { Modal } = await import("../../shared/modal.ts");
			if (this._destroyed) return;
			this._deleteModal?.destroy();
			const modal = new Modal(this.view, trigger);
			this._deleteModal = modal;
			const content = element.querySelector("#modal-content");
			content.setAttribute("role", "dialog");
			content.setAttribute("aria-modal", "true");
			content.setAttribute("aria-labelledby", "report-delete-title");
			const noun = keys.length === 1 ? "proposal" : "proposals";
			element.querySelector(
				"[data-role='report-delete-description']",
			).textContent =
				`Delete ${keys.length} executed ${noun}? Their reports, undo history, and report-only uploads will be deleted. Pages, tasks, and other workspace changes will remain.`;
			const confirm = element.querySelector(
				"[data-role='confirm-delete-reports']",
			);
			confirm.querySelector("[data-role='text']").textContent =
				`Delete ${keys.length} ${noun}`;
			confirm.addEventListener("click", () => {
				void this._deleteExecuted(keys, trigger.dataset.route, modal);
			});
			await modal.attach(element);
			confirm.focus();
		} finally {
			this._openingDelete = false;
		}
	}

	async _deleteExecuted(keys, route, modal) {
		if (this._deleting) return;
		this._deleting = true;
		const confirm = modal.modal.querySelector(
			"[data-role='confirm-delete-reports']",
		);
		const error = modal.modal.querySelector(
			"[data-role='report-delete-error']",
		);
		const spinner = confirm.querySelector("#spinner");
		confirm.disabled = true;
		spinner.dataset.visible = "true";
		error.hidden = true;
		this._renderFilters();
		try {
			const { request } = await import("../../shared/request.ts");
			const response = await request.delete(route, { keys });
			if (!response?.ok)
				throw new Error("Reports could not be deleted. Please try again.");
			const deleted = new Set(response.deleted || []);
			const skipped = response.skipped?.length || 0;
			const failed = response.failed?.length || 0;
			this._deleteMessage = [
				skipped ? `${skipped} no longer eligible or already deleted.` : "",
				failed ? `${failed} could not be deleted. Please try again.` : "",
			]
				.filter(Boolean)
				.join(" ");
			await modal.remove();
			if (this._destroyed) return;
			await withTransition(
				() => {
					for (const item of this.reportItems)
						if (deleted.has(item.dataset.key)) item.remove();
					this.postreconcile();
				},
				{ label: "reports:delete-executed" },
			);
			await this.view._refreshHomeWidget(this.component, this);
		} catch {
			this._deleteMessage = "Reports could not be deleted. Please try again.";
			if (modal.modal) {
				error.textContent = this._deleteMessage;
				error.hidden = false;
				confirm.disabled = false;
			}
		} finally {
			spinner.dataset.visible = "false";
			this._deleting = false;
			if (!this._destroyed) this._renderFilters();
		}
	}

	destroy() {
		this._destroyed = true;
		this.component.elt.removeEventListener("click", this._click);
		this._deleteModal?.destroy();
	}
}

export class StarredList extends BaseList {
	constructor(attributes) {
		super(attributes);
		this._listToggle = _listToggle(this.component, this.name);
	}

	get countElt() {
		return this.component.elt.querySelector("[data-role='starred-count']");
	}

	postreconcile() {
		super.postreconcile();
		this.countElt.textContent = this.itemCount;
		this._listToggle.classList.toggle("opacity-50", this.itemCount === 0);
		this._listToggle.classList.toggle(
			"pointer-events-none",
			this.itemCount === 0,
		);
		this.target.setAttribute("loaded", "");
	}
}
