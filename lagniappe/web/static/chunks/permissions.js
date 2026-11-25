/*! Third-party licenses: /third-party-licenses.txt */
import { a as FacetsBox } from './forms.js?v=b438e48a';
import { w as withTransition } from './foundation.js?v=b438e48a';

class PermissionSections {
  constructor(root, { readonly = false, onChange = () => {
  } } = {}) {
    this.root = root;
    this.readonly = readonly;
    this.onChange = onChange;
    this.selects = /* @__PURE__ */ new Map();
    this._destroyed = false;
    this._updated = this._updated.bind(this);
    this._change = this._change.bind(this);
  }
  async init() {
    this.setVisibility();
    if (this.readonly) return;
    for (const section of this.root.querySelectorAll(
      "[data-section]"
    )) {
      const input = section.querySelector(
        "[data-role='permission-picker']"
      );
      if (!input) continue;
      const select = new FacetsBox(
        input,
        section.dataset.section === "projects" ? { models: false } : {}
      );
      this.selects.set(section, select);
      await select.init();
      if (this._destroyed) return;
    }
    this.root.addEventListener("updated", this._updated);
    this.root.addEventListener("change", this._change);
  }
  _updated(event) {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const section = target.closest("[data-section]");
    if (!section) return;
    const select = this.selects.get(section);
    if (!select || target !== select.element) return;
    const entry = Object.values(
      event.detail.options
    )[0];
    if (!entry?.id) return;
    void withTransition(
      () => {
        if (this._destroyed) return;
        const list = section.querySelector("[data-role='permission-list']");
        if (!list) throw new Error("Permission list is missing");
        const exists = Array.from(
          list.querySelectorAll("input[type='radio']")
        ).some((input) => input.name === entry.id);
        if (!exists) {
          const item = section.querySelector("template")?.content.firstElementChild?.cloneNode(true);
          if (!(item instanceof Element))
            throw new Error("Permission row template is missing");
          const name = item.querySelector("[data-role='permission-name']");
          if (!name) throw new Error("Permission name field is missing");
          name.textContent = entry.label || entry.name;
          for (const input of item.querySelectorAll(
            "input[type='radio']"
          ))
            input.name = entry.id;
          list.append(item);
          this.onChange();
        }
        select.clear({ notify: false });
        this.setVisibility();
      },
      { label: "permissions:add-entry" }
    );
  }
  _change(event) {
    const target = event.target;
    if (!(target instanceof Element) || !target.closest("[data-section]"))
      return;
    void withTransition(
      () => {
        if (this._destroyed) return;
        if (target instanceof HTMLInputElement && target.matches("[data-role='remove-permission']") && !target.checked) {
          target.closest("li")?.remove();
          this.onChange();
        }
        this.setVisibility();
      },
      { label: "permissions:change" }
    );
  }
  setVisibility() {
    const sections = new Map(
      Array.from(
        this.root.querySelectorAll("[data-section]"),
        (section) => [section.dataset.section ?? "", section]
      )
    );
    const level = (name) => sections.get(name)?.querySelector("input[type='radio']:checked")?.value;
    const publicOff = level("public") === "FALSE";
    const modelLevel = level("models");
    const userLevel = level("users");
    const models = modelLevel && modelLevel !== "NONE";
    const users = userLevel && !["NONE", "VIEW"].includes(userLevel);
    const groups = !!sections.get("groups")?.querySelector("[data-role='permission-list'] li");
    for (const [name, section] of sections) {
      section.dataset.visible = String(
        !(publicOff && name !== "public" || models && ["categories", "projects", "pages"].includes(name) || name === "groups" && users || name === "users" && groups)
      );
    }
  }
  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;
    this.root.removeEventListener("updated", this._updated);
    this.root.removeEventListener("change", this._change);
    for (const select of this.selects.values()) select.destroy();
    this.selects.clear();
  }
}

var permissionSections = /*#__PURE__*/Object.freeze({
	__proto__: null,
	default: PermissionSections
});

class AccessRestrictions {
  constructor(root, { readonly = false, onChange = () => {
  } } = {}) {
    this.root = root;
    this.readonly = readonly;
    this.onChange = onChange;
    this.select = null;
    this._destroyed = false;
    this._updated = this._updated.bind(this);
    this._change = this._change.bind(this);
    this._click = this._click.bind(this);
  }
  async init() {
    if (this.readonly) return;
    const input = this.root.querySelector(
      "[data-role='restrict-group-input']"
    );
    if (!input) throw new Error("Access restriction picker is missing");
    this.select = new FacetsBox(input);
    await this.select.init();
    if (this._destroyed) return;
    this.root.addEventListener("updated", this._updated);
    this.root.addEventListener("change", this._change);
    this.root.addEventListener("click", this._click);
  }
  get list() {
    return this.root.querySelector(
      "[data-role='restricted-group-list']"
    );
  }
  _updated(event) {
    const select = this.select;
    if (!select || event.target !== select.element) return;
    const options = Object.entries(
      event.detail.options
    );
    if (!options.length) return;
    const list = this.list;
    const template = this.root.querySelector(
      "[data-role='restriction-template']"
    );
    const admin = this.root.querySelector("[name='admin']");
    if (!list || !template || !admin)
      throw new Error("Access restriction fields are missing");
    const selected = new Set(
      Array.from(
        list.querySelectorAll("[name='group-key']"),
        (input) => input.value
      )
    );
    admin.checked = false;
    for (const [key, option] of options) {
      if (selected.has(key)) continue;
      const item = template.content.firstElementChild?.cloneNode(true);
      if (!(item instanceof Element))
        throw new Error("Access restriction row template is empty");
      const input = item.querySelector("[name='group-key']");
      const name = item.querySelector("[data-role='group-name']");
      const button = item.querySelector("button");
      if (!input || !name || !button)
        throw new Error("Access restriction row fields are missing");
      input.value = key;
      name.textContent = option.name;
      button.dataset.key = key;
      list.append(item);
      selected.add(key);
    }
    select.clear({ notify: false });
    this.onChange();
  }
  _change(event) {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) || input.name !== "admin" || !input.checked)
      return;
    const list = this.list;
    if (!list) throw new Error("Access restriction list is missing");
    list.replaceChildren();
    this.select?.clear({ notify: false });
    this.onChange();
  }
  _click(event) {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const button = target.closest("[data-role='remove-restriction']");
    if (!button || !this.root.contains(button)) return;
    event.preventDefault();
    button.closest("li")?.remove();
    this.onChange();
  }
  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;
    this.root.removeEventListener("updated", this._updated);
    this.root.removeEventListener("change", this._change);
    this.root.removeEventListener("click", this._click);
    this.select?.destroy();
  }
}

var accessRestrictions = /*#__PURE__*/Object.freeze({
	__proto__: null,
	default: AccessRestrictions
});

export { accessRestrictions as a, permissionSections as p };
