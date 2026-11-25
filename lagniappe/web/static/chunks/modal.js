/*! Third-party licenses: /third-party-licenses.txt */
import { S as STYLES } from './ui-resources.js?v=b438e48a';
import { w as withTransition, r as request, c as captureError, E as ENDPOINTS } from './foundation.js?v=b438e48a';
import './upstreamUnavailable.js?v=b438e48a';
import './connectivity.js?v=b438e48a';

class Modal {
  constructor(view, trigger) {
    this._destroyed = false;
    this._listenersAttached = false;
    this._modal = null;
    this.trigger = trigger;
    this.view = view;
    this.keydown = this._keydown.bind(this);
    this.click = this._click.bind(this);
    this.key = null;
  }
  _attachListeners() {
    if (this._destroyed || this._listenersAttached || !this.modal) return;
    document.addEventListener("keydown", this.keydown);
    document.addEventListener("click", this.click);
    this.modal._lp_modal = this;
    this._listenersAttached = true;
  }
  _detach() {
    if (this._listenersAttached) {
      document.removeEventListener("keydown", this.keydown);
      document.removeEventListener("click", this.click);
      this._listenersAttached = false;
    }
    const modal = this._modal;
    if (modal?._lp_modal === this) delete modal._lp_modal;
    modal?.remove();
    this._modal = null;
    if (this.trigger) this.trigger.disabled = false;
  }
  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;
    this._detach();
  }
  get modal() {
    return this._modal;
  }
  _keydown(event) {
    const modal = this.modal;
    if (!modal) return;
    if (event.key === "Escape") {
      this.remove();
    } else if (event.key === "Enter" && event.target instanceof HTMLElement && event.target.tagName === "BUTTON") {
      event.target.click();
    } else if (event.key === "Tab") {
      const focusable = modal.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey) {
        if (document.activeElement === first || !modal.contains(document.activeElement)) {
          event.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last || !modal.contains(document.activeElement)) {
          event.preventDefault();
          first.focus();
        }
      }
    }
  }
  _click(event) {
    const modal = this.modal;
    const target = event.target;
    if (!(target instanceof Node)) return;
    if (this.trigger?.contains(target)) return;
    const content = modal?.querySelector("#modal-content");
    if (content && !content.contains(target)) {
      this.remove();
    } else if (target instanceof Element && target.closest("[lp-control='close']")) {
      event.stopPropagation();
      this.remove();
    }
  }
  async remove() {
    if (!this.modal) return;
    await withTransition(
      () => {
        this._detach();
      },
      { label: "modal:remove" }
    );
  }
  async load(route) {
    if (this._destroyed || this.view?._destroyed) return null;
    if (this.trigger) this.trigger.disabled = true;
    try {
      const modal = await request.get(route);
      if (this._destroyed || this.view?._destroyed) {
        if (this.trigger) this.trigger.disabled = false;
        return null;
      }
      if (!modal?.html) {
        captureError(new Error("No modal HTML provided"), this.trigger, {
          view: this.view?.dataset,
          route,
          modal
        });
        if (this.trigger) this.trigger.disabled = false;
        return null;
      }
      const attached = await this.attach(modal.html);
      if (this.trigger) this.trigger.disabled = false;
      return attached;
    } catch (error) {
      captureError(error, this.trigger, this.view?.dataset);
      if (this.trigger) this.trigger.disabled = false;
    }
  }
  async attach(html, component) {
    if (this._destroyed || this.view?._destroyed) return null;
    try {
      const modal = html.querySelector("#modal") || (html instanceof HTMLElement ? html : null);
      if (!modal) return null;
      if (this.trigger) this.trigger.disabled = true;
      await withTransition(
        () => {
          if (this._destroyed || this.view?._destroyed) return;
          this._detach();
          this._modal = modal;
          document.body.appendChild(modal);
          this._attachListeners();
        },
        { label: "modal:attach" }
      );
      return this.modal;
    } catch (error) {
      captureError(error, component, this.view?.dataset);
      return null;
    }
  }
}
class DeleteModal extends Modal {
  async init() {
    const trigger = this.trigger;
    if (!trigger) return;
    const entity = trigger.closest("[lp-entity]") || trigger.closest("[lp-component]")?._lp_component?.active?.target?.closest("[lp-entity]");
    this.key = trigger.dataset.deleteKey || entity?.dataset?.key || entity?.id || null;
    if (!this.key || !this.view) {
      captureError(
        new Error("No key or view provided"),
        this.trigger,
        this.view?.dataset
      );
      return;
    }
    await this.load(
      trigger.dataset.deleteModalRoute || ENDPOINTS.delete(this.key)
    );
    const modal = this.modal;
    if (!modal) {
      if (this.trigger) this.trigger.disabled = false;
      return;
    }
    this.deleteButton = modal.querySelector(
      "[data-role='delete']"
    );
    if (!this.deleteButton) {
      if (this.trigger) this.trigger.disabled = false;
      captureError(
        new Error("Delete modal missing [data-role='delete']"),
        this.trigger,
        { view: this.view?.dataset }
      );
      return;
    }
    this.deleteButton.addEventListener("click", this.delete.bind(this));
    this.deleteButton.focus();
  }
  removeEntity(key) {
    document.querySelectorAll(`[data-key='${key}']`).forEach((elt) => {
      if (elt._lp_component) elt._lp_component.destroy();
      elt.remove();
    });
  }
  async delete() {
    const { deleteButton, modal } = this;
    if (!deleteButton || !modal) return;
    const spinner = deleteButton.querySelector("#spinner");
    try {
      const route = deleteButton.dataset.route;
      if (!spinner || !route)
        throw new Error("Delete action is missing its spinner or route");
      deleteButton.disabled = true;
      spinner.dataset.visible = "true";
      const options = Array.from(
        modal.querySelectorAll("[data-delete-option][name]")
      );
      const data = options.length ? Object.fromEntries(
        options.map((option) => [option.name, option.checked])
      ) : null;
      const response = await request.delete(route, data);
      if (!response?.ok) {
        deleteButton.disabled = false;
        spinner.dataset.visible = "false";
        return;
      }
      await this.remove();
      const returnUrl = this.trigger?.dataset.returnUrl;
      if (returnUrl) {
        window.location.assign(returnUrl);
        return;
      }
      await this.view?.reconcileChange?.({ type: "delete", key: this.key });
    } catch (error) {
      deleteButton.disabled = false;
      if (spinner) spinner.dataset.visible = "false";
      captureError(error, deleteButton, this.view?.dataset);
    }
  }
}
class HelpModal extends Modal {
  async init() {
    const trigger = this.trigger;
    if (!trigger) return;
    const section = trigger.closest("[lp-component]")?._lp_component?.help || trigger.getAttribute("lp-help") || trigger.closest("nav[lp-help]")?.getAttribute("lp-help");
    if (!section) {
      captureError(
        new Error("No section provided"),
        this.trigger,
        this.view?.dataset
      );
      return;
    }
    await this.load(ENDPOINTS.help(section));
  }
}
class OfflineModal extends Modal {
  constructor(view, trigger) {
    super(view, trigger);
    this._enabled = false;
    this._triggerClick = () => {
      void this.attach();
    };
  }
  async attach() {
    if (this._destroyed || this.view?._destroyed || this.modal) {
      return this.modal;
    }
    const modal = document.createElement("div");
    modal.id = "modal";
    modal.className = STYLES.modal.wrapper;
    const content = modal.appendChild(document.createElement("div"));
    content.className = STYLES.modal.content;
    content.id = "modal-content";
    const header = content.appendChild(document.createElement("div"));
    header.className = STYLES.modal.header;
    const headerText = header.appendChild(document.createElement("h2"));
    headerText.textContent = "Offline";
    headerText.className = "text-lg font-bold text-base-dark";
    const close = header.appendChild(document.createElement("button"));
    close.textContent = "Close";
    close.className = `${STYLES.button.close}`;
    close.onclick = () => {
      void this.remove();
    };
    const body = content.appendChild(document.createElement("div"));
    body.className = "p-6 text-slate-600";
    const bodyText = body.appendChild(document.createElement("p"));
    bodyText.textContent = "You are offline (or the server is starting up). You will be able to view any pages that have been cached, but search, documents and forms will be in read-only mode until you are online again.";
    await super.attach(modal);
    return void 0;
  }
  enable() {
    if (!this.trigger || this._destroyed || this._enabled) return;
    this.trigger.addEventListener("click", this._triggerClick);
    this._enabled = true;
  }
  disable() {
    if (!this.trigger || !this._enabled) return;
    this.trigger.removeEventListener("click", this._triggerClick);
    this._enabled = false;
  }
  destroy() {
    if (this._destroyed) return;
    this.disable();
    super.destroy();
  }
}

export { DeleteModal, HelpModal, Modal, OfflineModal };
