/*! Third-party licenses: /third-party-licenses.txt */
import { g as getFormElement } from './forms.js?v=b14914a4';
import { Q as QueryLifecycle, c as captureError, w as withTransition, r as request } from './foundation.js?v=b14914a4';
import { s as setIcon } from './ui-resources.js?v=b14914a4';
import './ui-controls.js?v=b14914a4';
import './modal.js?v=b14914a4';
import './upstreamUnavailable.js?v=b14914a4';
import './connectivity.js?v=b14914a4';
import './combobox.js?v=b14914a4';

const SAVED_STATE_MS = 1200;
const ROUTES = {
  page: (key) => `/pages/${key}/patch`,
  task: (key) => `/tasks/${key}/patch`
};
class TableEditor {
  constructor(attributes) {
    Object.assign(this, attributes);
    this.rows = null;
    this.kind = this.kind || this.component.kind;
    const columns = this.component.preload("columns");
    this.columns = new Map(
      (Array.isArray(columns) ? columns : []).filter(
        (column) => column !== null && typeof column === "object" && typeof column.field === "string"
      ).map((column) => [column.field, column])
    );
    this.activeEdit = null;
    this.checkboxEdits = /* @__PURE__ */ new Map();
    this._openLifecycle = new QueryLifecycle();
    this._checkboxLifecycle = new QueryLifecycle();
    this._preparedOpen = null;
    this._preparedCheckboxes = null;
    this._saves = /* @__PURE__ */ new Map();
    this._savedTimers = /* @__PURE__ */ new Map();
    this._destroyed = false;
    this._listenerTarget = null;
    this._onClick = (event) => void this._click(event).catch(captureError);
    this._onChange = (event) => void this._change(event).catch(captureError);
    this._onKeydown = (event) => void this._keydown(event).catch(captureError);
  }
  async init() {
    if (this._destroyed || this._listenerTarget) return;
    const rows = await this.component.loadWidget("IndexTable");
    if (this._destroyed || this.component._destroyed || this.view._destroyed || !rows?.target)
      return;
    this.rows = { target: rows.target };
    this._listenerTarget = rows.target;
    this._listenerTarget.addEventListener("click", this._onClick);
    this._listenerTarget.addEventListener("change", this._onChange);
    this._listenerTarget.addEventListener("keydown", this._onKeydown);
  }
  _ownsCell(cell) {
    return Boolean(
      !this._destroyed && !this.component._destroyed && !this.view._destroyed && cell?.isConnected && this.rows?.target.contains(cell)
    );
  }
  _canEdit(cell) {
    return this.visible === true && this._ownsCell(cell) && !this._saves.has(cell);
  }
  _parseValue(cell) {
    try {
      return JSON.parse(cell.dataset.editValue ?? "null");
    } catch {
      return null;
    }
  }
  _column(cell) {
    return this.columns.get(cell.dataset.column ?? "");
  }
  _schema(cell) {
    const column = this._column(cell);
    if (!column?.schema) return null;
    return {
      id: column.field,
      title: column.title,
      ...column.schema
    };
  }
  _route(cell) {
    const route = ROUTES[this.kind ?? ""];
    const key = cell.closest("tr[data-key]")?.dataset.key;
    return route && key ? route(key) : null;
  }
  _editRenderer(target) {
    return {
      readonly: false,
      kind: this.kind,
      id: "quick-edit",
      mode: "edit",
      cellEditing: true,
      form: { target }
    };
  }
  _control(root) {
    if (typeof root === "string") return null;
    for (const selector of [
      "input:not([type='hidden']):not([disabled])",
      "textarea:not([disabled])",
      "select:not([disabled])"
    ]) {
      if (root.matches?.(selector)) return root;
      const control = root.querySelector(selector);
      if (control) return control;
    }
    return null;
  }
  _editableCells() {
    const cells = this.rows?.target.querySelectorAll(
      'td[data-editable="true"]'
    );
    return Array.from(cells ?? []).filter(
      (candidate) => this._schema(candidate) && this._route(candidate)
    );
  }
  _isCheckboxCell(cell) {
    return this._schema(cell)?.type === "checkbox";
  }
  _changed(edit) {
    if (!edit.element) return false;
    if (typeof edit.element.changed === "function") {
      return edit.element.changed(edit.value);
    }
    return edit.element.value !== edit.value;
  }
  _renderValue(cell, html, { saved = false } = {}) {
    const wrapper = document.createElement("div");
    wrapper.dataset.editing = "false";
    wrapper.dataset.role = "quick-edit-result";
    const row = wrapper.appendChild(document.createElement("div"));
    row.dataset.role = "quick-edit-value";
    if (saved) {
      const icon = row.appendChild(document.createElement("span"));
      setIcon(icon, "check", "text-saved-default");
      icon.dataset.role = "quick-edit-saved";
    }
    const content = row.appendChild(document.createElement("div"));
    content.dataset.role = "quick-edit-content";
    content.innerHTML = html;
    cell.replaceChildren(wrapper);
  }
  _clearError(cell) {
    cell.querySelector("[data-role='quick-edit-error']")?.remove();
  }
  _showError(cell, message) {
    cell.dataset.editState = "error";
    let error = cell.querySelector(
      "[data-role='quick-edit-error']"
    );
    if (!error) {
      error = document.createElement("p");
      error.dataset.role = "quick-edit-error";
      error.setAttribute("role", "alert");
      cell.appendChild(error);
    }
    error.textContent = message || "Could not save this value.";
  }
  _editableCell(target) {
    const cell = target instanceof Element ? target.closest("td") : null;
    if (!this._canEdit(cell) || cell?.dataset.editable !== "true") return null;
    if (!this._schema(cell) || !this._route(cell)) return null;
    return cell;
  }
  async _prepareCheckboxes() {
    this._discardPreparedCheckboxes();
    if (this._destroyed || !this.visible || !this.rows) return null;
    this._cleanupCheckboxEdits();
    const batch = {
      token: this._checkboxLifecycle.begin(this.rows.target, {
        cancelTransport: false
      }),
      edits: /* @__PURE__ */ new Set(),
      ready: false
    };
    this._preparedCheckboxes = batch;
    const results = await Promise.allSettled(
      this._editableCells().filter((cell) => this._isCheckboxCell(cell)).map((cell) => this._prepareCheckbox(cell, batch))
    );
    const failure = results.find((result) => result.status === "rejected");
    if (failure || !this._checkboxLifecycle.isCurrent(batch.token)) {
      this._discardPreparedCheckboxes(batch);
      if (failure) captureError(failure.reason);
      return null;
    }
    batch.ready = true;
    return batch;
  }
  async refreshCheckboxes() {
    if (this._destroyed || !this.visible) return;
    const batch = await this._prepareCheckboxes();
    if (!batch) return;
    await withTransition(() => this._commitPreparedCheckboxes(batch), {
      label: "table-editor:refresh-checkboxes"
    });
  }
  async _prepareCheckbox(cell, batch) {
    if (!this.rows || !this._canEdit(cell) || this.checkboxEdits.has(cell))
      return;
    const schema = this._schema(cell);
    if (!schema) return;
    const value = this._parseValue(cell);
    const element = await getFormElement(
      this._editRenderer(this.rows.target),
      schema,
      value
    );
    let edit;
    try {
      if (!this._checkboxLifecycle.isCurrent(batch.token) || !this._canEdit(cell) || this.checkboxEdits.has(cell))
        return;
      const editor = element.cell;
      if (!editor) return;
      edit = { cell, element, editor, value, column: this._column(cell) };
      batch.edits.add(edit);
    } finally {
      if (!edit) element.destroy();
    }
  }
  _discardPreparedCheckboxes(batch = this._preparedCheckboxes) {
    if (!batch) return;
    for (const edit of batch.edits) this._releaseEdit(edit);
    batch.edits.clear();
    if (this._preparedCheckboxes === batch) this._preparedCheckboxes = null;
  }
  _commitPreparedCheckboxes(batch = this._preparedCheckboxes) {
    if (!batch?.ready) return;
    if (!this._checkboxLifecycle.isCurrent(batch.token) || !this.visible) {
      this._discardPreparedCheckboxes(batch);
      return;
    }
    for (const edit of batch.edits) {
      const { cell, editor } = edit;
      if (!edit.element || !editor || !this._canEdit(cell) || this.checkboxEdits.has(cell)) {
        this._releaseEdit(edit);
        continue;
      }
      this._clearSavedTimer(cell);
      const error = cell.querySelector(
        "[data-role='quick-edit-error']"
      )?.textContent;
      this._clearError(cell);
      edit.before = cell.innerHTML;
      this.checkboxEdits.set(cell, edit);
      cell.dataset.editState = "editing";
      cell.replaceChildren(editor);
      if (error) this._showError(cell, error);
    }
    batch.edits.clear();
    if (this._preparedCheckboxes === batch) this._preparedCheckboxes = null;
  }
  _cleanupCheckboxEdits() {
    this.checkboxEdits.forEach((edit, cell) => {
      if (!this._ownsCell(cell)) this._releaseEdit(edit);
    });
  }
  _releaseEdit(edit, restore = false) {
    if (!edit?.element) return;
    const { cell, element } = edit;
    if (restore && cell.isConnected && this.rows?.target.contains(cell)) {
      const error = cell.querySelector(
        "[data-role='quick-edit-error']"
      )?.textContent;
      cell.innerHTML = edit.before ?? "";
      if (this._saves.has(cell)) cell.dataset.editState = "saving";
      else delete cell.dataset.editState;
      if (error) this._showError(cell, error);
    }
    edit.element = null;
    edit.editor = null;
    if (this.activeEdit === edit) this.activeEdit = null;
    if (this._preparedOpen === edit) this._preparedOpen = null;
    if (this.checkboxEdits.get(cell) === edit) this.checkboxEdits.delete(cell);
    element.destroy();
  }
  _cancelCheckboxes() {
    for (const edit of this.checkboxEdits.values())
      this._releaseEdit(edit, true);
  }
  async _click(e) {
    if (!this.visible) return;
    e.stopPropagation();
    const cell = this._editableCell(e.target);
    if (!cell) return;
    if (this._isCheckboxCell(cell)) return;
    if (this.activeEdit?.cell === cell) return;
    e.preventDefault();
    await this._open(cell);
  }
  async _change(e) {
    if (!this.visible) return;
    const cell = this._editableCell(e.target);
    if (!cell || !this._isCheckboxCell(cell)) return;
    e.stopPropagation();
    const edit = this.checkboxEdits.get(cell);
    if (!edit) return;
    if (this.activeEdit && this.activeEdit.cell !== cell && !await this._commit(this.activeEdit.cell)) {
      if (this._canEdit(cell) && this.checkboxEdits.get(cell) === edit) {
        const control = this._control(cell);
        if (control instanceof HTMLInputElement)
          control.checked = edit.value === true;
      }
      return;
    }
    if (this._canEdit(cell) && this.checkboxEdits.get(cell) === edit) {
      await this._commitCheckbox(cell);
    }
  }
  async _open(cell) {
    if (!this._canEdit(cell)) return;
    if (this.activeEdit?.cell === cell) return;
    if (this._isCheckboxCell(cell)) return;
    const token = this._openLifecycle.begin(cell, { cancelTransport: false });
    this._releaseEdit(this._preparedOpen);
    if (this.activeEdit && !await this._commit(this.activeEdit.cell)) {
      return;
    }
    if (!this._openLifecycle.isCurrent(token) || !this._canEdit(cell)) return;
    const schema = this._schema(cell);
    if (!schema || !this.rows) return;
    const value = this._parseValue(cell);
    const element = await getFormElement(
      this._editRenderer(this.rows.target),
      schema,
      value
    );
    let edit;
    try {
      if (!this._openLifecycle.isCurrent(token) || !this._canEdit(cell)) return;
      const editor = element.cell;
      if (!editor) return;
      const prepared = {
        cell,
        element,
        editor,
        value,
        column: this._column(cell)
      };
      edit = prepared;
      this._preparedOpen = prepared;
      await withTransition(
        () => {
          if (!prepared.element || !this._openLifecycle.isCurrent(token) || !this._canEdit(cell))
            return;
          this._clearSavedTimer(cell);
          this._clearError(cell);
          prepared.before = cell.innerHTML;
          cell.dataset.editState = "editing";
          this.activeEdit = prepared;
          this._preparedOpen = null;
          cell.replaceChildren(editor);
        },
        { label: "table-editor:open-cell" }
      );
      if (this.activeEdit === edit && this._openLifecycle.isCurrent(token) && this._canEdit(cell)) {
        this._control(editor)?.focus({ preventScroll: true });
      }
    } finally {
      if (!edit) element.destroy();
      else if (this.activeEdit !== edit) this._releaseEdit(edit);
    }
  }
  async _keydown(e) {
    if (!this.activeEdit) return;
    if (!["Enter", "Escape", "Tab"].includes(e.key)) return;
    const { cell } = this.activeEdit;
    if (!(e.target instanceof Node) || !cell.contains(e.target)) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.key === "Escape") {
      this._openLifecycle.invalidate();
      this._releaseEdit(this._preparedOpen);
      this._cancel(cell);
      return;
    }
    const epoch = this._openLifecycle.epoch;
    const committed = await this._commit(cell);
    if (committed && e.key === "Tab" && epoch === this._openLifecycle.epoch && this._canEdit(cell) && !this.activeEdit)
      await this._focusNext(cell, e.shiftKey);
  }
  _nextEditableCell(cell, reverse = false) {
    const cells = this._editableCells();
    const index = cells.indexOf(cell);
    if (index < 0) return null;
    const offset = reverse ? -1 : 1;
    return cells[index + offset] || null;
  }
  async _focusNext(cell, reverse = false) {
    const next = this._nextEditableCell(cell, reverse);
    if (!this._canEdit(next)) return;
    next.focus?.();
    if (this._isCheckboxCell(next)) {
      this._control(next)?.focus({ preventScroll: true });
      return;
    }
    await this._open(next);
  }
  _cancel(cell) {
    if (!this.activeEdit || this.activeEdit.cell !== cell) return;
    this._releaseEdit(this.activeEdit, true);
  }
  async _commit(cell) {
    const pending = this._saves.get(cell)?.promise;
    if (pending) return pending;
    if (!this._canEdit(cell)) return false;
    if (!this.activeEdit || this.activeEdit.cell !== cell) return false;
    const edit = this.activeEdit;
    if (!this._changed(edit)) {
      this._cancel(cell);
      return true;
    }
    return this._startSave(edit, false);
  }
  async _commitCheckbox(cell) {
    const pending = this._saves.get(cell)?.promise;
    if (pending) return pending;
    if (!this._canEdit(cell)) return false;
    const edit = this.checkboxEdits.get(cell);
    if (!edit) return true;
    if (!this._changed(edit)) {
      cell.dataset.editState = "editing";
      this._clearError(cell);
      return true;
    }
    return this._startSave(edit, true);
  }
  _startSave(edit, checkbox) {
    const { cell } = edit;
    const route = this._route(cell);
    if (!edit.element || !route) return false;
    const payload = structuredClone({
      schema_id: edit.element.schema.id,
      form_generation: cell.dataset.formGeneration || "0",
      value: edit.element.value,
      column: edit.column
    });
    const operation = { edit, checkbox, payload, route };
    this._saves.set(cell, operation);
    this._clearSavedTimer(cell);
    cell.dataset.editState = "saving";
    cell.setAttribute("aria-busy", "true");
    cell.setAttribute("inert", "");
    this._clearError(cell);
    operation.promise = this._save(operation);
    return operation.promise;
  }
  async _save(operation) {
    const { edit, checkbox, payload, route } = operation;
    const { cell } = edit;
    try {
      const response = await request.patch(route, payload);
      if (!this._ownsCell(cell) || this._saves.get(cell) !== operation)
        return false;
      if (!response?.ok) {
        this._showError(cell, response?.error);
        return false;
      }
      const html = (response.html || null)?.body?.innerHTML ?? edit.before ?? "";
      cell.dataset.editValue = JSON.stringify(payload.value);
      if (checkbox && this.checkboxEdits.get(cell) === edit) {
        edit.before = html;
        edit.value = payload.value;
      } else {
        this._releaseEdit(edit);
        this._renderValue(cell, html, { saved: this.visible });
      }
      cell.dataset.editState = "saved";
      this._scheduleSavedTimer(cell);
      return true;
    } catch (error) {
      if (this._ownsCell(cell) && this._saves.get(cell) === operation) {
        this._showError(cell, "Could not save this value.");
        captureError(error);
      }
      return false;
    } finally {
      if (this._saves.get(cell) === operation) {
        this._saves.delete(cell);
        this._unlockCell(cell);
        if (checkbox && this._canEdit(cell) && !this.checkboxEdits.has(cell)) {
          void this.refreshCheckboxes().catch(captureError);
        }
      }
    }
  }
  _unlockCell(cell) {
    cell.removeAttribute("aria-busy");
    cell.removeAttribute("inert");
  }
  _scheduleSavedTimer(cell) {
    this._clearSavedTimer(cell);
    const timer = setTimeout(() => {
      if (this._savedTimers.get(cell) !== timer) return;
      this._savedTimers.delete(cell);
      if (this._ownsCell(cell)) this._clearSavedState(cell);
    }, SAVED_STATE_MS);
    this._savedTimers.set(cell, timer);
  }
  _clearSavedState(cell) {
    if (cell.dataset.editState === "saved") {
      if (this.checkboxEdits.has(cell)) cell.dataset.editState = "editing";
      else delete cell.dataset.editState;
    }
    cell.querySelector("[data-role='quick-edit-saved']")?.remove();
  }
  _clearSavedTimer(cell) {
    const timer = this._savedTimers.get(cell);
    if (timer === void 0) return;
    clearTimeout(timer);
    this._savedTimers.delete(cell);
    this._clearSavedState(cell);
  }
  _invalidatePreparation() {
    this._openLifecycle.invalidate();
    this._checkboxLifecycle.invalidate();
    this._releaseEdit(this._preparedOpen);
    this._discardPreparedCheckboxes();
  }
  _closeEdits() {
    this._invalidatePreparation();
    this._releaseEdit(this.activeEdit, true);
    this._cancelCheckboxes();
    for (const cell of this._savedTimers.keys()) this._clearSavedTimer(cell);
  }
  releaseRows(rows) {
    const retired = new Set(rows.filter((row) => row !== void 0));
    const affected = (cell) => {
      const row = cell.closest("tr[lp-entity]");
      return !this._ownsCell(cell) || row !== null && retired.has(row);
    };
    for (const edit of [
      this.activeEdit,
      this._preparedOpen,
      ...this.checkboxEdits.values()
    ]) {
      if (edit && affected(edit.cell)) this._releaseEdit(edit);
    }
    for (const edit of this._preparedCheckboxes?.edits || []) {
      if (affected(edit.cell)) this._releaseEdit(edit);
    }
    for (const cell of this._saves.keys()) {
      if (!affected(cell)) continue;
      this._saves.delete(cell);
      this._unlockCell(cell);
    }
    for (const cell of this._savedTimers.keys()) {
      if (affected(cell)) this._clearSavedTimer(cell);
    }
  }
  async prereconcile() {
    if (this._destroyed || !this.rows) return;
    const visibility = this.component.widgets.TableVisibility;
    const preserveForVisibility = !this.visible && this.rows.target.dataset.editing === "true" && visibility && this.component.active === visibility;
    if (preserveForVisibility) {
      this.visible = true;
      visibility.preserveEditor?.(this);
    }
    if (!this.visible) {
      this._invalidatePreparation();
      return;
    }
    await this._prepareCheckboxes();
  }
  postreconcile() {
    if (this._destroyed || !this.rows) return;
    if (!this.visible) this._closeEdits();
    this.rows.target.dataset.editing = this.visible ? "true" : "false";
    this.view.elt.querySelectorAll(
      'button[lp-show="table:TableEditor"]'
    ).forEach((button) => {
      button.dataset.editing = this.visible ? "true" : "false";
      button.setAttribute("aria-pressed", this.visible ? "true" : "false");
    });
    if (this.visible) this._commitPreparedCheckboxes();
  }
  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;
    this.visible = false;
    this._closeEdits();
    this._openLifecycle.destroy();
    this._checkboxLifecycle.destroy();
    this._listenerTarget?.removeEventListener("click", this._onClick);
    this._listenerTarget?.removeEventListener("change", this._onChange);
    this._listenerTarget?.removeEventListener("keydown", this._onKeydown);
    this._listenerTarget = null;
    for (const cell of this._saves.keys()) this._unlockCell(cell);
    this._saves.clear();
    this.checkboxEdits.clear();
    this.columns.clear();
    this.rows = null;
  }
}

export { TableEditor };
