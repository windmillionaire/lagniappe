/*! Third-party licenses: /third-party-licenses.txt */
import { s as setIcon, S as STYLES } from './ui-resources.js?v=be84e1e9';
import { w as withTransition, g as generateElementId } from './foundation.js?v=be84e1e9';
import { p as primitives } from './ui-controls.js?v=be84e1e9';
import { F as FormController, S as SelectBox } from './forms.js?v=be84e1e9';
import { f as fieldKind, C as CONFIG } from './builder.js?v=be84e1e9';

class Condition {
  constructor(builder) {
    this.builder = builder;
    this.element = builder.selectedElement;
    this.target = document.createElement("div");
    this.target.className = "flex flex-col gap-4";
    this.submitButton = this._createSubmitButton();
    this.header = this._createHeader();
    this.progress = this._createProgress();
    this.form = null;
    this.destroyables = [];
    this.options = /* @__PURE__ */ new Map();
    this.complete = false;
    this.focusTarget = null;
    this.index = -1;
    this._successTimer = null;
  }
  get html() {
    return [this.progress];
  }
  init() {
    this.destroy();
    if (this.draftSetting) {
      this.setting = structuredClone(this.draftSetting);
      delete this.draftSetting;
    }
    this.complete = false;
    this.form = new FormController(this);
    this.form.init();
    return;
  }
  showSuccess() {
    clearTimeout(this._successTimer ?? void 0);
    const status = document.createElement("span");
    const icon = status.appendChild(document.createElement("span"));
    status.dataset.kind = "success";
    setIcon(icon, "check", "ml-2 text-kind-default");
    this.header.querySelector("[data-role='title']")?.appendChild(status);
    this._successTimer = setTimeout(() => {
      void withTransition(() => status.remove(), {
        label: "builder:condition-success"
      });
    }, 1e3);
  }
  _createProgress() {
    const progress = document.createElement("div");
    progress.dataset.role = "updates";
    progress.dataset.visible = "false";
    progress.className = "flex flex-col gap-4";
    return progress;
  }
  showProgress() {
    for (const option of this.options.values()) {
      if (!this.progress.contains(option)) {
        this.progress.appendChild(option);
      }
    }
    this.progress.dataset.visible = "true";
    if (this.complete) {
      this.form?.showSubmitButton();
    }
  }
  hideProgress() {
    withTransition(() => {
      this.progress.dataset.visible = "false";
    });
  }
  focus() {
    const target = this.focusTarget || this.target;
    const inputSelector = "input:not([type='hidden']):not([disabled])";
    const textareaSelector = "textarea:not([disabled])";
    const selectSelector = "select:not([disabled])";
    const selector = `${inputSelector}, ${textareaSelector}, ${selectSelector}`;
    const focusable = target?.matches?.(selector) ? target : target?.querySelector?.(inputSelector) ?? target?.querySelector?.(textareaSelector) ?? target?.querySelector?.(selectSelector);
    focusable?.focus();
  }
  _createHeader() {
    const header = document.createElement("div");
    header.className = STYLES.form.header.container;
    const title = header.appendChild(document.createElement("div"));
    title.className = STYLES.form.header.title;
    title.dataset.role = "title";
    const controls = header.appendChild(document.createElement("div"));
    controls.className = STYLES.form.header.controls;
    controls.appendChild(
      primitives.toggle({ icon: "help", data: { kind: "help", role: "help" } })
    );
    controls.appendChild(
      primitives.toggle({
        icon: "close",
        data: { kind: "close", role: "close" }
      })
    );
    return header;
  }
  setTitle(title) {
    const node = this.header.querySelector("[data-role='title']");
    if (node) node.textContent = title;
  }
  _createSubmitButton() {
    const submitButton = document.createElement("button");
    submitButton.className = `${STYLES.button.submit}`;
    submitButton.dataset.visible = "false";
    submitButton.dataset.role = "save";
    return submitButton;
  }
  validate() {
    return false;
  }
  refreshSavedState() {
  }
  clearOptions() {
    for (const option of this.options.values()) option.remove();
    this.options.clear();
  }
  destroy() {
    clearTimeout(this._successTimer ?? void 0);
    this._successTimer = null;
    this.form?.destroy?.();
    this.form = null;
    this.destroyables.forEach((destroyable) => {
      destroyable?.destroy?.();
    });
    this.clearOptions();
    this.destroyables = [];
    this.focusTarget = null;
  }
}
class ConditionTarget extends Condition {
  addTargetSelect() {
    const selectElt = primitives.select({
      options: this.builder.getEligibleConditionTargets(),
      placeholder: "select a target element...",
      id: "target-element"
    });
    this.header.after(selectElt);
    const selectBox = new SelectBox(selectElt);
    if (this.setting.id) {
      selectBox.values.add(this.setting.id);
    }
    selectBox.init();
    this.destroyables.push(selectBox);
    this.focusTarget = selectElt;
    selectElt.addEventListener("updated", (e) => {
      this.clearOptions();
      const options = Object.values(
        e.detail.options
      );
      this.setting.id = options[0].id;
      this.setting.name = options[0].name;
      this.showProgress();
    });
  }
  addCheckboxTarget() {
    if (this.options.has("checkbox")) return;
    delete this.setting.value;
    this.setting.type = "checkbox";
    this.setting.checked = true;
    const checkboxMessage = document.createElement("p");
    checkboxMessage.dataset.kind = "success";
    checkboxMessage.textContent = "is checked";
    checkboxMessage.className = "font-semibold text-medium text-kind-default";
    this.options.set("checkbox", checkboxMessage);
  }
  addChooseValue() {
    if (this.options.has("value")) return;
    const element = this.setting.id && this.builder.elements.get(this.setting.id);
    if (!element) return;
    this.setting.type = element.schema.type;
    const options = element.schema.options || [];
    if (options.length > 0) {
      const selectElt = primitives.select({
        options: options.map((option) => ({
          label: option.label,
          value: option.value,
          details: {
            icon: this.setting.type === "radio" ? "radio" : "select",
            kind: "form",
            name: option.label
          }
        })),
        placeholder: "select an option...",
        id: "eligible-options"
      });
      const selectBox = new SelectBox(selectElt);
      if (typeof this.setting.value === "string" && this.setting.value) {
        selectBox.values.add(this.setting.value);
      }
      selectBox.init();
      this.destroyables.push(selectBox);
      this.options.set("value", selectElt);
      this.focusTarget = selectElt;
      selectElt.addEventListener("updated", (e) => {
        const options2 = Object.values(
          e.detail.options
        );
        this.setting.value = options2[0].id;
        this.setting.label = options2[0].name;
        this.showProgress();
      });
    } else {
      this.form?.showError("The target element must have at least one option.");
    }
  }
  validate() {
    if (!this.setting.id) {
      this.form?.showError("Please select a target element.");
      return false;
    } else if (this.setting.checked) {
      return true;
    } else if (this.setting.value) {
      return true;
    } else {
      this.form?.showError("Please select an option.");
      return false;
    }
  }
}

const MESSAGES = {
  checkbox: {
    text: "Values will be converted to 'True' or 'False'.",
    radio: "Component will be converted to a Radio with 'True' and 'False' values."
  },
  out: {
    text: "Values will be converted to a plain-text url",
    bookmark: "Values will not change"
  },
  location: { text: "Values will be converted to plain-text addresses" },
  textarea: { text: "Values will be converted to text; newlines will be lost" },
  radio: {
    text: "Values will be converted to the plain-text label of the option selected",
    select: "Component will be converted into a Select component with the same options"
  },
  select: {
    text: "Values will be converted to the plain-text label of the option selected",
    radio: "Component will be converted into a Radio component with the same options"
  },
  table: {
    textarea: "Values will be converted to a table with Markdown formatting"
  },
  todo: {
    textarea: "Values will be converted to a todo list with Markdown formatting"
  }
};
class Modify extends Condition {
  init() {
    this.destroy();
    this.setTitle("Replace or Delete");
    const help = this.header.querySelector("[data-role='help']");
    help?.setAttribute("lp-control", "help");
    help?.setAttribute("lp-help", "form_element_changes");
    help?.setAttribute(
      "aria-label",
      "Help with converting or deleting form elements"
    );
    this.target.replaceChildren(this.header);
    const deletion = this.target.appendChild(document.createElement("p"));
    deletion.className = "text-sm text-base-medium";
    deletion.textContent = "If an element is deleted, any values entered using that element in current submissions will be cleared, with the exception of tasks that have already been completed. Already completed tasks will retain the form that accompanied their original submitted values.";
    const source = this.builder.savedField(this.element.schema.id) || this.element.schema;
    const sourceKind = fieldKind(source);
    const kind = fieldKind(this.element.schema);
    const choices = (this.builder.conversionCatalog?.types || []).filter(
      (item) => {
        const rule = this.builder.conversionCatalog?.rules[sourceKind]?.[item.value];
        return rule && item.value !== (kind === "multiple" ? "select" : kind) && item.value !== "multiple" && !(this.builder.elt.dataset.formType === "page" && item.value === "todo");
      }
    );
    const actions = document.createElement("div");
    actions.className = choices.length ? "grid grid-cols-2 gap-3" : "grid grid-cols-1 gap-3";
    if (choices.length) {
      const explanation = this.target.appendChild(document.createElement("p"));
      explanation.className = "text-sm text-base-medium";
      explanation.textContent = "If you replace the element instead, those values will be converted in order to match the new component type. Values that cannot be converted will be cleared.";
      this.addReplacement(choices, source, actions);
    } else {
      const unavailable = this.target.appendChild(document.createElement("p"));
      unavailable.dataset.role = "conversion-unavailable";
      unavailable.dataset.kind = "error";
      unavailable.className = "text-sm text-kind-default";
      unavailable.textContent = "This component type cannot be converted";
    }
    this.target.append(actions);
    const remove = actions.appendChild(document.createElement("button"));
    remove.type = "button";
    remove.dataset.kind = "delete";
    remove.className = STYLES.button.submit;
    remove.textContent = "Delete";
    remove.addEventListener("click", () => {
      void withTransition(
        () => {
          if (this.builder._destroyed || this.builder.selectedElement !== this.element)
            return;
          this.builder.conditions.close();
          this.builder.removeElement();
          this.builder.settings.deselectItem();
          this.builder.formSettings.visible = true;
        },
        { label: "builder:delete-element" }
      );
    });
  }
  addReplacement(choices, source, actions) {
    const sourceKind = fieldKind(source);
    const selectElt = primitives.select({
      label: "Replace With",
      kind: "form",
      data: { kind: "form" },
      name: "conversion-type",
      placeholder: "Choose a new component...",
      selectIcon: "dropdown",
      options: []
    });
    this.target.append(selectElt);
    const select = selectElt.querySelector("select");
    const catalog = this.builder.conversionCatalog;
    if (!select || !catalog) return;
    const canUseAI = this.builder.elt.dataset.aiConversion === "true";
    for (const [title, ai] of [
      ["Deterministic conversions", false],
      ["AI conversions", true]
    ]) {
      const group = document.createElement("optgroup");
      group.label = title;
      for (const item of choices) {
        const rule = catalog.rules[sourceKind]?.[item.value];
        if (rule === "ai" !== ai) continue;
        const label = CONFIG.TABLE_COLUMNS.find(({ type }) => type === item.value)?.name || item.label;
        const name = ai ? `${label} (requires AI${canUseAI ? "" : " access"})` : label;
        const option = new Option(name, item.value);
        option.dataset.details = JSON.stringify({
          kind: "form",
          icon: item.value === "todo" ? "checklist" : item.value,
          name
        });
        option.disabled = ai && !canUseAI;
        group.append(option);
      }
      if (group.childElementCount) select.append(group);
    }
    const selectBox = new SelectBox(selectElt);
    selectBox.init();
    this.destroyables.push(selectBox);
    this.focusTarget = selectElt;
    const description = this.target.appendChild(document.createElement("p"));
    description.dataset.role = "conversion-description";
    description.dataset.kind = "success";
    description.className = "text-sm text-kind-default";
    description.setAttribute("aria-live", "polite");
    description.hidden = true;
    const instructionLabel = this.target.appendChild(
      document.createElement("label")
    );
    instructionLabel.className = "flex flex-col gap-2 text-sm";
    instructionLabel.textContent = "Conversion instructions (optional)";
    const instructions = instructionLabel.appendChild(
      document.createElement("textarea")
    );
    instructions.name = "conversion-instructions";
    instructions.className = STYLES.textarea;
    instructions.rows = 3;
    instructions.maxLength = 4e3;
    instructions.placeholder = "For example: one row per item; preserve completed checkboxes.";
    instructions.value = this.builder.conversionInstructions?.[source.id] || "";
    const alreadyAI = catalog.rules[sourceKind]?.[fieldKind(this.element.schema)] === "ai";
    instructionLabel.hidden = !alreadyAI;
    instructions.addEventListener("input", () => {
      if (!alreadyAI) return;
      this.builder.conversionInstructions ??= {};
      this.builder.conversionInstructions[source.id] = instructions.value;
      this.builder.updateSchema(false, `conversion-instructions:${source.id}`);
    });
    const convert = actions.appendChild(document.createElement("button"));
    convert.type = "button";
    convert.dataset.kind = "form";
    convert.className = STYLES.button.submit;
    convert.textContent = "Convert";
    convert.disabled = true;
    selectElt.addEventListener("updated", () => {
      const ai = catalog.rules[sourceKind]?.[select.value] === "ai";
      instructionLabel.hidden = !ai && !alreadyAI;
      convert.disabled = !select.value;
      description.hidden = !select.value;
      description.textContent = ai ? "AI will convert saved values after Save. Review the destination columns and any conversion instructions first. Unresolvable values will be cleared; originals remain available in View changes." : MESSAGES[sourceKind === "multiple" ? "select" : sourceKind]?.[select.value] || "Values will be converted to match the new component type. Values that cannot be converted will be cleared.";
    });
    convert.addEventListener("click", () => {
      const type = catalog.types.find(({ value }) => value === select.value);
      if (!type) return;
      const previous = this.element.schema;
      const next = {
        id: previous.id,
        title: previous.title,
        ...type.schema,
        ...previous.required !== void 0 ? { required: previous.required } : {},
        ...previous.placeholder !== void 0 ? { placeholder: previous.placeholder } : {},
        ...previous.visibility !== void 0 ? { visibility: previous.visibility } : {}
      };
      if (["radio", "select"].includes(next.type)) {
        const options = previous.options ?? source.options;
        next.options = options ? structuredClone(options) : sourceKind === "checkbox" ? [
          { value: "true", label: "True" },
          { value: "false", label: "False" }
        ] : [];
      }
      if (next.type === "table") next.columns = previous.columns || [];
      this.element.schema = next;
      this.builder.conversionInstructions ??= {};
      if (catalog.rules[sourceKind]?.[select.value] === "ai")
        this.builder.conversionInstructions[source.id] = instructions.value;
      else delete this.builder.conversionInstructions[source.id];
      this.builder.updateSchema();
      this.builder.restoreDraft();
      this.builder.header.message(
        "Conversion staged. Save will update submissions; values that cannot be converted will be cleared.",
        { persistent: true }
      );
    });
  }
}

var modify = /*#__PURE__*/Object.freeze({
	__proto__: null,
	default: Modify
});

class Status extends ConditionTarget {
  constructor(builder) {
    super(builder);
    this.key = "status";
    this.messages = {
      submit: "Add Status Message"
    };
  }
  init() {
    if (this.index !== -1) {
      this.setTitle("Edit Status Message");
      this.messages.submit = "Update Status Message";
      this.setting = { ...this.element.schema.status?.[this.index] };
    } else {
      this.setTitle("Create Status Message");
      this.setting = {};
    }
    super.init();
    const targets = this.builder.getEligibleConditionTargets();
    if (targets.length === 0) {
      this.form?.showError(
        "Status messages cannot be set using available components. Please add a radio button, checkbox, or select menu to the form before setting a status message."
      );
    } else {
      super.addTargetSelect();
    }
    this.showProgress();
  }
  showProgress() {
    const target = this.setting.id && this.builder.elements.get(this.setting.id);
    if (!target) return;
    if (this.setting.text) {
      this.complete = true;
    }
    if (target.schema.type === "checkbox") {
      this.addCheckboxTarget();
      this.addStatusText();
    } else {
      this.addChooseValue();
      if (this.setting.value) this.addStatusText();
    }
    super.showProgress();
  }
  addStatusText() {
    if (this.options.has("text")) return;
    const statusText = primitives.input({
      label: "Status Message",
      placeholder: "enter status message...",
      name: "status-message",
      type: "text",
      value: this.setting.text || null
    });
    this.options.set("text", statusText);
    this.focusTarget = statusText;
    statusText.addEventListener("input", (e) => {
      this.setting.text = e.target.value;
      this.showProgress();
    });
  }
  validate() {
    if (!super.validate()) return false;
    if (!this.setting.text) {
      this.form?.showError("Please enter a status message.");
      return false;
    }
    return true;
  }
}

var status = /*#__PURE__*/Object.freeze({
	__proto__: null,
	default: Status
});

class Visibility extends ConditionTarget {
  constructor(builder) {
    super(builder);
    this.key = "visibility";
    this.messages = {
      submit: "Add Visibility Condition"
    };
  }
  init() {
    if (this.index !== -1) {
      this.setTitle("Edit Visibility Condition");
      this.messages.submit = "Update Visibility Condition";
      this.setting = { ...this.element.schema.visibility?.[this.index] };
    } else {
      this.setTitle("Create Visibility Condition");
      this.setting = {};
    }
    super.init();
    const targets = this.builder.getEligibleConditionTargets();
    if (targets.length === 0) {
      this.form?.showError(
        "Visibility cannot be set using available components. Please add a radio button, checkbox, or select menu to the form before setting the visibility of this element."
      );
    } else {
      super.addTargetSelect();
    }
    this.showProgress();
  }
  showProgress() {
    const target = this.setting.id && this.builder.elements.get(this.setting.id);
    if (!target) return;
    if (target.schema.type === "checkbox") {
      this.addCheckboxTarget();
      this.complete = true;
    } else {
      this.addChooseValue();
      if (this.setting.value) this.complete = true;
    }
    super.showProgress();
  }
}

var visibility = /*#__PURE__*/Object.freeze({
	__proto__: null,
	default: Visibility
});

class Columns extends Condition {
  constructor(builder) {
    super(builder);
    this.key = "columns";
    this.messages = {
      submit: "Add Column"
    };
    this._updated = this._updated.bind(this);
  }
  init() {
    if (this.index !== -1) {
      this.setTitle("Edit Column");
      this.messages.submit = "Update Column";
      this.setting = { ...this.element.schema.columns?.[this.index] };
    } else {
      this.setTitle("Create Column");
      this.setting = {};
    }
    super.init();
    this.addColumnType();
    this.showProgress();
  }
  showProgress() {
    if (this.setting.title) {
      this.complete = true;
      this.addColumnName();
    }
    super.showProgress();
  }
  addColumnName() {
    if (this.options.has("name")) return;
    const columnName = primitives.input({
      label: "Column Name",
      placeholder: "enter column name...",
      name: "column-name",
      type: "text",
      value: this.setting.title || null
    });
    this.options.set("name", columnName);
    this.focusTarget = columnName;
    columnName.addEventListener("input", (e) => {
      this.setting.title = e.target.value;
      this.showProgress();
    });
  }
  _updateSetting(value) {
    delete this.setting.location;
    delete this.setting.input;
    delete this.setting.type;
    if (value === "out" || value === "in") {
      this.setting.location = value;
      this.setting.type = "link";
    } else if (value && value !== "checkbox") {
      this.setting.input = value;
      this.setting.type = "input";
    } else if (value === "checkbox") {
      this.setting.type = "checkbox";
    }
  }
  addColumnType() {
    const saved = this.builder.savedField(this.element.schema.id)?.columns?.find((column) => column.id === this.setting.id);
    if (saved) {
      const notice = document.createElement("p");
      notice.className = "text-sm text-base-medium";
      notice.textContent = "Save will convert this column. Values that cannot be converted will be cleared.";
      this.header.after(notice);
      this.destroyables.push({ destroy: () => notice.remove() });
    }
    const selectElt = primitives.select({
      label: "Column Type",
      kind: "form",
      placeholder: "select column type...",
      name: this.element.schema.id,
      options: CONFIG.TABLE_COLUMNS.filter(
        (input) => !saved || this.builder.conversionCatalog?.rules[fieldKind(saved)]?.[input.type] && this.builder.conversionCatalog.rules[fieldKind(saved)]?.[input.type] !== "ai"
      ).map((input) => ({
        label: input.name,
        value: input.type,
        details: { kind: "form", icon: input.type, name: input.name }
      }))
    });
    this.header.after(selectElt);
    const selectBox = new SelectBox(selectElt);
    const initial = this.setting.location || this.setting.input || this.setting.type;
    if (initial) {
      selectBox.values.add(initial);
    }
    selectBox.init();
    this.columnType = selectBox;
    this.destroyables.push(selectBox);
    this.focusTarget = selectElt;
    this.target.removeEventListener("updated", this._updated);
    this.target.addEventListener("updated", this._updated);
  }
  refreshSavedState() {
  }
  _updated(e) {
    const options = Object.values(
      e.detail.options
    );
    const value = options[0]?.id;
    if (!value) return;
    this._updateSetting(value);
    this.addColumnName();
    this.showProgress();
  }
  destroy() {
    this.target.removeEventListener("updated", this._updated);
    super.destroy();
    this.columnType = null;
  }
  validate() {
    if (!this.setting.title) {
      this.form?.showError("Please enter a column name");
      return false;
    }
    if (!this.setting.type) {
      this.form?.showError("Please select a column type");
      return false;
    }
    if (!this.setting.id) {
      do {
        this.setting.id = generateElementId("column");
      } while (this.element.schema.columns?.some(
        (column) => column.id === this.setting.id
      ));
    }
    return true;
  }
}

var columns = /*#__PURE__*/Object.freeze({
	__proto__: null,
	default: Columns
});

class Options extends Condition {
  constructor(builder) {
    super(builder);
    this.key = "options";
    this.messages = {
      submit: "Add Option"
    };
  }
  init() {
    if (this.index !== -1) {
      this.setTitle("Edit Option");
      this.messages.submit = "Update Option";
      this.setting = { ...this.element.schema.options?.[this.index] };
    } else {
      this.setTitle("Create Option");
      this.messages.submit = "Add Option";
      this.setting = {};
    }
    super.init();
    this.showProgress();
  }
  showProgress() {
    this.addOptionName();
    if (this.setting.label) {
      this.complete = true;
    }
    super.showProgress();
  }
  addOptionName() {
    if (this.options.has("name")) return;
    const optionName = primitives.input({
      label: "Option Name",
      placeholder: "enter option name...",
      name: "option-name",
      type: "text",
      value: this.setting.label || null
    });
    this.options.set("name", optionName);
    this.focusTarget = optionName;
    optionName.addEventListener("input", (e) => {
      this.setting.label = e.target.value;
      this.showProgress();
    });
  }
  validate() {
    if (!this.setting.label) {
      this.form?.showError("Please enter an option name.");
      return false;
    }
    if (!this.setting.value) {
      do {
        this.setting.value = generateElementId("option");
      } while (this.element.schema.options?.some(
        (option) => option.value === this.setting.value
      ));
    }
    return true;
  }
}

var options = /*#__PURE__*/Object.freeze({
	__proto__: null,
	default: Options
});

export { Condition as C, columns as c, modify as m, options as o, status as s, visibility as v };
