/*! Third-party licenses: /third-party-licenses.txt */
import { BaseList } from './baseList.js?v=bbf4a50a';
import { b as FormWidget, I as InputElement, T as TextareaElement } from './forms.js?v=bbf4a50a';
import { S as SectionToggle, s as sections } from './form-sections.js?v=bbf4a50a';
import { r as request, w as withTransition } from './foundation.js?v=bbf4a50a';
import './connectivity.js?v=bbf4a50a';

class ModelTask extends FormWidget {
  get formSelectElement() {
    const target = this.target.querySelector(
      '[data-action="select-form"]'
    );
    if (!target) return null;
    const control = SectionToggle.facet(this, target);
    control.init();
    this.destroyables.push(control);
    return control.elt;
  }
  get html() {
    this.nameElement = new InputElement(
      {
        kind: "task",
        readonly: this.readonly
      },
      {
        id: "name",
        name: "name",
        title: "Name",
        input: "text",
        required: true,
        label: "Name"
      },
      this.target.dataset.name || ""
    );
    return [this.nameElement.elt, this.formSelectElement];
  }
}
class CreateModelTask extends ModelTask {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Create Model Task",
      submitting: "Creating Model Task",
      submitted: "Model Task Created"
    };
  }
  postreconcile() {
    const created = this._created;
    super.postreconcile();
    if (created) {
      this.nameElement.clear();
      if (this.visible) this.form?.success();
      this.form?.resetSubmitButton();
    }
    if (this.visible) this.nameElement.focus();
  }
}
class ModelTaskInfo extends ModelTask {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Update Model Task",
      submitting: "Updating Model Task",
      submitted: "Model Task Updated"
    };
  }
  postreconcile() {
    super.postreconcile();
    const component = this.component?.elt;
    if (!component) return;
    const name = this.nameElement?.value || this.target.dataset.name || component.dataset.title || "";
    if (!name) return;
    component.dataset.title = name;
    const title = component.querySelector("span[data-role='title']");
    if (title && name !== title.textContent) {
      title.textContent = name;
    }
  }
}
class ModelTaskList extends BaseList {
  constructor(attributes) {
    super(attributes);
    this._click = this._click.bind(this);
    this._moving = false;
  }
  init() {
    this.component.elt.addEventListener("click", this._click);
    this._observer = new MutationObserver(() => this._updateMoveButtons());
    this._observeRows();
  }
  get rows() {
    return Array.from(
      this.target.querySelectorAll(":scope > li[lp-entity]")
    );
  }
  _observeRows() {
    this._observer?.disconnect();
    this._observer?.observe(this.target, { childList: true });
    this._updateMoveButtons();
  }
  _updateMoveButtons() {
    const rows = this.rows;
    rows.forEach((row, index) => {
      for (const button of row.querySelectorAll(
        "[data-role='move-model']"
      )) {
        const atEnd = button.dataset.direction === "up" ? index === 0 : index === rows.length - 1;
        button.disabled = this._moving || Boolean(this.readonly) || this.view.online === false || atEnd;
      }
    });
  }
  sync() {
    this._updateMoveButtons();
  }
  async _click(event) {
    const button = event.target instanceof Element ? event.target.closest("[data-role='move-model']") : null;
    if (!button || !this.target.contains(button)) return;
    event.preventDefault();
    event.stopPropagation();
    if (button.disabled || this._moving || this.readonly || this.view.online === false)
      return;
    const rows = this.rows;
    const row = button.closest("li[lp-entity]");
    if (!row) return;
    const index = rows.indexOf(row);
    const next = index + (button.dataset.direction === "up" ? -1 : 1);
    if (index < 0 || next < 0 || next >= rows.length) return;
    [rows[index], rows[next]] = [rows[next], rows[index]];
    const error = this.component.elt.querySelector(
      "[data-role='model-order-error']"
    );
    const route = this.target.dataset.reorderRoute;
    if (!route) return;
    if (error) error.dataset.visible = "false";
    this._moving = true;
    this.target.setAttribute("aria-busy", "true");
    this._updateMoveButtons();
    try {
      const response = await request.put(
        route,
        {
          model_tasks: rows.map((row2) => row2.dataset.key)
        },
        { replaceErrorPage: false }
      );
      if (!response?.ok) {
        if (error) {
          error.textContent = response?.error || "Could not save the model task order. Try again.";
          error.dataset.visible = "true";
        }
        return;
      }
      const current = new Map(this.rows.map((row2) => [row2.dataset.key, row2]));
      await withTransition(
        () => {
          response.model_tasks?.forEach((key, order) => {
            const row2 = current.get(key);
            if (!row2) return;
            row2.dataset.order = String(order + 1);
            this.target.append(row2);
          });
        },
        { label: "model-tasks:reorder" }
      );
    } finally {
      this._moving = false;
      this.target.setAttribute("aria-busy", "false");
      this._updateMoveButtons();
      if (button.isConnected && !button.disabled)
        button.focus({ preventScroll: true });
    }
  }
  postreconcile() {
    super.postreconcile();
    const rows = this.rows;
    const ordered = [...rows].sort(
      (a, b) => Number(a.dataset.order) - Number(b.dataset.order)
    );
    if (ordered.some((row, index) => row !== rows[index]))
      this.target.append(...ordered);
    this._observeRows();
    this.target.setAttribute("loaded", "");
  }
  destroy() {
    this.component.elt.removeEventListener("click", this._click);
    this._observer?.disconnect();
  }
}

var modelTasks = /*#__PURE__*/Object.freeze({
	__proto__: null,
	CreateModelTask: CreateModelTask,
	ModelTaskInfo: ModelTaskInfo,
	ModelTaskList: ModelTaskList
});

class ProjectForm extends FormWidget {
  get nameElement() {
    return new InputElement(
      {
        kind: "project",
        readonly: this.readonly
      },
      {
        id: "name",
        label: "Project Name",
        input: "text",
        placeholder: "name this project..."
      },
      this.target.dataset.name || ""
    ).elt;
  }
  get descriptionElement() {
    return new TextareaElement(
      {
        kind: "project",
        readonly: this.readonly
      },
      {
        id: "description",
        label: "Project Description",
        input: "textarea",
        placeholder: "describe this project..."
      },
      this.target.dataset.description || ""
    ).elt;
  }
}
class ProjectInfo extends ProjectForm {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Update Project",
      submitting: "Updating Project",
      submitted: "Project Updated"
    };
  }
  get html() {
    return [this.nameElement, this.descriptionElement];
  }
  postreconcile() {
    super.postreconcile();
    this.setEntityMetadata();
  }
}
class CreateProject extends ProjectForm {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Create Project",
      submitting: "Creating Project",
      submitted: "Project Created"
    };
    this.target.dataset.mode = "manual";
    this.target.dataset.role = "generate";
  }
  get html() {
    const name = this.nameElement;
    const description = this.descriptionElement;
    if (name) name.dataset.role = "manual";
    if (description) description.dataset.role = "manual";
    return [sections.generateEntityForm(this), name, description];
  }
  postreconcile() {
    this.target.querySelectorAll(
      "input, textarea"
    ).forEach((element) => {
      if (element.type !== "checkbox") {
        element.value = "";
      }
    });
    this.target.dataset.mode = "manual";
    this.form?.resetSubmitButton();
  }
}

var projectInfo = /*#__PURE__*/Object.freeze({
	__proto__: null,
	CreateProject: CreateProject,
	ProjectInfo: ProjectInfo
});

export { modelTasks as m, projectInfo as p };
