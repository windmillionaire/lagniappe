import { STYLES } from "../generated/styles.mjs";
import { withTransition } from "../shared/transitions.ts";
import { buttons } from "./buttons.ts";
import { primitives } from "./primitives.ts";
import type { SectionToggle } from "./sectionToggle.ts";

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

export class DueDate {
	declare destroy?: never;
	declare widget?: { readonly?: boolean };
	declare button: HTMLButtonElement;
	declare action?: string;
	declare kind: "task";
	declare aiEnabled: boolean;
	declare schedule: TaskSchedule;
	declare container: HTMLDivElement | null;
	declare groups: Partial<Record<DueGroup, HTMLDivElement>>;
	declare toggles: Partial<Record<RepeatGroup, HTMLElement>>;
	declare error: HTMLDivElement | null;
	declare open: boolean;
	declare closed?: boolean;
	declare toggle?: SectionToggle;

	constructor(button: HTMLButtonElement, widget?: { readonly?: boolean }) {
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
	}

	_click(e: MouseEvent) {
		const role =
			e.target instanceof Element
				? e.target.closest<HTMLElement>("[data-role]")?.dataset.role
				: undefined;
		if (!role) return;
		const input = this.groups.dueDate?.querySelector("input");

		switch (role) {
			case "today":
				this.schedule.due = new Date().toLocaleDateString("sv-SE");
				if (input) input.value = this.schedule.due;
				break;
			case "remove-due-date":
				if (input) input.value = "";
				this.schedule.due = null;
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
			this.schedule.due = target.value;
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
		if (target.name === "recurring") {
			this.schedule.recurring ??= {};
			this.container.appendChild(this.recurring);
			if (!target.checked) {
				this.clearGroup(this.recurring);
			}
			return;
		} else if (target.name === "unit") {
			this.schedule.recurring ??= {};
			this.schedule.recurring.unit = target.value;
			return;
		} else if (target.name === "scheduled") {
			this.schedule.scheduled ??= {};
			this.container.appendChild(this.scheduled);
			if (!target.checked) {
				this.clearGroup(this.groups.scheduled);
			}
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
			this.schedule.periodic ??= {};
			this.container.appendChild(this.periodic);
			if (!target.checked) {
				this.clearGroup(this.groups.periodic);
			}
			return;
		}
	}

	get active() {
		return Object.keys(this.schedule).length > 0;
	}

	showError(message: string) {
		if (!this.error) {
			this.error = primitives.error();
			this.error.classList.add("mb-3");
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
		this.container = primitives.div({
			style: `${STYLES.section} mt-2`,
			data: {
				visible: this.open ? "true" : "false",
				role: "date-form",
			},
		});

		const anchor =
			this.button.closest("[data-role='section-toggle-row']") ?? this.button;
		anchor.after(this.container);

		const choices = this.container.appendChild(
			primitives.div({
				style: "flex flex-col gap-3 pt-3",
			}),
		);

		const toggles = {
			recurring: primitives.checkbox({
				name: "recurring",
				label: "This task repeats when completed",
				checked: !!this.schedule.recurring,
			}),
			scheduled: primitives.checkbox({
				name: "scheduled",
				label: "This task repeats on a schedule",
				checked: !!this.schedule.scheduled,
			}),
			periodic: primitives.checkbox({
				name: "periodic",
				label: "This task repeats periodically",
				checked: !!this.schedule.periodic,
			}),
		};

		this.toggles = toggles;
		choices.append(
			this.dueDate,
			toggles.recurring,
			toggles.scheduled,
			...(this.aiEnabled ? [toggles.periodic] : []),
		);
	}

	clearGroup(container?: HTMLDivElement | null) {
		if (!container) return;

		const group = container.dataset.role;
		if (group === "due-date") {
			delete this.schedule.due;
			const input = this.groups.dueDate?.querySelector("input");
			if (input) input.value = "";
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
			return this.groups.dueDate;
		}
		return this.groups.dueDate;
	}

	_createDueDate() {
		const dueDateGroup = primitives.div({
			style: "pb-1",
			role: "due-date",
		});

		dueDateGroup.appendChild(
			primitives.input({
				name: "due-date",
				type: "date",
				value: this.schedule.due || "",
				label: "Due Date",
				data: {
					role: "set-due-date",
				},
			}),
		);

		const buttonRow = dueDateGroup.appendChild(
			primitives.div({
				style: "flex flex-col sm:flex-row gap-2 mt-3",
			}),
		);

		buttonRow.appendChild(
			buttons.default({
				text: "Today",
				role: "today",
			}),
		);

		buttonRow.appendChild(
			buttons.default({
				text: "Remove",
				role: "remove-due-date",
			}),
		);

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
			style: "flex flex-col gap-4 border-t border-base-medium mt-4",
			role: "recurring",
			data: {
				visible: this.schedule.recurring ? "true" : "false",
			},
		});

		const afterRow = recurringOptions.appendChild(
			primitives.div({ style: "flex flex-row items-center gap-2 mt-4" }),
		);

		afterRow.appendChild(
			primitives.span({ style: STYLES.label.default, text: "After" }),
		);

		afterRow.appendChild(
			primitives.input({
				name: "interval",
				type: "number",
				value: this.schedule.recurring?.interval || "1",
			}),
		);

		const unitWrapper = recurringOptions.appendChild(
			primitives.div({ style: "flex flex-col gap-2" }),
		);

		const units = [
			{
				label: "day",
				value: "day",
				name: "unit",
				checked:
					this.schedule.recurring?.unit === "day" ||
					!this.schedule.recurring?.unit,
			},
			{
				label: "week",
				value: "week",
				name: "unit",
				checked: this.schedule.recurring?.unit === "week",
			},
			{
				label: "month",
				value: "month",
				name: "unit",
				checked: this.schedule.recurring?.unit === "month",
			},
			{
				label: "year",
				value: "year",
				name: "unit",
				checked: this.schedule.recurring?.unit === "year",
			},
		];
		const unitRow = unitWrapper.appendChild(document.createElement("fieldset"));
		unitRow.className = STYLES.radio.fieldset.grid;

		units.forEach((unit) => {
			unitRow.appendChild(primitives.radio(unit));
		});

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
			style: "flex flex-col gap-4 border-t border-base-medium mt-4",
			role: "scheduled",
			data: { visible: this.schedule.scheduled ? "true" : "false" },
		});

		const scheduleType = scheduledOptions.appendChild(
			document.createElement("div"),
		);
		scheduleType.className = "flex flex-row items-center gap-2";

		const currentMode = this.schedule.scheduled?.mode || "daily";
		const scheduleTypes = [
			{
				label: "Daily",
				value: "daily",
				name: "schedule-type",
				checked: currentMode === "daily",
			},
			{
				label: "Weekly",
				value: "weekly",
				name: "schedule-type",
				checked: currentMode === "weekly",
			},
			...(this.aiEnabled
				? [
						{
							label: "Monthly",
							value: "monthly",
							name: "schedule-type",
							checked: currentMode === "monthly",
						},
						{
							label: "Yearly",
							value: "yearly",
							name: "schedule-type",
							checked: currentMode === "yearly",
						},
					]
				: []),
		];

		const scheduleTypeWrapper = scheduledOptions.appendChild(
			document.createElement("div"),
		);
		scheduleTypeWrapper.className = "flex flex-col gap-2";

		const scheduleSettings = scheduleTypeWrapper.appendChild(
			document.createElement("fieldset"),
		);
		scheduleSettings.className = STYLES.radio.fieldset.grid;

		scheduleTypes.forEach((type) => {
			scheduleSettings.appendChild(primitives.radio(type));
		});

		return scheduledOptions;
	}

	_createWeeklySchedule() {
		const weeklyOptions = primitives.div({
			style: STYLES.checkbox.grid,
			role: "weekly",
			data: {
				visible: this.schedule.scheduled?.mode === "weekly" ? "true" : "false",
			},
		});
		this.groups.scheduled?.appendChild(weeklyOptions);

		const weekDays = [
			"Monday",
			"Tuesday",
			"Wednesday",
			"Thursday",
			"Friday",
			"Saturday",
			"Sunday",
		];
		weekDays.forEach((day, index) => {
			weeklyOptions.appendChild(
				primitives.checkbox({
					label: day,
					value: index,
					name: `weekly-day-${index}`,
					checked: this.schedule.scheduled?.days?.includes(index) || false,
				}),
			);
		});

		return weeklyOptions;
	}

	_createMonthlySchedule() {
		const monthlyOptions = primitives.div({
			style: "flex flex-col gap-2",
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
				label: "Describe when this repeats (description will be parsed by AI)",
			}),
		);

		return monthlyOptions;
	}

	_createYearlySchedule() {
		const yearlyOptions = primitives.div({
			style: "flex flex-col gap-2",
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
				label: "Describe when this repeats (description will be parsed by AI)",
			}),
		);

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
			style: "flex flex-col gap-2 border-t border-base-medium mt-4 pt-4",
			role: "periodic",
			data: { visible: this.schedule.periodic ? "true" : "false" },
		});

		const startDate = periodicOptions.appendChild(
			primitives.input({
				name: "start-date",
				type: "date",
				value:
					this.schedule.start_date || new Date().toLocaleDateString("sv-SE"),
				label: "Start Date",
			}),
		);
		startDate.classList.add("mb-2");

		periodicOptions.appendChild(
			primitives.input({
				name: "periodic-description",
				type: "text",
				placeholder: "e.g., every 3 days, every 2 weeks, biweekly, quarterly",
				value: this.schedule.periodic?.description || "",
				label:
					"Describe how often this repeats (description will be parsed by AI)",
			}),
		);

		return periodicOptions;
	}

	clear() {
		if (!this.open) {
			Object.values(this.groups).forEach((group) => {
				this.clearGroup(group);
			});
			this.schedule = {};
		}
		this.open = false;
		this._reconcile();
	}
}
