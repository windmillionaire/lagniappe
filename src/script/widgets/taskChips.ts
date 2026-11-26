import type { ComboboxOption } from "../elements/combobox/combobox.ts";
import { isFacetOption } from "../elements/combobox/facets.ts";
import { DueDate } from "../elements/dueDate.ts";
import { SectionToggle } from "../elements/sectionToggle.ts";
import { type TaskAsset, TaskUpload } from "../elements/taskUpload.ts";
import { STYLES } from "../generated/styles.mjs";
import { setIcon } from "../shared/icons.ts";
import { request } from "../shared/index.ts";
import { withTransition } from "../shared/transitions.ts";
import type { RequestResult } from "../types/api";
import type Core from "../views/base/core.ts";
import type { Task } from "../views/base/task.ts";

export type TaskChipField =
	| "project"
	| "form"
	| "assigned_to"
	| "schedule"
	| "description"
	| "files";

type ComboboxSelectionDetail = {
	name?: string;
	options?: Record<string, ComboboxOption & { form?: ComboboxOption }>;
};

type AssetsChangedDetail = {
	assets: Record<string, TaskAsset>;
	action: "upload" | "delete";
};

type ActiveChipSession = {
	field: TaskChipField;
	drawer: HTMLElement;
	destroy: () => void;
};

type TaskChipView = Pick<Core, "getComponent">;

function parseOption(
	raw?: string,
): (ComboboxOption & { index?: string }) | null {
	if (!raw) return null;
	try {
		const parsed: unknown = JSON.parse(raw);
		const candidate = Array.isArray(parsed) ? parsed[0] : parsed;
		return isFacetOption(candidate) && Object.keys(candidate).length > 0
			? candidate
			: null;
	} catch {
		return null;
	}
}

export function setTaskTrayOpen(taskRow: HTMLElement, open: boolean) {
	const chips = taskRow.querySelector<HTMLElement>("[data-role='task-chips']");
	if (!chips) return;
	chips.dataset.trayOpen = open ? "true" : "false";
	const toggle = taskRow.querySelector<HTMLButtonElement>(
		"[data-role='chip-tray-toggle']",
	);
	if (!toggle) return;
	toggle.dataset.active = open ? "true" : "false";
	toggle.setAttribute("aria-expanded", open ? "true" : "false");
	const label = open ? "Hide task options" : "Add task details";
	toggle.setAttribute("aria-label", label);
	toggle.title = label;
	const icon = toggle.querySelector<HTMLElement>(".icon");
	if (icon) {
		setIcon(icon, open ? "minus" : "plus");
	}
}

function setChipHeaderControls(taskRow: HTMLElement, chipOpen: boolean) {
	const toggle = taskRow.querySelector<HTMLElement>(
		"[data-role='chip-tray-toggle']",
	);
	const closeBtn = taskRow.querySelector<HTMLElement>(
		"[data-role='chip-close']",
	);
	if (chipOpen) {
		taskRow.dataset.chipOpen = "true";
		const hasOpenWidget =
			Boolean(taskRow.dataset.open) && taskRow.dataset.open !== "false";
		if (!hasOpenWidget) {
			if (toggle) toggle.dataset.visible = "false";
			if (closeBtn) closeBtn.dataset.visible = "true";
		}
	} else {
		delete taskRow.dataset.chipOpen;
		if (toggle) toggle.dataset.visible = "true";
		if (closeBtn) closeBtn.dataset.visible = "false";
	}
}

export async function applyTaskChipUpdate(
	task: Task,
	response: RequestResult,
	options: {
		chipField?: string;
		openForm?: boolean;
		formChanged?: boolean;
		keepTrayOpen?: boolean;
	} = {},
) {
	const html = response.html || null;
	const update = html?.querySelector<HTMLElement>(`[id='${task.name}']`);
	if (!update) return;

	const prevTrayOpen =
		task.elt
			.querySelector<HTMLElement>("[data-role='task-chips']")
			?.getAttribute("data-tray-open") === "true";
	const prevFormUnsaved = Boolean(task.widgets.TaskForm?.unsavedState);
	const hadForm = Boolean(
		task.elt.querySelector(":scope > [data-widget='TaskForm']"),
	);
	const nextForm = update.querySelector<HTMLElement>(
		":scope > [data-widget='TaskForm']",
	);
	const formMutated = Boolean(
		options.formChanged ||
			options.chipField === "form" ||
			hadForm !== Boolean(nextForm),
	);

	Object.assign(task.elt.dataset, {
		...update.dataset,
		open: task.elt.dataset.open,
	});
	task._replaceNav(update);

	if (prevTrayOpen || options.keepTrayOpen) {
		setTaskTrayOpen(task.elt, true);
	}

	if (prevFormUnsaved && !formMutated) {
		const saveToggle = task.elt.querySelector<HTMLElement>(
			"[data-role='save-toggle']",
		);
		if (saveToggle) {
			saveToggle.dataset.saved = "false";
			saveToggle.dataset.visible = "true";
		}
	}

	if (task.activeWidget) {
		task.nav?.reconcile(task.activeWidget.name, task.name);
	}

	if (formMutated) {
		const existingFormElt = task.elt.querySelector<HTMLElement>(
			":scope > [data-widget='TaskForm']",
		);
		const wasFormActive = task.active?.name === "TaskForm";
		if (task.widgets.TaskForm) {
			task.widgets.TaskForm.destroy?.();
			delete task.widgets.TaskForm;
		}
		existingFormElt?.remove();
		if (wasFormActive) {
			task.active = null;
			task.elt.dataset.open = "false";
			task.nav?.reconcile(null, task.name);
		}
		if (nextForm) {
			task.elt.append(nextForm);
			if (options.openForm || wasFormActive) {
				const activated = await task.activate("TaskForm");
				await task.prepareRender(activated);
				await withTransition(
					() => {
						if (task._destroyed) return;
						task.render(activated);
					},
					{ label: `${task.name}:open-attached-form` },
				);
			}
		}
	}
}

export class TaskChipController {
	declare view: TaskChipView;
	declare sessions: Map<HTMLLIElement, ActiveChipSession>;

	constructor(view: TaskChipView) {
		this.view = view;
		this.sessions = new Map();
	}

	hasOpenEditor(taskRow: HTMLLIElement | null): boolean {
		if (!taskRow) return false;
		if (this.sessions.has(taskRow)) return true;
		return Boolean(taskRow.querySelector("[data-role='rename-form']"));
	}

	toggleTray(taskRow: HTMLLIElement, force?: boolean) {
		if (taskRow.dataset.canEditChips !== "true") return;
		const chips = taskRow.querySelector<HTMLElement>(
			"[data-role='task-chips']",
		);
		if (!chips) return;
		const currentlyOpen = chips.dataset.trayOpen === "true";
		const nextOpen = force ?? !currentlyOpen;
		if (!nextOpen) {
			this.closeChip(taskRow);
		}
		setTaskTrayOpen(taskRow, nextOpen);
	}

	closeChip(taskRow: HTMLLIElement) {
		document.dispatchEvent(new CustomEvent("lp:close-date-picker"));
		const existing = this.sessions.get(taskRow);
		if (existing) {
			existing.destroy();
			this.sessions.delete(taskRow);
		}
		const drawer = taskRow.querySelector<HTMLElement>(
			":scope > [data-role='chip-drawer']",
		);
		if (drawer) {
			drawer.dataset.visible = "false";
			drawer.removeAttribute("data-chip-field");
			drawer.replaceChildren();
		}
		setChipHeaderControls(taskRow, false);
		taskRow
			.querySelectorAll<HTMLElement>("[data-chip][data-editing='true']")
			.forEach((chip) => {
				delete chip.dataset.editing;
			});
	}

	closeAll() {
		for (const taskRow of Array.from(this.sessions.keys())) {
			this.closeChip(taskRow);
		}
	}

	async openChip(taskRow: HTMLLIElement, field: TaskChipField) {
		if (taskRow.dataset.canEditChips !== "true") return;
		const existing = this.sessions.get(taskRow);
		if (existing?.field === field) {
			this.closeChip(taskRow);
			return;
		}
		this.closeChip(taskRow);

		const drawer = taskRow.querySelector<HTMLElement>(
			":scope > [data-role='chip-drawer']",
		);
		const chips = taskRow.querySelector<HTMLElement>(
			"[data-role='task-chips']",
		);
		if (!drawer || !chips) return;

		setTaskTrayOpen(taskRow, true);
		setChipHeaderControls(taskRow, true);
		this._markEditingChips(taskRow, field);
		drawer.dataset.chipField = field;
		drawer.dataset.visible = "true";

		const onKeydown = (e: KeyboardEvent) => {
			if (e.key !== "Escape") return;
			// Let an open combobox dropdown consume Escape first before closing the drawer.
			if (drawer.querySelector("[role='listbox'][data-visible='true']")) return;
			e.preventDefault();
			e.stopPropagation();
			this.closeChip(taskRow);
		};
		drawer.addEventListener("keydown", onKeydown);

		let cleanupInner: (() => void) | null = null;
		const destroy = () => {
			drawer.removeEventListener("keydown", onKeydown);
			cleanupInner?.();
		};
		this.sessions.set(taskRow, { field, drawer, destroy });

		if (field === "project" || field === "form" || field === "assigned_to") {
			cleanupInner = this._mountComboboxDrawer(taskRow, chips, drawer, field);
		} else if (field === "schedule") {
			cleanupInner = this._mountScheduleDrawer(taskRow, chips, drawer);
		} else if (field === "description") {
			cleanupInner = this._mountDescriptionDrawer(taskRow, drawer);
		} else if (field === "files") {
			cleanupInner = await this._mountFilesDrawer(taskRow, chips, drawer);
		}
	}

	_markEditingChips(taskRow: HTMLLIElement, field: TaskChipField) {
		taskRow
			.querySelectorAll<HTMLElement>(`[data-chip='${field}']`)
			.forEach((chip) => {
				chip.dataset.editing = "true";
			});
	}

	_drawerErrorElement() {
		const error = document.createElement("p");
		error.className = STYLES.message;
		error.dataset.kind = "error";
		error.dataset.role = "drawer-error";
		error.dataset.visible = "false";
		return error;
	}

	_showDrawerError(drawer: HTMLElement, message: string) {
		const error = drawer.querySelector<HTMLElement>(
			"[data-role='drawer-error']",
		);
		if (!error) return;
		error.textContent = message;
		error.dataset.visible = message ? "true" : "false";
	}

	_mountComboboxDrawer(
		taskRow: HTMLLIElement,
		chips: HTMLElement,
		drawer: HTMLElement,
		field: "project" | "form" | "assigned_to",
	) {
		const config = {
			project: {
				title: "Project Tracking",
				buttonTitle: "Link a project...",
				index: "project",
				kind: "project",
				name: "project",
				placeholder: "link a project...",
				creatable: true,
				preloadRaw: chips.dataset.projectPreload,
			},
			form: {
				title:
					taskRow.dataset.hasForm === "true" ? "Change Form" : "Attach Form",
				buttonTitle: "Attach a form...",
				index: "form",
				kind: "form",
				name: "form",
				placeholder: "attach a form...",
				creatable: true,
				formType: "task",
				preloadRaw: chips.dataset.formPreload,
			},
			assigned_to: {
				title: "Assigned To",
				buttonTitle: "Assign to...",
				index: "user",
				kind: "user",
				name: "assigned_to",
				placeholder: "assign to...",
				creatable: false,
				permission: "assign",
				preloadRaw: chips.dataset.assigneePreload,
			},
		}[field];

		const errorEl = this._drawerErrorElement();

		const container = document.createElement("div");
		container.dataset.role = `${field}-chip-select`;
		container.dataset.kind = config.kind;

		const button = document.createElement("button");
		button.type = "button";
		button.setAttribute("lp-select", "");
		button.className = STYLES.select.button;
		button.dataset.index = config.index;
		button.dataset.kind = config.kind;
		button.dataset.name = config.name;
		button.dataset.title = config.buttonTitle;
		button.dataset.placeholder = config.placeholder;
		if (config.preloadRaw) {
			button.dataset.preload = config.preloadRaw;
		}
		if (config.creatable) button.dataset.creatable = "true";
		if ("formType" in config && config.formType) {
			button.dataset.formType = config.formType;
		}
		if ("permission" in config && config.permission) {
			button.dataset.permission = config.permission;
		}
		container.appendChild(button);

		drawer.replaceChildren(errorEl, container);

		const facet = SectionToggle.facet({ readonly: false }, button);
		facet.init();

		const baseClear = facet.clear.bind(facet);
		facet.clear = () => {
			if (facet.open) {
				facet.open = false;
				facet._reconcile();
				return;
			}
			baseClear();
			const data = new FormData();
			data.append("active", "TaskChip");
			data.append("chip_field", field);
			if (field === "project") {
				data.append("project", "");
				data.append("model", "");
			} else {
				data.append(config.name, "");
			}
			void this._saveChip(taskRow, drawer, data, {
				chipField: field,
				formChanged: field === "form",
			});
		};

		const onUpdated = (e: Event) => {
			const detail =
				e instanceof CustomEvent ? (e.detail as ComboboxSelectionDetail) : null;
			const entries = detail?.options ? Object.entries(detail.options) : [];
			const [selectedId, selectedOption] = entries[0] ?? ["", undefined];

			const data = new FormData();
			data.append("active", "TaskChip");
			data.append("chip_field", field);
			data.append(config.name, selectedId || "");

			let openForm = false;
			let formChanged = field === "form";

			if (field === "form" && selectedId) {
				openForm = true;
			} else if (
				field === "project" &&
				selectedOption?.form?.id &&
				chips.dataset.canForm === "true"
			) {
				const currentForm = parseOption(chips.dataset.formPreload);
				if (currentForm?.id !== selectedOption.form.id) {
					data.append("form", selectedOption.form.id);
					openForm = true;
					formChanged = true;
				}
			}

			void this._saveChip(taskRow, drawer, data, {
				chipField: field,
				openForm,
				formChanged,
			});
		};

		facet.select?.element.addEventListener("updated", onUpdated);

		return () => {
			facet.select?.element.removeEventListener("updated", onUpdated);
			facet.destroy();
		};
	}

	_mountScheduleDrawer(
		taskRow: HTMLLIElement,
		chips: HTMLElement,
		drawer: HTMLElement,
	) {
		const errorEl = this._drawerErrorElement();

		const form = document.createElement("form");
		form.dataset.role = "schedule-chip-form";
		form.dataset.kind = "task";
		form.className = "flex flex-col gap-3";

		const anchor = document.createElement("button");
		anchor.type = "button";
		anchor.hidden = true;
		anchor.dataset.action = "schedule";
		anchor.dataset.role = "date-select";
		anchor.dataset.title = "Schedule";
		anchor.dataset.aiEnabled = chips.dataset.aiEnabled || "false";
		if (chips.dataset.schedule)
			anchor.dataset.schedule = chips.dataset.schedule;
		if (chips.dataset.dueDate) anchor.dataset.dueDate = chips.dataset.dueDate;
		form.appendChild(anchor);

		const saveBtn = document.createElement("button");
		saveBtn.type = "submit";
		saveBtn.dataset.role = "save-schedule";
		saveBtn.className = STYLES.button.submit;
		saveBtn.textContent = "Save Schedule";

		drawer.replaceChildren(errorEl, form);

		const dueDate = new DueDate(anchor, { readonly: false, inline: true });
		dueDate.init();
		dueDate.open = true;
		if (dueDate.container) {
			dueDate.container.dataset.visible = "true";
			dueDate.container.classList.remove("mt-2");
		}
		form.appendChild(saveBtn);

		const onSubmit = (e: Event) => {
			e.preventDefault();
			e.stopPropagation();
			const data = new FormData(form);
			data.append("active", "TaskChip");
			data.append("chip_field", "schedule");
			void this._saveChip(taskRow, drawer, data, { chipField: "schedule" });
		};
		form.addEventListener("submit", onSubmit);

		const dueInput = form.querySelector<HTMLInputElement>(
			"input[name='due-date']",
		);
		dueInput?.focus({ preventScroll: true });

		return () => {
			form.removeEventListener("submit", onSubmit);
		};
	}

	_mountDescriptionDrawer(taskRow: HTMLLIElement, drawer: HTMLElement) {
		const current = taskRow.dataset.description || "";
		const errorEl = this._drawerErrorElement();

		const form = document.createElement("form");
		form.dataset.role = "description-chip-form";
		form.dataset.kind = "task";
		form.className = "flex flex-col gap-3";

		const textarea = document.createElement("textarea");
		textarea.name = "description";
		textarea.className = `${STYLES.input} min-h-20 resize-y`;
		textarea.placeholder = "describe this task...";
		textarea.value = current;
		form.appendChild(textarea);

		const saveBtn = document.createElement("button");
		saveBtn.type = "submit";
		saveBtn.dataset.role = "save-description";
		saveBtn.className = STYLES.button.submit;
		saveBtn.textContent = "Save Description";
		form.appendChild(saveBtn);

		drawer.replaceChildren(errorEl, form);

		const submitDescription = () => {
			const data = new FormData();
			data.append("active", "TaskChip");
			data.append("chip_field", "description");
			data.append("description", textarea.value);
			void this._saveChip(taskRow, drawer, data, { chipField: "description" });
		};

		const onSubmit = (e: Event) => {
			e.preventDefault();
			e.stopPropagation();
			submitDescription();
		};
		const onKeydown = (e: KeyboardEvent) => {
			if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
				e.preventDefault();
				submitDescription();
			}
		};
		form.addEventListener("submit", onSubmit);
		textarea.addEventListener("keydown", onKeydown);
		textarea.focus({ preventScroll: true });

		return () => {
			form.removeEventListener("submit", onSubmit);
			textarea.removeEventListener("keydown", onKeydown);
		};
	}

	async _mountFilesDrawer(
		taskRow: HTMLLIElement,
		chips: HTMLElement,
		drawer: HTMLElement,
	) {
		const errorEl = this._drawerErrorElement();

		const host = document.createElement("div");
		host.dataset.role = "files-chip-host";
		host.dataset.kind = "file";
		host.className = "flex flex-col gap-2";

		const anchor = document.createElement("button");
		anchor.type = "button";
		anchor.hidden = true;
		anchor.dataset.action = "uploadFile";
		anchor.dataset.role = "file-select";
		anchor.dataset.title = "Attach File/Photo";
		anchor.dataset.kind = "file";
		anchor.dataset.preload = chips.dataset.filesPreload || "{}";
		host.appendChild(anchor);

		drawer.replaceChildren(errorEl, host);

		const upload = new TaskUpload(anchor, {
			key: taskRow.dataset.key,
			readonly: false,
		});
		await upload.init();
		upload.target.dataset.visible = "true";
		upload.target.classList.remove("mt-2");

		const onAssetsChanged = (e: Event) => {
			const detail =
				e instanceof CustomEvent ? (e.detail as AssetsChangedDetail) : null;
			if (!detail) return;
			const liveChips = taskRow.querySelector<HTMLElement>(
				"[data-role='task-chips']",
			);
			if (liveChips) {
				liveChips.dataset.filesPreload = JSON.stringify(detail.assets || {});
			}
			if (detail.action === "upload") {
				const data = new FormData();
				data.append("active", "TaskChip");
				data.append("chip_field", "files");
				data.append("assets", JSON.stringify(detail.assets || {}));
				void this._saveChip(taskRow, drawer, data, {
					chipField: "files",
					keepDrawerOpen: true,
				}).then((saved) => {
					if (!saved) return;
					const updatedPreload = taskRow.querySelector<HTMLElement>(
						"[data-role='task-chips']",
					)?.dataset.filesPreload;
					if (!updatedPreload) return;
					try {
						upload.assets = JSON.parse(updatedPreload) as Record<
							string,
							TaskAsset
						>;
						upload.renderAssets();
					} catch {
						// Ignore malformed preload
					}
				});
			}
		};

		upload.target.addEventListener("task-assets-changed", onAssetsChanged);

		return () => {
			upload.target.removeEventListener("task-assets-changed", onAssetsChanged);
			upload.destroy();
		};
	}

	async _saveChip(
		taskRow: HTMLLIElement,
		drawer: HTMLElement,
		data: FormData,
		options: {
			chipField: TaskChipField;
			openForm?: boolean;
			formChanged?: boolean;
			keepDrawerOpen?: boolean;
		},
	) {
		const route = taskRow.dataset.route;
		const task = this.view.getComponent(taskRow) as Task | null;
		if (!route || !task) return false;

		this._showDrawerError(drawer, "");
		drawer.setAttribute("aria-busy", "true");
		const buttons = Array.from(
			drawer.querySelectorAll<HTMLButtonElement>("button"),
		);
		buttons.forEach((btn) => {
			btn.disabled = true;
		});

		const response = await request.put<RequestResult>(route, data);

		drawer.removeAttribute("aria-busy");
		if (!response?.ok) {
			buttons.forEach((btn) => {
				btn.disabled = false;
			});
			this._showDrawerError(
				drawer,
				response?.error || "Could not update task. Please try again.",
			);
			return false;
		}

		await applyTaskChipUpdate(task, response, {
			chipField: options.chipField,
			openForm: options.openForm,
			formChanged: options.formChanged,
			keepTrayOpen: true,
		});

		if (options.keepDrawerOpen) {
			buttons.forEach((btn) => {
				btn.disabled = false;
			});
			setChipHeaderControls(taskRow, true);
			this._markEditingChips(taskRow, options.chipField);
		} else {
			this.closeChip(taskRow);
		}
		return true;
	}

	startRename(taskRow: HTMLLIElement) {
		if (taskRow.dataset.canEditChips !== "true") return;
		const anchor = taskRow.querySelector<HTMLElement>("[data-menu-anchor]");
		const titleSpan = anchor?.querySelector<HTMLElement>("[data-role='title']");
		if (!anchor || !titleSpan) return;
		if (anchor.querySelector("[data-role='rename-form']")) return;

		const originalName =
			taskRow.dataset.name || titleSpan.textContent?.trim() || "";
		const menuWrap = anchor.querySelector<HTMLElement>("[lp-menu='title']");
		titleSpan.hidden = true;
		if (menuWrap) menuWrap.hidden = true;

		const form = document.createElement("form");
		form.dataset.role = "rename-form";
		form.className = STYLES.task.rename.form;

		const input = document.createElement("input");
		input.type = "text";
		input.name = "name";
		input.value = originalName;
		input.setAttribute("aria-label", "Task name");
		input.className = STYLES.task.rename.input;
		form.appendChild(input);

		anchor.appendChild(form);
		input.focus({ preventScroll: true });
		input.select();

		let finished = false;
		const restore = () => {
			form.remove();
			titleSpan.hidden = false;
			if (menuWrap) menuWrap.hidden = false;
		};

		const commit = async () => {
			if (finished) return;
			finished = true;
			const nextName = input.value.trim();
			if (!nextName || nextName === originalName) {
				restore();
				return;
			}
			const route = taskRow.dataset.route;
			const task = this.view.getComponent(taskRow) as Task | null;
			if (!route || !task) {
				restore();
				return;
			}
			input.disabled = true;
			const data = new FormData();
			data.append("active", "TaskChip");
			data.append("chip_field", "name");
			data.append("name", nextName);

			const response = await request.put<RequestResult>(route, data);
			if (!response?.ok) {
				finished = false;
				input.disabled = false;
				const error = taskRow.querySelector<HTMLElement>("[data-role='error']");
				if (error) {
					error.textContent = response?.error || "Could not rename task.";
					error.dataset.visible = "true";
				}
				input.focus({ preventScroll: true });
				return;
			}
			await applyTaskChipUpdate(task, response, { chipField: "name" });
		};

		form.addEventListener("submit", (e) => {
			e.preventDefault();
			e.stopPropagation();
			void commit();
		});
		input.addEventListener("keydown", (e) => {
			if (e.key !== "Escape") return;
			e.preventDefault();
			e.stopPropagation();
			finished = true;
			restore();
		});
		input.addEventListener("blur", () => {
			void commit();
		});
	}
}
