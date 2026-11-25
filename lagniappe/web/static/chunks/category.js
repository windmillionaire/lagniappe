/*! Third-party licenses: /third-party-licenses.txt */
import { b as FormWidget, I as InputElement, T as TextareaElement } from './forms.js?v=bcd14aa3';
import { s as sections, S as SectionToggle } from './form-sections.js?v=bcd14aa3';
import './ui-resources.js?v=bcd14aa3';
import './ui-controls.js?v=bcd14aa3';
import './foundation.js?v=bcd14aa3';
import './upstreamUnavailable.js?v=bcd14aa3';
import './connectivity.js?v=bcd14aa3';
import './modal.js?v=bcd14aa3';
import './combobox.js?v=bcd14aa3';
import './protocol.js?v=bcd14aa3';
import './uploads.js?v=bcd14aa3';
import './directUpload.js?v=bcd14aa3';

class CategoryForm extends FormWidget {
  get nameElement() {
    return new InputElement(
      { kind: "category", readonly: this.readonly },
      {
        id: "name",
        title: "Category Name",
        placeholder: "name this category...",
        input: "text"
      },
      this.target.dataset.name || ""
    ).elt;
  }
  get descriptionElement() {
    return new TextareaElement(
      {
        kind: "category",
        readonly: this.readonly
      },
      {
        id: "description",
        label: "Category Description",
        input: "textarea",
        placeholder: "describe this category..."
      },
      this.target.dataset.description || ""
    ).elt;
  }
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
}
class CategoryInfo extends CategoryForm {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Update Category",
      submitting: "Updating Category",
      submitted: "Category Updated",
      queued: "Queued Sync"
    };
  }
  offline({ data, method, route }) {
    return {
      id: `update:category:${this.key}`,
      action: "update",
      kind: "category",
      method,
      route,
      target_key: this.key,
      data
    };
  }
  handleOfflineQueue({ phase, record }) {
    if (record?.kind !== "category" || record.target_key !== this.key) return;
    if (phase === "queued") {
      this.form?.queued();
      this.setEntityMetadata();
    }
    if (phase === "replayed") {
      this.form?.success();
      this.setEntityMetadata();
    }
  }
  get html() {
    return [this.nameElement, this.descriptionElement, this.formSelectElement];
  }
  postreconcile() {
    super.postreconcile();
    this.setEntityMetadata();
  }
}
class CreateCategory extends CategoryForm {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Create Category",
      submitting: "Creating Category",
      submitted: "Category Created"
    };
  }
  async init() {
    this.target.dataset.mode = "manual";
    this.target.dataset.role = "generate";
    await super.init();
  }
  get html() {
    const name = this.nameElement;
    const description = this.descriptionElement;
    if (name) name.dataset.role = "manual";
    if (description) description.dataset.role = "manual";
    return [
      sections.generateEntityForm(this),
      name,
      description,
      this.formSelectElement
    ];
  }
}

export { CategoryInfo, CreateCategory };
