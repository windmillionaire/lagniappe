import { STYLES } from "styles";
import { withTransition } from "../shared";
import { buttons } from "./buttons";
import { primitives } from "./primitives";

/**
 * @testable infrastructure
 */
export class DueDate {
	constructor(button, widget) {
		this.widget = widget;
		this.action = button.dataset.action;
		this.button = button;
		this.kind = "task";
		this.aiEnabled = this.button.dataset.aiEnabled !== "false";
		this.schedule = JSON.parse(this.button.dataset.schedule ?? "{}");
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

		this.container.addEventListener("input", this._input);
		this.container.addEventListener("click", this._click);
		this.container.addEventListener("change", this._change);

		if (this.schedule.recurring) {
			this.container.appendChild(this.recurring);
		} else if (this.schedule.scheduled) {
			this.container.appendChild(this.scheduled);
			if (this.schedule.scheduled.mode === "weekly") {
				this.groups.scheduled.appendChild(this.weekly);
			} else if (this.aiEnabled && this.schedule.scheduled.mode === "monthly") {
				this.groups.scheduled.appendChild(this.monthly);
			} else if (this.aiEnabled && this.schedule.scheduled.mode === "yearly") {
				this.groups.scheduled.appendChild(this.yearly);
			}
		} else if (this.aiEnabled && this.schedule.periodic) {
			this.container.appendChild(this.periodic);
		}
	}

	_click(e) {
		const role = e.target.closest("[data-role]")?.dataset.role;
		if (!role) return;

		switch (role) {
			case "today":
				this.schedule.due = new Date().toLocaleDateString("sv-SE");
				this.groups.dueDate.querySelector("input").value = this.schedule.due;
				break;
			case "remove-due-date":
				this.groups.dueDate.querySelector("input").value = "";
				this.schedule.due = null;
				break;
		}
	}

	_input(e) {
		if (e.target.name === "monthly-description") {
			this.schedule.scheduled.description = e.target.value;
			return;
		} else if (e.target.name === "yearly-description") {
			this.schedule.scheduled.description = e.target.value;
			return;
		} else if (e.target.name === "periodic-description") {
			this.schedule.periodic.description = e.target.value;
			return;
		} else if (e.target.name === "due-date") {
			this.schedule.due = e.target.value;
			return;
		} else if (e.target.name === "interval") {
			this.schedule.recurring ??= {};
			this.schedule.recurring.interval = e.target.value;
			return;
		}
	}

	_change(e) {
		if (e.target.name === "recurring") {
			this.schedule.recurring ??= {};
			this.container.appendChild(this.recurring);
			if (!e.target.checked) {
				this.clearGroup(this.recurring);
			}
			return;
		} else if (e.target.name === "unit") {
			this.schedule.recurring ??= {};
			this.schedule.recurring.unit = e.target.value;
			return;
		} else if (e.target.name === "scheduled") {
			this.schedule.scheduled ??= {};
			this.container.appendChild(this.scheduled);
			if (!e.target.checked) {
				this.clearGroup(this.groups.scheduled);
			}
			return;
		} else if (e.target.name === "schedule-type") {
			this.schedule.scheduled ??= {};
			this.schedule.scheduled.mode = e.target.value;
			if (!e.target.checked) {
				this.clearGroup(this.groups[e.target.value]);
			} else if (e.target.value === "daily") {
				[this.groups.weekly, this.groups.monthly, this.groups.yearly].forEach(
					(group) => {
						this.clearGroup(group);
					},
				);
			} else if (e.target.value === "weekly") {
				this.groups.scheduled.appendChild(this.weekly);
			} else if (this.aiEnabled && e.target.value === "monthly") {
				this.groups.scheduled.appendChild(this.monthly);
			} else if (this.aiEnabled && e.target.value === "yearly") {
				this.groups.scheduled.appendChild(this.yearly);
			}
			return;
		} else if (e.target.name.startsWith("weekly-day-")) {
			this.schedule.scheduled.days = Array.from(
				this.weekly.querySelectorAll("input:checked"),
			).map((input) => input.value);
			return;
		} else if (e.target.name === "periodic") {
			if (!this.aiEnabled) return;
			this.schedule.periodic ??= {};
			this.container.appendChild(this.periodic);
			if (!e.target.checked) {
				this.clearGroup(this.groups.periodic);
			}
			return;
		}
	}

	get active() {
		return Object.keys(this.schedule).length > 0;
	}

	showError(message) {
		if (!this.error) {
			this.error = primitives.error();
			this.error.classList.add("mb-3");
			this.container.prepend(this.error);
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
			this.toggle.display();

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
			style: STYLES.section,
			data: {
				visible: this.open ? "true" : "false",
				role: "date-form",
			},
		});

		this.button.after(this.container);

		const choices = this.container.appendChild(
			primitives.div({
				style: "flex flex-col gap-3 pt-3",
			}),
		);

		this.toggles = {
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

		choices.append(
			this.dueDate,
			this.toggles.recurring,
			this.toggles.scheduled,
			...(this.aiEnabled ? [this.toggles.periodic] : []),
		);
	}

	clearGroup(container) {
		if (!container) return;

		const group = container.dataset.role;
		if (group === "due-date") {
			delete this.schedule.due;
			this.groups.dueDate.querySelector("input").value = "";
		} else {
			container.remove();
			delete this.groups[group];
			delete this.schedule[group];
			if (this.toggles[group]) {
				this.toggles[group].querySelector("input").checked = false;
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

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_due_date
	 * @features tasks
	 * @dimensions create due-date badge
	 */
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
				min: "1",
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
		const weeklyOptions = this.groups.scheduled.appendChild(
			primitives.div({
				style: STYLES.checkbox.grid,
				role: "weekly",
				data: {
					visible:
						this.schedule.scheduled?.mode === "weekly" ? "true" : "false",
				},
			}),
		);

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
		const monthlyOptions = this.groups.scheduled.appendChild(
			primitives.div({
				style: "flex flex-col gap-2",
				role: "monthly",
				data: {
					visible:
						this.schedule.scheduled?.mode === "monthly" ? "true" : "false",
				},
			}),
		);

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

		monthlyOptions.appendChild(
			primitives.explain_prompt({
				explain: "schedule",
				classes: ["self-start", "-mb-2"],
			}),
		);

		return monthlyOptions;
	}

	_createYearlySchedule() {
		const yearlyOptions = this.groups.scheduled.appendChild(
			primitives.div({
				style: "flex flex-col gap-2",
				role: "yearly",
				data: {
					visible:
						this.schedule.scheduled?.mode === "yearly" ? "true" : "false",
				},
			}),
		);

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

		yearlyOptions.appendChild(
			primitives.explain_prompt({
				explain: "schedule",
				classes: ["self-start", "-mb-2"],
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

		periodicOptions.appendChild(
			primitives.explain_prompt({
				explain: "schedule",
				classes: ["self-start", "-mb-2"],
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
