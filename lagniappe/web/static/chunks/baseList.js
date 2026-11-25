/*! Third-party licenses: /third-party-licenses.txt */
function listHtml(response) {
  if (!response || typeof response !== "object" || !("html" in response)) {
    return;
  }
  const { html } = response;
  if (html && typeof html === "object" && "querySelector" in html && typeof html.querySelector === "function" && "querySelectorAll" in html && typeof html.querySelectorAll === "function") {
    return html;
  }
}
class BaseList {
  constructor(attributes) {
    Object.assign(this, attributes);
    this.refreshScope = "collection";
    this._created = [];
    this._updated = null;
    this._itemCount = 0;
    this._isEmpty = false;
  }
  get itemCount() {
    return this._itemCount || Array.from(this.target.querySelectorAll("li")).length;
  }
  get ifEmpty() {
    if (this.readonly || !this._isEmpty || this._created.length > 0)
      return false;
    return this.itemCount === 0 ? this.target.dataset.ifEmpty : false;
  }
  updated(response) {
    const html = listHtml(response);
    if (!html) return;
    this._itemCount = Array.from(html.querySelectorAll("li")).length;
    this._updated = html.querySelector(
      `[data-widget='${this.name}']`
    );
    this._isEmpty = this._updated?.children?.length === 0;
  }
  created(response) {
    const html = listHtml(response);
    if (!html) return;
    this._created = Array.from(html.querySelectorAll("li")).map((elt) => {
      return this.target.querySelector(`[data-key="${elt.dataset.key}"]`) ? null : elt;
    }).filter((elt) => elt !== null);
    this.modified = this.modified || this._created.length > 0;
  }
  refresh(response) {
    this.updated(response);
    this.postreconcile();
  }
  updateTarget() {
    if (!this._updated || Array.isArray(this._updated)) return;
    this.target.replaceWith(this._updated);
    this.target = this._updated;
    this._updated = null;
  }
  postreconcile() {
    this.updateTarget();
    if (this._created && this._created.length > 0) {
      this.target.prepend(...this._created);
      for (const item of this._created) this.view.addFlash(item);
      this._created = [];
    }
    const empty = this.target.querySelector("[data-role='empty']");
    const items = this.target.querySelectorAll("li:not([data-role='empty'])");
    if (items.length > 0) empty?.remove();
    const visible = this.visible || this.component.active === this || this.target.dataset.persistent === "true";
    this.target.dataset.visible = this.itemCount > 0 && visible ? "true" : "false";
    this._itemCount = 0;
    this.loaded = true;
    this.target.setAttribute("loaded", "");
  }
}

export { BaseList, listHtml };
