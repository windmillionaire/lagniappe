import { STYLES } from "../generated/styles.mjs";
import { setIcon } from "../shared/icons.ts";
import { withTransition } from "../shared/transitions.ts";
import { primitives, wrapDateInput } from "./primitives.ts";
import type { SectionToggle } from "./sectionToggle.ts";

function formatLocalIsoDate(date: Date) {
	const y = String(date.getFullYear()).padStart(4, "0");
	const m = String(date.getMonth() + 1).padStart(2, "0");
	const d = String(date.getDate()).padStart(2, "0");
	return `${y}-${m}-${d}`;
}

function todayIsoDate(now = new Date()) {
	return formatLocalIsoDate(now);
}

function addDaysIsoDate(days: number, now = new Date()) {
	return formatLocalIsoDate(
		new Date(now.getFullYear(), now.getMonth(), now.getDate() + days),
	);
}

interface RepeatDetails {
	description?: string | null;
	text?: string | null;
}

interface ScheduledDetails extends RepeatDetails {
	mode?: string | null;
	days?: (number | string)[] | null;
}

interface RecurringDetails {
	interval?: string | number | null;
	unit?: string | null;
}

export interface TaskSchedule {
	due?: string | null;
	start_date?: string | null;
	recurring?: RecurringDetails | null;
	scheduled?: ScheduledDetails | null;
	periodic?: RepeatDetails | null;
}

type DueGroup =
	| "dueDate"
	| "recurring"
	| "scheduled"
	| "weekly"
	| "monthly"
	| "yearly"
	| "periodic";
type RepeatGroup = "recurring" | "scheduled" | "periodic";

function isRecord(value: unknown): value is Record<string, unknown> {
	return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function optionalText(value: unknown): value is string | null | undefined {
	return value == null || typeof value === "string";
}

function isRepeatDetails(
	value: unknown,
): value is RepeatDetails | null | undefined {
	return (
		value == null ||
		(isRecord(value) &&
			optionalText(value.description) &&
			optionalText(value.text))
	);
}

function isSchedule(value: unknown): value is TaskSchedule {
	if (
		!isRecord(value) ||
		!optionalText(value.due) ||
		!optionalText(value.start_date)
	)
		return false;
	const { recurring, scheduled, periodic } = value;
	return (
		(recurring == null ||
			(isRecord(recurring) &&
				optionalText(recurring.unit) &&
				(optionalText(recurring.interval) ||
					typeof recurring.interval === "number"))) &&
		(scheduled == null ||
			(isRecord(scheduled) &&
				isRepeatDetails(scheduled) &&
				optionalText(scheduled.mode) &&
				(scheduled.days == null ||
					(Array.isArray(scheduled.days) &&
						scheduled.days.every(
							(day) => typeof day === "number" || typeof day === "string",
						))))) &&
		isRepeatDetails(periodic)
	);
}

function isRepeatGroup(group: string | undefined): group is RepeatGroup {
	return group === "recurring" || group === "scheduled" || group === "periodic";
}

function isScheduleGroup(
	group: string | undefined,
): group is "weekly" | "monthly" | "yearly" {
	return group === "weekly" || group === "monthly" || group === "yearly";
}

function segmentedOption(options: {
	type: "checkbox" | "radio";
	name: string;
	label: string;
	value?: string;
	checked?: boolean;
}) {
	const label = document.createElement("label");
	label.className = "lp-schedule-seg-option";
	const input = document.createElement("input");
	input.type = options.type;
	input.name = options.name;
	input.className = "lp-schedule-sr-input";
	if (options.value !== undefined) input.value = options.value;
	if (options.checked) input.checked = true;
	const text = document.createElement("span");
	text.textContent = options.label;
	label.append(input, text);
	return label;
}

function quickChip(options: {
	text: string;
	role: string;
	accent?: boolean;
	icon?: string;
}) {
	const button = document.createElement("button");
	button.type = "button";
	button.className = "lp-schedule-quick";
	button.dataset.role = options.role;
	if (options.accent) button.dataset.accent = "true";
	if (options.icon) {
		const icon = document.createElement("span");
		setIcon(icon, options.icon, "icon-xs");
		button.appendChild(icon);
	}
	const label = document.createElement("span");
	label.textContent = options.text;
	button.appendChild(label);
	return button;
}

export class DueDate {
	declare destroy?: never;
	declare widget?: { readonly?: boolean; inline?: boolean };
	declare button: HTMLButtonElement;
	declare action?: string;
	declare kind: "task";
	declare aiEnabled: boolean;
	declare schedule: TaskSchedule;
	declare container: HTMLDivElement | null;
	declare groups: Partial<Record<DueGroup, HTMLDivElement>>;
	declare toggles: Partial<Record<RepeatGroup, HTMLElement>>;
	declare noneButton: HTMLButtonElement | null;
	declare clearDueButton: HTMLButtonElement | null;
	declare error: HTMLDivElement | null;
	declare open: boolean;
	declare closed?: boolean;
	declare toggle?: SectionToggle;

	constructor(
		button: HTMLButtonElement,
		widget?: { readonly?: boolean; inline?: boolean },
	) {
		this.widget = widget;
		this.action = button.dataset.action;
		this.button = button;
		this.kind = "task";
		this.aiEnabled = this.button.dataset.aiEnabled !== "false";
		const schedule: unknown = JSON.parse(this.button.dataset.schedule ?? "{}");
		this.schedule = isSchedule(schedule) ? schedule : {};
		if (this.button.dataset.dueDate) {
			this.schedule.due = this.button.dataset.dueDate;
		}

		this.container = null;
		this.groups = {};
		this.toggles = {};
		this.noneButton = null;
		this.clearDueButton = null;
		this.error = null;
		this.open = false;

		this._input = this._input.bind(this);
		this._click = this._click.bind(this);
		this._change = this._change.bind(this);
	}

	init() {
		this.toggle?.display();
		if (this.toggle?.readonly || this.widget?.readonly) return;

		this.createOptionGroups();

		const { container } = this;
		if (!container) return;
		container.addEventListener("input", this._input);
		container.addEventListener("click", this._click);
		container.addEventListener("change", this._change);

		if (this.schedule.recurring) {
			container.appendChild(this.recurring);
		} else if (this.schedule.scheduled) {
			const scheduled = container.appendChild(this.scheduled);
			if (this.schedule.scheduled.mode === "weekly") {
				scheduled.appendChild(this.weekly);
			} else if (this.aiEnabled && this.schedule.scheduled.mode === "monthly") {
				scheduled.appendChild(this.monthly);
			} else if (this.aiEnabled && this.schedule.scheduled.mode === "yearly") {
				scheduled.appendChild(this.yearly);
			}
		} else if (this.aiEnabled && this.schedule.periodic) {
			container.appendChild(this.periodic);
		}
		this._syncNoneButton();
		this._syncClearDueButton();
	}

	_syncNoneButton() {
		if (!this.noneButton) return;
		const hasRepeat = Boolean(
			this.schedule.recurring ||
				this.schedule.scheduled ||
				this.schedule.periodic,
		);
		this.noneButton.dataset.active = hasRepeat ? "false" : "true";
		this.noneButton.setAttribute("aria-pressed", hasRepeat ? "false" : "true");
	}

	_syncClearDueButton() {
		if (!this.clearDueButton) return;
		const input = this.groups.dueDate?.querySelector<HTMLInputElement>(
			"input[name='due-date']",
		);
		const hasValue = Boolean(input?.value || this.schedule.due);
		this.clearDueButton.hidden = !hasValue;
	}

	_setDueInputValue(value: string) {
		const input = this.groups.dueDate?.querySelector<HTMLInputElement>(
			"input[name='due-date']",
		);
		if (input) input.value = value;
		this.schedule.due = value || null;
		this._syncClearDueButton();
	}

	_click(e: MouseEvent) {
		const role =
			e.target instanceof Element
				? e.target.closest<HTMLElement>("[data-role]")?.dataset.role
				: undefined;
		if (!role) return;

		switch (role) {
			case "today":
				this._setDueInputValue(todayIsoDate());
				break;
			case "tomorrow":
				this._setDueInputValue(addDaysIsoDate(1));
				break;
			case "next-week":
				this._setDueInputValue(addDaysIsoDate(7));
				break;
			case "remove-due-date":
				this._setDueInputValue("");
				break;
			case "repeat-none":
				[
					this.groups.recurring,
					this.groups.scheduled,
					this.groups.periodic,
				].forEach((group) => {
					this.clearGroup(group);
				});
				this._syncNoneButton();
				break;
		}
	}

	_input(e: Event) {
		const { target } = e;
		if (!(target instanceof HTMLInputElement)) return;
		if (target.name === "monthly-description") {
			if (this.schedule.scheduled)
				this.schedule.scheduled.description = target.value;
			return;
		} else if (target.name === "yearly-description") {
			if (this.schedule.scheduled)
				this.schedule.scheduled.description = target.value;
			return;
		} else if (target.name === "periodic-description") {
			if (this.schedule.periodic)
				this.schedule.periodic.description = target.value;
			return;
		} else if (target.name === "due-date") {
			this.schedule.due = target.value || null;
			this._syncClearDueButton();
			return;
		} else if (target.name === "interval") {
			this.schedule.recurring ??= {};
			this.schedule.recurring.interval = target.value;
			return;
		}
	}

	_change(e: Event) {
		const { target } = e;
		if (!(target instanceof HTMLInputElement) || !this.container) return;
		if (target.name === "due-date") {
			this.schedule.due = target.value || null;
			this._syncClearDueButton();
			return;
		}
		if (target.name === "recurring") {
			if (target.checked) {
				this.schedule.recurring ??= {};
				this.container.appendChild(this.recurring);
			} else {
				this.clearGroup(this.groups.recurring);
			}
			this._syncNoneButton();
			return;
		} else if (target.name === "unit") {
			this.schedule.recurring ??= {};
			this.schedule.recurring.unit = target.value;
			return;
		} else if (target.name === "scheduled") {
			if (target.checked) {
				this.schedule.scheduled ??= {};
				this.container.appendChild(this.scheduled);
			} else {
				this.clearGroup(this.groups.scheduled);
			}
			this._syncNoneButton();
			return;
		} else if (target.name === "schedule-type") {
			this.schedule.scheduled ??= {};
			this.schedule.scheduled.mode = target.value;
			if (!target.checked) {
				if (isScheduleGroup(target.value))
					this.clearGroup(this.groups[target.value]);
			} else if (target.value === "daily") {
				[this.groups.weekly, this.groups.monthly, this.groups.yearly].forEach(
					(group) => {
						this.clearGroup(group);
					},
				);
			} else if (target.value === "weekly") {
				this.groups.scheduled?.appendChild(this.weekly);
			} else if (this.aiEnabled && target.value === "monthly") {
				this.groups.scheduled?.appendChild(this.monthly);
			} else if (this.aiEnabled && target.value === "yearly") {
				this.groups.scheduled?.appendChild(this.yearly);
			}
			return;
		} else if (target.name.startsWith("weekly-day-")) {
			if (!this.schedule.scheduled) return;
			this.schedule.scheduled.days = Array.from(
				this.weekly.querySelectorAll<HTMLInputElement>("input:checked"),
			).map((input) => input.value);
			return;
		} else if (target.name === "periodic") {
			if (!this.aiEnabled) return;
			if (target.checked) {
				this.schedule.periodic ??= {};
				this.container.appendChild(this.periodic);
			} else {
				this.clearGroup(this.groups.periodic);
			}
			this._syncNoneButton();
			return;
		}
	}

	get active() {
		return Object.keys(this.schedule).length > 0;
	}

	showError(message: string) {
		if (!this.error) {
			this.error = primitives.error();
			this.error.classList.add("mb-2");
			this.container?.prepend(this.error);
		}
		this.error.textContent = message;
		this.error.dataset.visible = "true";
	}

	hideError() {
		if (this.error) this.error.dataset.visible = "false";
	}

	toggleVisibility() {
		this.open = !this.open;
		this._reconcile();
	}

	_reconcile() {
		if (this.closed) {
			const invalid = this.checkValidity();
			if (invalid) {
				this.showError(invalid);
				this.open = true;
				return;
			}
		}

		withTransition(() => {
			this.hideError();

			if (!this.open) {
				this.button.focus({ preventScroll: true });
			}
			this.toggle?.display();

			if (this.container)
				this.container.dataset.visible = this.open ? "true" : "false";
		});
	}

	checkValidity() {
		if (this.schedule.recurring) {
			this.schedule.recurring.interval ??= 1;
			this.schedule.recurring.unit ??= "day";
		}

		if (this.schedule.scheduled) {
			this.schedule.scheduled.mode ??= "daily";
			if (this.schedule.scheduled.mode === "weekly") {
				if (
					!this.schedule.scheduled.days ||
					this.schedule.scheduled.days.length === 0
				) {
					return "Weekly scheduled tasks must specify at least one day.";
				}
			} else if (
				this.schedule.scheduled.mode === "monthly" ||
				this.schedule.scheduled.mode === "yearly"
			) {
				if (
					!this.schedule.scheduled.description ||
					this.schedule.scheduled.description.trim() === ""
				) {
					return "Monthly and yearly scheduled tasks must include a description.";
				}
			}
		}

		if (this.schedule.periodic) {
			if (
				!this.schedule.periodic.description ||
				this.schedule.periodic.description.trim() === ""
			) {
				return "Periodic tasks must include a description of how often they repeat.";
			}
			if (!this.schedule.due) {
				return "Periodic tasks must have a start date.";
			}
		}

		return null;
	}

	createOptionGroups() {
		const containerStyle = this.widget?.inline
			? STYLES.task.schedule.root
			: `${STYLES.section} mt-2 ${STYLES.task.schedule.root}`;
		this.container = primitives.div({
			style: containerStyle,
			data: {
				visible: this.open ? "true" : "false",
				role: "date-form",
			},
		});

		const anchor =
			this.button.closest("[data-role='section-toggle-row']") ?? this.button;
		anchor.after(this.container);

		const repeatSection = primitives.div({
			style: "flex flex-col gap-2",
		});
		const repeatLabel = primitives.span({
			style: "text-sm font-semibold text-base-dark",
			text: "Repeat",
		});

		const segBar = primitives.div({
			style: "lp-schedule-seg",
			role: "repeat-modes",
		});

		const noneBtn = document.createElement("button");
		noneBtn.type = "button";
		noneBtn.className = "lp-schedule-seg-option";
		noneBtn.dataset.role = "repeat-none";
		noneBtn.textContent = "Doesn't repeat";
		this.noneButton = noneBtn;

		const toggles = {
			recurring: segmentedOption({
				type: "checkbox",
				name: "recurring",
				label: "After completion",
				checked: !!this.schedule.recurring,
			}),
			scheduled: segmentedOption({
				type: "checkbox",
				name: "scheduled",
				label: "On a schedule",
				checked: !!this.schedule.scheduled,
			}),
			periodic: segmentedOption({
				type: "checkbox",
				name: "periodic",
				label: "Periodically",
				checked: !!this.schedule.periodic,
			}),
		};

		this.toggles = toggles;
		segBar.append(
			noneBtn,
			toggles.recurring,
			toggles.scheduled,
			...(this.aiEnabled ? [toggles.periodic] : []),
		);
		repeatSection.append(repeatLabel, segBar);

		this.container.append(this.dueDate, repeatSection);
	}

	clearGroup(container?: HTMLDivElement | null) {
		if (!container) return;

		const group = container.dataset.role;
		if (group === "due-date") {
			delete this.schedule.due;
			const input = this.groups.dueDate?.querySelector("input");
			if (input) input.value = "";
			this._syncClearDueButton();
		} else {
			container.remove();
			if (isRepeatGroup(group)) {
				delete this.groups[group];
				delete this.schedule[group];
				const toggle = this.toggles[group]?.querySelector("input");
				if (toggle) toggle.checked = false;
			} else if (isScheduleGroup(group)) {
				delete this.groups[group];
			}
		}
	}

	get dueDate() {
		if (!this.groups.dueDate) {
			this.groups.dueDate = this._createDueDate();
		}
		return this.groups.dueDate;
	}

	_createDueDate() {
		const dueDateGroup = primitives.div({
			style: "flex flex-col gap-2",
			role: "due-date",
		});

		const inputId = `lp-due-date-${Math.random().toString(36).slice(2, 8)}`;

		const labelRow = dueDateGroup.appendChild(
			primitives.div({ style: "lp-schedule-label-row" }),
		);
		const dueLabel = document.createElement("label");
		dueLabel.htmlFor = inputId;
		dueLabel.className = "text-sm font-semibold text-base-dark";
		dueLabel.textContent = "Due Date";

		const sep = document.createElement("span");
		sep.className = "lp-schedule-sep";
		sep.setAttribute("aria-hidden", "true");

		const todayBtn = quickChip({ text: "Today", role: "today", accent: true });
		const tomorrowBtn = quickChip({ text: "Tomorrow", role: "tomorrow" });
		const nextWeekBtn = quickChip({ text: "Next week", role: "next-week" });
		const clearBtn = quickChip({
			text: "Clear",
			role: "remove-due-date",
			icon: "x",
		});
		clearBtn.hidden = !this.schedule.due;
		this.clearDueButton = clearBtn;

		labelRow.append(
			dueLabel,
			sep,
			todayBtn,
			tomorrowBtn,
			nextWeekBtn,
			clearBtn,
		);

		const input = primitives.input({
			id: inputId,
			name: "due-date",
			type: "date",
			value: this.schedule.due || "",
			data: {
				role: "set-due-date",
			},
		});
		const dateWrap = wrapDateInput(input);
		dateWrap.classList.add("lp-schedule-date-field");
		dueDateGroup.appendChild(dateWrap);

		return dueDateGroup;
	}

	get recurring() {
		if (!this.groups.recurring) {
			this.groups.recurring = this._createRecurring();
		}
		[this.groups.scheduled, this.groups.periodic].forEach((option) => {
			this.clearGroup(option);
		});
		return this.groups.recurring;
	}

	_createRecurring() {
		const recurringOptions = primitives.div({
			style: "lp-schedule-sub",
			role: "recurring",
			data: {
				visible: this.schedule.recurring ? "true" : "false",
			},
		});

		const row = recurringOptions.appendChild(
			primitives.div({ style: "flex flex-wrap items-end gap-3" }),
		);

		const everyCol = row.appendChild(
			primitives.div({ style: "flex flex-col gap-1 w-24" }),
		);
		everyCol.appendChild(
			primitives.span({
				style: "text-xs font-semibold text-base-dark",
				text: "Every",
			}),
		);
		const intervalInput = primitives.input({
			name: "interval",
			type: "number",
			value: this.schedule.recurring?.interval || "1",
		});
		intervalInput.min = "1";
		everyCol.appendChild(intervalInput);

		const unitCol = row.appendChild(
			primitives.div({ style: "flex flex-col gap-1" }),
		);
		unitCol.appendChild(
			primitives.span({
				style: "text-xs font-semibold text-base-dark",
				text: "Unit",
			}),
		);

		const units = [
			{
				label: "Days",
				value: "day",
				checked:
					this.schedule.recurring?.unit === "day" ||
					!this.schedule.recurring?.unit,
			},
			{
				label: "Weeks",
				value: "week",
				checked: this.schedule.recurring?.unit === "week",
			},
			{
				label: "Months",
				value: "month",
				checked: this.schedule.recurring?.unit === "month",
			},
			{
				label: "Years",
				value: "year",
				checked: this.schedule.recurring?.unit === "year",
			},
		];
		const unitBar = unitCol.appendChild(document.createElement("fieldset"));
		unitBar.className = "lp-schedule-seg";
		units.forEach((unit) => {
			unitBar.appendChild(
				segmentedOption({
					type: "radio",
					name: "unit",
					label: unit.label,
					value: unit.value,
					checked: unit.checked,
				}),
			);
		});

		const hint = document.createElement("p");
		hint.className = "text-xs text-base-medium";
		hint.textContent =
			"Next due date is scheduled after you mark this task complete.";
		recurringOptions.appendChild(hint);

		return recurringOptions;
	}

	get scheduled() {
		if (!this.groups.scheduled) {
			this.groups.scheduled = this._createSchedule();
		}
		[this.groups.recurring, this.groups.periodic].forEach((option) => {
			this.clearGroup(option);
		});
		return this.groups.scheduled;
	}

	get weekly() {
		if (!this.groups.weekly) {
			this.groups.weekly = this._createWeeklySchedule();
		}
		[this.groups.monthly, this.groups.yearly].forEach((option) => {
			this.clearGroup(option);
		});
		return this.groups.weekly;
	}

	get monthly() {
		if (!this.groups.monthly) {
			this.groups.monthly = this._createMonthlySchedule();
		}
		[this.groups.yearly, this.groups.weekly].forEach((option) => {
			this.clearGroup(option);
		});
		return this.groups.monthly;
	}

	get yearly() {
		if (!this.groups.yearly) {
			this.groups.yearly = this._createYearlySchedule();
		}
		[this.groups.monthly, this.groups.weekly].forEach((option) => {
			this.clearGroup(option);
		});
		return this.groups.yearly;
	}

	_createSchedule() {
		const scheduledOptions = primitives.div({
			style: "lp-schedule-sub",
			role: "scheduled",
			data: { visible: this.schedule.scheduled ? "true" : "false" },
		});

		const currentMode = this.schedule.scheduled?.mode || "daily";
		const scheduleTypes = [
			{ label: "Daily", value: "daily", checked: currentMode === "daily" },
			{ label: "Weekly", value: "weekly", checked: currentMode === "weekly" },
			...(this.aiEnabled
				? [
						{
							label: "Monthly",
							value: "monthly",
							checked: currentMode === "monthly",
						},
						{
							label: "Yearly",
							value: "yearly",
							checked: currentMode === "yearly",
						},
					]
				: []),
		];

		const scheduleBar = scheduledOptions.appendChild(
			document.createElement("fieldset"),
		);
		scheduleBar.className = "lp-schedule-seg";
		scheduleTypes.forEach((type) => {
			scheduleBar.appendChild(
				segmentedOption({
					type: "radio",
					name: "schedule-type",
					label: type.label,
					value: type.value,
					checked: type.checked,
				}),
			);
		});

		return scheduledOptions;
	}

	_createWeeklySchedule() {
		const weeklyOptions = primitives.div({
			style: "lp-schedule-days",
			role: "weekly",
			data: {
				visible: this.schedule.scheduled?.mode === "weekly" ? "true" : "false",
			},
		});
		this.groups.scheduled?.appendChild(weeklyOptions);

		const weekDays = [
			["Mon", "Monday"],
			["Tue", "Tuesday"],
			["Wed", "Wednesday"],
			["Thu", "Thursday"],
			["Fri", "Friday"],
			["Sat", "Saturday"],
			["Sun", "Sunday"],
		] as const;
		const selectedDays = new Set(
			(this.schedule.scheduled?.days || []).map((d) => String(d)),
		);
		weekDays.forEach(([shortLabel, fullLabel], index) => {
			const pill = document.createElement("label");
			pill.className = "lp-schedule-day";
			pill.title = fullLabel;
			const input = document.createElement("input");
			input.type = "checkbox";
			input.className = "lp-schedule-sr-input";
			input.name = `weekly-day-${index}`;
			input.value = String(index);
			input.setAttribute("aria-label", fullLabel);
			if (selectedDays.has(String(index))) input.checked = true;
			const span = document.createElement("span");
			span.textContent = shortLabel;
			pill.append(input, span);
			weeklyOptions.appendChild(pill);
		});

		return weeklyOptions;
	}

	_createMonthlySchedule() {
		const monthlyOptions = primitives.div({
			style: "flex flex-col gap-1.5",
			role: "monthly",
			data: {
				visible: this.schedule.scheduled?.mode === "monthly" ? "true" : "false",
			},
		});
		this.groups.scheduled?.appendChild(monthlyOptions);

		monthlyOptions.appendChild(
			primitives.input({
				name: "monthly-description",
				type: "text",
				placeholder: "e.g., first Monday, last day, 15th",
				value:
					this.schedule.scheduled?.mode === "monthly"
						? this.schedule.scheduled?.description || ""
						: "",
				label: "When each month?",
			}),
		);
		const hint = document.createElement("p");
		hint.className = "text-xs text-base-medium";
		hint.textContent = "Parsed by AI when you save.";
		monthlyOptions.appendChild(hint);

		return monthlyOptions;
	}

	_createYearlySchedule() {
		const yearlyOptions = primitives.div({
			style: "flex flex-col gap-1.5",
			role: "yearly",
			data: {
				visible: this.schedule.scheduled?.mode === "yearly" ? "true" : "false",
			},
		});
		this.groups.scheduled?.appendChild(yearlyOptions);

		yearlyOptions.appendChild(
			primitives.input({
				name: "yearly-description",
				type: "text",
				placeholder: "e.g., December 25th, third Thursday in November",
				value:
					this.schedule.scheduled?.mode === "yearly"
						? this.schedule.scheduled?.description || ""
						: "",
				label: "When each year?",
			}),
		);
		const hint = document.createElement("p");
		hint.className = "text-xs text-base-medium";
		hint.textContent = "Parsed by AI when you save.";
		yearlyOptions.appendChild(hint);

		return yearlyOptions;
	}

	get periodic() {
		if (!this.groups.periodic) {
			this.groups.periodic = this._createPeriodic();
		}
		[this.groups.recurring, this.groups.scheduled].forEach((option) => {
			this.clearGroup(option);
		});
		return this.groups.periodic;
	}

	_createPeriodic() {
		const periodicOptions = primitives.div({
			style: "lp-schedule-sub",
			role: "periodic",
			data: { visible: this.schedule.periodic ? "true" : "false" },
		});

		const startDate = periodicOptions.appendChild(
			primitives.input({
				name: "start-date",
				type: "date",
				value: this.schedule.start_date || todayIsoDate(),
				label: "Start Date",
			}),
		);
		startDate
			.querySelector("[data-role='date-input-wrap']")
			?.classList.add("lp-schedule-date-field");

		const descField = primitives.div({ style: "flex flex-col gap-1" });
		descField.appendChild(
			primitives.input({
				name: "periodic-description",
				type: "text",
				placeholder: "e.g., every 3 days, every 2 weeks, biweekly, quarterly",
				value: this.schedule.periodic?.description || "",
				label: "How often does it repeat?",
			}),
		);

		const hint = document.createElement("p");
		hint.className = "text-xs text-base-medium";
		hint.textContent = "Parsed by AI when you save.";
		descField.appendChild(hint);
		periodicOptions.appendChild(descField);

		return periodicOptions;
	}

	clear() {
		if (!this.open) {
			Object.values(this.groups).forEach((group) => {
				this.clearGroup(group);
			});
			this.schedule = {};
			this._syncNoneButton();
			this._syncClearDueButton();
		}
		this.open = false;
		this._reconcile();
	}
}
