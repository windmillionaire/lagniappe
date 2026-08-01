/*! Third-party licenses: /third-party-licenses.txt */
import { S as STYLES } from './styles.js?v=b7488009';
import { r as request } from './request.js?v=b7488009';
import './connectivity.js?v=b7488009';
import { s as setIcon, c as createIcon, i as iconDefinition } from './icons.js?v=b7488009';
import { withTransition } from './utilities.js?v=b7488009';
import { F as FacetsBox } from './facets.js?v=b7488009';
import { b as buttons } from './buttons.js?v=b7488009';
import { p as primitives } from './primitives.js?v=b7488009';
import { f as formatting } from './formatting.js?v=b7488009';
import { E as ENDPOINTS } from './endpoints.js?v=b7488009';
import { B as BaseUpload, u as uploadElement, U as UploadMenu } from './baseUpload.js?v=b7488009';

/**
 * @testable infrastructure
 */
class DueDate {
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

const UPLOAD_DROPZONE_TEXT =
	"Drop file/photo here, click to upload, or tap to choose camera/files";

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_file
 * @features tasks
 * @dimensions create file-upload
 */
class TaskUpload extends BaseUpload {
	constructor(button, widget) {
		super({
			button,
			action: button.dataset.action,
		});

		this.widget = widget;
		this.target = document.createElement("div");
		this.target.className = "w-full flex flex-col gap-2 group/upload";
		this.target.dataset.visible = "false";
		this.button.insertAdjacentElement("afterend", this.target);

		this.assets = JSON.parse(button.dataset.preload || "{}");
		this.task = button.closest("[lp-component]");
		this.taskRow = button.closest("li[lp-entity][data-kind='task']");
		this.key = this.taskRow?.dataset.key || widget?.key;
		this.endpoints = this.key ? ENDPOINTS.TaskUpload({ key: this.key }) : {};

		this.assetsInput = this._assetsInput();
		this.assetsList = this._assetsList();

		this.kind = "file";
		this.inputName = "task-file";
		this.uploadType = "file";
		this.messages = {
			submit: "Attach File/Photo",
			submitting: "Attaching File/Photo",
			submitted: "File/Photo Attached",
		};
		this.dropzone = uploadElement.dropzone({ text: UPLOAD_DROPZONE_TEXT });
		this.menuOptions = ["replace", "paste"];
		this.uploadMenu = new UploadMenu(this);

		this.toggle = null;
		this._deleteFile = this._deleteFile.bind(this);
	}

	get html() {
		return [this.assetsInput, this.dropzone.element, this.assetsList];
	}

	get formData() {
		const data = new FormData();
		const file = this.fileInput?.element.files[0];
		if (file) data.append(this.inputName, file);
		if (this.mimeType?.element) {
			data.append(this.mimeType.element.name, this.mimeType.element.value);
		}
		this._syncAssetsInput();
		data.append(this.assetsInput.name, this.assetsInput.value);

		return this.applyDirectUploads(data);
	}

	async init() {
		await super.init();

		this.toggle?.display();
		this.assetsList.addEventListener("click", this._deleteFile);
		this.renderAssets();
	}

	_assetsInput() {
		const input = document.createElement("input");
		input.type = "hidden";
		input.name = "assets";
		input.value = JSON.stringify(this.assets || {});
		return input;
	}

	_assetsList() {
		const list = document.createElement("ul");
		list.dataset.role = "saved-files";
		list.dataset.kind = "file";
		list.className =
			"outline-2 outline-kind-default rounded-md divide-y-kind-light bg-kind-bg w-full";
		return list;
	}

	_syncAssetsInput() {
		this.assetsInput.value = JSON.stringify(this.assets || {});
	}

	_deleteUrl(file) {
		if (file.delete_url) return file.delete_url;
		const key = file.key || file.id;
		if (!key || !file.attached || !this.taskRow) return null;
		return this.endpoints.remove(key);
	}

	_deleteButton(file) {
		const name = file.name || file.filename || "attachment";
		const button = document.createElement("button");
		button.type = "button";
		button.dataset.role = "delete-task-file";
		button.dataset.kind = "delete";
		button.dataset.active = "false";
		button.dataset.route = this._deleteUrl(file) || "";
		button.className = STYLES.toggle.container;
		button.setAttribute("aria-label", `Delete ${name}`);
		button.title = `Delete ${name}`;

		const active = button.appendChild(document.createElement("span"));
		setIcon(active, "trash.active", STYLES.toggle.icon.active);

		const inactive = button.appendChild(document.createElement("span"));
		setIcon(inactive, "trash.inactive", STYLES.toggle.icon.inactive);

		return button;
	}

	_fileUrl(file) {
		if (file.url) return file.url;
		if (file.kind === "file" && file.id) return `/files/${file.id}`;
		return "#";
	}

	_assetItem([name, file]) {
		const label = file.name || file.filename || name;
		const item = document.createElement("li");
		item.dataset.key = file.key || file.id || "";
		item.dataset.kind = "file";
		item.className =
			"flex flex-row items-baseline justify-between gap-4 p-4 rounded-md bg-base-bg";

		const link = item.appendChild(document.createElement("a"));
		link.href = this._fileUrl(file);
		link.dataset.kind = "file";
		link.className = STYLES.link.title;
		link.textContent = label;

		item.appendChild(this._deleteButton(file));
		return item;
	}

	renderAssets() {
		this._syncAssetsInput();
		const entries = Object.entries(this.assets || {});
		this.assetsList.dataset.visible = entries.length > 0 ? "true" : "false";
		this.assetsList.replaceChildren(
			...entries.map((entry) => this._assetItem(entry)),
		);
	}

	shouldAutoUpload() {
		return true;
	}

	async autoUpload() {
		await this.uploadFile();
	}

	async uploadFile() {
		if (!this.endpoints.upload) {
			this.showError("Upload route unavailable");
			return;
		}

		this.dropzone.setText(`${createIcon("spinner").outerHTML} Uploading...`);
		const prepared = await this.prepareSubmit({ route: this.endpoints.upload });
		if (!prepared) return;

		const response = await request.post(this.endpoints.upload, this.formData);
		if (!response.ok) {
			this.showError(response.error || "Could not upload attachment");
			return;
		}

		withTransition(() => {
			this.assets = response.assets || {};
			this.renderAssets();
			this.reset();
		});
	}

	_removeBadge(file) {
		if (!this.task || !file) return;
		const labels = new Set([file.name, file.filename].filter(Boolean));
		const url = this._fileUrl(file);
		const urls = new Set(url === "#" ? [] : [url]);

		this.task.querySelectorAll("[data-kind='file']").forEach((badge) => {
			if (badge.closest("[data-role='saved-files']")) return;
			const link = badge.querySelector("a");
			const text = badge.textContent.trim();
			if (labels.has(text) || (link && urls.has(link.getAttribute("href")))) {
				badge.remove();
			}
		});
	}

	async _deleteFile(e) {
		const button = e.target.closest("[data-role='delete-task-file']");
		if (!button) return;

		e.preventDefault();
		e.stopPropagation();

		const item = button.closest("[data-kind='file']");
		const key = item?.dataset.key;
		const file = Object.values(this.assets || {}).find(
			(asset) => (asset.key || asset.id) === key,
		);
		const route = button.dataset.route;
		if (!route) {
			if (key) {
				this.assets = Object.fromEntries(
					Object.entries(this.assets || {}).filter(
						([, asset]) => (asset.key || asset.id) !== key,
					),
				);
			}
			this.renderAssets();
			return;
		}

		const data = new FormData();
		data.append("assets", JSON.stringify(this.assets || {}));
		button.disabled = true;
		const response = await request.delete(route, data);
		button.disabled = false;
		if (!response.ok) {
			this.showError(response.error || "Could not delete attachment");
			return;
		}

		withTransition(() => {
			this.assets = response.assets || {};
			this.renderAssets();
			this._removeBadge(response.deleted || file);
		});
	}

	toggleVisibility() {
		this.target.dataset.visible =
			this.target.dataset.visible === "true" ? "false" : "true";
	}

	reset() {
		super.reset();
	}

	clear() {
		this.reset();
		this.toggle.display();
	}

	showError(message) {
		super.showError(message);
	}

	hideError() {
		super.hideError();
	}

	destroy() {
		this.assetsList.removeEventListener("click", this._deleteFile);
		super.destroy();
	}
}

/**
 * @testable infrastructure
 */
const clearButton = (open) => {
	const clearButton = document.createElement("button");
	clearButton.dataset.role = "clear";
	clearButton.dataset.kind = "delete";
	clearButton.type = "button";
	clearButton.className = STYLES.form.icon;
	setIcon(
		clearButton.appendChild(document.createElement("span")),
		open ? "x" : "clear",
		"icon-sm",
	);
	return clearButton;
};

/**
 * @testable infrastructure
 */
const dueDateText = (parent) => {
	if (!parent.active) {
		return formatting.text({
			kind: parent.kind,
			text: parent.button.dataset.title,
		});
	}

	const schedule = parent.schedule;
	let displayText = "Due";

	if (schedule.due) {
		displayText += ` ${formatting.date(schedule.due)}`;
	} else {
		displayText = "No Due Date";
	}

	if (schedule.recurring) {
		const interval = schedule.recurring.interval || "1";
		const unit = schedule.recurring.unit || "day";
		const pluralUnit = parseInt(interval, 10) > 1 ? `${unit}s` : unit;
		displayText += ` (repeats when completed after ${interval} ${pluralUnit})`;
	} else if (schedule.scheduled) {
		displayText += ` (repeats ${
			schedule.scheduled.text || schedule.scheduled.mode
		})`;
	} else if (schedule.periodic) {
		displayText += ` (repeats ${schedule.periodic.text || "periodically"})`;
	}

	return formatting.text({ kind: parent.kind, text: displayText });
};

/**
 * @testable infrastructure
 */
const detailsText = (parent) => {
	if (!parent.active) {
		return formatting.text({
			kind: parent.kind,
			text: parent.button.dataset.title,
		});
	}

	return formatting.name({ ...parent.details, link: !parent.readonly });
};

/**
 * @testable infrastructure
 */
const fileText = (parent) => {
	const firstAsset = Object.values(parent.assets || {})[0];
	const filename =
		parent.filename || firstAsset?.name || firstAsset?.filename || "";

	if (!parent.active || !filename) {
		return formatting.text({
			kind: parent.kind,
			text: "Attach File/Photo",
		});
	}

	const display =
		filename.length > 20 ? `${filename.substring(0, 17)}...` : filename;

	return formatting.text({
		kind: parent.kind,
		text: display,
	});
};

/**
 * @testable false
 * @covered-by src/script/elements/sectionToggle.mjs::FacetControl
 */
const detailsLinkRow = (details) => {
	if (!details?.name) return null;
	const kind = details.kind || details.index || details.type || "default";

	const row = document.createElement("div");
	row.dataset.kind = kind;
	row.className = `${STYLES.form.submission.default} text-kind-default`;

	const name = formatting.name({ ...details, link: Boolean(details.id) });
	row.appendChild(
		formatting.iconLabel({
			icon: iconDefinition(kind) ? kind : "in",
			kind,
			content: name,
			iconClasses: "text-kind-default",
		}),
	);

	return row;
};

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_with_project
 * @pair tasks:select-toggle-layout
 */
class SectionToggle {
	static facet(widget, element) {
		return new FacetControl(widget, element);
	}

	static date(widget, button) {
		const control = new DueDate(button, widget);
		control.toggle = new SectionToggle(control, widget);
		return control;
	}

	static upload(widget, button) {
		const control = new TaskUpload(button, widget);
		control.toggle = new SectionToggle(control, widget);
		return control;
	}

	constructor(parent, widget = parent.widget) {
		this.parent = parent;
		this.widget = widget;
		this.readonly = Boolean(
			widget?.readonly ||
				parent?.readonly ||
				parent?.button?.dataset.readonly === "true" ||
				parent?.button?.disabled,
		);
		this.init();
	}

	init() {
		if (this.readonly) return;

		this.parent.button.addEventListener("click", (e) => {
			if (e.target.closest("a")) {
				return;
			}

			e.preventDefault();
			e.stopPropagation();

			if (e.target.closest("[data-role='clear']")) {
				this.parent.clear();
			} else {
				this.parent.toggleVisibility();
			}
		});
		this.parent.button.addEventListener("keydown", (e) => {
			if (!["Enter", "Escape"].includes(e.key)) return;

			e.preventDefault();
			e.stopPropagation();

			if (e.target.closest("[data-role='clear']")) {
				this.parent.clear();
			} else {
				this.parent.toggleVisibility();
			}
		});
	}

	_setButtonReadonly() {
		if (!this.readonly) return;

		const button = this.parent.button;
		button.dataset.readonly = "true";
		button.disabled = true;
		button.setAttribute("aria-disabled", "true");
	}

	display() {
		let text = "";
		if (this.parent.action === "schedule") {
			text = dueDateText(this.parent);
		} else if (this.parent.index) {
			text = detailsText(this.parent);
		} else if (this.parent.action === "uploadFile") {
			text = fileText(this.parent);
		}

		const semanticIcon =
			this.parent.action === "schedule"
				? "dueDate"
				: this.parent.icon || this.parent.index;
		const icon = iconDefinition(semanticIcon) ? semanticIcon : this.parent.kind;

		const title = formatting.iconLabel({
			icon,
			kind: this.parent.kind,
			content: text,
			classes: "flex-1 leading-normal",
			iconClasses: "text-kind-default",
		});

		let action = null;
		if (!this.readonly) {
			action =
				this.parent.active || this.parent.open
					? clearButton(this.parent.open)
					: null;
		}

		const contents = [title, action].filter(Boolean);

		this.parent.button.replaceChildren(...contents);
		this._setButtonReadonly();
	}
}

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_add_category_to_page
 * @tests tests_e2e/005_pages/test_005a_page_tabs.py::test_switch_page_form
 * @tests tests_e2e/005_pages/test_005d_page_permissions.py::test_page_viewer_reads_page_without_page_editing_affordances
 * @tests tests_e2e/007_categories/test_007e_category_permissions.py::test_category_viewer_opens_readonly_settings
 * @pairs pages:readonly pages:form-switch
 * @pairs categories:readonly categories:default-form
 */
class FacetControl {
	constructor(widget, element) {
		this.widget = widget;
		this.root = element?.closest?.("[lp-select]") || element;
		this.button = this.root?.matches?.("button[lp-select]") ? this.root : null;
		this.container = this._container();
		this.input = this.button
			? null
			: this.root?.querySelector?.("input, select") || this.root;
		this.source = this.button || this.input || this.root;
		this.action = this.source?.dataset.action;
		this.index = this.source?.dataset.index || this.root?.dataset.index;
		this.kind =
			this.source?.dataset.kind || this.root?.dataset.kind || this.index;
		this.details = this._preload()[0] || {};
		this.select = null;
		this.element = null;
		this.toggle = null;
		this.open = false;

		this._updated = this._updated.bind(this);
		this._deactivate = this._deactivate.bind(this);
	}

	_container() {
		if (!this.button) return this.root?.closest?.("[data-role]");

		const parent = this.button.parentElement?.closest?.("[data-role]");
		if (parent && !this.button.dataset.role) return parent;
		return parent?.dataset.role === this.button.dataset.role
			? parent
			: this.button;
	}

	get elt() {
		return this.container || this.root;
	}

	get readonly() {
		return Boolean(
			this.widget?.readonly ||
				this.source?.dataset.readonly === "true" ||
				this.root?.dataset.readonly === "true" ||
				this.source?.disabled,
		);
	}

	get active() {
		return Object.keys(this.details).length > 0;
	}

	init() {
		if (!this.root) return;

		if (this.readonly) {
			this._initReadonly();
			return;
		}

		this.button ? this._initButtonFacet() : this._initInputFacet();
	}

	_preload() {
		const raw = this.source?.dataset.preload || this.root?.dataset.preload;
		if (!raw) return [];

		try {
			const parsed = JSON.parse(raw);
			if (Array.isArray(parsed)) {
				return parsed.filter((item) => {
					if (!item) return false;
					return typeof item !== "object" || Object.keys(item).length > 0;
				});
			}
			if (parsed && typeof parsed === "object") {
				return Object.keys(parsed).length > 0 ? [parsed] : [];
			}
			return parsed ? [parsed] : [];
		} catch {
			return [];
		}
	}

	_initReadonly() {
		this.root.dataset.readonly = "true";
		const rows = this._preload()
			.map((details) =>
				detailsLinkRow({
					kind: this.kind,
					index: this.index,
					...details,
				}),
			)
			.filter(Boolean);

		if (rows.length === 0) return;
		this.source.replaceWith(...rows);
	}

	_initButtonFacet() {
		this.toggle = new SectionToggle(this, this.widget);
		this.toggle.display();

		this.select = new FacetsBox(this.button);
		this.element = document.createElement("input");
		this.element.className = STYLES.select.default;
		this.element.dataset.visible = "false";
		this.element.dataset.kind = this.kind;
		this.element.name = this.button.dataset.name || this.index;
		this.button.after(this.element);

		this.select.element = this.element;
		if (this.active) this.select.addOption(this.details, true);
		this.select.init();

		this.select.element.addEventListener("updated", this._updated);
		this.select.element.addEventListener("deactivate", this._deactivate);
	}

	_initInputFacet() {
		this.select = new FacetsBox(this.root);
		this.select.init();
	}

	_updated(e) {
		if (Object.values(e.detail.options).length > 0) {
			this.details = Object.values(e.detail.options)[0];
		} else {
			this.details = {};
		}
		this.open = false;
		this._reconcile();
	}

	_deactivate() {
		this.open = false;
		this._reconcile();
	}

	toggleVisibility() {
		if (this.readonly) return;
		this.open = !this.open;
		this._reconcile();
	}

	_reconcile() {
		if (!this.button || !this.element) return;

		withTransition(() => {
			if (!this.open) {
				this.button.dataset.visible = "true";
				this.element.dataset.visible = "false";
				this.button.focus({ preventScroll: true });
			} else {
				this.button.dataset.visible = "false";
				this.element.dataset.visible = "true";
				this.element.focus({ preventScroll: true });
				this.select.showPanel();
			}
			this.toggle.display();
		});
	}

	addOption(option) {
		this.details = option || {};
		this.select?.addOption(option);
		this.toggle?.display();
	}

	clear() {
		if (this.readonly) return;
		this.details = {};
		this.select?.clear();
		this.open = false;
		this._reconcile();
	}

	destroy() {
		if (this.select?.element) {
			this.select.element.removeEventListener("updated", this._updated);
			this.select.element.removeEventListener("deactivate", this._deactivate);
		}
		this.select?.destroy();
	}
}

export { SectionToggle as S };
