/*! Third-party licenses: /third-party-licenses.txt */
import { w as withTransition } from './foundation.js?v=be84e1e9';
import { B as BaseUpload, u as uploadElement, U as UploadMenu, T as TaskUpload } from './uploads.js?v=be84e1e9';
import { p as primitives, b as buttons, f as formatting } from './ui-controls.js?v=be84e1e9';
import { S as STYLES, s as setIcon, i as iconDefinition } from './ui-resources.js?v=be84e1e9';
import { i as isFacetOption, a as FacetsBox } from './forms.js?v=be84e1e9';

const AUTOFILL_DROPZONE_TEXT = "Click or drop to add a related image or a pdf";
class AutofillUpload extends BaseUpload {
  constructor(attributes) {
    super(attributes);
    this.parent = attributes.parent;
    this.target = attributes.target;
    this.name = "autofill";
    this.icon = "generate";
    this.uploadType = "file";
    this.deferred = true;
    this.messages = {
      submit: "Autofill Form",
      submitting: "Starting...",
      submitted: "Autofill queued"
    };
    this.context = uploadElement.contextUpload({
      text: AUTOFILL_DROPZONE_TEXT
    });
    this.inputName = "autofill-file";
    this.dropzone = this.context.dropzone;
    this.menuOptions = ["remove", "replace", "paste"];
    this.uploadMenu = new UploadMenu(this);
    this._initialized = false;
    this._click = this._click.bind(this);
  }
  async init() {
    this.parent.target.addEventListener("click", this._click);
  }
  get submitGroup() {
    return this.target.querySelector(
      "[data-role='autofill-submit-group']"
    );
  }
  get submitButton() {
    return this.submitGroup?.querySelector(
      "button[type='submit']"
    ) ?? null;
  }
  _canFallbackToMultipart() {
    return false;
  }
  async _click(e) {
    const role = e.target instanceof Element ? e.target.closest("button")?.dataset.role : void 0;
    if (role !== "cancel-autofill" && role !== "show-autofill") return;
    e.preventDefault();
    e.stopPropagation();
    if (!this._initialized) {
      await super.init();
      if (this.submitGroup) this.target.append(this.submitGroup);
      this._initialized = true;
    }
    await withTransition(
      () => {
        if (role === "show-autofill") {
          this.target.dataset.visible = "true";
          this.parent.form?.toggleSubForm(this);
          this.target.querySelector("textarea")?.focus();
        } else if (role === "cancel-autofill") {
          this.target.dataset.visible = "false";
          this.parent.form?.toggleSubForm();
          this.reset();
          const textarea = this.target.querySelector("textarea");
          if (textarea) textarea.value = "";
        }
      },
      { label: `autofill:${role}` }
    );
  }
  get html() {
    return [this.context.element];
  }
}

const autofill = (form) => {
  const section = form.target.querySelector(
    '[data-role="autofill"]'
  );
  if (!section) return null;
  const autofill2 = new AutofillUpload({
    target: section,
    parent: form
  });
  autofill2.init();
  form.destroyables.push(autofill2);
  return section;
};
const generateEntityForm = (form) => {
  const section = form.target.querySelector(
    'div[data-role="generate"]'
  );
  if (!section) return null;
  const manualButton = section.querySelector(
    'button[data-role="manual"]'
  );
  const aiButton = section.querySelector(
    'button[data-role="ai"]'
  );
  const generate = section.querySelector('[name="generate"]');
  const description = section.querySelector(
    '[name="user_description"]'
  );
  const aiFields = section.querySelectorAll(
    '[data-role="ai"]:not(button)'
  );
  if (!manualButton || !aiButton || !generate || !description) return section;
  const setMode = (mode) => {
    form.target.dataset.mode = mode;
    aiFields.forEach((element) => {
      element.dataset.visible = mode === "ai" ? "true" : "false";
    });
    form.target.querySelectorAll('[data-role="manual"]').forEach((element) => {
      if (!section.contains(element)) {
        element.dataset.visible = mode === "manual" ? "true" : "false";
      }
    });
  };
  setMode(form.target.dataset.mode || "manual");
  aiButton.addEventListener("click", () => {
    withTransition(() => {
      const changed = !generate.checked;
      setMode("ai");
      manualButton.dataset.active = "false";
      aiButton.dataset.active = "true";
      generate.checked = true;
      if (changed)
        generate.dispatchEvent(new Event("change", { bubbles: true }));
      description.focus();
    });
  });
  manualButton.addEventListener("click", () => {
    withTransition(() => {
      const changed = generate.checked;
      setMode("manual");
      manualButton.dataset.active = "true";
      aiButton.dataset.active = "false";
      generate.checked = false;
      if (changed)
        generate.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });
  return section;
};
const generateImageForm = () => {
  const container = document.createElement("div");
  container.dataset.role = "generate-image";
  container.className = "flex flex-col gap-4";
  container.dataset.visible = "false";
  const usePageInfo = primitives.checkbox({
    label: "Use page info",
    name: "info",
    checked: true});
  const prompt = primitives.textarea({
    name: "prompt",
    placeholder: "or describe the image you wish to create",
    rows: 3});
  const submitGroup = document.createElement("div");
  submitGroup.dataset.role = "submit-group";
  submitGroup.className = "flex flex-wrap gap-2 w-full";
  submitGroup.appendChild(
    buttons.default({
      role: "cancel",
      text: "Cancel",
      kind: "default",
      type: "button"
    })
  );
  submitGroup.appendChild(
    buttons.default({
      role: "generate",
      text: "Generate",
      kind: "page",
      type: "submit",
      icon: "generate"
    })
  );
  container.append(usePageInfo, prompt, submitGroup);
  return {
    element: container,
    submitGroup,
    reset: () => {
      usePageInfo.checked = false;
      prompt.value = "";
    },
    visible: () => {
      return container.dataset.visible === "true";
    },
    hide: () => {
      container.dataset.visible = "false";
    },
    show: () => {
      container.dataset.visible = "true";
      prompt.focus();
    }
  };
};
const sections = {
  generateEntityForm,
  generateImageForm,
  autofill
};

function isRecord(value) {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
function optionalText(value) {
  return value == null || typeof value === "string";
}
function isRepeatDetails(value) {
  return value == null || isRecord(value) && optionalText(value.description) && optionalText(value.text);
}
function isSchedule(value) {
  if (!isRecord(value) || !optionalText(value.due) || !optionalText(value.start_date))
    return false;
  const { recurring, scheduled, periodic } = value;
  return (recurring == null || isRecord(recurring) && optionalText(recurring.unit) && (optionalText(recurring.interval) || typeof recurring.interval === "number")) && (scheduled == null || isRecord(scheduled) && isRepeatDetails(scheduled) && optionalText(scheduled.mode) && (scheduled.days == null || Array.isArray(scheduled.days) && scheduled.days.every(
    (day) => typeof day === "number" || typeof day === "string"
  ))) && isRepeatDetails(periodic);
}
function isRepeatGroup(group) {
  return group === "recurring" || group === "scheduled" || group === "periodic";
}
function isScheduleGroup(group) {
  return group === "weekly" || group === "monthly" || group === "yearly";
}
class DueDate {
  constructor(button, widget) {
    this.widget = widget;
    this.action = button.dataset.action;
    this.button = button;
    this.kind = "task";
    this.aiEnabled = this.button.dataset.aiEnabled !== "false";
    const schedule = JSON.parse(this.button.dataset.schedule ?? "{}");
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
  _click(e) {
    const role = e.target instanceof Element ? e.target.closest("[data-role]")?.dataset.role : void 0;
    if (!role) return;
    const input = this.groups.dueDate?.querySelector("input");
    switch (role) {
      case "today":
        this.schedule.due = (/* @__PURE__ */ new Date()).toLocaleDateString("sv-SE");
        if (input) input.value = this.schedule.due;
        break;
      case "remove-due-date":
        if (input) input.value = "";
        this.schedule.due = null;
        break;
    }
  }
  _input(e) {
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
  _change(e) {
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
          }
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
        this.weekly.querySelectorAll("input:checked")
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
  showError(message) {
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
        if (!this.schedule.scheduled.days || this.schedule.scheduled.days.length === 0) {
          return "Weekly scheduled tasks must specify at least one day.";
        }
      } else if (this.schedule.scheduled.mode === "monthly" || this.schedule.scheduled.mode === "yearly") {
        if (!this.schedule.scheduled.description || this.schedule.scheduled.description.trim() === "") {
          return "Monthly and yearly scheduled tasks must include a description.";
        }
      }
    }
    if (this.schedule.periodic) {
      if (!this.schedule.periodic.description || this.schedule.periodic.description.trim() === "") {
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
        role: "date-form"
      }
    });
    this.button.after(this.container);
    const choices = this.container.appendChild(
      primitives.div({
        style: "flex flex-col gap-3 pt-3"
      })
    );
    const toggles = {
      recurring: primitives.checkbox({
        name: "recurring",
        label: "This task repeats when completed",
        checked: !!this.schedule.recurring
      }),
      scheduled: primitives.checkbox({
        name: "scheduled",
        label: "This task repeats on a schedule",
        checked: !!this.schedule.scheduled
      }),
      periodic: primitives.checkbox({
        name: "periodic",
        label: "This task repeats periodically",
        checked: !!this.schedule.periodic
      })
    };
    this.toggles = toggles;
    choices.append(
      this.dueDate,
      toggles.recurring,
      toggles.scheduled,
      ...this.aiEnabled ? [toggles.periodic] : []
    );
  }
  clearGroup(container) {
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
      role: "due-date"
    });
    dueDateGroup.appendChild(
      primitives.input({
        name: "due-date",
        type: "date",
        value: this.schedule.due || "",
        label: "Due Date",
        data: {
          role: "set-due-date"
        }
      })
    );
    const buttonRow = dueDateGroup.appendChild(
      primitives.div({
        style: "flex flex-col sm:flex-row gap-2 mt-3"
      })
    );
    buttonRow.appendChild(
      buttons.default({
        text: "Today",
        role: "today"
      })
    );
    buttonRow.appendChild(
      buttons.default({
        text: "Remove",
        role: "remove-due-date"
      })
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
        visible: this.schedule.recurring ? "true" : "false"
      }
    });
    const afterRow = recurringOptions.appendChild(
      primitives.div({ style: "flex flex-row items-center gap-2 mt-4" })
    );
    afterRow.appendChild(
      primitives.span({ style: STYLES.label.default, text: "After" })
    );
    afterRow.appendChild(
      primitives.input({
        name: "interval",
        type: "number",
        value: this.schedule.recurring?.interval || "1"
      })
    );
    const unitWrapper = recurringOptions.appendChild(
      primitives.div({ style: "flex flex-col gap-2" })
    );
    const units = [
      {
        label: "day",
        value: "day",
        name: "unit",
        checked: this.schedule.recurring?.unit === "day" || !this.schedule.recurring?.unit
      },
      {
        label: "week",
        value: "week",
        name: "unit",
        checked: this.schedule.recurring?.unit === "week"
      },
      {
        label: "month",
        value: "month",
        name: "unit",
        checked: this.schedule.recurring?.unit === "month"
      },
      {
        label: "year",
        value: "year",
        name: "unit",
        checked: this.schedule.recurring?.unit === "year"
      }
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
      data: { visible: this.schedule.scheduled ? "true" : "false" }
    });
    const scheduleType = scheduledOptions.appendChild(
      document.createElement("div")
    );
    scheduleType.className = "flex flex-row items-center gap-2";
    const currentMode = this.schedule.scheduled?.mode || "daily";
    const scheduleTypes = [
      {
        label: "Daily",
        value: "daily",
        name: "schedule-type",
        checked: currentMode === "daily"
      },
      {
        label: "Weekly",
        value: "weekly",
        name: "schedule-type",
        checked: currentMode === "weekly"
      },
      ...this.aiEnabled ? [
        {
          label: "Monthly",
          value: "monthly",
          name: "schedule-type",
          checked: currentMode === "monthly"
        },
        {
          label: "Yearly",
          value: "yearly",
          name: "schedule-type",
          checked: currentMode === "yearly"
        }
      ] : []
    ];
    const scheduleTypeWrapper = scheduledOptions.appendChild(
      document.createElement("div")
    );
    scheduleTypeWrapper.className = "flex flex-col gap-2";
    const scheduleSettings = scheduleTypeWrapper.appendChild(
      document.createElement("fieldset")
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
        visible: this.schedule.scheduled?.mode === "weekly" ? "true" : "false"
      }
    });
    this.groups.scheduled?.appendChild(weeklyOptions);
    const weekDays = [
      "Monday",
      "Tuesday",
      "Wednesday",
      "Thursday",
      "Friday",
      "Saturday",
      "Sunday"
    ];
    weekDays.forEach((day, index) => {
      weeklyOptions.appendChild(
        primitives.checkbox({
          label: day,
          value: index,
          name: `weekly-day-${index}`,
          checked: this.schedule.scheduled?.days?.includes(index) || false
        })
      );
    });
    return weeklyOptions;
  }
  _createMonthlySchedule() {
    const monthlyOptions = primitives.div({
      style: "flex flex-col gap-2",
      role: "monthly",
      data: {
        visible: this.schedule.scheduled?.mode === "monthly" ? "true" : "false"
      }
    });
    this.groups.scheduled?.appendChild(monthlyOptions);
    monthlyOptions.appendChild(
      primitives.input({
        name: "monthly-description",
        type: "text",
        placeholder: "e.g., first Monday, last day, 15th",
        value: this.schedule.scheduled?.mode === "monthly" ? this.schedule.scheduled?.description || "" : "",
        label: "Describe when this repeats (description will be parsed by AI)"
      })
    );
    return monthlyOptions;
  }
  _createYearlySchedule() {
    const yearlyOptions = primitives.div({
      style: "flex flex-col gap-2",
      role: "yearly",
      data: {
        visible: this.schedule.scheduled?.mode === "yearly" ? "true" : "false"
      }
    });
    this.groups.scheduled?.appendChild(yearlyOptions);
    yearlyOptions.appendChild(
      primitives.input({
        name: "yearly-description",
        type: "text",
        placeholder: "e.g., December 25th, third Thursday in November",
        value: this.schedule.scheduled?.mode === "yearly" ? this.schedule.scheduled?.description || "" : "",
        label: "Describe when this repeats (description will be parsed by AI)"
      })
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
      data: { visible: this.schedule.periodic ? "true" : "false" }
    });
    const startDate = periodicOptions.appendChild(
      primitives.input({
        name: "start-date",
        type: "date",
        value: this.schedule.start_date || (/* @__PURE__ */ new Date()).toLocaleDateString("sv-SE"),
        label: "Start Date"
      })
    );
    startDate.classList.add("mb-2");
    periodicOptions.appendChild(
      primitives.input({
        name: "periodic-description",
        type: "text",
        placeholder: "e.g., every 3 days, every 2 weeks, biweekly, quarterly",
        value: this.schedule.periodic?.description || "",
        label: "Describe how often this repeats (description will be parsed by AI)"
      })
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

const clearButton = (open, label, onClick) => {
  const button = document.createElement("button");
  button.dataset.role = "clear";
  button.dataset.kind = "delete";
  button.type = "button";
  button.className = STYLES.select.action;
  button.setAttribute("aria-label", label);
  button.title = label;
  setIcon(
    button.appendChild(document.createElement("span")),
    open ? "x" : "clear",
    "icon-sm"
  );
  button.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    onClick();
  });
  return button;
};
const openLinkButton = (parent) => {
  if (!parent.index || !parent.active || parent.open || !parent.details?.id) {
    return null;
  }
  const details = {
    kind: parent.kind,
    index: parent.index,
    ...parent.details
  };
  const href = formatting.url(details).toString();
  const label = parent.details.name ? `Open ${parent.details.name}` : `Open ${parent.button?.dataset.title || "item"}`;
  const link = document.createElement("a");
  link.dataset.role = "open-link";
  link.dataset.kind = String(details.kind || parent.kind || "default");
  link.href = href;
  link.className = STYLES.select.action;
  link.setAttribute("aria-label", label);
  link.title = label;
  setIcon(link.appendChild(document.createElement("span")), "right", "icon-sm");
  return link;
};
const dueDateText = (parent) => {
  if (!parent.active) {
    return formatting.text({
      kind: parent.kind,
      text: parent.button?.dataset.title
    });
  }
  const schedule = parent.schedule ?? {};
  let displayText = "Due";
  if (schedule.due) {
    displayText += ` ${formatting.date(schedule.due)}`;
  } else {
    displayText = "No Due Date";
  }
  if (schedule.recurring) {
    const interval = schedule.recurring.interval || "1";
    const unit = schedule.recurring.unit || "day";
    const pluralUnit = parseInt(String(interval), 10) > 1 ? `${unit}s` : unit;
    displayText += ` (repeats when completed after ${interval} ${pluralUnit})`;
  } else if (schedule.scheduled) {
    displayText += ` (repeats ${schedule.scheduled.text || schedule.scheduled.mode})`;
  } else if (schedule.periodic) {
    displayText += ` (repeats ${schedule.periodic.text || "periodically"})`;
  }
  return formatting.text({ kind: parent.kind, text: displayText });
};
const detailsText = (parent) => {
  if (!parent.active) {
    return formatting.text({
      kind: parent.kind,
      text: parent.button?.dataset.title
    });
  }
  return formatting.name({ ...parent.details, link: false });
};
const fileText = (parent) => {
  const firstAsset = Object.values(parent.assets || {})[0];
  const filename = parent.filename || firstAsset?.name || firstAsset?.filename || "";
  if (!parent.active || !filename) {
    return formatting.text({
      kind: parent.kind,
      text: "Attach File/Photo"
    });
  }
  return formatting.text({
    kind: parent.kind,
    text: filename
  });
};
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
      iconClasses: "text-kind-default"
    })
  );
  return row;
};
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
      widget?.readonly || parent?.readonly || parent?.button?.dataset.readonly === "true" || parent?.button?.disabled
    );
    this.row = null;
    this.init();
  }
  _ensureRow() {
    const button = this.parent.button;
    if (!button) return null;
    const existing = button.parentElement;
    if (existing?.dataset.role === "section-toggle-row") {
      this.row = existing;
      return this.row;
    }
    if (!existing) return null;
    const row = document.createElement("div");
    row.dataset.role = "section-toggle-row";
    if (this.parent.kind) row.dataset.kind = this.parent.kind;
    row.className = STYLES.select.row;
    existing.insertBefore(row, button);
    row.appendChild(button);
    this.row = row;
    return row;
  }
  init() {
    this._ensureRow();
    if (this.readonly) return;
    this.parent.button?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.parent.toggleVisibility();
    });
    this.parent.button?.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || !this.parent.open) return;
      e.preventDefault();
      e.stopPropagation();
      this.parent.toggleVisibility();
    });
  }
  _setButtonReadonly() {
    if (!this.readonly) return;
    const button = this.parent.button;
    if (!button) return;
    button.dataset.readonly = "true";
    button.disabled = true;
    button.setAttribute("aria-disabled", "true");
  }
  display() {
    const button = this.parent.button;
    if (!button) return;
    const row = this._ensureRow();
    let text = "";
    if (this.parent.action === "schedule") {
      text = dueDateText(this.parent);
    } else if (this.parent.index) {
      text = detailsText(this.parent);
    } else if (this.parent.action === "uploadFile") {
      text = fileText(this.parent);
    }
    const label = document.createElement("span");
    label.className = STYLES.select.label;
    if (typeof text === "string") label.textContent = text;
    else label.appendChild(text);
    const fullText = label.textContent?.trim() || "";
    if (fullText) button.title = fullText;
    else button.removeAttribute("title");
    const contents = [label];
    if (!this.readonly) {
      button.setAttribute("aria-expanded", String(Boolean(this.parent.open)));
      const chevron = document.createElement("span");
      setIcon(chevron, "down", STYLES.select.expandIndicator);
      contents.push(chevron);
    } else {
      button.removeAttribute("aria-expanded");
    }
    button.replaceChildren(...contents);
    if (row) {
      for (const node of row.querySelectorAll(
        ":scope > [data-role='open-link'], :scope > [data-role='clear']"
      )) {
        node.remove();
      }
      const link = openLinkButton(this.parent);
      if (link) row.appendChild(link);
      if (!this.readonly && (this.parent.active || this.parent.open)) {
        const fieldTitle = button.dataset.title || "selection";
        const clearLabel = this.parent.open ? `Close ${fieldTitle}` : `Clear ${fieldTitle}`;
        row.appendChild(
          clearButton(this.parent.open, clearLabel, () => this.parent.clear())
        );
      }
    }
    this._setButtonReadonly();
  }
}
class FacetControl {
  constructor(widget, element) {
    this.widget = widget;
    this.root = element?.closest("[lp-select]") || element;
    this.button = this.root?.matches("button[lp-select]") ? this.root : null;
    this.container = this._container();
    this.input = this.button ? null : this.root?.querySelector("input, select") || this.root;
    this.source = this.button || this.input || this.root;
    this.action = this.source?.dataset.action;
    this.index = this.source?.dataset.index || this.root?.dataset.index;
    this.kind = this.source?.dataset.kind || this.root?.dataset.kind || this.index;
    this.details = this._preload()[0] || {};
    this.select = null;
    this.element = null;
    this.toggle = null;
    this.open = false;
    this._updated = this._updated.bind(this);
    this._deactivate = this._deactivate.bind(this);
  }
  _container() {
    if (!this.button)
      return this.root?.closest("[data-role]") ?? null;
    const parent = this.button.parentElement?.closest("[data-role]");
    if (parent && !this.button.dataset.role) return parent;
    return parent && parent.dataset.role === this.button.dataset.role ? parent : this.button;
  }
  get elt() {
    return this.container || this.root;
  }
  get readonly() {
    return Boolean(
      this.widget?.readonly || this.source?.dataset.readonly === "true" || this.root?.dataset.readonly === "true" || this.source?.disabled
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
      return (Array.isArray(parsed) ? parsed : [parsed]).filter(isFacetOption).filter((item) => Object.keys(item).length > 0);
    } catch {
      return [];
    }
  }
  _initReadonly() {
    if (!this.root || !this.source) return;
    this.root.dataset.readonly = "true";
    const rows = this._preload().map(
      (details) => detailsLinkRow({
        kind: this.kind,
        index: this.index,
        ...details
      })
    ).filter((row) => row !== null);
    if (rows.length === 0) return;
    this.source.replaceWith(...rows);
  }
  _initButtonFacet() {
    if (!this.button) return;
    this.toggle = new SectionToggle(this, this.widget);
    this.toggle.display();
    this.select = new FacetsBox(this.button);
    this.element = document.createElement("input");
    this.element.className = STYLES.select.default;
    this.element.dataset.visible = "false";
    this.element.dataset.kind = String(this.kind);
    this.element.name = String(this.button.dataset.name || this.index);
    this.button.after(this.element);
    this.select.element = this.element;
    this.select.init();
    this.select.element.addEventListener("updated", this._updated);
    this.select.element.addEventListener("deactivate", this._deactivate);
  }
  _initInputFacet() {
    if (!this.root) return;
    this.select = new FacetsBox(this.root);
    this.select.init();
  }
  _updated(e) {
    const detail = e instanceof CustomEvent ? e.detail : null;
    const options = detail && typeof detail === "object" && "options" in detail ? detail.options : null;
    this.details = options && typeof options === "object" ? Object.values(options).find(isFacetOption) ?? {} : {};
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
    const { button, element, select, toggle } = this;
    if (!button || !element) return;
    withTransition(() => {
      if (!this.open) {
        button.dataset.visible = "true";
        element.dataset.visible = "false";
        button.focus({ preventScroll: true });
      } else {
        button.dataset.visible = "false";
        element.dataset.visible = "true";
        element.focus({ preventScroll: true });
        select?.showPanel();
      }
      toggle?.display();
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

export { SectionToggle as S, sections as s };
