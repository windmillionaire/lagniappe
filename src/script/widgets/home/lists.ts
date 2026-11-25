import {
	BaseList,
	type ListAttributes,
	listHtml,
} from "../../elements/base/baseList.ts";
import type { Modal } from "../../shared/modal.ts";
import { localStore } from "../../shared/storage.ts";
import { withTransition } from "../../shared/transitions.ts";
import type Core from "../../views/base/core.ts";

type HomeListAttributes = ListAttributes & {
	component: ListAttributes["component"] & { elt: HTMLElement; name: string };
};

type ReportListAttributes = HomeListAttributes & {
	view: Pick<Core, "addFlash"> &
		Partial<Pick<Core, "ensureDeferredOperations">> &
		NonNullable<ConstructorParameters<typeof Modal>[0]> & {
			online: boolean;
			_refreshHomeWidget(
				component: HomeListAttributes["component"],
				widget: ToolReportList,
			): Promise<boolean>;
		};
};

interface DeleteReportsResult {
	deleted: string[];
	skipped: string[];
	failed: string[];
}

const REPORT_FILTERS = ["active", "executed", "answers"] as const;
type ReportFilter = (typeof REPORT_FILTERS)[number];

function isReportFilter(value: unknown): value is ReportFilter {
	return REPORT_FILTERS.some((filter) => filter === value);
}

function reportCategory(report: DOMStringMap): ReportFilter {
	if (report.outputKind === "answer") return "answers";
	return report.outputKind === "proposal" && report.status === "complete"
		? "executed"
		: "active";
}

function _listToggle(
	component: HomeListAttributes["component"],
	widgetName: string,
) {
	return component.elt.querySelector<HTMLButtonElement>(
		`[lp-show='${component.name}:${widgetName}'][data-toggle]`,
	);
}

function _syncEmptyCount(
	toggle: HTMLButtonElement | null,
	widgetName: string,
	empty: boolean,
) {
	const indicator = toggle?.querySelector<HTMLElement>(
		`[data-indicator='${widgetName}']`,
	);
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

	declare component: HomeListAttributes["component"];
	declare _listToggle: HTMLButtonElement | null;

	constructor(attributes: HomeListAttributes) {
		super(attributes);
		this._listToggle = _listToggle(this.component, this.name);
	}

	_syncUnavailableToggle() {
		const ListClass = this.constructor as typeof LoadedHomeList;
		if (!ListClass.disableToggleWhenUnavailable || !this._listToggle) {
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
		const ListClass = this.constructor as typeof LoadedHomeList;
		if (
			ListClass.unlockToggleWhenPopulated &&
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
	declare component: ReportListAttributes["component"];
	declare view: ReportListAttributes["view"];
	declare _listToggle: HTMLButtonElement | null;
	declare storageKey: string;
	declare filters: Set<ReportFilter>;
	declare _deleteMessage: string;
	declare _deleteModal?: Modal;
	declare _openingDelete?: boolean;
	declare _deleting?: boolean;
	declare _destroyed?: boolean;

	constructor(attributes: ReportListAttributes) {
		super(attributes);
		this._listToggle = _listToggle(this.component, this.name);
		this.storageKey = `home-report-filters:${this.component.elt.dataset.reportUser}`;
		const saved = localStore.getJSON(this.storageKey);
		this.filters = new Set<ReportFilter>(
			Array.isArray(saved) && saved.every(isReportFilter)
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
			this.target.querySelectorAll<HTMLLIElement>(
				"li[lp-entity][data-kind='report']",
			),
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

	created(response: unknown) {
		super.created(response);
		const items =
			listHtml(response)?.querySelectorAll<HTMLLIElement>(
				"li[lp-entity][data-kind='report']",
			) || [];
		for (const item of items) this.filters.add(reportCategory(item.dataset));
		if (items.length) localStore.setJSON(this.storageKey, [...this.filters]);
	}

	_click(event: Event) {
		if (!(event.target instanceof Element)) return;
		const filter = event.target.closest<HTMLElement>(
			"[data-role='report-filter']",
		);
		const value = filter?.dataset.filter;
		if (filter && this.target.contains(filter) && isReportFilter(value)) {
			if (this.filters.has(value)) this.filters.delete(value);
			else this.filters.add(value);
			localStore.setJSON(this.storageKey, [...this.filters]);
			void withTransition(() => this._renderFilters(), {
				label: "reports:filter",
			});
		}
		const clear = event.target.closest<HTMLButtonElement>(
			"[data-role='delete-executed-reports']",
		);
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
		for (const button of this.target.querySelectorAll<HTMLButtonElement>(
			"[data-role='report-filter']",
		)) {
			const filter = button.dataset.filter;
			if (!isReportFilter(filter)) continue;
			const selected = this.filters.has(filter).toString();
			button.dataset.active = selected;
			button.setAttribute("aria-pressed", selected);
			const count = button.querySelector("[data-role='report-count']");
			if (count) count.textContent = String(counts[filter]);
		}
		const paginated = this.isPaginated;
		const empty = this.target.querySelector<HTMLElement>(
			"[data-role='report-empty']",
		);
		if (empty) {
			empty.hidden = visible > 0;
			const suffix = paginated ? " on this page." : ".";
			const [firstFilter] = this.filters;
			empty.textContent = !firstFilter
				? "Select a report type to show."
				: this.filters.size === 1
					? `${
							{
								active: "No active proposals",
								executed: "No executed proposals",
								answers: "No answers",
							}[firstFilter]
						}${suffix}`
					: `No reports match the selected types${suffix}`;
		}
		const clear = this.target.querySelector<HTMLButtonElement>(
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
		const result = this.target.querySelector<HTMLElement>(
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
			for (const item of created) this.view.addFlash(item);
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

	async _openDelete(trigger: HTMLButtonElement) {
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
			.map((item) => item.dataset.key)
			.filter((key): key is string => Boolean(key));
		const route = trigger.dataset.route;
		if (!keys.length || !route) return;
		const element = this.target
			.querySelector<HTMLTemplateElement>(
				"[data-role='report-delete-template']",
			)
			?.content.querySelector("#modal")
			?.cloneNode(true);
		if (!(element instanceof HTMLElement)) return;
		const content = element.querySelector("#modal-content");
		const description = element.querySelector(
			"[data-role='report-delete-description']",
		);
		const confirm = element.querySelector<HTMLButtonElement>(
			"[data-role='confirm-delete-reports']",
		);
		const confirmLabel = confirm?.querySelector("[data-role='text']");
		if (!content || !description || !confirm || !confirmLabel) return;
		this._openingDelete = true;
		try {
			const { Modal } = await import("../../shared/modal.ts");
			if (this._destroyed) return;
			this._deleteModal?.destroy();
			const modal = new Modal(this.view, trigger);
			this._deleteModal = modal;
			content.setAttribute("role", "dialog");
			content.setAttribute("aria-modal", "true");
			content.setAttribute("aria-labelledby", "report-delete-title");
			const noun = keys.length === 1 ? "proposal" : "proposals";
			description.textContent = `Delete ${keys.length} executed ${noun}? Their reports, undo history, and report-only uploads will be deleted. Pages, tasks, and other workspace changes will remain.`;
			confirmLabel.textContent = `Delete ${keys.length} ${noun}`;
			confirm.addEventListener("click", () => {
				void this._deleteExecuted(keys, route, modal);
			});
			await modal.attach(element);
			confirm.focus();
		} finally {
			this._openingDelete = false;
		}
	}

	async _deleteExecuted(
		keys: string[],
		route: string,
		modal: Pick<Modal, "modal" | "remove">,
	) {
		if (this._deleting) return;
		const confirm = modal.modal?.querySelector<HTMLButtonElement>(
			"[data-role='confirm-delete-reports']",
		);
		const error = modal.modal?.querySelector<HTMLElement>(
			"[data-role='report-delete-error']",
		);
		const spinner = confirm?.querySelector<HTMLElement>("#spinner");
		if (!confirm || !error || !spinner) return;
		this._deleting = true;
		confirm.disabled = true;
		spinner.dataset.visible = "true";
		error.hidden = true;
		this._renderFilters();
		try {
			const { request } = await import("../../shared/request.ts");
			const response = await request.delete<DeleteReportsResult>(route, {
				keys,
			});
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
					for (const item of this.reportItems) {
						const key = item.dataset.key;
						if (key && deleted.has(key)) item.remove();
					}
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
	declare component: HomeListAttributes["component"];
	declare _listToggle: HTMLButtonElement | null;

	constructor(attributes: HomeListAttributes) {
		super(attributes);
		this._listToggle = _listToggle(this.component, this.name);
	}

	get countElt() {
		return this.component.elt.querySelector("[data-role='starred-count']");
	}

	postreconcile() {
		super.postreconcile();
		const count = this.countElt;
		if (count) count.textContent = String(this.itemCount);
		this._listToggle?.classList.toggle("opacity-50", this.itemCount === 0);
		this._listToggle?.classList.toggle(
			"pointer-events-none",
			this.itemCount === 0,
		);
		this.target.setAttribute("loaded", "");
	}
}
