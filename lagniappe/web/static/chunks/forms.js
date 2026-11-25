/*! Third-party licenses: /third-party-licenses.txt */
import { c as createIcon, S as STYLES, s as setIcon } from './ui-resources.js?v=b8c49d0d';
import { p as primitives, f as formatting } from './ui-controls.js?v=b8c49d0d';
import { c as captureError, g as generateElementId, w as withTransition, s as showBriefly, E as ENDPOINTS, r as request, f as areEqual } from './foundation.js?v=b8c49d0d';
import { Modal } from './modal.js?v=b8c49d0d';
import { R as Results, a as RemoteQueryCombobox, C as Combobox } from './combobox.js?v=b8c49d0d';
import './connectivity.js?v=b8c49d0d';
import './protocol.js?v=b8c49d0d';

function currentReviewOperation(widget, incoming) {
  const current = widget.reviewState?.operation;
  if (current?.key === incoming?.key)
    return Number(current?.revision) > Number(incoming?.revision) ? current : incoming;
  return current?.type === "autofill" && !current.terminal && incoming?.type !== "form-change" && (!incoming || incoming.terminal) ? current : incoming;
}
function renderReviewBar(widget, incoming = null) {
  const target = widget?.target;
  const marker = target?.querySelector?.("[lp-edited-marker]");
  if (!widget || !target || !marker) return;
  const state = widget.reviewState ?? JSON.parse(target.dataset.formState || "{}");
  widget.reviewState = state;
  if (incoming) state.operation = incoming;
  const operation = state.operation;
  const running = operation && !operation.terminal;
  const runningAutofill = running && operation.type === "autofill";
  const unresolvedReviews = (state.reviews ?? []).filter(
    (review2) => !widget._reviewedOperations?.has(review2.operation)
  );
  const awaitingNewAutofill = !state.stale_autofill && operation?.type === "autofill" && (running || operation.terminal && operation.status === "succeeded") && !widget._reviewedOperations?.has(operation.key) && !unresolvedReviews.some((review2) => review2.operation === operation.key);
  const reviews = runningAutofill || awaitingNewAutofill ? [] : unresolvedReviews;
  const migrationNotice = JSON.parse(
    target.dataset.migrationNotice || "[]"
  );
  const migration = migrationNotice.length > 0;
  const remote = marker._lp_edited_state?.response;
  const messages = [];
  if (reviews.length) messages.push("Autofill is complete.");
  if (migration || remote && marker._lp_edited_state?.schemaChanged)
    messages.push("This form's fields have changed.");
  if (state.stale_autofill && !running)
    messages.push("Run Autofill again for new suggestions.");
  const remoteNotice = remote && !runningAutofill && !reviews.length && !marker._lp_edited_state?.schemaChanged;
  if (remoteNotice) messages.push("Another user has edited this form.");
  const copy = marker.querySelector(
    "[data-role='edited-message']"
  );
  if (copy) {
    copy.textContent = messages.join(" ");
    copy.hidden = !messages.length;
  }
  const progress = marker.querySelector(
    "[data-role='form-operation']"
  );
  const showTerminal = operation?.terminal && ["failed", "cancelled", "superseded"].includes(operation.status ?? "");
  const awaitingReview = !state.stale_autofill && operation?.terminal && operation.status === "succeeded" && operation.type === "autofill" && !widget._reviewedOperations?.has(operation.key) && !reviews.some((review2) => review2.operation === operation.key) && !remoteNotice;
  if (progress) {
    progress.hidden = !running && (!!remoteNotice || !showTerminal && !awaitingReview);
    progress.textContent = running ? `${operation.type === "form-change" ? "Form update" : "Autofill"} is running \xB7 ${operation.phase_label || "Queued"} \xB7 ${Math.max(0, operation.elapsed_seconds || 0)}s${operation.retry_reason ? " \xB7 Retrying" : ""}` : showTerminal ? operation.status === "cancelled" ? "Autofill cancelled. Retry can reuse the uploaded file." : `Autofill ${operation.status}.${operation.error ? ` ${operation.error}` : ""} Saved answers were unchanged. Retry can reuse the uploaded file.` : awaitingReview ? "Autofill is complete. Loading values to review\u2026" : "";
  }
  const review = marker.querySelector(
    "[data-role='edited-reset']"
  );
  if (review) {
    review.hidden = !!runningAutofill || !reviews.length && !remote;
    if ((reviews.length || remote) && !review.dataset?.reviewPending)
      review.textContent = "Review values";
  }
  const changes = marker.querySelector(
    "[data-role='migration-changes']"
  );
  if (changes) changes.hidden = !migration;
  const cancel = marker.querySelector(
    "[data-role='autofill-cancel']"
  );
  if (cancel) cancel.hidden = !running || !operation.can_cancel;
  const retry = marker.querySelector(
    "[data-role='autofill-retry']"
  );
  if (retry) {
    retry.hidden = !state.retry_operation || !!running;
    retry.disabled = !!widget._autofillRetryPending;
    retry.textContent = widget._autofillRetryPending ? "Retrying\u2026" : "Retry autofill";
  }
  for (const control of target.querySelectorAll(
    "[data-role='autofill-submit']"
  )) {
    control.disabled = !!running;
  }
  marker.dataset.visible = messages.length || running || showTerminal || awaitingReview ? "true" : "false";
}
function installReviewBar(widget) {
  widget._reviewBar?.destroy();
  const target = widget.target;
  if (widget.revisionPreview || !target?.dataset.formState) return;
  widget.reviewState = JSON.parse(target.dataset.formState);
  renderReviewBar(widget);
  const click = async (event) => {
    if (!(event.target instanceof Element)) return;
    const button = event.target.closest(
      "[data-role='autofill-cancel'], [data-role='autofill-retry']"
    );
    if (!button) return;
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true;
    if (button.dataset.role === "autofill-cancel") {
      button.textContent = "Cancelling\u2026";
      const progress = widget.target?.querySelector(
        "[data-role='form-operation']"
      );
      if (progress) progress.textContent = "Cancellation requested\u2026";
    }
    try {
      if (button.dataset.role === "autofill-cancel") {
        const operation = widget.reviewState?.operation;
        if (!operation?.can_cancel) return;
        const data = new FormData();
        data.set("operation-id", String(operation.operation_id));
        const { request } = await import('./foundation.js?v=b8c49d0d').then(function (n) { return n.p; });
        const response = await request.post(
          `/tools/operations/${encodeURIComponent(operation.key)}/cancel`,
          data
        );
        if (!response?.ok)
          throw new Error(
            response?.error || "Could not cancel autofill. Try again."
          );
        if (response.status && typeof response.status === "object") {
          renderReviewBar(widget, response.status);
          const manager = await widget.view?.ensureDeferredOperations?.();
          await manager?.receive(response.status);
        }
      } else {
        widget._autofillRetryPending = true;
        renderReviewBar(widget);
        widget._autofillRetry = widget.reviewState?.retry_operation;
        widget.target?.dispatchEvent(
          new CustomEvent("submit", {
            bubbles: true,
            cancelable: true,
            detail: {
              role: "autofill-submit",
              update: true,
              onSettled: () => {
                widget._autofillRetryPending = false;
                renderReviewBar(widget);
              }
            }
          })
        );
      }
    } catch (error) {
      if (button.dataset.role === "autofill-retry") {
        widget._autofillRetryPending = false;
        renderReviewBar(widget);
      }
      widget.component?.showError?.(
        error instanceof Error ? error.message : String(error)
      );
      captureError(error);
    } finally {
      if (button.dataset.role === "autofill-cancel")
        button.textContent = "Cancel autofill";
      if (button.dataset.role === "autofill-cancel") button.disabled = false;
    }
  };
  target.addEventListener("click", click);
  widget._reviewBar = {
    destroy: () => target.removeEventListener("click", click)
  };
}

const CONTROLS = {
  "permission-sections": () => import('./permissions.js?v=b8c49d0d').then(function (n) { return n.p; }),
  "access-restrictions": () => import('./permissions.js?v=b8c49d0d').then(function (n) { return n.a; })
};
const isFormControl = (name) => name !== void 0 && Object.hasOwn(CONTROLS, name);
async function initFormControls(form) {
  const target = form.target;
  const selector = "[data-form-control]";
  const roots = [
    ...target.matches?.(selector) ? [target] : [],
    ...target.querySelectorAll?.(selector) ?? []
  ];
  for (const root of roots) {
    const name = root.dataset.formControl;
    if (!isFormControl(name)) throw new Error(`Unknown form control: ${name}`);
    const { default: Control } = await CONTROLS[name]();
    if (form._destroyed) return;
    const control = new Control(root, {
      readonly: form.readonly,
      onChange: form.markUnsavedState
    });
    form.destroyables.push(control);
    await control.init();
    if (form._destroyed) {
      control.destroy();
      return;
    }
  }
}

async function getFormElement(renderer, schema, submission) {
  switch (schema.type) {
    case "checkbox": {
      const { CheckboxElement } = await Promise.resolve().then(function () { return checkbox; });
      return new CheckboxElement(renderer, schema, submission);
    }
    case "radio": {
      const { RadioElement } = await Promise.resolve().then(function () { return radio; });
      return new RadioElement(renderer, schema, submission);
    }
    case "textarea": {
      const { TextareaElement } = await Promise.resolve().then(function () { return textarea; });
      return new TextareaElement(renderer, schema, submission);
    }
    case "input": {
      const { InputElement } = await Promise.resolve().then(function () { return input; });
      return new InputElement(renderer, schema, submission);
    }
    case "select": {
      const { SelectElement } = await Promise.resolve().then(function () { return select; });
      return new SelectElement(renderer, schema, submission);
    }
    case "html": {
      const { HtmlElement } = await Promise.resolve().then(function () { return html; });
      return new HtmlElement(renderer, schema, submission);
    }
    case "signature": {
      const { SignatureElement } = await import('./form-complex.js?v=b8c49d0d').then(function (n) { return n.s; });
      return new SignatureElement(renderer, schema, submission);
    }
    case "table": {
      const { TableElement } = await import('./form-complex.js?v=b8c49d0d').then(function (n) { return n.t; });
      return new TableElement(renderer, schema, submission);
    }
    case "todo": {
      const { TodoElement } = await import('./form-complex.js?v=b8c49d0d').then(function (n) { return n.a; });
      return new TodoElement(renderer, schema, submission);
    }
    case "link": {
      const { LinkElement } = await Promise.resolve().then(function () { return link; });
      return new LinkElement(renderer, schema, submission);
    }
    case "bookmark": {
      const { BookmarkElement } = await Promise.resolve().then(function () { return bookmark; });
      return new BookmarkElement(renderer, schema, submission);
    }
    case "location": {
      const { LocationElement } = await import('./location.js?v=b8c49d0d');
      return new LocationElement(renderer, schema, submission);
    }
    case "status": {
      const { StatusElement } = await Promise.resolve().then(function () { return status; });
      return new StatusElement(renderer, schema, submission);
    }
    default:
      throw new Error(`Unknown form element type: ${schema.type}`);
  }
}

class FormRenderer {
  constructor(form) {
    this.id = generateElementId("renderer");
    this.form = form;
    this.kind = form.kind || form.target.dataset.kind || "form";
    this.elements = /* @__PURE__ */ new Map();
    this.visibilityTriggers = /* @__PURE__ */ new Map();
    this.visibilityConditions = /* @__PURE__ */ new Map();
    this.statusTriggers = /* @__PURE__ */ new Set();
    this.status = null;
    this._onChange = this._onChange.bind(this);
  }
  get target() {
    return this.form.target;
  }
  get readonly() {
    return this.form.readonly;
  }
  get showEmptyFields() {
    return this.form.showEmptyFields;
  }
  get historyFillEnabled() {
    return this.form.historyFillEnabled;
  }
  async render() {
    await this._createElements();
    const html = Array.from(this.elements.values()).map((element) => element.elt).filter((element) => Boolean(element));
    this.form.target.replaceChildren(...html);
    this._initStatusTriggers();
    this._initVisibilityTriggers();
    if (!this.readonly) {
      this.target.addEventListener("change", this._onChange);
    }
    this._updateDerivedState();
    this.target.setAttribute("rendered", "");
  }
  destroy() {
    this.elements.forEach((element) => {
      if (element.destroy) element.destroy();
    });
    this.target.removeAttribute("rendered");
    this.target.removeEventListener("change", this._onChange);
    this.visibilityTriggers.clear();
    this.visibilityConditions.clear();
    this.statusTriggers.clear();
  }
  _packageSubmission() {
    const result = Object.fromEntries(
      Array.from(this.elements.values()).map((element) => [
        element.schema.id,
        element.value
      ])
    );
    return result;
  }
  _onChange(event) {
    const target = event.target;
    if (!target || !("closest" in target) || typeof target.closest !== "function")
      return;
    const trigger = target.closest(".form-element");
    if (!trigger) return;
    const element = this.elements.get(trigger.id);
    if (!element) return;
    if (this.statusTriggers.has(element)) {
      this.status?.update();
    }
    if (this.visibilityTriggers.has(element)) {
      this._updateVisibility(element);
    }
  }
  addHistoryFillButtons(submission) {
    if (!this.historyFillEnabled || !submission) return;
    for (const [fieldId, value] of Object.entries(submission)) {
      const element = this.elements.get(`${fieldId}-${this.id}`);
      element?.addHistoryFill?.(value);
    }
  }
  async _initStatusTriggers() {
    this.statusTriggers.clear();
    this.status = Array.from(this.elements.values()).find(
      (element) => element.schema.type === "status"
    );
    if (!this.status) return;
    const messages = Array.isArray(this.status.schema.status) ? this.status.schema.status : [];
    for (const message of messages) {
      if (!message?.id) continue;
      const trigger = this.elements.get(`${message.id}-${this.id}`);
      if (!trigger) continue;
      this.statusTriggers.add(trigger);
    }
  }
  async _initVisibilityTriggers() {
    this.visibilityTriggers = /* @__PURE__ */ new Map();
    this.visibilityConditions.clear();
    for (const target of this.elements.values()) {
      if (!target.schema.visibility || !target.elt) continue;
      const conditions = target.schema.visibility.filter(
        (trigger) => Boolean(trigger?.id)
      );
      if (conditions.length === 0) continue;
      this.visibilityConditions.set(target, conditions);
      for (const trigger of conditions) {
        const element = this.elements.get(`${trigger.id}-${this.id}`);
        if (!element?.elt) continue;
        const values = this.visibilityTriggers.get(element) || /* @__PURE__ */ new Set();
        values.add(target);
        this.visibilityTriggers.set(element, values);
      }
    }
  }
  _updateDerivedState() {
    this.status?.update();
    this.visibilityConditions.forEach((_conditions, target) => {
      this._updateVisibilityTarget(target);
    });
  }
  _updateVisibility(trigger) {
    const targets = this.visibilityTriggers.get(trigger);
    if (!targets) return;
    const changes = Array.from(targets, (target) => ({
      target,
      visible: this._visibilityConditionsMatch(target)
    })).filter(
      ({ target, visible }) => target.elt?.dataset.visible !== (visible ? "true" : "false")
    );
    if (!changes.length) return;
    void withTransition(
      () => {
        changes.forEach(({ target, visible }) => {
          const { elt } = target;
          if (elt) elt.dataset.visible = visible ? "true" : "false";
        });
      },
      { label: "form:conditional-visibility" }
    );
  }
  _updateVisibilityTarget(target) {
    const visible = this._visibilityConditionsMatch(target);
    const { elt } = target;
    if (elt) elt.dataset.visible = visible ? "true" : "false";
  }
  _visibilityConditionsMatch(target) {
    const conditions = (this.visibilityConditions.get(target) || []).filter(
      (condition) => condition?.id
    );
    if (conditions.length === 0) return true;
    const groups = /* @__PURE__ */ new Map();
    for (const condition of conditions) {
      const group = groups.get(condition.id) || [];
      group.push(condition);
      groups.set(condition.id, group);
    }
    return Array.from(groups.entries()).every(([triggerId, group]) => {
      const element = this.elements.get(`${triggerId}-${this.id}`);
      if (!element) return false;
      const { active } = element;
      if (!active)
        throw new TypeError(
          `Condition trigger ${triggerId} cannot match a value`
        );
      return group.some((condition) => active.call(element, condition.value));
    });
  }
  async _createElements() {
    for (const eltSchema of this.form.schema) {
      const eltSubmission = this.form.submission?.[eltSchema.id];
      try {
        const element = await getFormElement(
          this,
          eltSchema,
          eltSubmission
        );
        this.elements.set(element.id, element);
      } catch (error) {
        captureError(error, this.target, {
          schema: eltSchema,
          submission: eltSubmission
        });
      }
    }
  }
}

const presentFragment = (fragment) => Boolean(fragment);
class FormController {
  constructor(widget) {
    this._widget = widget;
    this._destroyed = false;
    this._submitGroup = widget.submitGroup ?? null;
    this._submitButton = widget.submitButton ?? null;
    this._header = widget.header ?? null;
    this._messages = widget.messages ?? {};
    this._icon = widget.icon ?? null;
    this._error = widget.error ?? null;
    this._editedMarker = widget.target?.querySelector("[lp-edited-marker]") ?? null;
    this._subForm = null;
    this.renderer = null;
    this.destroyables = [];
    this._offlineBlocked = false;
    this._offlineListener = null;
    this._unsavedStateListener = null;
    this._resetListener = null;
    this._queued = false;
    this.markUnsavedState = this.markUnsavedState.bind(this);
    this.clearUnsavedState = this.clearUnsavedState.bind(this);
    this.submitting = this.submitting.bind(this);
    this.syncOfflineState = this.syncOfflineState.bind(this);
  }
  get target() {
    return this._widget.target;
  }
  get key() {
    return this._widget.key;
  }
  get html() {
    return this._widget.html;
  }
  get readonly() {
    return this._widget.readonly;
  }
  get showEmptyFields() {
    return this._widget.showEmptyFields;
  }
  get historyFillEnabled() {
    return this._widget.historyFillEnabled ?? false;
  }
  get submitGroup() {
    if (this.readonly) {
      return null;
    } else if (this._subForm) {
      return this._subForm.submitGroup;
    } else if (this._submitGroup) {
      return this._submitGroup;
    } else {
      return this.target.querySelector(
        "[data-role='submit-group']"
      );
    }
  }
  get submitButton() {
    if (this.readonly) {
      return null;
    } else if (this._subForm) {
      return this._subForm.submitButton;
    } else if (this._submitButton) {
      return this._submitButton;
    } else if (this.submitGroup) {
      return this.submitGroup.querySelector(
        "button[type='submit']"
      );
    } else {
      return this.target.querySelector(
        "button[type='submit']"
      );
    }
  }
  get schema() {
    return this._widget.schema ?? [];
  }
  get submission() {
    return this._widget.submission ?? {};
  }
  get htmlFields() {
    return this._widget.htmlFields ?? {};
  }
  get messages() {
    if (this._subForm) {
      return this._subForm.messages;
    } else {
      return this._messages ?? {};
    }
  }
  get icon() {
    if (this._subForm) {
      return this._subForm.icon;
    } else {
      return this._icon ?? null;
    }
  }
  get error() {
    const error = this._error ?? this.target.querySelector("[data-role='error']") ?? primitives.error(void 0);
    if (!this.target.contains(error)) {
      const anchor = this.submitGroup || this.submitButton;
      anchor ? anchor.before(error) : this.target.prepend(error);
    }
    return error;
  }
  get canSubmitOffline() {
    if (this._subForm?.deferred) return false;
    return this.target?.hasAttribute("lp-offline") && typeof this._widget.offline === "function";
  }
  async init() {
    try {
      await this._initialize();
    } catch (error) {
      this.destroy();
      throw error;
    }
  }
  async _initialize() {
    const prepend = this._widget.prepend;
    const append = this._widget.append;
    const html = this.html ?? [];
    const schema = this.schema ?? [];
    if (schema.length > 0) {
      this.renderer = new FormRenderer(this);
      await this.renderer.render();
    } else if (html.length > 0) {
      this.target.replaceChildren(...html.filter(presentFragment));
    }
    this.target.setAttribute("autocomplete", "off");
    if (this._header && !this.target.contains(this._header)) {
      this.target.prepend(this._header);
    }
    if (Array.isArray(prepend)) {
      this.target.prepend(...prepend.filter(presentFragment));
    }
    const submitGroup = this.submitGroup ?? this.submitButton;
    if (Array.isArray(append)) {
      this.target.append(...append.filter(presentFragment));
      if (submitGroup) this.target.append(submitGroup);
    } else if (submitGroup && !this.target.contains(submitGroup)) {
      this.target.append(submitGroup);
    }
    if (this._editedMarker) {
      const autofillPanel = this.target.querySelector("[data-role='autofill']");
      if (autofillPanel) {
        autofillPanel.before(this._editedMarker);
      } else if (!this.target.contains(this._editedMarker)) {
        const markerAnchor = this.submitGroup ?? this.submitButton;
        if (markerAnchor) {
          markerAnchor.before(this._editedMarker);
        } else {
          this.target.append(this._editedMarker);
        }
      }
    }
    await initFormControls(this);
    if (this._destroyed) return;
    this._initSubmitButton();
    this._initOfflineState();
    this._initUnsavedState();
    this.target.setAttribute("rendered", "");
  }
  _initOfflineState() {
    const viewElt = this._widget.view?.elt;
    if (viewElt && !this._offlineListener) {
      this._offlineListener = () => this.syncOfflineState();
      viewElt.addEventListener("offline-status", this._offlineListener);
    }
    this.syncOfflineState();
  }
  _initUnsavedState() {
    if (this.readonly || !this.submitButton || this._unsavedStateListener)
      return;
    this._unsavedStateListener = this.markUnsavedState;
    this._resetListener = () => queueMicrotask(this.clearUnsavedState);
    this.target.addEventListener("input", this._unsavedStateListener);
    this.target.addEventListener("change", this._unsavedStateListener);
    this.target.addEventListener("reset", this._resetListener);
    this.syncOfflineState();
  }
  markUnsavedState(event = null) {
    const control = event?.target;
    if (control && (!("matches" in control) || typeof control.matches !== "function" || !control.matches("input, select, textarea, [contenteditable='true']") || "disabled" in control && control.disabled)) {
      return;
    }
    if (this._widget.markUnsavedState) {
      this._widget.markUnsavedState();
    } else {
      this._widget.unsavedState = true;
      this.syncOfflineState();
    }
  }
  clearUnsavedState() {
    if (this._widget.clearUnsavedState) {
      this._widget.clearUnsavedState();
    } else {
      this._widget.unsavedState = false;
    }
    if (!this._queued && !this._offlineBlocked && this.submitButton) {
      this.setSubmitButton({
        message: "submit",
        icon: this.icon,
        disabled: false
      });
    }
  }
  success() {
    if (!this.submitButton) return;
    this._queued = false;
    this.clearUnsavedState();
    this.hideError();
    this.setSubmitButton({
      message: "submitted",
      icon: "check",
      fade: true,
      disabled: false
    });
  }
  submitting() {
    if (!this.submitButton) return;
    if (this.syncOfflineState()) return;
    this._queued = false;
    this.setSubmitButton({
      message: "submitting",
      icon: "spinner"
    });
    this.hideError();
  }
  setSubmitButton(attributes) {
    const { submitButton, submitGroup } = this;
    const { message, icon, disabled, fade = false } = attributes;
    if (!submitButton) return;
    let textElement = submitButton.querySelector(
      "span[data-role='text']"
    );
    if (!textElement) {
      textElement = document.createElement("span");
      textElement.dataset.role = "text";
      submitButton.replaceChildren(textElement);
    }
    textElement.textContent = this.messages[message] ?? message ?? "";
    let iconWrapper = submitButton.querySelector(
      "span[data-role='icon']"
    );
    if (icon) {
      if (!iconWrapper) {
        iconWrapper = document.createElement("span");
        iconWrapper.dataset.role = "icon";
        submitButton.prepend(iconWrapper);
      }
      const iconElement = createIcon(icon);
      iconWrapper.dataset.visible = "true";
      if (fade) {
        showBriefly(iconWrapper, iconElement);
      } else {
        iconWrapper.replaceChildren(iconElement);
      }
    } else if (iconWrapper) {
      iconWrapper.replaceChildren();
      iconWrapper.dataset.visible = "false";
    }
    submitButton.dataset.visible = "true";
    submitButton.classList.remove("hidden");
    submitButton.disabled = Boolean(disabled);
    submitButton.setAttribute("aria-disabled", disabled ? "true" : "false");
    submitButton.classList.toggle("opacity-75", Boolean(disabled));
    submitButton.classList.toggle("cursor-not-allowed", Boolean(disabled));
    submitButton.classList.toggle("pointer-events-none", Boolean(disabled));
    if (submitGroup) submitGroup.dataset.visible = "true";
  }
  queued() {
    if (!this.submitButton) return;
    this._queued = true;
    this.hideError();
    this.setSubmitButton({
      message: "queued",
      icon: "offline",
      disabled: false
    });
  }
  toggleSubForm(form) {
    if (form) {
      this.hideSubmitGroup();
      this._subForm = form;
    } else {
      this._subForm = null;
      this.showSubmitGroup();
    }
    this._initSubmitButton();
  }
  _initSubmitButton() {
    const submitButton = this.submitButton;
    if (!this.messages?.submit || !submitButton) return;
    this.setSubmitButton({ message: "submit", icon: this.icon });
    if (submitButton.__initialized || !this.messages?.submitting) return;
    submitButton.__initialized = true;
    submitButton.addEventListener("click", this.submitting);
  }
  syncOfflineState() {
    if (!this.submitButton) return false;
    const blocked = Boolean(
      this._widget.view?.offline && !this.canSubmitOffline
    );
    const wasBlocked = this._offlineBlocked;
    if (blocked) {
      this._offlineBlocked = true;
      this.hideError();
      this.setSubmitButton({
        message: "Server Offline",
        icon: "offline",
        disabled: true
      });
      return true;
    }
    this._offlineBlocked = false;
    if (this._queued) return false;
    if (this.submitButton.disabled && !wasBlocked) return false;
    if (this._widget.unsavedState) {
      this.setSubmitButton({
        message: "submit",
        icon: "builder.unsaved",
        disabled: false
      });
      return false;
    }
    if (wasBlocked) {
      this.setSubmitButton({
        message: "submit",
        icon: this.icon,
        disabled: false
      });
    }
    return false;
  }
  showError(error) {
    const errorElement = this.error;
    if (!errorElement) return;
    withTransition(() => {
      errorElement.textContent = error;
      errorElement.dataset.visible = "true";
      this.setSubmitButton({
        message: "submit",
        icon: this.icon,
        disabled: false
      });
      this.syncOfflineState();
    });
  }
  hideError() {
    if (!this.error) return;
    this.error.textContent = "";
    this.error.dataset.visible = "false";
  }
  showSubmitButton() {
    if (!this.submitButton) return;
    this.hideError();
    this.setSubmitButton({
      message: "submit",
      icon: this.icon,
      disabled: false
    });
    this.syncOfflineState();
  }
  showSubmitGroup() {
    if (!this.submitGroup) return;
    this.hideError();
    this.setSubmitButton({
      message: "submit",
      icon: this.icon,
      disabled: false
    });
    this.syncOfflineState();
  }
  hideSubmitGroup() {
    if (!this.submitGroup) return;
    this.hideError();
    this.submitGroup.dataset.visible = "false";
    const submitButton = this.submitButton;
    if (!submitButton) throw new TypeError("Submit group has no submit button");
    submitButton.disabled = true;
  }
  hideSubmitButton() {
    if (!this.submitButton) return;
    this.hideError();
    this.submitButton.dataset.visible = "false";
    this.submitButton.disabled = true;
  }
  resetSubmitButton() {
    this._queued = false;
    this.setSubmitButton({
      message: "submit",
      icon: this.icon,
      disabled: false
    });
    this.hideError();
    this.syncOfflineState();
  }
  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;
    const submitButton = this.submitButton;
    if (submitButton?.__initialized) {
      submitButton.removeEventListener("click", this.submitting);
      delete submitButton.__initialized;
    }
    if (this._offlineListener) {
      this._widget.view?.elt?.removeEventListener(
        "offline-status",
        this._offlineListener
      );
      this._offlineListener = null;
    }
    if (this._unsavedStateListener) {
      this.target?.removeEventListener("input", this._unsavedStateListener);
      this.target?.removeEventListener("change", this._unsavedStateListener);
      this._unsavedStateListener = null;
    }
    if (this._resetListener) {
      this.target?.removeEventListener("reset", this._resetListener);
      this._resetListener = null;
    }
    if (this.renderer) this.renderer.destroy();
    this.destroyables.forEach((destroyable) => {
      if (destroyable.destroy) destroyable.destroy();
    });
    this.destroyables = [];
  }
}

var controller = /*#__PURE__*/Object.freeze({
	__proto__: null,
	FormController: FormController
});

const Submitter = (BaseClass) => {
  const ComboboxBase = BaseClass;
  class SubmittingCombobox extends ComboboxBase {
    init() {
      this.multiple ??= JSON.parse(this.parent.dataset.multiple || "false");
      this.create = !!this.create;
      if (this.element?.name) {
        this.name = this.element.name;
        this.element.removeAttribute("name");
      }
      const preload = JSON.parse(
        this.preload || "[]"
      );
      (Array.isArray(preload) ? preload : [preload]).forEach((option) => {
        this.addOption(option, true);
      });
      this.updatePanel(this.results.create(this.items || []));
      this.updateSelect(true);
      super.init();
    }
    setupSelect() {
      if (this.select) {
        this.select.innerHTML = "";
        return;
      } else {
        this.select = document.createElement("select");
        this.element.after(this.select);
        this.select.multiple = Boolean(this.multiple);
        this.select.name = String(this.name);
        this.select.style.display = "none";
      }
    }
    updateSelect(preloading = false) {
      this.setupSelect();
      const select = this.select;
      if (!select) return;
      this.values.forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.selected = true;
        select.appendChild(option);
      });
      if (this.options.length > 0) {
        this.updatePlaceholder();
      }
      if (!preloading) {
        this.dispatchChangeEvents();
      }
    }
    dispatchChangeEvents() {
      const event = new CustomEvent("updated", {
        bubbles: true,
        detail: {
          name: this.name,
          options: Object.fromEntries(
            this.options.filter((o) => o.id !== void 0 && this.values.has(o.id)).map((o) => [o.id, o])
          )
        }
      });
      this.element.dispatchEvent(event);
      this.select?.dispatchEvent(new Event("change", { bubbles: true }));
    }
    updatePlaceholder() {
      let displaySet;
      const focusedOption = this.focusedOption();
      if (focusedOption && !this.multiple) {
        displaySet = /* @__PURE__ */ new Set([focusedOption.dataset.id]);
      } else if (focusedOption && this.multiple) {
        displaySet = /* @__PURE__ */ new Set([...this.values, focusedOption.dataset.id]);
      } else {
        displaySet = new Set(this.values);
      }
      const totalCount = displaySet.size;
      if (totalCount === 0) {
        this.element.placeholder = this.placeholder;
        this.element.dataset.values = "false";
        return;
      }
      this.element.dataset.values = "true";
      const options = Array.from(displaySet).map((id) => this.options.find((o) => o.id === id)).filter((option) => option !== void 0);
      const names = options.map((o) => o.name).join(", ");
      const kinds = new Set(
        options.map((o) => o.kind).filter((k) => k && k !== "default")
      );
      if (kinds.size === 1) {
        this.element.dataset.kind = Array.from(kinds)[0];
      } else {
        this.element.dataset.kind = this.kind || "default";
      }
      this.element.value = "";
      this.element.placeholder = names || this.placeholder;
    }
    focusOption(index) {
      super.focusOption(index);
      this.updatePlaceholder();
    }
    unfocusOption(option) {
      super.unfocusOption(option);
      this.updatePlaceholder();
    }
    selectOption(option) {
      const key = option.dataset.id;
      if (key === void 0) return;
      if (!this.multiple) {
        this.values.clear();
        this.values.add(key);
        this.hidePanel();
      } else if (this.values.has(key)) {
        this.values.delete(key);
        this.unfocusOption(option);
        if (option._checkbox) option._checkbox.checked = false;
      } else {
        this.values.add(key);
        if (option._checkbox) option._checkbox.checked = true;
      }
      this.updateSelect();
    }
    elementKeydown(event) {
      super.elementKeydown(event);
      if (event.defaultPrevented) return;
      if (event.key === "Enter") {
        event.stopPropagation();
        event.preventDefault();
        if (this.panelOpen) {
          this.hidePanel();
        } else if (this.options.length > 0) {
          this.showPanel();
        }
      } else if (this.values.size > 0 && (event.key === "Backspace" || event.key === "Delete")) {
        event.stopPropagation();
        this.clear();
      }
    }
    deactivate() {
      this.hidePanel();
      this.unfocusOption();
      this.element.dispatchEvent(
        new CustomEvent("deactivate", { bubbles: true })
      );
      this.element.value = "";
      this.updatePlaceholder();
    }
    addValue(value, preloading = false) {
      this.values.add(value);
      this.updateSelect(preloading);
    }
    addOption(option = {}, preloading = false) {
      if (Object.keys(option).length === 0) return;
      if (option.id && !this.options.some((o) => o.id === option.id)) {
        this.options.unshift(option);
      }
      this.results.add(option);
      if (option.id !== void 0) this.addValue(option.id, preloading);
    }
    clear({ notify = true } = {}) {
      if (this.values.size === 0) return;
      this.values.clear();
      this.focusedIndex = -1;
      this.element.value = "";
      this.hidePanel();
      this.updateSelect(!notify);
    }
  }
  return SubmittingCombobox;
};

function isFacetOption(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const data = { ...value };
  return ["id", "name", "kind", "hash"].every(
    (key) => data[key] === void 0 || typeof data[key] === "string"
  );
}
class FacetsBox extends Submitter(RemoteQueryCombobox) {
  constructor(element, args = {}) {
    super(element);
    this.endpoint = ENDPOINTS.facet(String(this.index));
    this.indexArgs = args;
    const formType = this.formType;
    if (formType) {
      this.indexArgs["form-type"] = formType;
    }
    if (this.includeUsers === "false") {
      this.indexArgs["include-users"] = "false";
    }
    if (this.permission) {
      this.indexArgs.permission = this.permission;
    }
    let index = this.index;
    if (formType) {
      index = `${this.index}-${formType}`;
    } else if (this.indexArgs.models === false) {
      index = `${this.index}-no-models`;
    }
    this.results = new Results(index);
  }
  _input(event) {
    const query = event.target.value.trim();
    if (query) return this._search(query);
    this.settleQueryInput();
    this.updatePanel(this.results.create());
    return this.showPanel();
  }
  elementClick(event) {
    super.elementClick(event);
    this.showPanel();
  }
  selectOption(option) {
    if (option.dataset.command === "create") {
      return this._createOption(option);
    }
    if (!option.dataset.id) return;
    this.invalidateQuery();
    super.selectOption(option);
    this.results.save(option);
  }
  get selectedOptions() {
    return this.options.filter(
      (o) => o.id !== void 0 && this.values.has(o.id)
    );
  }
  _search(query) {
    const params = new URLSearchParams();
    params.set("q", query);
    if (this.creatable === "true") {
      params.set("creatable", "true");
    }
    Object.entries(this.indexArgs).forEach(([key, value]) => {
      params.set(key, String(value));
    });
    this.selectedOptions.forEach(({ hash }) => {
      params.append("preload", String(hash));
    });
    return this.runQuery(
      query,
      (token) => request.get(this.endpoint, params, {
        signal: token.signal
      }),
      (response) => {
        if (response?.ok) {
          this.updatePanel(response.results || null);
        } else {
          this.clearQueryResults();
        }
        return this.showPanel();
      }
    );
  }
  _createOption(option) {
    const selectedOptions = this.selectedOptions;
    const query = this.element.value.trim();
    this.hidePanel();
    const data = new FormData();
    data.set("name", option.dataset.name || query);
    Object.entries(this.indexArgs).forEach(([key2, value]) => {
      data.set(key2, String(value));
    });
    const key = `create:${query}`;
    return this.runQuery(
      key,
      () => request.post(`${this.endpoint}/create`, data),
      (response) => {
        if (!response?.ok) return;
        let html = response.results || null;
        if (this.multiple && response.option) {
          html = this.results.create(
            [...selectedOptions, response.option].filter(
              (item, index, items) => item?.id && items.findIndex((i) => i?.id === item.id) === index
            )
          );
        }
        this.updatePanel(html);
        const created = [
          ...this.panel?.querySelectorAll(
            "[role='option'][data-id]"
          ) || []
        ].find((item) => item.dataset.id === response.option?.id);
        if (!created) return;
        super.selectOption(created);
        this.results.save(created);
      },
      {
        cancelTransport: false,
        getCurrentKey: () => `create:${this.element.value.trim()}`
      }
    );
  }
}

class SelectBox extends Submitter(Combobox) {
  constructor(element) {
    super(element);
    this.results = new Results();
    this.items = [];
  }
  init() {
    const select = this.parent.querySelector("select");
    if (!select) throw new Error("SelectBox requires a native select element");
    this.select = select;
    const multiple = JSON.parse(
      this.select.dataset.multiple || "false"
    );
    this.multiple = multiple;
    this.select.name = String(this.name);
    this.select.multiple = multiple;
    this.select.style.display = "none";
    const input = document.createElement("input");
    this.element = input;
    this.select.after(input);
    input.className = `${this.select.className}`;
    input.dataset.mode = "select";
    input.readOnly = true;
    input.setAttribute("inputmode", "none");
    this._createItems();
    super.init();
  }
  updateSelect(preloading = false) {
    Array.from(this.select.options).forEach((option) => {
      option.selected = this.values.has(option.value);
    });
    if (this.values.size === 0) {
      this.select.selectedIndex = -1;
    }
    this.updatePlaceholder();
    if (!preloading) {
      this.dispatchChangeEvents();
    }
  }
  _createItems() {
    if (this.select.options.length === 0) return;
    this.items = Array.from(this.select.options).filter((option) => option.value).map((option) => {
      const details = JSON.parse(
        option.dataset.details || "{}"
      );
      return {
        id: option.value,
        name: option.textContent ?? "",
        kind: this.select.dataset.kind || "default",
        ...details,
        disabled: option.disabled || (option.parentElement?.hasAttribute("disabled") ?? false)
      };
    });
  }
  selectOption(option) {
    if (option.getAttribute("aria-disabled") === "true") return;
    super.selectOption(option);
  }
  elementClick(event) {
    event.stopPropagation();
    this.panelOpen ? this.hidePanel() : void this.showPanel();
  }
  addOption(option) {
    if (!this.items) this._createItems();
    if (option.id !== void 0) this.values.add(option.id);
  }
  hidePanel() {
    super.hidePanel();
    this.element.blur();
  }
}

const NON_HISTORY_FILLABLE_TYPES = /* @__PURE__ */ new Set(["html", "signature", "status"]);
class BaseElement {
  constructor(renderer, schema, submission) {
    this.renderer = renderer;
    this.schema = schema;
    this.readonly = renderer.readonly;
    this.element = null;
    this.destroyables = [];
    this.submission = submission;
    this.static = false;
    this._elt = null;
    this._read = null;
    this._edit = null;
  }
  get submission() {
    return this._submission ?? null;
  }
  set submission(value) {
    const submission = value ?? null;
    if (submission === null || typeof submission === "object" && Object.keys(submission).length === 0) {
      this._submission = null;
    } else {
      this._submission = submission;
    }
  }
  get hasSubmission() {
    return this.submission !== null && this.submission !== "";
  }
  get showEmptyFields() {
    return this.renderer.showEmptyFields;
  }
  get historyFillable() {
    return !NON_HISTORY_FILLABLE_TYPES.has(this.schema?.type ?? "");
  }
  get canHistoryFill() {
    return Boolean(
      this.renderer.historyFillEnabled && this.historyFillable && !this.readonly && !this.cellEditing && !this.static && !this.hasSubmission && this.schema?.id
    );
  }
  get mode() {
    if (this.renderer.mode) {
      return this.renderer.mode;
    } else if (this.readonly) {
      return "read";
    } else if (this.hasSubmission) {
      return "read";
    } else {
      return "edit";
    }
  }
  get id() {
    if (this.renderer.id) {
      return `${this.schema.id}-${this.renderer.id}`;
    }
    return this.schema.id;
  }
  get cellEditing() {
    return this.renderer.cellEditing === true;
  }
  get label() {
    if (this.cellEditing) return null;
    return this.schema.title || this.schema.label;
  }
  get read() {
    return this._read;
  }
  get edit() {
    return this._edit;
  }
  get cellEdit() {
    const edit = this.edit;
    if (!edit) return null;
    this._elt = edit;
    edit.dataset.editing = "true";
    edit.dataset.type = String(this.schema.type);
    return edit;
  }
  get cell() {
    if (this.cellEditing) return this.cellEdit;
    if (!this.hasSubmission) return null;
    return this.read?.innerHTML ?? "";
  }
  readonlyPlaceholder() {
    const empty = document.createElement("p");
    empty.className = `${STYLES.form.submission.default} text-base-medium italic`;
    empty.textContent = "Not provided";
    return empty;
  }
  historyValueAvailable(value) {
    if (value === null || value === void 0 || value === "") return false;
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === "object") return Object.keys(value).length > 0;
    return true;
  }
  fillFromHistory(value) {
    if (!this.historyValueAvailable(value)) return false;
    const current = this._elt;
    if (!current) return false;
    this.submission = value;
    current.classList.add("opacity-50", "pointer-events-none");
    this.destroy();
    const elt = this.create();
    if (!elt) return false;
    current.replaceWith(elt);
    this._elt = elt;
    elt.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }
  historyFillButton(value) {
    if (!this.canHistoryFill || !this.historyValueAvailable(value)) return null;
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.role = "history-fill";
    button.ariaLabel = "Fill from latest history";
    button.title = "Fill from latest history";
    button.className = STYLES.form.icon;
    setIcon(
      button.appendChild(document.createElement("span")),
      "historyFill",
      "icon-xs"
    );
    const labelSpan = button.appendChild(document.createElement("span"));
    labelSpan.textContent = "Use last";
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (button.disabled) return;
      if (typeof value !== "function") {
        this.fillFromHistory(value);
        return;
      }
      const readValue = () => "value" in this ? this.value ?? this.submission : this.submission;
      const before = JSON.stringify(readValue());
      button.disabled = true;
      labelSpan.textContent = "Loading...";
      try {
        const restored = await value();
        if (button.isConnected && this.canHistoryFill && JSON.stringify(readValue()) === before)
          this.fillFromHistory(restored);
      } finally {
        button.disabled = false;
        if (button.isConnected) labelSpan.textContent = "Use last";
      }
    });
    return button;
  }
  addHistoryFill(value) {
    const button = this.historyFillButton(value);
    if (!button) return false;
    const elt = this.elt;
    if (!elt) return false;
    const label = elt.dataset?.role === "label" ? elt : elt.querySelector("[data-role='label']");
    if (!label || label.querySelector("[data-role='history-fill']")) {
      return false;
    }
    label.append(button);
    return true;
  }
  create() {
    let elt;
    if (this.readonly && this.schema.type !== "table") {
      elt = document.createElement("div");
      const label2 = primitives.label({
        label: this.label,
        tag: "h3"
      });
      elt.appendChild(label2);
    } else {
      elt = this.edit;
    }
    if (!elt) return null;
    const label = elt.dataset?.role === "label" ? elt : elt.querySelector("[data-role='label']");
    elt.id = this.id;
    elt.classList.add("form-element", "group/element");
    if (this.schema.type !== "table") {
      elt.dataset.mode = this.mode;
    }
    let read = null;
    if (this.hasSubmission) {
      read = this.read;
    } else if (this.showEmptyFields && !this.static) {
      read = this.readonlyPlaceholder();
    }
    if (read) {
      read.dataset.role = "read";
      if (!this.readonly && this.hasSubmission) {
        read.classList.add("cursor-pointer", "transition-colors");
        const readRow = document.createElement("div");
        readRow.dataset.role = "read-row";
        readRow.className = STYLES.form.readRow;
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.role = "edit";
        button.ariaLabel = `Edit ${this.label}`;
        button.title = `Edit ${this.label}`;
        button.className = STYLES.form.readEdit;
        setIcon(
          button.appendChild(document.createElement("span")),
          "edit",
          "icon-sm"
        );
        readRow.append(read, button);
        elt.appendChild(readRow);
      } else {
        elt.appendChild(read);
        if (this.readonly) {
          elt.classList.add("flex", "flex-col", "gap-1");
        }
      }
    }
    if (label && "clear" in this && this.clear && !this.readonly) {
      const clearButton = label.appendChild(document.createElement("button"));
      clearButton.type = "button";
      clearButton.dataset.role = "clear";
      clearButton.dataset.kind = "default";
      clearButton.ariaLabel = `Clear ${this.label}`;
      clearButton.title = `Clear ${this.label}`;
      clearButton.hidden = !this.hasSubmission;
      clearButton.className = `group-data-[mode=read]/element:hidden ${STYLES.form.icon}`;
      setIcon(
        clearButton.appendChild(document.createElement("span")),
        "x",
        "icon-xs"
      );
      const clearText = clearButton.appendChild(document.createElement("span"));
      clearText.textContent = "Clear";
    }
    elt._lp_element = this;
    return elt;
  }
  get elt() {
    if (this._elt) return this._elt;
    if (this.readonly && !this.hasSubmission && !this.static && !this.showEmptyFields)
      return null;
    this._elt = this.create();
    return this._elt;
  }
  destroy() {
    this.destroyables.forEach((d) => {
      if (d.destroy) d.destroy();
    });
    this.destroyables = [];
    this._read = null;
    this._edit = null;
  }
  changed(value) {
    return this.submission !== value;
  }
  update(value) {
    const current = this.elt;
    if (current?.contains(document.activeElement)) {
      return false;
    } else if (!this.changed(value)) {
      return true;
    }
    if ("updateSubmission" in this && typeof this.updateSubmission === "function") {
      this.updateSubmission(value);
      return true;
    }
    this.submission = value;
    current?.classList.add("opacity-50", "pointer-events-none");
    this.destroy();
    const elt = this.create();
    if (elt) current?.replaceWith(elt);
    this._elt = elt;
    return true;
  }
}

class InputElement extends BaseElement {
  get value() {
    const input = this.elt instanceof HTMLInputElement ? this.elt : this.elt?.querySelector("input");
    if (input) return input.value;
    if (this.submission === null || this.submission === void 0) return null;
    return String(this.submission);
  }
  changed(value) {
    if (this.value === String(value ?? "")) return false;
    return true;
  }
  clear() {
    this.submission = null;
    const input = this._edit?.querySelector("input");
    if (input) input.value = "";
  }
  focus() {
    const input = this._edit?.querySelector("input");
    if (input) input.focus();
  }
  get read() {
    if (this._read) return this._read;
    this._read = document.createElement("p");
    this._read.className = STYLES.form.submission.default;
    const submission = this.submission;
    if ((typeof submission === "string" || submission instanceof Date) && this.schema.input === "date") {
      this._read.textContent = formatting.date(submission) || "";
    } else if (typeof submission === "string" && submission && this.schema.input === "time") {
      this._read.textContent = formatting.time(submission);
    } else if (typeof submission === "string" && submission && this.schema.input === "tel") {
      this._read.textContent = formatting.tel(submission);
    } else if (typeof submission === "string" && submission && this.schema.input === "email") {
      this._read.appendChild(formatting.email(submission));
    } else {
      this._read.textContent = this.hasSubmission ? String(this.submission) : "";
    }
    this._read.classList.add("group-data-[mode=edit]/element:hidden");
    return this._read;
  }
  get cell() {
    if (this.cellEditing) return this.cellEdit;
    if (!this.hasSubmission) return null;
    return this.read.innerHTML;
  }
  get edit() {
    if (this._edit) return this._edit;
    this._edit = primitives.input({
      label: this.label,
      name: this.schema.id || this.schema.name,
      type: this.schema.input || "text",
      placeholder: this.schema.placeholder,
      value: this.submission,
      disabled: this.renderer.readonly
    });
    const input = this._edit.matches?.("input") ? this._edit : this._edit.querySelector("input");
    input?.classList.add("group-data-[mode=read]/element:hidden");
    return this._edit;
  }
}

var input = /*#__PURE__*/Object.freeze({
	__proto__: null,
	InputElement: InputElement
});

class TextareaElement extends BaseElement {
  get value() {
    const textarea = findTextarea(this.elt);
    if (textarea) return textarea.value;
    if (this.submission === null || this.submission === void 0) return null;
    return String(this.submission);
  }
  changed(value) {
    if (this.value === String(value ?? "")) return false;
    return true;
  }
  clear() {
    this.submission = null;
    const textarea = findTextarea(this._edit);
    if (textarea) textarea.value = "";
  }
  get read() {
    if (this._read) return this._read;
    this._read = document.createElement("p");
    this._read.textContent = this.hasSubmission ? String(this.submission) : "";
    this._read.className = STYLES.form.submission.grows;
    this._read.classList.add(
      "whitespace-pre-wrap",
      "group-data-[mode=edit]/element:hidden"
    );
    return this._read;
  }
  get edit() {
    if (this._edit) return this._edit;
    this._edit = primitives.textarea({
      label: this.label,
      name: this.schema.id,
      placeholder: this.schema.placeholder,
      rows: 3,
      value: this.submission,
      disabled: this.renderer.readonly
    });
    const textarea = this._edit.matches?.("textarea") ? this._edit : this._edit.querySelector("textarea");
    textarea?.classList.add("group-data-[mode=read]/element:hidden");
    return this._edit;
  }
}
const findTextarea = (root) => root?.matches("textarea") ? root : root?.querySelector("textarea");

var textarea = /*#__PURE__*/Object.freeze({
	__proto__: null,
	TextareaElement: TextareaElement
});

function installMigrationNotice(widget) {
  widget._migrationNotice?.destroy();
  const target = widget.target;
  if (!target || widget.revisionPreview || target.dataset.completed === "true")
    return;
  const values = JSON.parse(
    target.dataset.migrationNotice || "[]"
  );
  if (!values.length) return;
  let trigger = target.querySelector(
    "[data-role='migration-changes']"
  );
  let banner = null;
  if (!trigger) {
    banner = document.createElement("p");
    banner.dataset.role = "migration-notice";
    banner.className = STYLES.message;
    banner.textContent = "This form was updated. ";
    trigger = banner.appendChild(document.createElement("button"));
    trigger.type = "button";
    trigger.className = "font-semibold underline underline-offset-2";
    trigger.textContent = "View changes";
    target.prepend(banner);
  }
  const modal = new Modal(widget.view, trigger);
  widget._migrationNotice = {
    destroy: () => {
      modal.destroy();
      trigger.removeEventListener("click", click);
      banner?.remove();
    }
  };
  const click = async () => {
    const root = document.createElement("div");
    root.id = "modal";
    root.className = STYLES.modal.wrapper;
    root.dataset.kind = widget.kind || widget.component?.kind || widget.view?.kind || "default";
    const content = root.appendChild(document.createElement("section"));
    content.id = "modal-content";
    content.className = `${STYLES.modal.content} w-full sm:max-w-3xl`;
    content.setAttribute("role", "dialog");
    content.setAttribute("aria-modal", "true");
    content.setAttribute("aria-label", "Form changes");
    const header = content.appendChild(document.createElement("header"));
    header.className = STYLES.modal.header;
    const heading = header.appendChild(document.createElement("h2"));
    heading.className = "text-lg font-bold text-base-dark";
    heading.textContent = "Form changes";
    const close = header.appendChild(document.createElement("button"));
    close.type = "button";
    close.setAttribute("lp-control", "close");
    close.className = STYLES.button.close;
    close.textContent = "Close";
    const body = content.appendChild(document.createElement("div"));
    body.className = "space-y-4 p-4 sm:p-6";
    const intro = body.appendChild(document.createElement("p"));
    intro.className = "text-sm text-base-medium";
    intro.textContent = "These values changed when the form was updated. The notice clears when this submission is next saved or completed.";
    const fields = body.appendChild(document.createElement("div"));
    fields.className = "space-y-4";
    for (const value of values) {
      const row = fields.appendChild(document.createElement("section"));
      row.className = "rounded-md border border-base-light/50 bg-base-bg p-3";
      const title = row.appendChild(document.createElement("h3"));
      title.className = "mb-2 font-semibold text-base-dark";
      title.textContent = value.label;
      const cells = row.appendChild(document.createElement("div"));
      cells.className = "grid gap-2 sm:grid-cols-2";
      for (const key of ["before", "after"]) {
        const cell = cells.appendChild(document.createElement("div"));
        cell.dataset.role = `migration-${key}`;
        cell.className = "min-w-0 rounded-md border border-base-light/50 bg-white p-3";
        const label = cell.appendChild(document.createElement("h4"));
        label.className = "mb-2 text-xs font-semibold text-base-medium";
        label.textContent = key === "before" ? "Before" : "After the update";
        const content2 = cell.appendChild(document.createElement("p"));
        content2.className = "whitespace-pre-wrap break-words text-sm";
        if (key === "after" && value.reason === "invalid") {
          content2.dataset.kind = "error";
          content2.className += " italic text-kind-default";
          content2.textContent = "Value not able to be converted";
        } else if (key === "after" && value.reason === "deleted") {
          content2.dataset.kind = "error";
          content2.className += " italic text-kind-default";
          content2.textContent = "Deleted from form";
        } else {
          if (key === "after") label.textContent = "Converted value";
          content2.textContent = value[key];
        }
      }
    }
    await modal.attach(root, widget.component);
    close.focus();
  };
  trigger.addEventListener("click", click);
}

const compatibleField = (before, after) => {
  if (!before || !after) return false;
  const kind = (field) => field.type === "input" ? field.input || "text" : field.type === "link" ? field.location || "out" : field.type;
  if (kind(before) !== kind(after) || Boolean(before.multiple) !== Boolean(after.multiple))
    return false;
  if (before.options?.some(
    ({ value }) => !after.options?.some((option) => option.value === value)
  ))
    return false;
  return !before.columns?.some(
    (column) => !compatibleField(
      column,
      after.columns?.find((item) => item.id === column.id)
    )
  );
};
const incompatibleSchema = (before, after) => (before || []).some(
  (field) => !compatibleField(
    field,
    (after || []).find((item) => item.id === field.id)
  )
);

class FormWidget {
  constructor(attributes) {
    Object.assign(this, attributes);
    this.destroyables = [];
    this.messages = {};
    this.schema = attributes.schema || null;
    this.submission = attributes.submission || null;
    this.form = null;
    this.initialTarget = this.target ? this.target.cloneNode(true) : null;
    this.initialized = false;
    this.unsavedState = false;
    this._revisionBaseline = null;
    this._created = false;
    this._updated = false;
    this._success = false;
    this._preparedReset = null;
    this._preparingReset = null;
    this._preparingState = null;
    this._resetEpoch = 0;
    this._replacementVersion = 0;
    this._replacementPromise = null;
    this._replacementInert = null;
    this._migrationNotice = null;
    this._reviewBar = null;
    this._deferredOperation = this.target?.dataset?.operation || null;
    this._click = this._click.bind(this);
    this._syncFieldClearEvent = this._syncFieldClearEvent.bind(this);
  }
  get deferredLocked() {
    return Boolean(
      this._deferredOperation && this.target?.dataset?.deferredLock
    );
  }
  lockDeferredOperation(descriptor = {}) {
    const operation = descriptor.operation || descriptor.key;
    if (!operation) return false;
    this._deferredOperation = operation;
    for (const target of [this.target, this.initialTarget]) {
      if (!target) continue;
      target.dataset.operation = operation;
      target.dataset.operationRevision = String(descriptor.revision ?? 0);
      target.dataset.operationScope = descriptor.scope || "";
      if (descriptor.blocks_edit === true || descriptor.scope === "form-change")
        target.dataset.deferredLock = "form";
      else delete target.dataset.deferredLock;
      if (descriptor.status && typeof descriptor.status === "object") {
        target.dataset.operationBootstrap = JSON.stringify(descriptor.status);
        if (target.dataset.formState) {
          const state = JSON.parse(target.dataset.formState);
          state.operation = descriptor.status;
          if (descriptor.status.type === "autofill" && !descriptor.status.terminal)
            state.stale_autofill = false;
          target.dataset.formState = JSON.stringify(state);
        }
      }
    }
    if (descriptor.status && typeof descriptor.status === "object") {
      this.reviewState = { ...this.reviewState, operation: descriptor.status };
      if (descriptor.status.type === "autofill" && !descriptor.status.terminal)
        this.reviewState.stale_autofill = false;
      renderReviewBar(this, descriptor.status);
    }
    return true;
  }
  get showEmptyFields() {
    return this.readonly && this.component?.showEmptyFields === true;
  }
  get formData() {
    const data = this.target instanceof HTMLFormElement ? new FormData(this.target) : new FormData();
    const state = this.reviewState ?? JSON.parse(this.target?.dataset?.formState || "{}");
    if (state.revision) data.set("form-revision", state.revision);
    for (const operation of this._reviewedOperations ?? [])
      data.append("reviewed-operation", operation);
    for (const operation of this._usedAutofillOperations ?? [])
      data.append("used-autofill-operation", operation);
    if (this._autofillRetry) data.set("autofill-retry", this._autofillRetry);
    return this.form?._subForm?.applyDirectUploads?.(data) ?? data;
  }
  get revisionEntries() {
    return [];
  }
  get revisionBaseline() {
    return this._revisionBaseline;
  }
  revisionSnapshot() {
    const grouped = /* @__PURE__ */ new Map();
    const entries = [...this.formData.entries(), ...this.revisionEntries];
    for (const [name, rawValue] of entries) {
      if ([
        "form-revision",
        "reviewed-operation",
        "used-autofill-operation",
        "autofill-retry"
      ].includes(name))
        continue;
      let value = rawValue;
      if (typeof File !== "undefined" && rawValue instanceof File) {
        if (!rawValue.name && rawValue.size === 0) continue;
        value = JSON.stringify({
          name: rawValue.name,
          size: rawValue.size,
          type: rawValue.type,
          lastModified: rawValue.lastModified
        });
      }
      const values = grouped.get(name) ?? [];
      values.push(String(value));
      grouped.set(name, values);
    }
    return JSON.stringify(
      Array.from(grouped.entries()).sort(([left], [right]) => left.localeCompare(right)).map(([name, values]) => [name, values.sort()])
    );
  }
  commitRevisionBaseline({ clearUnsaved = false } = {}) {
    this._revisionBaseline = this.revisionSnapshot();
    this._baselineSubmission = structuredClone(
      this.form?.renderer?._packageSubmission?.() ?? this.submission ?? {}
    );
    if (clearUnsaved) this.clearUnsavedState();
    return this._revisionBaseline;
  }
  revisionCanReset(preview) {
    return Boolean(preview && preview.name === this.name);
  }
  captureFormState() {
    const fields = [];
    const files = [];
    for (const [name, value] of this.formData.entries()) {
      if (typeof File !== "undefined" && value instanceof File) {
        if (value.name && value.size > 0) {
          files.push({
            name,
            file: value,
            filename: value.name,
            type: value.type
          });
        }
      } else {
        fields.push([name, value]);
      }
    }
    const formControls = Array.from(
      this.target?.querySelectorAll?.("[data-combobox-id]") || []
    ).filter((control) => !control.closest?.(".form-element")).map((control) => {
      const combobox = control._lp_combobox;
      if (!combobox?.name) return null;
      return {
        name: combobox.name,
        options: (combobox.options || []).filter(
          (option) => combobox.values?.has(option.id)
        )
      };
    }).filter((control) => control !== null);
    return {
      fields,
      files,
      form_controls: formControls,
      renderer_schema: structuredClone(this.schema),
      renderer_submission: this.form?.renderer?._packageSubmission?.() ?? null
    };
  }
  buildLocalRevision(response, state = this.captureFormState()) {
    const latestSchema = response.schema ?? [];
    const localSchema = state.renderer_schema ?? this.schema ?? [];
    const latestIds = new Set(
      latestSchema.map((field) => field?.id).filter(Boolean)
    );
    const localIds = new Set(
      localSchema.map((field) => field?.id).filter(Boolean)
    );
    const remoteSubmission = response.submission ?? {};
    const mergedSubmission = structuredClone(remoteSubmission);
    const localSubmission = state.renderer_submission ?? {};
    for (const id of localIds) {
      if (!latestIds.has(id) || !Object.hasOwn(localSubmission, id) || !compatibleField(
        localSchema.find((field) => field.id === id),
        latestSchema.find((field) => field.id === id)
      ))
        continue;
      mergedSubmission[id] = structuredClone(localSubmission[id]);
    }
    const html = response.html ? response.html.cloneNode(true) : null;
    const target = html?.querySelector(
      `[data-widget='${this.name}']`
    );
    this._applyQueuedFields(target, state);
    return {
      state,
      response: {
        ...response,
        html,
        schema: latestSchema,
        submission: mergedSubmission
      }
    };
  }
  async prepareRevision(response) {
    await this.updated(response);
    this._success = false;
    await this.prereconcile();
    return () => {
      this.postreconcile();
      this.commitRevisionBaseline({ clearUnsaved: true });
    };
  }
  async applyRevision(response) {
    const commit = await this.prepareRevision(response);
    commit();
  }
  async prepareLocalRevision(response, {
    remoteSnapshot = null,
    markUnsaved = false,
    selectedSubmission = void 0
  } = {}) {
    const wasUnsaved = this.unsavedState === true;
    const wasQueued = this.form?._queued === true;
    const local = this.buildLocalRevision(response);
    if (selectedSubmission !== void 0) {
      local.response.submission = selectedSubmission;
    }
    await this.updated(local.response);
    this._success = false;
    await this.prereconcile();
    return () => {
      this._skipQueuedRestore = true;
      try {
        this.postreconcile();
        this._restoreQueuedFiles(local.state);
      } finally {
        this._skipQueuedRestore = false;
      }
      if (remoteSnapshot !== null) this._revisionBaseline = remoteSnapshot;
      this._baselineSubmission = structuredClone(response.submission ?? {});
      if (wasQueued) {
        this.form?.queued();
      } else if (wasUnsaved || markUnsaved) {
        this.markUnsavedState();
      } else {
        this.commitRevisionBaseline({ clearUnsaved: true });
      }
      return local;
    };
  }
  async applyLocalRevision(response, options = {}) {
    const commit = await this.prepareLocalRevision(response, options);
    return commit();
  }
  async prepareSubmit(options) {
    if (this.deferredLocked) return false;
    return await this.form?._subForm?.prepareSubmit?.(options) ?? true;
  }
  markUnsavedState() {
    if (this.readonly || this.headless) return;
    this.unsavedState = true;
    this.form?.syncOfflineState?.();
  }
  clearUnsavedState() {
    this.unsavedState = false;
  }
  async init() {
    if (this.target?.hasAttribute("lp-load") && !this.target.hasAttribute("loaded"))
      return;
    await this._initForm();
    this.commitRevisionBaseline();
    this.initialized = true;
    this.target.setAttribute("initialized", "");
    const queue = this.view?.offlineQueue;
    if (typeof queue?.presentFor === "function" && typeof this.handleOfflineQueue === "function") {
      void queue.presentFor(this).catch((error) => {
        this.view?.reportStartupError?.(
          error,
          this.target,
          "offline-conflict-restore"
        );
      });
    }
  }
  async stageOfflineConflict(conflict = this._offlineConflict) {
    if (!conflict) return;
    const watcher = this.view?.EditWatcher || await this.view?.ensureEditWatcher?.();
    return watcher?.stageConflict?.(this, conflict);
  }
  _applyQueuedFields(target, record) {
    if (!target) return;
    const fields = /* @__PURE__ */ new Map();
    for (const [name, value] of record.fields || []) {
      const values = fields.get(name) || [];
      values.push(String(value));
      fields.set(name, values);
    }
    for (const name of ["name", "description"]) {
      const values = fields.get(name);
      if (values) target.dataset[name] = values[0] || "";
    }
    for (const control of target.querySelectorAll("[name]")) {
      if (["form-generation", "form-revision", "reviewed-operation"].includes(
        control.name
      ))
        continue;
      const values = fields.get(control.name) || [];
      if (control instanceof HTMLInputElement) {
        if (["checkbox", "radio"].includes(control.type)) {
          const checked = values.includes(control.value);
          control.checked = checked;
          control.defaultChecked = checked;
          control.toggleAttribute("checked", checked);
          const attribute = control.closest(
            "[data-role='attribute']"
          );
          if (attribute) attribute.dataset.selected = checked.toString();
        } else if (control.type !== "file" && values.length > 0) {
          control.value = values[0];
          control.defaultValue = values[0];
          control.setAttribute("value", values[0]);
        }
      } else if (control instanceof HTMLTextAreaElement) {
        control.value = values[0] || "";
        control.defaultValue = control.value;
        control.textContent = control.value;
      } else if (control instanceof HTMLSelectElement) {
        for (const option of control.options) {
          const selected = values.includes(option.value);
          option.selected = selected;
          option.defaultSelected = selected;
          option.toggleAttribute("selected", selected);
        }
      }
    }
    const preloadSources = Array.from(
      target.querySelectorAll("[name], [data-index]")
    );
    for (const state of record.form_controls || []) {
      const source = preloadSources.find(
        (element) => element.getAttribute("name") === state.name || element.dataset.index === state.name
      );
      if (!source) continue;
      const root = source.closest("[lp-select]") || source;
      const preload = JSON.stringify(state.options || []);
      source.dataset.preload = preload;
      root.dataset.preload = preload;
    }
  }
  _restoreQueuedFiles(record) {
    if (typeof DataTransfer === "undefined") return;
    const files = /* @__PURE__ */ new Map();
    for (const entry of record.files || []) {
      const values = files.get(entry.name) || [];
      values.push(entry.file);
      files.set(entry.name, values);
    }
    for (const input of this.target.querySelectorAll(
      "input[type='file'][name]"
    )) {
      const saved = files.get(input.name);
      if (!saved?.length) continue;
      try {
        const transfer = new DataTransfer();
        for (const file of saved) transfer.items.add(file);
        input.files = transfer.files;
      } catch {
      }
    }
  }
  async _initForm({ replace = true } = {}) {
    if (replace && this.initialTarget) {
      const visible = this.target?.dataset.visible;
      if (visible !== void 0) {
        this.initialTarget.dataset.visible = visible;
      }
      this.target.replaceWith(this.initialTarget);
      this.target = this.initialTarget;
      this.initialTarget = this.target.cloneNode(true);
    } else if (!this.initialTarget) {
      this.initialTarget = this.target.cloneNode(true);
    }
    this.target._lp_widget = this;
    this.form = new FormController(this);
    await this.form.init();
    if (this.target.dataset.formState) installReviewBar(this);
    if (this.target.dataset.migrationNotice && this.target.dataset.migrationNotice !== "[]")
      installMigrationNotice(this);
    if (this.target.dataset.formGeneration !== void 0) {
      const generation = document.createElement("input");
      generation.type = "hidden";
      generation.name = "form-generation";
      generation.value = this.target.dataset.formGeneration;
      this.target.append(generation);
    }
    this.target.addEventListener("click", this._click);
    this.target.addEventListener("input", this._syncFieldClearEvent);
    this.target.addEventListener("change", this._syncFieldClearEvent);
    this.target.addEventListener("updated", this._syncFieldClearEvent);
    this._syncEditAllButton();
    const hasDeferredOperation = this.target.matches?.("[data-operation]") || this.target.querySelector?.("[data-operation]");
    if (hasDeferredOperation) {
      const manager = await this.view?.ensureDeferredOperations?.();
      manager?.scan(this.target);
    }
    this.initialized = true;
    this.loaded = this.target.hasAttribute("loaded");
    this.target.setAttribute("initialized", "");
  }
  _editableReadFields() {
    if (this.readonly || this.revisionPreview || !this.target) return [];
    return Array.from(
      this.target.querySelectorAll(
        ".form-element[data-mode='read']"
      )
    ).filter((element) => Boolean(element.querySelector("[data-role='read']")));
  }
  _syncEditAllButton() {
    if (!this.target) return;
    const existingBar = this.target.querySelector(
      ":scope > [data-role='edit-all-bar']"
    );
    const readFields = this._editableReadFields();
    if (readFields.length < 2) {
      existingBar?.remove();
      return;
    }
    if (existingBar) {
      existingBar.hidden = false;
      return;
    }
    const firstField = this.target.querySelector(".form-element");
    if (!firstField) return;
    const bar = document.createElement("div");
    bar.dataset.role = "edit-all-bar";
    bar.className = "flex items-center justify-end -mb-3";
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.role = "edit-all";
    button.ariaLabel = "Edit all fields";
    button.title = "Edit all fields";
    button.className = STYLES.form.editAll;
    setIcon(
      button.appendChild(document.createElement("span")),
      "edit",
      "icon-xs"
    );
    const text = button.appendChild(document.createElement("span"));
    text.textContent = "Edit all";
    bar.appendChild(button);
    if (firstField.parentElement === this.target) {
      this.target.insertBefore(bar, firstField);
    } else {
      firstField.before(bar);
    }
  }
  _hasFieldValue(element) {
    const field = element._lp_element ?? this.form?.renderer?.elements.get(element.id);
    if (field && "value" in field) {
      const val = field.value;
      if (Array.isArray(val)) return val.length > 0;
      if (val && typeof val === "object") return Object.keys(val).length > 0;
      return val !== null && val !== void 0 && val !== "";
    }
    if (element.querySelector(
      "input[type='radio']:checked, input[type='checkbox']:checked"
    )) {
      return true;
    }
    const textInput = element.querySelector("input:not([type='radio']):not([type='checkbox']), textarea");
    if (textInput) return textInput.value !== "";
    const select = element.querySelector("select");
    if (select) return select.selectedOptions.length > 0 && select.value !== "";
    return false;
  }
  _syncFieldClear(element) {
    if (!element) return;
    const clearButton = element.querySelector(
      "[data-role='label'] [data-role='clear']"
    );
    if (!clearButton) return;
    clearButton.hidden = !this._hasFieldValue(element);
  }
  _syncFieldClearEvent(e) {
    if (this.readonly) return;
    const target = e.target;
    const element = target?.closest(".form-element") ?? null;
    this._syncFieldClear(element);
    if (e.type === "change") this._syncEditAllButton();
  }
  _focusFieldControl(element) {
    const field = element._lp_element ?? this.form?.renderer?.elements.get(element.id);
    if (field && "focus" in field && typeof field.focus === "function") {
      field.focus();
      return;
    }
    const control = element.querySelector(
      "input:not([type='hidden']):not(:disabled), textarea:not(:disabled), select:not(:disabled)"
    );
    control?.focus();
  }
  _enterFieldEdit(element, { focus = true } = {}) {
    void withTransition(
      () => {
        element.dataset.mode = "edit";
        this._syncFieldClear(element);
        this._syncEditAllButton();
        if (focus) this._focusFieldControl(element);
      },
      { label: "form:edit-field" }
    );
  }
  _click(e) {
    if (this.readonly) return;
    const target = e.target;
    if (!target?.closest) return;
    const editAll = target.closest("[data-role='edit-all']");
    if (editAll && this.target.contains(editAll)) {
      e.preventDefault();
      e.stopPropagation();
      const readFields = this._editableReadFields();
      if (readFields.length === 0) return;
      void withTransition(
        () => {
          for (const field of readFields) {
            field.dataset.mode = "edit";
            this._syncFieldClear(field);
          }
          this._syncEditAllButton();
          this._focusFieldControl(readFields[0]);
        },
        { label: "form:edit-all-fields" }
      );
      return;
    }
    const element = target.closest(".form-element");
    const role = target.closest("[data-role]")?.dataset.role;
    if (!element) return;
    if (role === "edit") {
      e.preventDefault();
      e.stopPropagation();
      this._enterFieldEdit(element);
      return;
    }
    if (role === "clear") {
      e.preventDefault();
      e.stopPropagation();
      const field = element._lp_element ?? this.form?.renderer?.elements.get(element.id);
      field?.clear?.();
      this._syncFieldClear(element);
      return;
    }
    if (element.dataset.mode === "read") {
      if (target.closest("a, button, input, textarea, select, summary")) return;
      if (target.closest("[data-role='read']") || target.closest("[data-role='label']")) {
        e.preventDefault();
        e.stopPropagation();
        this._enterFieldEdit(element);
      }
    }
  }
  get header() {
    return this.target?.querySelector("[data-role='header']");
  }
  get submitGroup() {
    return this.target?.querySelector(
      "[data-role='submit-group']"
    );
  }
  get submitButton() {
    return this.target?.querySelector(
      'button[type="submit"]:not([data-role])'
    );
  }
  async prepareReset(options = {}) {
    if (this._preparingReset) return this._preparingReset;
    if (this._preparedReset) return;
    const pending = this._prepareReset(options);
    this._preparingReset = pending;
    try {
      await pending;
    } finally {
      if (this._preparingReset === pending) this._preparingReset = null;
    }
  }
  async _prepareReset({
    nextTarget = (this.initialTarget || this.target).cloneNode(
      true
    ),
    staged = {},
    beforeInit = null,
    afterInit = null
  } = {}) {
    if (this._preparedReset) return;
    const epoch = this._resetEpoch;
    const visible = this.target?.dataset.visible;
    if (visible !== void 0) nextTarget.dataset.visible = visible;
    const stagedState = {
      target: nextTarget,
      initialTarget: null,
      form: null,
      initialized: false,
      loaded: this.loaded,
      destroyables: [],
      _migrationNotice: null,
      _reviewBar: null,
      ...staged
    };
    let adopted = false;
    const stagedWidget = new Proxy(this, {
      get(target, property, receiver) {
        if (!adopted && Object.hasOwn(stagedState, property)) {
          return stagedState[property];
        }
        return Reflect.get(target, property, receiver);
      },
      set(target, property, value) {
        if (!adopted) {
          stagedState[property] = value;
          return true;
        }
        return Reflect.set(target, property, value);
      }
    });
    this._preparingState = stagedState;
    try {
      await beforeInit?.(stagedWidget);
      if (epoch !== this._resetEpoch) return;
      await stagedWidget._initForm({ replace: false });
      if (epoch !== this._resetEpoch) return;
      await afterInit?.(stagedWidget);
      if (epoch !== this._resetEpoch) return;
      this._preparedReset = {
        adopt: Object.keys(stagedState),
        state: stagedState,
        revisionBaseline: stagedWidget.revisionSnapshot(),
        baselineSubmission: structuredClone(
          stagedWidget.form?.renderer?._packageSubmission?.() ?? stagedWidget.submission ?? {}
        ),
        activate: () => {
          adopted = true;
        }
      };
    } finally {
      if (this._preparedReset?.state !== stagedState)
        this._destroyFormState(stagedState);
      if (this._preparingState === stagedState) this._preparingState = null;
    }
  }
  commitReset() {
    if (!this._preparedReset) return false;
    const { adopt, state, revisionBaseline, baselineSubmission, activate } = this._preparedReset;
    this._preparedReset = null;
    const previousTarget = this.target;
    const previousInert = this._replacementInert;
    const visible = previousTarget?.dataset.visible;
    if (visible !== void 0) state.target.dataset.visible = visible;
    this.clearUnsavedState();
    this.destroy();
    if (previousTarget !== state.target)
      previousTarget.replaceWith(state.target);
    const widget = this;
    for (const property of adopt) widget[property] = state[property];
    if (previousInert != null) this.target.inert = previousInert;
    activate?.();
    this.target._lp_widget = this;
    this._revisionBaseline = revisionBaseline;
    this._baselineSubmission = baselineSubmission;
    return true;
  }
  discardPreparedReset() {
    this._resetEpoch = (this._resetEpoch || 0) + 1;
    if (this._preparingState) this._destroyFormState(this._preparingState);
    if (this._preparedReset) this._destroyFormState(this._preparedReset.state);
    this._preparedReset = null;
  }
  _destroyFormState(state) {
    state._reviewBar?.destroy();
    state._reviewBar = null;
    state._migrationNotice?.destroy();
    state._migrationNotice = null;
    state.form?.destroy?.();
    state.destroyables?.forEach((destroyable) => {
      destroyable.destroy?.();
    });
    state.destroyables = [];
  }
  async reset() {
    await this.prepareReset();
    this.commitReset();
  }
  setEntityMetadata() {
    if (this.revisionPreview) return;
    const pageTitle = document.querySelector(
      "[data-nav='view'] [data-role='title']"
    );
    const pageDescription = document.querySelector("[data-role='description']");
    const name = this.target.querySelector("[name='name']")?.value || this.target.dataset.name || "";
    const description = this.target.querySelector("[name='description']")?.value || this.target.dataset.description || "";
    if (pageTitle && pageTitle.textContent !== name)
      pageTitle.textContent = name;
    if (pageDescription && pageDescription.textContent !== description)
      pageDescription.textContent = description;
  }
  created() {
    this._created = true;
  }
  success() {
    this._success = true;
  }
  updated(response) {
    const updatedTarget = (response.html || null)?.querySelector(
      `[data-widget='${this.name}']`
    );
    const ownsRendererState = !updatedTarget || [updatedTarget, this.target, this.initialTarget].some(
      (target) => target?.hasAttribute?.("data-schema") || target?.hasAttribute?.("data-submission")
    );
    if (updatedTarget) {
      this.initialTarget = updatedTarget;
      this._deferredOperation = updatedTarget.dataset.operation || null;
      this._updated = true;
      this._replacementVersion = (this._replacementVersion || 0) + 1;
    }
    if (ownsRendererState && Object.hasOwn(response, "schema")) {
      this.schema = response.schema;
    }
    if (ownsRendererState && Object.hasOwn(response, "submission")) {
      this.submission = response.submission;
    }
    if (ownsRendererState && Object.hasOwn(response, "form_state") && this.initialTarget) {
      const formState = response.form_state;
      const operation = currentReviewOperation(this, formState.operation);
      this.initialTarget.dataset.formState = JSON.stringify({
        ...formState,
        operation
      });
      if (operation?.key)
        this.lockDeferredOperation({
          operation: operation.key,
          revision: operation.revision,
          scope: operation.scope,
          blocks_edit: operation.blocks_edit,
          status: operation
        });
    }
    if (ownsRendererState && Object.hasOwn(response, "generation") && this.initialTarget)
      this.initialTarget.dataset.formGeneration = String(response.generation);
    if (ownsRendererState && Object.hasOwn(response, "migration_notice") && this.initialTarget)
      this.initialTarget.dataset.migrationNotice = JSON.stringify(
        response.migration_notice
      );
  }
  async prereconcile() {
    if (this._replacementPromise) return this._replacementPromise;
    if (!this._updated) return;
    if (this._preparedReset?.version === this._replacementVersion) return;
    this._replacementInert ??= Boolean(this.target.inert);
    this.target.inert = true;
    const pending = (async () => {
      let preparedVersion;
      do {
        preparedVersion = this._replacementVersion;
        this.discardPreparedReset();
        await this.prepareReset();
        if (this._preparedReset) this._preparedReset.version = preparedVersion;
      } while (preparedVersion !== this._replacementVersion);
    })();
    this._replacementPromise = pending;
    try {
      await pending;
    } catch (error) {
      this._restoreInteractivity();
      throw error;
    } finally {
      if (this._replacementPromise === pending) this._replacementPromise = null;
    }
  }
  _restoreInteractivity() {
    if (this._replacementInert == null) return;
    this.target.inert = this._replacementInert;
    this._replacementInert = null;
  }
  postreconcile() {
    const updated = this._updated;
    if (!this._created && !updated) return;
    if (updated && (this._replacementPromise || this._preparedReset?.version !== void 0 && this._preparedReset.version !== this._replacementVersion)) {
      this.modified = true;
      return;
    }
    this._created = false;
    this._updated = false;
    if (updated) {
      this.commitReset();
      this._restoreInteractivity();
      if (this.visible) this.target.dataset.visible = "true";
    }
    if (this._success) {
      this.form?.success();
      this._success = false;
    }
  }
  destroy() {
    this.discardPreparedReset();
    this._restoreInteractivity();
    this._reviewBar?.destroy();
    this._reviewBar = null;
    this._migrationNotice?.destroy();
    this._migrationNotice = null;
    this.form?.destroy();
    this.destroyables.forEach((destroyable) => {
      if (destroyable.destroy) destroyable.destroy();
    });
    this.destroyables = [];
    this.form = null;
  }
  showError(error) {
    this.form?.showError(error);
  }
}

class RadioElement extends BaseElement {
  get value() {
    return Array.from(
      this.elt?.querySelectorAll("input[type='radio']") ?? []
    ).find((radio) => radio.checked)?.value;
  }
  changed(value) {
    if (this.value === value) return false;
    return true;
  }
  active(value) {
    return this.elt?.querySelector(
      `input[type="radio"][value="${String(value)}"]`
    )?.checked ?? this.submission === value;
  }
  get read() {
    if (this._read) return this._read;
    const option = this.schema.options?.find(
      (opt) => opt.value === this.submission
    );
    this._read = document.createElement("div");
    this._read.className = STYLES.form.submission.default;
    if (option) {
      this._read.textContent = option.label;
    }
    this._read.classList.add("group-data-[mode=edit]/element:hidden");
    return this._read;
  }
  get edit() {
    if (this._edit) return this._edit;
    this._edit = document.createElement("fieldset");
    if (this.label) {
      const legend = primitives.label({
        label: this.label,
        tag: "legend"
      });
      legend.classList.add("mb-1");
      this._edit.appendChild(legend);
    }
    const container = this._edit.appendChild(document.createElement("div"));
    const layout = this.schema.layout ?? "column";
    container.className = `${STYLES.radio.fieldset[layout]}`;
    this.schema.options?.forEach((option) => {
      container.appendChild(
        primitives.radio({
          label: option.label,
          value: option.value,
          name: this.schema.id || this.schema.name,
          checked: this.submission === option.value
        })
      );
    });
    container.classList.add("group-data-[mode=read]/element:hidden");
    return this._edit;
  }
  clear() {
    this.submission = null;
    this.edit.querySelectorAll('input[type="radio"]').forEach((radio) => {
      radio.checked = false;
    });
  }
}

var radio = /*#__PURE__*/Object.freeze({
	__proto__: null,
	RadioElement: RadioElement
});

class CreateForm extends FormWidget {
  init() {
    this.messages = {
      submit: "Create Form",
      submitting: "Creating Form",
      submitted: "Form Created"
    };
    void super.init();
  }
  get html() {
    this.nameElement = new InputElement(
      this,
      {
        id: "name",
        required: true,
        input: "text",
        label: "Name"
      },
      void 0
    );
    const formType = new RadioElement(
      this,
      {
        id: "form-type",
        required: true,
        layout: "row",
        options: [
          { label: "Page", value: "page" },
          { label: "Task", value: "task" }
        ]
      },
      void 0
    );
    return [this.nameElement.edit, formType.edit];
  }
  postreconcile() {
    const created = this._created;
    super.postreconcile();
    if (created) {
      this.nameElement.clear();
      this.success();
      this.form?.resetSubmitButton();
    }
    this.nameElement.focus();
    this.target.dataset.visible = "true";
  }
}

var form = /*#__PURE__*/Object.freeze({
	__proto__: null,
	CreateForm: CreateForm
});

class FacetedSearchElement extends BaseElement {
  active(value) {
    return (typeof value === "string" ? this.combobox?.values.has(value) : void 0) ?? this.values.some((option) => option.id === value || option === value);
  }
  get values() {
    let submission = this.submission;
    if (typeof submission === "string") {
      submission = JSON.parse(submission);
      return (Array.isArray(submission) ? submission : [submission]).filter(
        isFacetOption
      );
    }
    return isFacetOption(submission) ? [submission] : [];
  }
  get read() {
    if (this._read) return this._read;
    const read = document.createElement("div");
    read.className = "flex flex-row flex-wrap gap-2";
    read.dataset.kind = String(this.renderer.kind);
    this.values.forEach((item) => {
      const container = read.appendChild(document.createElement("div"));
      container.className = STYLES.form.submission.default;
      container.appendChild(formatting.name(item));
    });
    read.classList.add("group-data-[mode=edit]/element:hidden");
    this._read = read;
    return read;
  }
  get edit() {
    if (this._edit) return this._edit;
    this._edit = primitives.input({
      label: this.schema.title || this.schema.label,
      name: this.schema.id || this.schema.name,
      data: {
        placeholder: this.schema.placeholder || "search...",
        multiple: this.schema.multiple,
        kind: this.renderer.kind,
        index: this.schema.index,
        creatable: this.schema.creatable
      }
    });
    this._edit.querySelector("input")?.setAttribute("lp-select", "");
    const combobox = new FacetsBox(this._edit);
    this.combobox = combobox;
    this.values.forEach((value) => {
      combobox.addOption(value);
    });
    combobox.init();
    this.destroyables.push(combobox);
    this._edit.querySelector("[lp-select]")?.classList.add("group-data-[mode=read]/element:hidden");
    return this._edit;
  }
  clear() {
    this.combobox?.clear();
    this.submission = null;
  }
  destroy() {
    this.combobox?.destroy();
  }
}

class CheckboxElement extends BaseElement {
  active() {
    const input = this.elt?.querySelector("input");
    if (input) return input.checked;
    if (typeof this.submission === "boolean") return this.submission;
    return Boolean(this.schema.checked);
  }
  get value() {
    return this.active();
  }
  changed(value) {
    if (this.value === value) return false;
    return true;
  }
  get cell() {
    if (this.cellEditing) return this.cellEdit;
    if (!this.submission) return null;
    const icon = primitives.icon({ icon: "check", kind: "success" });
    return icon.outerHTML;
  }
  get read() {
    if (this._read) return this._read;
    if (!this.readonly) return null;
    this._read = document.createElement("div");
    this._read.className = STYLES.form.submission.default;
    const icon = this._read.appendChild(document.createElement("span"));
    if (this.submission) {
      setIcon(icon, "check", "text-success mr-1.5");
      this._read.append(icon, document.createTextNode("True"));
    } else {
      setIcon(icon, "x", "text-failure mr-1.5");
      this._read.append(icon, document.createTextNode("False"));
    }
    this._read.classList.add(
      "group-data-[mode=edit]/element:hidden",
      "text-base-dark"
    );
    return this._read;
  }
  get edit() {
    if (this._edit) return this._edit;
    const value = typeof this.submission === "boolean" ? this.submission : this.schema.checked;
    this._edit = primitives.checkbox({
      label: this.label,
      checked: value,
      name: this.schema.id || this.schema.name,
      disabled: this.renderer.readonly,
      styles: {
        label: STYLES.checkbox.label
      }
    });
    return this._edit;
  }
}

var checkbox = /*#__PURE__*/Object.freeze({
	__proto__: null,
	CheckboxElement: CheckboxElement
});

function isLinkSubmission(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const data = { ...value };
  return ["id", "name", "kind", "index", "type"].every(
    (key) => data[key] === void 0 || typeof data[key] === "string"
  ) && ["url", "title"].every(
    (key) => data[key] == null || typeof data[key] === "string"
  );
}
class LinkElement extends BaseElement {
  constructor(renderer, schema, submission) {
    super(renderer, schema, submission);
    this.combobox = null;
  }
  get value() {
    const submission = this.linkSubmission;
    if (this.combobox) {
      const id = this.combobox?.values.size > 0 ? Array.from(this.combobox.values)[0] : null;
      if (submission?.id === id) return submission;
      const selected = this.combobox.selectedOptions;
      return selected.length > 0 ? selected[0] : null;
    } else {
      const inputs = this.elt?.querySelectorAll("input");
      if (!inputs?.length) {
        if (submission?.url) {
          return {
            url: submission.url,
            title: submission.title ?? ""
          };
        }
        return null;
      }
      const result = {};
      inputs.forEach((input) => {
        const key = input.name.slice(input.name.indexOf(":") + 1);
        result[key] = input.value;
      });
      return result.url ? result : null;
    }
  }
  changed(value) {
    if (areEqual(this.value, value)) return false;
    return true;
  }
  get linkSubmission() {
    return isLinkSubmission(this.submission) ? this.submission : null;
  }
  get read() {
    if (this._read) return this._read;
    const submission = this.linkSubmission;
    if (!submission) return null;
    this._read = document.createElement("div");
    this._read.className = `${STYLES.form.submission.default} group-data-[mode=edit]/element:hidden`;
    if (submission.id) {
      if (!submission.name) return null;
      const name = formatting.name({ ...submission, link: true });
      this._read.appendChild(
        formatting.iconLabel({
          icon: "in",
          kind: submission.kind,
          content: name,
          classes: STYLES.form.linkLabel,
          iconClasses: "text-kind-default"
        })
      );
    } else if (submission.url) {
      const link = document.createElement("a");
      link.dataset.kind = "page";
      link.className = STYLES.link.default;
      link.target = "_blank";
      link.href = submission.url;
      link.textContent = submission.title || submission.url;
      this._read.appendChild(
        formatting.iconLabel({
          icon: "out",
          kind: "page",
          content: link,
          classes: STYLES.form.linkLabel,
          iconClasses: "text-base-default"
        })
      );
    }
    return this._read;
  }
  get cell() {
    if (this._cell) return this._cell;
    const read = this.read;
    if (!read) return "";
    this._cell = document.createElement("div");
    this._cell.classList.add("flex", "flex-row", "items-baseline");
    this._cell.innerHTML = read.innerHTML;
    return this._cell.outerHTML;
  }
  get edit() {
    if (this._edit) return this._edit;
    const submission = this.linkSubmission;
    let edit;
    if (this.schema.location === "in") {
      edit = primitives.input({
        name: this.schema.id,
        label: this.label,
        kind: this.renderer.kind,
        data: {
          index: "internal",
          placeholder: "search...",
          preload: submission ? JSON.stringify(submission) : null
        }
      });
      this.combobox = new FacetsBox(edit);
      this.combobox.init();
      this.destroyables.push(this.combobox);
      this.combobox.element.classList.add(
        "group-data-[mode=read]/element:hidden"
      );
    } else {
      edit = document.createElement("div");
      edit.classList.add("flex", "flex-col", "gap-1");
      if (this.label) {
        const label = primitives.label({
          label: this.label,
          tag: "h3"
        });
        edit.appendChild(label);
      }
      const inputs = edit.appendChild(document.createElement("div"));
      inputs.classList.add("flex", "flex-col", "gap-2");
      inputs.append(
        primitives.input({
          name: `${this.schema.id}:url`,
          type: "url",
          placeholder: "url",
          value: submission?.url
        }),
        primitives.input({
          name: `${this.schema.id}:title`,
          type: "text",
          placeholder: "name (optional)",
          value: submission?.title
        })
      );
      inputs.classList.add("group-data-[mode=read]/element:hidden");
    }
    this._edit = edit;
    return this._edit;
  }
  clear() {
    if (this.combobox) {
      this.combobox.clear();
    }
    this.submission = null;
    this.edit.querySelectorAll("input").forEach((input) => {
      input.value = "";
    });
  }
}

var link = /*#__PURE__*/Object.freeze({
	__proto__: null,
	LinkElement: LinkElement
});

class SelectElement extends BaseElement {
  get value() {
    if (this.combobox?.values.size) {
      const values = Array.from(this.combobox.values);
      return this.schema.multiple ? values : values[0];
    }
    return null;
  }
  changed(value) {
    if (areEqual(this.value, value)) return false;
    return true;
  }
  active(value) {
    return typeof value === "string" && (this.combobox?.values.has(value) ?? this.values.includes(value));
  }
  get values() {
    if (!this.hasSubmission) return [];
    const submission = this.submission;
    return typeof submission === "string" ? [submission] : Array.isArray(submission) ? submission.filter(
      (value) => typeof value === "string"
    ) : [];
  }
  get read() {
    if (this._read) return this._read;
    if (!this.schema.options) return null;
    const options = this.schema.options;
    const read = document.createElement("div");
    read.className = "flex flex-row flex-wrap gap-2";
    this.values.forEach((item) => {
      const option = options.find((opt) => opt.value === item);
      if (!option) return;
      const container = read.appendChild(document.createElement("div"));
      container.className = STYLES.form.submission.default;
      container.textContent = option.label;
    });
    read.classList.add("group-data-[mode=edit]/element:hidden");
    this._read = read;
    return read;
  }
  get edit() {
    if (this._edit) return this._edit;
    if (!this.schema.options) return null;
    this._edit = primitives.select({
      options: this.schema.options || [],
      label: this.label,
      name: this.schema.id || this.schema.name,
      kind: this.renderer.kind,
      data: {
        placeholder: this.schema.placeholder || "select an option...",
        multiple: this.schema.multiple,
        preload: this.values ? JSON.stringify(this.values.map((value) => ({ id: value }))) : "[]"
      }
    });
    this.combobox = new SelectBox(this._edit);
    this.combobox.init();
    this.destroyables.push(this.combobox);
    const select = this._edit.matches?.("[lp-select]") ? this._edit : this._edit.querySelector("[lp-select]");
    select?.classList.add("group-data-[mode=read]/element:hidden");
    return this._edit;
  }
  clear() {
    if (this.combobox) {
      this.combobox.clear();
    }
    this.submission = null;
    const select = this.edit?.querySelector("select");
    if (select) select.value = "";
  }
}

var select = /*#__PURE__*/Object.freeze({
	__proto__: null,
	SelectElement: SelectElement
});

class HtmlElement extends BaseElement {
  constructor(renderer, schema, submission) {
    super(renderer, schema, submission);
    this.static = true;
    this.html = null;
    this._destroyed = false;
  }
  async _getHtml() {
    const form = this.renderer.form;
    if (!form?.key) return "";
    return await request.get(
      ENDPOINTS.html(form.key, this.schema.id).getContent
    ).then((response) => response?.markup ?? "").catch((error) => {
      captureError(error, form.target, {
        schema: this.schema
      });
      return "";
    });
  }
  create() {
    if (this._elt) return this._elt;
    const elt = document.createElement("div");
    elt.className = "html-content";
    const fields = this.renderer.form?.htmlFields;
    if (fields && Object.hasOwn(fields, this.schema.id)) {
      this.html = fields[this.schema.id];
      elt.innerHTML = this.html;
    } else if (this.html === null) {
      this._getHtml().then((html) => {
        if (this._destroyed) return;
        this.html = html;
        elt.innerHTML = html;
      });
    } else {
      elt.innerHTML = this.html;
    }
    return elt;
  }
  destroy() {
    this._destroyed = true;
    super.destroy();
  }
}

var html = /*#__PURE__*/Object.freeze({
	__proto__: null,
	HtmlElement: HtmlElement
});

class BookmarkElement extends BaseElement {
  get bookmark() {
    const value = this.submission;
    const url = value && typeof value === "object" && "url" in value && typeof value.url === "string" ? value.url : void 0;
    const title = value && typeof value === "object" && "title" in value && typeof value.title === "string" ? value.title : void 0;
    return { url, title };
  }
  get value() {
    const inputs = this.elt?.querySelectorAll("input");
    const result = {};
    inputs?.forEach((input) => {
      const key = input.name.slice(input.name.indexOf(":") + 1);
      result[key] = input.type === "checkbox" ? input.checked : input.value;
    });
    return result;
  }
  changed(value) {
    if (areEqual(this.value, value)) return false;
    return true;
  }
  get read() {
    if (this._read) return this._read;
    this._read = document.createElement("div");
    this._read.className = STYLES.form.submission.default;
    const link = document.createElement("a");
    link.dataset.kind = "page";
    link.className = STYLES.link.default;
    link.target = "_blank";
    const { url, title } = this.bookmark;
    link.href = url ?? "";
    link.textContent = title || url || "";
    this._read.appendChild(
      formatting.iconLabel({
        icon: "out",
        kind: "page",
        content: link,
        classes: STYLES.form.linkLabel,
        iconClasses: "text-base-default"
      })
    );
    this._read.classList.add("group-data-[mode=edit]/element:hidden");
    return this._read;
  }
  get edit() {
    if (this._edit) return this._edit;
    const edit = document.createElement("div");
    edit.classList.add("flex", "flex-col", "gap-2");
    if (this.label) {
      const label = primitives.label({
        label: this.label,
        tag: "h3"
      });
      edit.appendChild(label);
    }
    const inputs = edit.appendChild(document.createElement("div"));
    inputs.classList.add("flex", "flex-col", "gap-2");
    const { url, title } = this.bookmark;
    inputs.append(
      primitives.input({
        name: `${this.schema.id}:url`,
        type: "url",
        placeholder: "url",
        value: url
      }),
      primitives.input({
        name: `${this.schema.id}:title`,
        type: "text",
        placeholder: "name (optional)",
        value: title
      })
    );
    const choices = inputs.appendChild(document.createElement("div"));
    choices.className = "flex flex-col gap-2 mt-2";
    choices.dataset.element = "choices";
    choices.appendChild(
      primitives.checkbox({
        label: "Replace page photo with link image",
        name: `${this.schema.id}:replace-image`,
        checked: Boolean(url)
      })
    );
    choices.appendChild(
      primitives.checkbox({
        label: "Replace page description with link description",
        name: `${this.schema.id}:replace-description`,
        checked: Boolean(url)
      })
    );
    choices.appendChild(
      primitives.checkbox({
        label: "Replace page name with link title",
        name: `${this.schema.id}:replace-name`,
        checked: Boolean(url)
      })
    );
    inputs.classList.add("group-data-[mode=read]/element:hidden");
    edit.appendChild(choices);
    this._edit = edit;
    return this._edit;
  }
}

var bookmark = /*#__PURE__*/Object.freeze({
	__proto__: null,
	BookmarkElement: BookmarkElement
});

class StatusElement extends BaseElement {
  constructor(renderer, schema, submission) {
    super(renderer, schema, submission);
    this.messageElement = null;
    this.statusInput = null;
    this.static = true;
  }
  update() {
    const elt = this.elt;
    const { messageElement, statusInput } = this;
    if (!elt || !messageElement || !statusInput) return;
    const messages = [];
    const activeElementIds = [];
    const statuses = Array.isArray(this.schema.status) ? this.schema.status : [];
    statuses.forEach((status) => {
      if (!status?.id || !status.text) return;
      const element = this.renderer.elements?.get(
        `${status.id}-${this.renderer.id}`
      );
      if (!element) return;
      if (element.active?.(status.value)) {
        messages.push(status.text);
        activeElementIds.push(element.schema.id);
      }
    });
    messageElement.replaceChildren();
    if (messages.length > 0) {
      messages.forEach((message, index) => {
        if (index > 0) messageElement.appendChild(document.createElement("br"));
        messageElement.appendChild(document.createTextNode(message));
      });
      elt.dataset.visible = "true";
      statusInput.value = JSON.stringify(activeElementIds);
    } else {
      elt.dataset.visible = "false";
      statusInput.value = "";
    }
  }
  create() {
    if (this._elt) return this._elt;
    const elt = document.createElement("div");
    elt.dataset.kind = "status";
    elt.className = STYLES.message;
    elt.dataset.visible = "false";
    this.messageElement = elt.appendChild(document.createElement("span"));
    this.statusInput = elt.appendChild(
      primitives.input({
        name: this.schema.id,
        type: "hidden"
      })
    );
    return elt;
  }
}

var status = /*#__PURE__*/Object.freeze({
	__proto__: null,
	StatusElement: StatusElement
});

export { BaseElement as B, CheckboxElement as C, FormController as F, InputElement as I, LinkElement as L, RadioElement as R, SelectBox as S, TextareaElement as T, FacetsBox as a, FormWidget as b, FacetedSearchElement as c, compatibleField as d, currentReviewOperation as e, incompatibleSchema as f, getFormElement as g, FormRenderer as h, isFacetOption as i, controller as j, form as k, renderReviewBar as r };
