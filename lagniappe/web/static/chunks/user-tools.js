/*! Third-party licenses: /third-party-licenses.txt */
import { b as FormWidget, I as InputElement, c as FacetedSearchElement, R as RadioElement } from './forms.js?v=b6c361d7';

class CreateUser extends FormWidget {
  init() {
    this.messages = {
      submit: "Create User",
      submitting: "Creating",
      submitted: "User Created"
    };
    void super.init();
  }
  get html() {
    const details = document.createElement("div");
    details.className = "flex flex-col gap-4 sm:flex-row";
    this.nameElement = new InputElement(this, {
      id: "name",
      required: true,
      input: "text",
      label: "Name"
    });
    this.nameElement.edit.classList.add("w-full", "sm:basis-1/2");
    details.appendChild(this.nameElement.edit);
    const email = new InputElement(this, {
      id: "email",
      required: true,
      input: "email",
      label: "Email"
    });
    email.edit.classList.add("w-full", "sm:basis-1/2");
    details.appendChild(email.edit);
    const pageOptions = {
      id: "page",
      kind: "page",
      label: "Attach to Existing Page",
      placeholder: "select a page...",
      index: "page",
      creatable: true
    };
    const page = new FacetedSearchElement(this, pageOptions);
    const groupOptions = {
      id: "group",
      kind: "user",
      label: "User Group(s)",
      placeholder: "select user group(s)...",
      index: "group",
      multiple: true
    };
    const group = new FacetedSearchElement(this, groupOptions);
    this.destroyables.push(page, group);
    const aiAccess = this.target.dataset.canEditAi === "true" ? new RadioElement(
      this,
      {
        id: "ai_access",
        label: "AI Access",
        required: true,
        layout: "row",
        options: [
          { label: "None", value: "NONE" },
          { label: "Ask", value: "ASK" },
          { label: "Create", value: "CREATE" }
        ]
      },
      "NONE"
    ).edit : null;
    return [details, aiAccess, page.edit, group.edit];
  }
  async prereconcile() {
    this._focusNameAfterReconcile = this._created || this.target?.dataset.visible !== "true";
    await super.prereconcile();
    if (this._created) await this.prepareReset();
  }
  postreconcile() {
    const created = this._created;
    const focusName = this._focusNameAfterReconcile || created;
    this._focusNameAfterReconcile = false;
    if (created) this.commitReset();
    super.postreconcile();
    if (created) {
      this.form?.resetSubmitButton();
    }
    if (focusName && !this.target?.contains(document.activeElement)) {
      this.nameElement.focus();
    }
  }
}
class CreateUserGroup extends FormWidget {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Create User Group",
      submitting: "Creating",
      submitted: "User Group Created"
    };
    this._newGroupSelector = null;
    this._newGroupForm = null;
  }
  get html() {
    const name = new InputElement(this, {
      id: "name",
      required: true,
      input: "text",
      label: "Group Name"
    });
    return [name.edit];
  }
  get selectors() {
    return this.component?.elt.querySelector("[data-role='group-selectors']");
  }
  async created(response) {
    const html = response?.html || null;
    this._newGroupSelector = html?.body.querySelector(
      "button[lp-show]:not([lp-control])"
    );
    this._newGroupForm = html?.body.querySelector("form");
    if (this._newGroupForm && this.component) {
      this._newGroupForm.dataset.visible = "false";
      this.component.elt.appendChild(this._newGroupForm);
      const newGroupWidget = this._newGroupForm.dataset.widget;
      await this.component.activate(newGroupWidget);
    }
  }
  async prereconcile() {
    await super.prereconcile();
    if (this._newGroupSelector) await this.prepareReset();
  }
  postreconcile() {
    if (this._newGroupSelector) {
      this.commitReset();
      this.target.dataset.visible = "false";
      this.selectors?.appendChild(this._newGroupSelector);
      this._newGroupSelector = null;
      if (this.component) this.component.nav = null;
    }
  }
}

var user = /*#__PURE__*/Object.freeze({
	__proto__: null,
	CreateUser: CreateUser,
	CreateUserGroup: CreateUserGroup
});

class PublicPermissions extends FormWidget {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Update Public Permissions",
      submitting: "Updating Public Permissions",
      submitted: "Public Permissions Updated"
    };
  }
}
class GroupPermissions extends FormWidget {
  constructor(attributes) {
    super(attributes);
    this.messages = {
      submit: "Update User Group",
      submitting: "Updating User Group",
      submitted: "User Group Updated"
    };
    this._submittedName = null;
  }
  async prepareSubmit(options) {
    if (!await super.prepareSubmit(options)) return false;
    this._submittedName = this.formData.get("name");
    return true;
  }
  async reset() {
    this._submittedName = null;
    await super.reset();
  }
  async prepareRevision(response) {
    this._submittedName = null;
    return super.prepareRevision(response);
  }
  postreconcile() {
    const updated = this._updated;
    const localName = this.target.querySelector("[name='name']")?.value;
    const newerDraft = updated && this._submittedName !== null && localName !== this._submittedName;
    super.postreconcile();
    if (!updated || this._updated) return;
    this._submittedName = null;
    if (!this.revisionPreview) {
      const selector = Array.from(
        this.component?.elt?.querySelectorAll(
          "[data-role='group-selectors'] button[data-key]"
        ) ?? []
      ).find((button) => button.dataset.key === this.key);
      const label = selector?.querySelector("[data-role='group-name']");
      if (label) label.textContent = this.target.dataset.name ?? "";
    }
    if (newerDraft && localName !== void 0) {
      const input = this.target.querySelector("[name='name']");
      if (input) input.value = localName;
      this.markUnsavedState();
    }
  }
}

var userPermissions = /*#__PURE__*/Object.freeze({
	__proto__: null,
	GroupPermissions: GroupPermissions,
	PublicPermissions: PublicPermissions
});

export { userPermissions as a, user as u };
