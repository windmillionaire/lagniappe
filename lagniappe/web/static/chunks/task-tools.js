/*! Third-party licenses: /third-party-licenses.txt */
import { b as FormWidget, I as InputElement, T as TextareaElement, F as FormController } from './forms.js?v=b74a2211';
import { S as SectionToggle, s as sections } from './form-sections.js?v=b74a2211';
import { w as withTransition, r as request, c as captureError } from './foundation.js?v=b74a2211';
import { BaseList } from './baseList.js?v=b74a2211';
import './connectivity.js?v=b74a2211';
import { E as EmbeddedTable } from './baseTable.js?v=b74a2211';

const TASK_BUTTONS = {
  selectUser: "facet",
  selectForm: "facet",
  selectProject: "facet",
  selectCategory: "facet",
  schedule: "date",
  uploadFile: "upload"
};
class BaseTaskSettings extends FormWidget {
  constructor(attributes) {
    super(attributes);
    this.buttons = {};
    this._actions = null;
    this._formUpdatedListener = this._formUpdatedListener.bind(this);
  }
  _formUpdatedListener(e) {
    const detail = e.detail;
    const project = detail.options ? Object.values(detail.options)[0] : null;
    const formControl = this.buttons.selectForm;
    if (detail.name === "project" && project?.form && formControl && !formControl.readonly) {
      if (formControl.details?.id !== project.form.id) {
        formControl.clear();
        formControl.addOption(project.form);
      }
    } else if (detail.name === "form") {
      const options = Object.keys(detail.options);
      if (options.length === 0) return;
      const formKey = Object.keys(detail.options)[0];
      const component = this.component;
      if (!component) return;
      const existingForm = component.elt.querySelector(
        `[data-widget="TaskForm"]`
      )?.dataset.formKey;
      if (!existingForm || existingForm === formKey) return;
      const form = component.widgets.TaskForm;
      void withTransition(
        () => {
          form?.destroy?.();
          delete component.widgets.TaskForm;
          component.elt.querySelector(`[data-widget="TaskForm"]`)?.remove();
          component.elt.querySelector('[lp-control="form"]')?.remove();
        },
        { label: "task-settings:replace-attached-form" }
      );
    }
  }
  get html() {
    return [this.nameElement, this.descriptionElement, this.actions];
  }
  get actions() {
    return this.target.querySelector(
      "[data-role='action-buttons']"
    );
  }
  async _initForm() {
    await super._initForm();
    await this._initActions();
  }
  async _initActions() {
    const actions = this.actions;
    if (!actions) return;
    const buttons = Array.from(
      actions.querySelectorAll("button[data-action]")
    );
    if (buttons.length === 0) return;
    this.buttons = {};
    for (const button of buttons) {
      const action = button.dataset.action;
      if (!action || !(action in TASK_BUTTONS)) continue;
      const factory = TASK_BUTTONS[action];
      const control = factory && SectionToggle[factory] ? SectionToggle[factory](this, button) : null;
      if (!control) continue;
      await control.init();
      this.buttons[action] = control;
      if ("destroy" in control && typeof control.destroy === "function") {
        this.destroyables.push(control);
      }
    }
    actions.addEventListener("updated", this._formUpdatedListener);
    this._actions = actions;
  }
  get pageElement() {
    return this._facetElement('[data-role="page-select"]');
  }
  get nameElement() {
    const nameElement = new InputElement(
      {
        kind: "task",
        readonly: this.readonly
      },
      {
        id: "name",
        title: "Name",
        input: "text",
        placeholder: "name this task..."
      },
      this.target.dataset.name
    ).elt;
    return nameElement;
  }
  get descriptionElement() {
    return new TextareaElement(
      {
        kind: "task",
        readonly: this.readonly
      },
      {
        id: "description",
        title: "Description",
        input: "textarea",
        placeholder: "describe this task..."
      },
      this.target.dataset.description
    ).elt;
  }
  get formData() {
    const data = super.formData;
    ["task-file", "mimetype"].forEach((name) => {
      data.delete(name);
    });
    return data;
  }
  _facetElement(selector) {
    const target = this.target.querySelector(selector);
    if (!target) return null;
    const control = SectionToggle.facet(this, target);
    control.init();
    this.destroyables.push(control);
    return control.elt;
  }
  destroy() {
    this._actions?.removeEventListener("updated", this._formUpdatedListener);
    this._actions = null;
    super.destroy();
    this.buttons = {};
  }
}
class TaskSettings extends BaseTaskSettings {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Update Task",
      submitting: "Updating",
      submitted: "Task Updated"
    };
  }
}
class TaskMove extends BaseTaskSettings {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Move Task",
      submitting: "Moving",
      submitted: "Task Moved"
    };
  }
  get html() {
    return [this.pageElement];
  }
}
class TaskCombine extends FormWidget {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Combine Tasks",
      submitting: "Combining",
      submitted: "Tasks Combined"
    };
  }
}
class CreateUserTask extends BaseTaskSettings {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Create Personal Task",
      submitting: "Creating",
      submitted: "Task Created"
    };
  }
  postreconcile() {
    if (this._resetAfterCreate) {
      this.commitReset();
      this._resetAfterCreate = false;
    }
    super.postreconcile();
    if (this.target.dataset.visible === "true") {
      this.target.querySelector("input[name='name']")?.focus();
    }
  }
  async created() {
    await this.prepareReset();
    this._resetAfterCreate = true;
  }
  offline() {
    return {
      action: "create",
      kind: "task"
    };
  }
}
class CreateTask extends BaseTaskSettings {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Create Task",
      submitting: "Creating",
      submitted: "Task Created"
    };
    if (this.component?.widgets.PageTaskList?.itemCount === 0) {
      delete this.target.dataset.close;
    }
  }
  postreconcile() {
    if (this._resetAfterCreate) {
      this.commitReset();
      this._resetAfterCreate = false;
    }
    if (this._closeAfterCreate) {
      this.target.dataset.close = this._closeAfterCreate;
      this._closeAfterCreate = null;
    }
    super.postreconcile();
    if (this.target.dataset.visible === "true") {
      this.target.querySelector("input[name='name']")?.focus();
    }
  }
  async created() {
    await this.prepareReset();
    this._resetAfterCreate = true;
    if ((this.component?.widgets.PageTaskList?.itemCount ?? 0) > 0) {
      this._closeAfterCreate = "tasks:PageTaskList";
    }
  }
}

var taskSettings = /*#__PURE__*/Object.freeze({
	__proto__: null,
	BaseTaskSettings: BaseTaskSettings,
	CreateTask: CreateTask,
	CreateUserTask: CreateUserTask,
	TaskCombine: TaskCombine,
	TaskMove: TaskMove,
	TaskSettings: TaskSettings
});

class PageTaskList extends BaseList {
  constructor(attributes) {
    super(attributes);
    this._change = this._change.bind(this);
    this._click = this._click.bind(this);
    this._setActiveTask = this._setActiveTask.bind(this);
    this._scrollOpenedTask = this._scrollOpenedTask.bind(this);
    this._added = [];
    this._removed = [];
    this._replaced = [];
    this._updated = [];
  }
  init() {
    this.target.addEventListener("change", this._change);
    this.target.addEventListener("click", this._click);
    this.target.addEventListener("set-subcomponent", this._setActiveTask);
    this.target.addEventListener("component-opened", this._scrollOpenedTask);
  }
  _change(e) {
    const target = e.target;
    if (!target?.closest) return;
    const widget = target.closest("[data-widget]")?.dataset.widget;
    if (widget !== "TaskSettings" && widget !== "TaskForm") {
      return;
    }
    const task = target.closest("li");
    const saved = task?.querySelector("[data-saved]");
    if (saved) {
      saved.dataset.saved = "false";
      saved.dataset.visible = "true";
    }
  }
  _click(e) {
    const target = e.target;
    if (!target?.closest) return;
    const submitter = target.closest(
      "[data-role='save-toggle'], [data-role='complete-toggle']"
    );
    const role = submitter?.dataset?.role;
    if (submitter && this.target.contains(submitter)) {
      const task = this.view.getComponent(submitter);
      if (!task) return;
      const route = task.elt.dataset.route;
      task.disable();
      e.stopPropagation();
      e.preventDefault();
      if (role === "complete-toggle" && (!task.active || task.elt.dataset.completed === "true")) {
        const data = new FormData();
        data.append("role", role);
        if (task.elt.dataset.completed === "true") {
          const choice = task.elt.querySelector(
            "[data-role='completion-submission-choice']:checked"
          );
          data.append("completion_submission", choice?.value || "modified");
        }
        void this.view.update(task, data, route);
        return;
      }
      submitter.dispatchEvent(
        new CustomEvent("submit", {
          bubbles: true,
          detail: { update: true, role, route }
        })
      );
      return;
    }
    const completedHeader = this.completedHeader;
    if (completedHeader?.contains(target)) {
      const expandToggle = this.expandToggle;
      const completedTasks = this.completedTasks;
      if (!expandToggle || !completedTasks) return;
      const open = expandToggle.dataset.open !== "true";
      expandToggle.dataset.open = open ? "true" : "false";
      expandToggle.setAttribute("aria-expanded", open ? "true" : "false");
      expandToggle.setAttribute("aria-label", open ? "Collapse" : "Expand");
      expandToggle.title = open ? "Collapse" : "Expand";
      completedTasks.dataset.visible = open ? "true" : "false";
    }
  }
  _setActiveTask(e) {
    const { subcomponent } = e.detail;
    this._moveTaskIfNecessary(subcomponent.elt);
    this._setListVisibility();
  }
  _scrollOpenedTask(e) {
    const { component, trigger } = e.detail || {};
    const task = component?.elt;
    if (e.target !== task || !task?.matches("li[lp-component][data-kind='task']") || !this.target.contains(task) || trigger !== task.querySelector(":scope > [lp-nav][lp-show]"))
      return;
    if (!component?.active || !("target" in component.active) || !component.active.target)
      return;
    const { top, bottom } = task.getBoundingClientRect();
    const viewportTop = 80;
    const viewportBottom = window.innerHeight || document.documentElement.clientHeight;
    const viewportHeight = viewportBottom - viewportTop;
    const taskHeight = bottom - top;
    const usableHeight = Math.min(taskHeight, viewportHeight);
    const visibleHeight = Math.min(bottom, viewportBottom) - Math.max(top, viewportTop);
    if (usableHeight <= 0 || visibleHeight >= usableHeight / 2) return;
    task.classList.add("scroll-mt-20");
    task.scrollIntoView({
      behavior: "auto",
      block: taskHeight <= viewportHeight ? "nearest" : "start"
    });
  }
  _moveTaskIfNecessary(taskElt) {
    if (this._existingTask(taskElt)) return;
    const completed = taskElt.dataset.completed === "true";
    const list = completed ? this.completedTasks : this.activeTasks;
    if (list && !list.contains(taskElt)) {
      const moving = this.activeTasks?.contains(taskElt) || this.completedTasks?.contains(taskElt);
      list.prepend(taskElt);
      if (!moving) this.view.addFlash(taskElt);
    }
  }
  _existingTask(taskElt) {
    const key = taskElt?.dataset?.key;
    const id = taskElt?.id;
    if (!key && !id) return null;
    return Array.from(
      this.target.querySelectorAll(
        "li[lp-component][data-kind='task']"
      )
    ).find((elt) => {
      return elt !== taskElt && (key && elt.dataset.key === key || id && elt.id === id);
    });
  }
  async focusTask(taskId) {
    const taskElt = this.target.querySelector(`[data-key="${taskId}"]`);
    if (!taskElt) return false;
    const task = this.view.getComponent(taskElt);
    if (!task) return false;
    const revealCompleted = this.completedTasks?.contains(taskElt);
    await task.activate("default");
    await task.prepareRender(true);
    await withTransition(
      () => {
        if (revealCompleted) this._openCompletedTasks();
        task.render(true);
      },
      { label: "page-tasks:focus" }
    );
    taskElt.scrollIntoView({ behavior: "auto", block: "start" });
    return true;
  }
  _openCompletedTasks() {
    const completed = this.completedTasks;
    const toggle = this.expandToggle;
    if (!completed || !toggle) return;
    completed.dataset.visible = "true";
    toggle.dataset.open = "true";
    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", "Collapse");
    toggle.title = "Collapse";
  }
  _setListVisibility() {
    if (!this.target.hasAttribute("loaded")) return;
    const activeTasks = this.activeTasks;
    const completedTasks = this.completedTasks;
    const completedHeader = this.completedHeader;
    if (!activeTasks || !completedTasks || !completedHeader) return;
    const hasActive = this.activeCount > 0;
    const hasCompleted = this.completedCount > 0;
    const empty = activeTasks.querySelector("[data-role='empty']");
    const showEmpty = Boolean(empty) && !hasActive && !hasCompleted && Object.is(this.component.active, this);
    if (empty) empty.dataset.visible = showEmpty ? "true" : "false";
    activeTasks.dataset.visible = hasActive || showEmpty ? "true" : "false";
    completedHeader.dataset.visible = hasCompleted ? "true" : "false";
  }
  get ifEmpty() {
    const createTask = this.component.widgets.CreateTask;
    const createTaskClosing = createTask?.visible === false && createTask.target?.dataset.visible === "true";
    return this._isEmpty && this._created.length === 0 && !createTaskClosing ? this.target.dataset.ifEmpty : false;
  }
  get activeTasks() {
    return this.target.querySelector("[data-role='active-tasks']");
  }
  get expandToggle() {
    return this.target.querySelector("[data-role='expand']");
  }
  get completedTasks() {
    return this.target.querySelector(
      "[data-role='completed-tasks']"
    );
  }
  get completedHeader() {
    return this.target.querySelector(
      "[data-role='completed-header']"
    );
  }
  get activeCount() {
    if (!this.activeTasks) return 0;
    return this.activeTasks.querySelectorAll(
      "li[lp-component][data-kind='task']"
    ).length;
  }
  get completedCount() {
    if (!this.completedTasks) return 0;
    return this.completedTasks.querySelectorAll(
      "li[lp-component][data-kind='task']"
    ).length;
  }
  refreshDescriptor() {
    if (this.component.name !== "tasks" || !this.view.key || !this.target.hasAttribute("loaded")) {
      return null;
    }
    return {
      rows: Array.from(
        this.target.querySelectorAll(
          "li[lp-entity][data-kind='task']"
        ),
        (task) => ({
          key: task.dataset.key,
          hash: task.dataset.hash || "",
          fingerprint: task.dataset.fingerprint || ""
        })
      )
    };
  }
  _parseRefreshTask(html) {
    if (!html) return null;
    const template = document.createElement("template");
    template.innerHTML = html.trim();
    return template.content.querySelector(
      "li[lp-component][data-kind='task']"
    );
  }
  async prepareRefreshDelta(delta) {
    const existing = new Map(
      Array.from(
        this.target.querySelectorAll(
          "li[lp-entity][data-kind='task']"
        ),
        (task) => [task.dataset.key, task]
      )
    );
    const known = new Set(existing.keys());
    for (const key of delta.remove || []) known.delete(key);
    for (const { key } of delta.upsert || []) known.add(key);
    if ((delta.order || []).some((key) => !known.has(key))) {
      const response = await this.view.load(this.component, this.route);
      return this.prepareRefresh(response ?? void 0);
    }
    this._removed = (delta.remove || []).map((key) => existing.get(key)).filter((task) => task !== void 0);
    this._replaced = [];
    this._added = [];
    for (const update of delta.upsert || []) {
      const task = this._parseRefreshTask(update.html);
      if (!task || task.dataset.key !== update.key) {
        throw new Error("Invalid page-task refresh row");
      }
      const current = existing.get(update.key);
      if (current) this._replaced.push({ from: current, to: task });
      else this._added.push(task);
    }
    await this.prereconcile();
    return () => {
      this.postreconcile();
      const refreshed = new Map(
        Array.from(
          this.target.querySelectorAll(
            "li[lp-entity][data-kind='task']"
          ),
          (task) => [task.dataset.key, task]
        )
      );
      const preserveActiveOrder = Boolean(
        this.activeTasks?.querySelector(
          "li[lp-entity][data-kind='task'][data-open]:not([data-open='false'])"
        )
      );
      const preserveCompletedOrder = Boolean(
        this.completedTasks?.querySelector(
          "li[lp-entity][data-kind='task'][data-open]:not([data-open='false'])"
        )
      );
      const activeOrder = [];
      const completedOrder = [];
      for (const key of delta.order || []) {
        const task = refreshed.get(key);
        if (!task) {
          throw new Error("Page-task refresh order references a missing row");
        }
        const list = task.dataset.completed === "true" ? this.completedTasks : this.activeTasks;
        const preserveOrder = task.dataset.completed === "true" ? preserveCompletedOrder : preserveActiveOrder;
        if (preserveOrder) {
          if (list && !list.contains(task)) list.append(task);
        } else {
          (task.dataset.completed === "true" ? completedOrder : activeOrder).push(task);
        }
      }
      for (const [list, desired] of [
        [this.activeTasks, activeOrder],
        [this.completedTasks, completedOrder]
      ]) {
        if (!list || !desired.length) continue;
        const current = Array.from(list.children).filter(
          (child) => child.matches("li[lp-entity][data-kind='task']")
        );
        if (current.length !== desired.length || current.some((task, index) => task !== desired[index])) {
          list.append(...desired);
        }
      }
      this.target.querySelectorAll("li[data-role='empty']").forEach((empty) => {
        empty.remove();
      });
      this._isEmpty = (delta.order || []).length === 0;
      if (this._isEmpty && delta.empty) {
        const template = document.createElement("template");
        template.innerHTML = delta.empty.trim();
        const empty = template.content.querySelector("li[data-role='empty']");
        if (empty) this.activeTasks?.append(empty);
      }
      this._setListVisibility();
    };
  }
  async refreshDelta(delta) {
    const commit = await this.prepareRefreshDelta(delta);
    commit?.();
  }
  updated(response) {
    if (!response.html) return;
    const updated = [
      response.html.querySelector("[data-role='active-tasks']"),
      response.html.querySelector(
        "[data-role='completed-header']"
      ),
      response.html.querySelector("[data-role='completed-tasks']")
    ];
    if (updated.some((element) => !element)) {
      this._updated = [];
      return;
    }
    this._isEmpty = !response.html.querySelector("[data-key]");
    this._updated = updated.filter((element) => element !== null);
  }
  async prepareRefresh(response) {
    if (!this._queueRefresh(response)) return;
    await this.prereconcile();
    return () => this.postreconcile();
  }
  async refresh(response) {
    const commit = await this.prepareRefresh(response);
    commit?.();
  }
  _queueRefresh(response) {
    if (!response?.html) return;
    const existingTasks = new Map(
      Array.from(
        this.target.querySelectorAll(
          "li[lp-component][data-kind='task']"
        )
      ).map((elt) => [elt.id, elt])
    );
    const newTasks = new Map(
      Array.from(
        response.html.querySelectorAll(
          "li[lp-component][data-kind='task']"
        )
      ).map((elt) => [elt.id, elt])
    );
    this._added = [];
    this._removed = [];
    this._replaced = [];
    existingTasks.forEach((elt, id) => {
      if (!newTasks.has(id)) {
        this._removed.push(elt);
      }
    });
    newTasks.forEach((elt, id) => {
      const existing = existingTasks.get(id);
      if (existing) {
        if (existing.dataset.fingerprint !== elt.dataset.fingerprint) {
          this._replaced.push({ from: existing, to: elt });
        }
      } else {
        this._added.push(elt);
      }
    });
    return true;
  }
  _restorableWidgetName(taskElt, open) {
    if (!open || open === "false") return null;
    const widget = open === "true" ? taskElt.dataset.default : open;
    if (!widget) return null;
    return taskElt.querySelector(`[data-widget='${widget}']`) ? widget : null;
  }
  _hasPendingLocalFormState(component, replacement = null) {
    return Object.values(component?.widgets ?? {}).some((widget) => {
      if (widget.unsavedState === true || widget.form?._queued === true || widget.target?.querySelector?.(
        "[lp-edited-marker][data-visible='true']"
      )) {
        return true;
      }
      if (component?.active !== widget || widget.visible !== true || !widget.name) {
        return false;
      }
      return Boolean(
        replacement?.querySelector?.(`[data-widget='${widget.name}']`)
      );
    });
  }
  async prereconcile() {
    const needsRefresh = this.activeCount > 0 || this.completedCount > 0;
    const hasUpdated = this._updated.length > 0;
    if (hasUpdated) {
      if (needsRefresh) {
        const html = document.createElement("div");
        html.append(...this._updated);
        this._queueRefresh({ html });
      } else {
        this._replaceAll = [...this._updated];
      }
    }
    this._updated = [];
    this._removed = this._removed.filter((elt) => {
      const component = this.view.getComponent(elt);
      return !this._hasPendingLocalFormState(component);
    });
    this._preparedReplacements = [];
    for (const { from, to } of this._replaced) {
      const current = this.view.getComponent(from);
      if (this._hasPendingLocalFormState(current, to)) continue;
      const open = this._restorableWidgetName(to, current?.open);
      const replacement = this.view.getComponent(to);
      if (current?.key) this.view.components[current.key] = current;
      if (replacement && open) {
        await replacement.activate(open);
        await replacement.prepareRender(true);
      }
      this._preparedReplacements.push({
        current,
        from,
        replacement,
        to
      });
    }
    this._replaced = [];
    this._preparedCreated = [];
    for (const elt of this._created) {
      const pendingAdded = this._added.some((added) => {
        return elt.dataset.key && added.dataset.key === elt.dataset.key || elt.id && added.id === elt.id;
      });
      if (pendingAdded || this._existingTask(elt)) continue;
      const newTask = this.view.getComponent(elt);
      if (!newTask) continue;
      const hasForm = newTask.elt.dataset.default === "TaskForm";
      if (hasForm) {
        await newTask.activate("TaskForm");
        await newTask.prepareRender(true);
      }
      this._preparedCreated.push({ hasForm, newTask, elt });
    }
    this._created = [];
  }
  postreconcile() {
    if (this.component.active?.name === "CreateTask") {
      this._closeOpenTasks();
    }
    if (this._replaceAll) {
      this.target.replaceChildren(...this._replaceAll);
      this._replaceAll = null;
    }
    for (const elt of this._removed) {
      const component = this.view.getComponent(elt);
      component?.destroy?.();
      elt.remove();
    }
    this._removed = [];
    for (const { current, from, replacement, to } of this._preparedReplacements || []) {
      from.replaceWith(to);
      current?.destroy?.();
      if (replacement) {
        if (replacement.key)
          this.view.components[replacement.key] = replacement;
        if (replacement.active) replacement.render(true);
      }
      this._moveTaskIfNecessary(to);
    }
    this._preparedReplacements = [];
    for (const elt of this._added) {
      this._moveTaskIfNecessary(elt);
    }
    this._added = [];
    for (const { hasForm, newTask, elt } of this._preparedCreated || []) {
      this.activeTasks?.prepend(elt);
      this.view.addFlash(elt);
      if (hasForm) newTask.render(true);
    }
    this._preparedCreated = [];
    this.target.setAttribute("loaded", "");
    this._setListVisibility();
  }
  _closeOpenTasks() {
    const openTasks = this.target.querySelectorAll(
      "li[lp-component][data-kind='task'][data-open]:not([data-open='false'])"
    );
    openTasks.forEach((elt) => {
      const task = this.view.getComponent(elt);
      task?.closeOpenWidget?.();
    });
  }
}

var pageTaskList = /*#__PURE__*/Object.freeze({
	__proto__: null,
	PageTaskList: PageTaskList
});

async function renderOriginalSubmission(response, key) {
  const host = document.createElement("div");
  host.dataset.kind = "task";
  const form = new FormController({
    target: host,
    key,
    readonly: true,
    schema: response.schema || [],
    submission: response.submission || {},
    htmlFields: response.html_fields || {},
    showEmptyFields: false
  });
  await form.init();
  const error = response.schema_error || response.content_error;
  if (error) {
    const message = document.createElement("p");
    message.setAttribute("role", "status");
    message.textContent = error;
    host.prepend(message);
  }
  if (response.raw_submission) {
    const raw = document.createElement("pre");
    raw.dataset.role = "original-raw-answers";
    raw.className = "whitespace-pre-wrap break-words";
    raw.textContent = JSON.stringify(response.raw_submission, null, 2);
    host.append(raw);
  }
  return { form, host };
}
class TaskForm extends FormWidget {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Update",
      submitting: "Updating",
      submitted: "Updated",
      queued: "Queued Sync"
    };
    this._historyFillRequest = null;
    this._historyFillSubmission = null;
    this._historyFillGeneration = 0;
    this._originalCompletionForm = null;
    this._archivedSubmissionForm = null;
    this._originalCompletionGeneration = 0;
    this._showOriginalCompletion = this._showOriginalCompletion.bind(this);
    this._showArchivedSubmission = this._showArchivedSubmission.bind(this);
    this._selectCompletionSubmission = this._selectCompletionSubmission.bind(this);
  }
  get autofillElement() {
    if (this.readonly) return null;
    return sections.autofill(this);
  }
  get historyFillRoute() {
    return this.endpoints?.latestHistorySubmission;
  }
  get historyFillEnabled() {
    return Boolean(
      !this.revisionPreview && !this.readonly && this.hasHistory && this.historyFillRoute
    );
  }
  get hasHistory() {
    return Boolean(
      this.target?.dataset.history || this.component?.elt?.querySelector("[data-widget='TaskHistory']")
    );
  }
  get prepend() {
    const archived = this.target.querySelector(
      "[data-role='archived-submission-controls']"
    );
    archived?.querySelector("[data-role='load-archived-submission']")?.addEventListener("click", this._showArchivedSubmission);
    const original = this.target.querySelector(
      "[data-role='original-completion-controls']"
    );
    original?.querySelector("[data-role='view-original-completion']")?.addEventListener("click", this._showOriginalCompletion);
    original?.querySelector(
      "[data-role='completion-submission-options']"
    )?.addEventListener("change", this._selectCompletionSubmission);
    return [
      archived,
      original,
      this.target.querySelector("[data-role='empty-completed-submission']")
    ];
  }
  get append() {
    const error = this.target?.dataset.schemaError;
    const notice = error ? document.createElement("p") : null;
    if (notice) {
      notice.textContent = error ?? null;
      notice.setAttribute("role", "status");
    }
    let raw = null;
    if (error && this.target?.dataset.rawSubmission) {
      raw = document.createElement("pre");
      raw.dataset.role = "original-raw-answers";
      raw.className = "whitespace-pre-wrap break-words";
      raw.textContent = JSON.stringify(
        JSON.parse(this.target.dataset.rawSubmission),
        null,
        2
      );
    }
    return [this.autofillElement, notice, raw];
  }
  _setCompletionView(showOriginal) {
    const controls = this.target.querySelector(
      "[data-role='original-completion-controls']"
    );
    if (!controls) return;
    let current = this.target.querySelector(
      "[data-role='current-completion-detail']"
    );
    if (!current) {
      current = document.createElement("div");
      current.dataset.role = "current-completion-detail";
      current.className = "flex flex-col gap-6";
      current.append(
        ...Array.from(this.target.children).filter(
          (child) => child !== controls && !child.matches("[lp-edited-marker]")
        )
      );
      controls.after(current);
    }
    current.hidden = showOriginal;
    const original = controls.querySelector(
      "[data-role='original-completion-detail']"
    );
    if (original) original.hidden = !showOriginal;
  }
  _selectCompletionSubmission(event) {
    event.stopPropagation();
    if (event.target instanceof HTMLInputElement)
      this._setCompletionView(event.target.value === "original");
  }
  async _showOriginalCompletion(event) {
    event.preventDefault();
    event.stopPropagation();
    const button = event.currentTarget;
    if (!button) return;
    const controls = button.closest(
      "[data-role='original-completion-controls']"
    );
    const target = controls?.querySelector(
      "[data-role='original-completion-detail']"
    );
    if (!controls || !target) return;
    if (button.disabled || !button.dataset.route) return;
    const generation = this._originalCompletionGeneration;
    button.disabled = true;
    try {
      if (!this._originalCompletionForm) {
        const response = await request.get(
          button.dataset.route
        );
        if (!response) throw new Error("Submission response is unavailable.");
        const { form, host } = await renderOriginalSubmission(
          response,
          this.key
        );
        host.className = "flex flex-col gap-6";
        if (generation !== this._originalCompletionGeneration || !this.target.contains(button)) {
          form.destroy();
          return;
        }
        target.replaceChildren(host);
        this._originalCompletionForm = form;
      }
      this._setCompletionView(true);
      const options = controls.querySelector(
        "[data-role='completion-submission-options']"
      );
      if (!options) return;
      for (const radio of options.querySelectorAll("input")) {
        radio.disabled = false;
        radio.checked = radio.value === "original";
      }
      options.hidden = false;
      options.querySelector("input:checked")?.focus();
    } catch (error) {
      if (generation !== this._originalCompletionGeneration) return;
      target.textContent = "Could not load the original submission. Please try again.";
      target.hidden = false;
      captureError(error, this.target, { route: button.dataset.route });
    } finally {
      button.disabled = false;
    }
  }
  async _showArchivedSubmission(event) {
    event.preventDefault();
    event.stopPropagation();
    const button = event.currentTarget;
    if (!button) return;
    if (button.disabled || !button.dataset.route) return;
    const generation = this._originalCompletionGeneration;
    const target = button.closest("[data-role='archived-submission-controls']")?.querySelector("[data-role='archived-submission-detail']");
    if (!target) return;
    button.disabled = true;
    try {
      if (!this._archivedSubmissionForm) {
        const response = await request.get(
          button.dataset.route
        );
        if (!response) throw new Error("Submission response is unavailable.");
        const { form, host } = await renderOriginalSubmission(
          response,
          this.key
        );
        if (generation !== this._originalCompletionGeneration || !this.target.contains(button)) {
          form.destroy();
          return;
        }
        host.className = "flex flex-col gap-6";
        target.replaceChildren(host);
        this._archivedSubmissionForm = form;
      }
      target.hidden = false;
      const original = this.target.querySelector(
        "[data-role='original-completion-controls']"
      );
      if (original) original.hidden = false;
    } catch (error) {
      if (generation !== this._originalCompletionGeneration) return;
      target.textContent = "Could not load the archived version. Please try again.";
      target.hidden = false;
      captureError(error, this.target, { route: button.dataset.route });
    } finally {
      button.disabled = false;
    }
  }
  _clearOriginalCompletion() {
    this._originalCompletionGeneration += 1;
    this._originalCompletionForm?.destroy();
    this._originalCompletionForm = null;
    this._archivedSubmissionForm?.destroy();
    this._archivedSubmissionForm = null;
  }
  destroy() {
    this._clearOriginalCompletion();
    super.destroy();
  }
  offline({ data, method, route }) {
    return {
      id: `update:task:${this.key}`,
      action: "update",
      kind: "task",
      method,
      route,
      target_key: this.key,
      data
    };
  }
  handleOfflineQueue({ phase, record }) {
    if (record?.kind !== "task" || record.target_key !== this.key) return;
    if (phase === "queued") this.form?.queued();
    if (phase === "conflict") {
      this._offlineConflict = {
        record,
        response: record.conflictResponse
      };
      return this.stageOfflineConflict();
    }
    if (phase === "replayed") this.form?.success();
  }
  _resetHistoryFillCache() {
    this._historyFillRequest = null;
    this._historyFillSubmission = null;
    this._historyFillGeneration += 1;
  }
  async init() {
    await super.init();
    await this.loadHistoryFill();
  }
  async prepareReset(options = {}) {
    this._clearOriginalCompletion();
    this._resetHistoryFillCache();
    const afterInit = options.afterInit;
    await super.prepareReset({
      ...options,
      afterInit: async (widget) => {
        await afterInit?.(widget);
        await widget.loadHistoryFill();
      }
    });
  }
  async reset() {
    await this.prepareReset();
    this.commitReset();
  }
  async latestHistorySubmission() {
    if (this._historyFillSubmission) return this._historyFillSubmission;
    if (!this._historyFillRequest) {
      const route = this.historyFillRoute;
      if (!route) return [];
      const pending2 = request.get(route).then((response) => response?.history_fields || []).catch((error) => {
        if (this._historyFillRequest === pending2) {
          this._historyFillRequest = null;
          captureError(error, this.target, { route: this.historyFillRoute });
        }
        return [];
      });
      this._historyFillRequest = pending2;
    }
    const pending = this._historyFillRequest;
    const submission = await pending;
    if (this._historyFillRequest === pending)
      this._historyFillSubmission = submission;
    return submission;
  }
  async historyValue(fieldId) {
    const form = this.form;
    const generation = this._historyFillGeneration;
    const route = this.historyFillRoute;
    if (!form || !route) return null;
    const response = await request.get(
      route,
      { field: fieldId },
      { replaceErrorPage: false }
    );
    if (this.form !== form || this._historyFillGeneration !== generation)
      return null;
    if (!response?.ok) {
      form.showError(
        response?.error || "Could not fill this value from history. Try again."
      );
      return null;
    }
    form.hideError();
    return response.latest_submission?.[fieldId];
  }
  async loadHistoryFill() {
    const form = this.form;
    const renderer = form?.renderer;
    if (!this.historyFillEnabled || !renderer) return;
    const generation = this._historyFillGeneration;
    const fields = await this.latestHistorySubmission();
    if (this.form !== form || this._historyFillGeneration !== generation)
      return;
    renderer.addHistoryFillButtons(
      Object.fromEntries(fields.map((id) => [id, () => this.historyValue(id)]))
    );
  }
}

var taskForm = /*#__PURE__*/Object.freeze({
	__proto__: null,
	TaskForm: TaskForm
});

class TaskHistory extends EmbeddedTable {
  constructor(attributes) {
    super(attributes);
    this._updated = null;
  }
  get table() {
    return this.target.querySelector("[data-role='table']");
  }
  async updated(response) {
    this._updated = (response.html || null)?.querySelector(
      "[data-role='completion-history']"
    ) ?? null;
  }
  postreconcile() {
    if (!this._updated) return;
    this.visible = true;
    this.target.dataset.visible = "true";
    this.table?.replaceChildren(this._updated);
    this._updated.dataset.visible = "true";
    for (const table of this._updated.querySelectorAll("table")) {
      table.dataset.visible = "true";
      this.initVisibility(table, `columns-${this.component.name}-history`);
    }
    this._updated = null;
  }
}

var taskHistory = /*#__PURE__*/Object.freeze({
	__proto__: null,
	TaskHistory: TaskHistory
});

export { taskForm as a, taskHistory as b, pageTaskList as p, taskSettings as t };
