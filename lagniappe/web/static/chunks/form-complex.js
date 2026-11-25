/*! Third-party licenses: /third-party-licenses.txt */
import { S as STYLES, s as setIcon } from './ui-resources.js?v=bcd14aa3';
import { E as ENDPOINTS, f as areEqual, w as withTransition, r as request, c as captureError, d as debounce } from './foundation.js?v=bcd14aa3';
import { B as BaseElement, L as LinkElement, I as InputElement, C as CheckboxElement, g as getFormElement } from './forms.js?v=bcd14aa3';
import { p as primitives } from './ui-controls.js?v=bcd14aa3';
import './connectivity.js?v=bcd14aa3';
import './protocol.js?v=bcd14aa3';

const COMPACT_COLUMN_TYPES = /* @__PURE__ */ new Set(["checkbox"]);
const TABLE_CELL_ELEMENTS = {
  checkbox: CheckboxElement,
  input: InputElement,
  link: LinkElement
};
const TAP_MOVE_TOLERANCE = 8;
const HOVER_SUPPRESSION_MS = 250;
const HOVER_HIDE_DELAY_MS = 500;
const TAP_SUPPRESSION_MS = 500;
const ACTIONS = [
  ["moveUp", "up", "Move row up"],
  ["moveDown", "down", "Move row down"],
  ["edit", "edit", "Edit row"],
  ["delete", "delete", "Delete row"]
];
function isRowSubmission(value) {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
function tableRows(value) {
  if (!isRowSubmission(value) || !Array.isArray(value.rows)) return null;
  return value.rows.filter(isRowSubmission);
}
class TableElement extends BaseElement {
  constructor(renderer, schema, submission) {
    super(renderer, schema, submission);
    this._input = null;
    this._table = null;
    this._tbody = null;
    this._thead = null;
    this._form = null;
    this._container = null;
    this._createButton = null;
    this._actions = null;
    this._activeRow = null;
    this._actionsOpen = false;
    this._actionsPinned = false;
    this._actionsListenersAdded = false;
    this._hideActionsTimer = null;
    this._pendingTouchAction = null;
    this._suppressHoverUntil = 0;
    this._suppressTapUntil = 0;
    if (!this.renderer.readonly) {
      const key = this.renderer.form?.key;
      if (key)
        this._validate = ENDPOINTS.renderer.validateRow(key, this.schema.id);
      this._click = this._click.bind(this);
      this._rowPointerOver = this._rowPointerOver.bind(this);
      this._rowPointerDown = this._rowPointerDown.bind(this);
      this._rowPointerMove = this._rowPointerMove.bind(this);
      this._rowPointerUp = this._rowPointerUp.bind(this);
      this._rowPointerCancel = this._rowPointerCancel.bind(this);
      this._rowClick = this._rowClick.bind(this);
      this._rowFocusIn = this._rowFocusIn.bind(this);
      this._scheduleHideActions = this._scheduleHideActions.bind(this);
      this._cancelHideActions = this._cancelHideActions.bind(this);
      this._documentPointerDown = this._documentPointerDown.bind(this);
      this._documentKeyDown = this._documentKeyDown.bind(this);
    }
  }
  get value() {
    return this.submission;
  }
  get mode() {
    return this.renderer.readonly ? "read" : "edit";
  }
  changed(value) {
    if (areEqual(this.value, value)) return false;
    return true;
  }
  _setSubmission(value) {
    this.submission = value;
    if (this._input) {
      const rows = tableRows(value);
      this._input.value = rows ? JSON.stringify(rows) : "";
    }
  }
  updateSubmission(value) {
    this._hideActions();
    this._setSubmission(value);
    this._redrawRows();
  }
  _redrawRows() {
    const { _tbody: tbody, _container: container } = this;
    if (!tbody || !container) return;
    const rows = tableRows(this.submission) ?? [];
    if (rows.length === 0) {
      tbody.innerHTML = "";
      container.dataset.visible = "false";
      return;
    }
    const existing = Array.from(tbody.rows);
    for (let i = 0; i < rows.length; i++) {
      const serialized = JSON.stringify(rows[i]);
      if (i < existing.length) {
        if (existing[i].dataset.submission !== serialized) {
          existing[i].replaceWith(this.row(i, rows[i]));
        } else {
          existing[i].dataset.index = String(i);
          const actions = existing[i].querySelector(
            "[data-role='row-actions']"
          );
          if (actions) actions.dataset.index = String(i);
        }
      } else {
        tbody.appendChild(this.row(i, rows[i]));
      }
    }
    while (tbody.children.length > rows.length) {
      tbody.lastChild?.remove();
    }
    container.dataset.visible = "true";
  }
  _redrawTable({
    after = null,
    dispatchChange = false
  } = {}) {
    return withTransition(() => {
      this._hideActions();
      this._redrawRows();
      if (after) after();
      if (dispatchChange) {
        this._edit?.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
  }
  _commitRows(rows, { after = null } = {}) {
    const value = rows.length > 0 ? { rows } : null;
    this._suppressHoverUntil = performance.now() + HOVER_SUPPRESSION_MS;
    this._setSubmission(value);
    return this._redrawTable({ after, dispatchChange: true });
  }
  _removeForm() {
    this._form?.remove();
    this._form = null;
    if (this._container) {
      this._container.dataset.visible = this._tbody?.children.length ? "true" : "false";
    }
  }
  _actionRow(target) {
    return target.closest("tr[data-index]") || this._activeRow;
  }
  _moveRow(index, direction) {
    const rows = tableRows(this.submission) ?? [];
    const newIndex = direction === "moveUp" ? index - 1 : index + 1;
    if (newIndex < 0 || newIndex >= rows.length) return;
    [rows[index], rows[newIndex]] = [rows[newIndex], rows[index]];
    this._commitRows(rows);
  }
  async _click(e) {
    e.stopPropagation();
    const target = e.target;
    if (!(target instanceof Element)) return;
    const role = target.closest("[data-role]")?.dataset.role;
    const handled = [
      "create",
      "cancel",
      "edit",
      "delete",
      "validate",
      "moveUp",
      "moveDown"
    ];
    if (role && handled.includes(role)) {
      e.preventDefault();
      e.stopPropagation();
    } else if (role) {
      e.stopPropagation();
      return;
    }
    if (role === "create") {
      if (this._form) return;
      const form = await this.form();
      await withTransition(
        () => {
          if (!this._container || !this._edit) return;
          this._container.dataset.visible = "false";
          this._form = form;
          this._edit.appendChild(this._form);
        },
        { label: "embedded-form:create" }
      );
    } else if (role === "cancel") {
      withTransition(() => {
        this._removeForm();
      });
    } else if (role === "edit") {
      const index = this._actionRow(target)?.dataset.index;
      if (index === void 0) return;
      this._hideActions();
      const form = await this.form(index);
      const success = await withTransition(
        () => {
          if (!this._container || !this._edit) return;
          this._container.dataset.visible = "false";
          this._form = form;
          this._edit.appendChild(this._form);
        },
        { label: "embedded-form:edit" }
      );
      if (success) this._scrollFormIntoView();
    } else if (role === "delete") {
      const index = Number.parseInt(
        this._actionRow(target)?.dataset.index ?? "",
        10
      );
      const previousRows = tableRows(this.submission);
      if (Number.isNaN(index) || !previousRows) return;
      const rows = previousRows.filter((_, rowIndex) => rowIndex !== index);
      this._commitRows(rows);
    } else if (role === "moveUp" || role === "moveDown") {
      const index = Number.parseInt(
        this._actionRow(target)?.dataset.index ?? "",
        10
      );
      if (Number.isNaN(index)) return;
      this._moveRow(index, role);
    } else if (role === "validate") {
      const button = target.closest("button");
      const form = this._form;
      const route = this._validate;
      if (!button || !form || !route) return;
      const index = form.dataset.index;
      const formData = new FormData(form);
      button.disabled = true;
      try {
        const response = await request.get(route, formData);
        if (!response?.ok || this._form !== form) return;
        const row = response.row;
        if (!isRowSubmission(row)) return;
        const rows = tableRows(this.submission) ?? [];
        if (index !== void 0 && index !== "") {
          rows[Number.parseInt(index, 10)] = row;
        } else {
          rows.push(row);
        }
        await this._commitRows(rows, { after: () => this._removeForm() });
      } catch (error) {
        captureError(error);
      } finally {
        button.disabled = false;
      }
    }
  }
  table() {
    this._container = document.createElement("div");
    this._container.className = "table-container";
    this._container.dataset.visible = "false";
    const table = this._container.appendChild(document.createElement("table"));
    table.className = STYLES.form.table.table;
    const thead = table.appendChild(document.createElement("thead"));
    this._thead = thead;
    thead.className = "bg-base-bg";
    this.schema.columns?.forEach((column) => {
      const headerCell = thead.appendChild(document.createElement("th"));
      headerCell.className = COMPACT_COLUMN_TYPES.has(column.type) ? STYLES.form.table.cell.compact.th : STYLES.form.table.cell.th;
      const title = headerCell.appendChild(document.createElement("div"));
      title.className = STYLES.form.table.cell.title;
      const span = title.appendChild(document.createElement("span"));
      span.textContent = column.title ?? null;
    });
    if (!this.renderer.readonly) {
      const actionHeader = this._thead.appendChild(
        document.createElement("th")
      );
      actionHeader.className = STYLES.form.table.rowActionHeader;
      actionHeader.setAttribute("aria-hidden", "true");
    }
    this._tbody = table.appendChild(document.createElement("tbody"));
    this._tbody.className = STYLES.form.table.body;
    if (!this.renderer.readonly) {
      this._tbody.addEventListener("pointerover", this._rowPointerOver);
      this._tbody.addEventListener("pointerdown", this._rowPointerDown);
      this._tbody.addEventListener("pointermove", this._rowPointerMove);
      this._tbody.addEventListener("click", this._rowClick);
      this._tbody.addEventListener("focusin", this._rowFocusIn);
      this._tbody.addEventListener("pointerleave", this._scheduleHideActions);
      this._tbody.addEventListener("focusout", this._scheduleHideActions);
    }
    const rows = tableRows(this.submission) ?? [];
    for (const [index, submission] of rows.entries()) {
      this._tbody.appendChild(this.row(index, submission));
    }
    if (rows.length > 0) {
      this._container.dataset.visible = "true";
    }
    return this._container;
  }
  get embedded() {
    if (this._embedded) return this._embedded;
    this._embedded = this.table();
    return this._embedded;
  }
  get edit() {
    if (this._edit) return this._edit;
    this._edit = document.createElement("div");
    this._edit.className = STYLES.form.table.container;
    this._edit.dataset.kind = String(this.renderer.kind);
    const rows = tableRows(this.submission);
    this._input = this._edit.appendChild(
      primitives.input({
        name: this.schema.id,
        type: "hidden",
        value: rows ? JSON.stringify(rows) : ""
      })
    );
    const label = this._edit.appendChild(
      primitives.label({
        label: this.schema.title,
        tag: "h3",
        styles: { label: STYLES.label.row }
      })
    );
    if (!this.renderer.readonly) {
      this._createButton = document.createElement("button");
      this._createButton.type = "button";
      this._createButton.dataset.role = "create";
      this._createButton.ariaLabel = `Add row to ${this.schema.title || "table"}`;
      this._createButton.title = "Add row";
      this._createButton.className = `group-data-[mode=read]/element:hidden ${STYLES.form.icon}`;
      this._createButton.dataset.kind = "add";
      setIcon(
        this._createButton.appendChild(document.createElement("span")),
        "addRow",
        "icon-xs"
      );
      const text = this._createButton.appendChild(
        document.createElement("span")
      );
      text.textContent = "Add row";
      label.appendChild(this._createButton);
    }
    this._table = this.table();
    this._edit.appendChild(this._table);
    if (!this.renderer.readonly) {
      this._edit.addEventListener("click", this._click);
      this._edit.addEventListener("submit", (e) => {
        e.preventDefault();
        e.stopPropagation();
      });
    }
    return this._edit;
  }
  _tableCellElement(column, submission) {
    const ElementClass = column.type === "checkbox" || column.type === "input" || column.type === "link" ? TABLE_CELL_ELEMENTS[column.type] : null;
    if (!ElementClass) {
      captureError(new Error(`Unsupported table column type: ${column.type}`));
      return null;
    }
    return new ElementClass(this._rowRenderer(), column, submission[column.id]);
  }
  _rowRenderer() {
    return { id: this.id, readonly: this.readonly, mode: this.mode };
  }
  row(index, submission) {
    const rowElt = document.createElement("tr");
    rowElt.dataset.index = String(index);
    rowElt.dataset.submission = JSON.stringify(submission);
    if (!this.renderer.readonly) rowElt.tabIndex = 0;
    this.schema.columns?.forEach((column) => {
      const cell = document.createElement("td");
      cell.className = COMPACT_COLUMN_TYPES.has(column.type) ? STYLES.form.table.cell.compact.default : STYLES.form.table.cell.default;
      rowElt.appendChild(cell);
      const element = this._tableCellElement(column, submission);
      const content = element?.cell;
      cell.innerHTML = typeof content === "string" ? content : content?.outerHTML ?? "";
    });
    if (!this.renderer.readonly) {
      const actionCell = rowElt.appendChild(document.createElement("td"));
      actionCell.className = STYLES.form.table.rowActionCell;
      actionCell.appendChild(this._rowActions(index));
    }
    return rowElt;
  }
  _rowActions(index) {
    const actions = document.createElement("div");
    actions.dataset.role = "row-actions";
    actions.dataset.index = String(index);
    actions.setAttribute("aria-label", "Row actions");
    actions.className = STYLES.form.table.rowActions;
    actions.hidden = true;
    for (const [role, icon, label] of ACTIONS) {
      const button = actions.appendChild(document.createElement("button"));
      button.type = "button";
      button.dataset.role = role;
      button.className = STYLES.form.table.actionButton;
      button.title = label;
      button.setAttribute("aria-label", label);
      if (role === "delete") button.dataset.kind = "delete";
      const iconElement = button.appendChild(document.createElement("span"));
      setIcon(iconElement, icon, "icon-sm");
    }
    actions.addEventListener("pointerenter", this._cancelHideActions);
    actions.addEventListener("pointerleave", this._scheduleHideActions);
    actions.addEventListener("focusin", this._cancelHideActions);
    actions.addEventListener("focusout", this._scheduleHideActions);
    return actions;
  }
  _rowPointerOver(e) {
    if (e.pointerType && e.pointerType !== "mouse") return;
    if (performance.now() < this._suppressHoverUntil) return;
    if (this._actionsPinned) return;
    const row = e.target instanceof Element ? e.target.closest("tr[data-index]") : null;
    if (!row) return;
    this._showActions(row);
  }
  _rowPointerDown(e) {
    if (e.pointerType === "mouse") return;
    const target = e.target;
    if (!(target instanceof Element) || target.closest("a, button, input, select, textarea, [data-role]")) {
      return;
    }
    const row = target.closest("tr[data-index]");
    if (!row) return;
    this._pendingTouchAction = {
      row,
      pointerId: e.pointerId,
      x: e.clientX,
      y: e.clientY,
      canceled: false
    };
    document.addEventListener("pointermove", this._rowPointerMove, true);
    document.addEventListener("pointerup", this._rowPointerUp, true);
    document.addEventListener("pointercancel", this._rowPointerCancel, true);
  }
  _rowPointerMove(e) {
    const pending = this._pendingTouchAction;
    if (!pending || pending.pointerId !== e.pointerId) return;
    const moved = Math.hypot(e.clientX - pending.x, e.clientY - pending.y);
    if (moved > TAP_MOVE_TOLERANCE) {
      pending.canceled = true;
      this._suppressTapUntil = performance.now() + TAP_SUPPRESSION_MS;
      this._hideActions();
    }
  }
  _rowPointerUp(e) {
    const pending = this._pendingTouchAction;
    if (!pending || pending.pointerId !== e.pointerId) return;
    const hideActiveActions = !pending.canceled && this._actionsOpen && this._actionsPinned && pending.row === this._activeRow;
    this._clearPendingTouchAction();
    if (!pending.canceled) {
      this._suppressTapUntil = performance.now() + TAP_SUPPRESSION_MS;
      if (hideActiveActions) {
        this._hideActions();
        return;
      }
      this._showActions(pending.row, { pinned: true });
    }
  }
  _rowPointerCancel(e) {
    if (this._pendingTouchAction && this._pendingTouchAction.pointerId !== e.pointerId) {
      return;
    }
    this._clearPendingTouchAction();
  }
  _rowClick(e) {
    if (performance.now() < this._suppressTapUntil) return;
    const fineHover = window.matchMedia(
      "(hover: hover) and (pointer: fine)"
    ).matches;
    if (fineHover) return;
    const target = e.target;
    if (!(target instanceof Element) || target.closest("a, button, input, select, textarea, [data-role]")) {
      return;
    }
    const row = target.closest("tr[data-index]");
    if (!row) return;
    if (this._actionsOpen && this._actionsPinned && row === this._activeRow) {
      this._hideActions();
      return;
    }
    this._showActions(row, { pinned: true });
  }
  _clearPendingTouchAction() {
    this._pendingTouchAction = null;
    document.removeEventListener("pointermove", this._rowPointerMove, true);
    document.removeEventListener("pointerup", this._rowPointerUp, true);
    document.removeEventListener("pointercancel", this._rowPointerCancel, true);
  }
  _rowFocusIn(e) {
    if (this._pendingTouchAction) return;
    const row = e.target instanceof Element ? e.target.closest("tr[data-index]") : null;
    if (!row) return;
    this._showActions(row, { pinned: true });
  }
  _showActions(row, { pinned = false } = {}) {
    if (this._form || !row || !this._edit?.contains(row)) return;
    this._cancelHideActions();
    this._activeRow = row;
    this._actionsPinned = pinned;
    const actions = row.querySelector("[data-role='row-actions']");
    if (!actions) return;
    if (this._actions && this._actions !== actions) {
      this._actions.hidden = true;
    }
    this._actions = actions;
    this._updateActionStates(row);
    actions.hidden = false;
    if (!this._actionsOpen) {
      this._actionsOpen = true;
      this._addActionsListeners();
    }
  }
  _updateActionStates(row) {
    const index = Number.parseInt(row.dataset.index ?? "", 10);
    const length = tableRows(this.submission)?.length || this._tbody?.children.length || 0;
    if (Number.isNaN(index)) return;
    const states = {
      moveUp: index <= 0,
      moveDown: index >= length - 1
    };
    for (const [role, disabled] of Object.entries(states)) {
      const button = this._actions?.querySelector(
        `[data-role='${role}']`
      );
      if (!button) continue;
      button.disabled = disabled;
      button.setAttribute("aria-disabled", disabled ? "true" : "false");
    }
  }
  _addActionsListeners() {
    if (this._actionsListenersAdded) return;
    document.addEventListener("pointerdown", this._documentPointerDown, true);
    document.addEventListener("keydown", this._documentKeyDown, true);
    this._actionsListenersAdded = true;
  }
  _removeActionsListeners() {
    if (!this._actionsListenersAdded) return;
    document.removeEventListener(
      "pointerdown",
      this._documentPointerDown,
      true
    );
    document.removeEventListener("keydown", this._documentKeyDown, true);
    this._actionsListenersAdded = false;
  }
  _documentPointerDown(e) {
    if (!(e.target instanceof Node)) return;
    if (this._actions?.contains(e.target)) return;
    if (this._activeRow?.contains(e.target)) return;
    this._hideActions();
  }
  _documentKeyDown(e) {
    if (e.key === "Escape") this._hideActions();
  }
  _scheduleHideActions() {
    this._cancelHideActions();
    this._hideActionsTimer = window.setTimeout(() => {
      if (this._actionsPinned) return;
      if (this._actions?.matches(":hover")) return;
      if (this._activeRow?.matches(":hover")) return;
      if (this._actions?.contains(document.activeElement)) return;
      if (this._activeRow?.contains(document.activeElement)) return;
      this._hideActions();
    }, HOVER_HIDE_DELAY_MS);
  }
  _cancelHideActions() {
    if (this._hideActionsTimer) {
      window.clearTimeout(this._hideActionsTimer);
      this._hideActionsTimer = null;
    }
  }
  _hideActions() {
    this._cancelHideActions();
    if (this._actions) {
      this._actions.hidden = true;
    }
    this._removeActionsListeners();
    this._actionsOpen = false;
    this._actionsPinned = false;
    this._activeRow = null;
  }
  _scrollFormIntoView() {
    const form = this._form;
    if (!form) return;
    window.requestAnimationFrame(() => {
      if (!this._form || this._form !== form) return;
      const rect = form.getBoundingClientRect();
      const isVisible = rect.top >= 0 && rect.left >= 0 && rect.bottom <= window.innerHeight && rect.right <= window.innerWidth;
      if (isVisible) return;
      const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
      form.scrollIntoView({
        behavior,
        block: "center",
        inline: "nearest"
      });
    });
  }
  async form(index) {
    const hasIndex = index !== void 0 && index !== null && index !== "";
    const submission = hasIndex ? tableRows(this.submission)?.[Number(index)] : void 0;
    const form = document.createElement("form");
    form.className = STYLES.form.table.form;
    if (hasIndex) {
      form.dataset.index = index;
    }
    for (const column of this.schema.columns ?? []) {
      const element = await getFormElement(
        this._rowRenderer(),
        column,
        submission?.[column.id]
      );
      if (element.edit) form.appendChild(element.edit);
    }
    const buttons = form.appendChild(document.createElement("div"));
    buttons.className = STYLES.button.group;
    const cancel = buttons.appendChild(document.createElement("button"));
    cancel.className = STYLES.button.submit;
    cancel.dataset.kind = "cancel";
    cancel.dataset.role = "cancel";
    cancel.textContent = "Cancel";
    const submit = buttons.appendChild(document.createElement("button"));
    submit.className = STYLES.button.submit;
    submit.textContent = hasIndex ? "Save Changes" : "Add Row";
    submit.dataset.role = "validate";
    form.addEventListener("change", (e) => {
      e.stopPropagation();
    });
    form.addEventListener("updated", (e) => {
      e.stopPropagation();
    });
    return form;
  }
  destroy() {
    this._clearPendingTouchAction();
    this._hideActions();
    if (!this.renderer.readonly && this._tbody) {
      this._tbody.removeEventListener("pointerover", this._rowPointerOver);
      this._tbody.removeEventListener("pointerdown", this._rowPointerDown);
      this._tbody.removeEventListener("pointermove", this._rowPointerMove);
      this._tbody.removeEventListener("click", this._rowClick);
      this._tbody.removeEventListener("focusin", this._rowFocusIn);
      this._tbody.removeEventListener(
        "pointerleave",
        this._scheduleHideActions
      );
      this._tbody.removeEventListener("focusout", this._scheduleHideActions);
    }
    if (!this.renderer.readonly && this._edit) {
      this._edit.removeEventListener("click", this._click);
    }
    this._actions = null;
    super.destroy();
  }
}

var table = /*#__PURE__*/Object.freeze({
	__proto__: null,
	TableElement: TableElement
});

class SignatureElement extends BaseElement {
  get value() {
    return this.signatureInput?.value ?? null;
  }
  changed(value) {
    if (areEqual(this.value, value)) return false;
    return true;
  }
  get read() {
    if (this._read) return this._read;
    this._read = document.createElement("div");
    this._read.className = STYLES.signature.pad;
    const signature = this._read.appendChild(document.createElement("img"));
    signature.src = String(this.submission);
    signature.alt = "Signature";
    if (this.submission && this.signatureInput) {
      this.signatureInput.value = this.schema.id;
    }
    this._read.classList.add("group-data-[mode=edit]/element:hidden");
    return this._read;
  }
  get edit() {
    if (this._edit) return this._edit;
    this._edit = document.createElement("div");
    this._edit.className = "flex flex-col gap-2";
    if (this.label) {
      const label = primitives.label({
        label: this.label,
        tag: "h3"
      });
      this._edit.appendChild(label);
    }
    this.signatureInput = this._edit.appendChild(
      primitives.input({
        name: this.schema.id,
        type: "hidden"
      })
    );
    if (this.submission) {
      this.signatureInput.value = this.schema.id;
    }
    const signatureContainer = this._edit.appendChild(
      document.createElement("div")
    );
    signatureContainer.dataset.role = "signature";
    signatureContainer.className = STYLES.signature.pad;
    const reset = signatureContainer.appendChild(
      document.createElement("button")
    );
    reset.className = STYLES.signature.reset;
    reset.id = "reset-button";
    const resetIcon = reset.appendChild(document.createElement("span"));
    setIcon(resetIcon, "reset");
    const signature = new Signature(
      signatureContainer,
      typeof this.submission === "string" ? this.submission : null,
      this.schema.id
    );
    this.signature = signature;
    this.signature.init();
    this.destroyables.push(this.signature);
    reset.addEventListener("click", () => this.clear());
    this._edit.addEventListener("updated", () => {
      if (this.signatureInput) this.signatureInput.value = signature.inputName;
    });
    signatureContainer.classList.add("group-data-[mode=read]/element:hidden");
    return this._edit;
  }
  clear() {
    this.submission = null;
    if (this.signature) {
      this.signature.clear();
    }
    if (this.signatureInput) {
      this.signatureInput.value = "";
    }
  }
}
class Signature {
  constructor(container, imageUrl = null, inputName = "signature-image") {
    this.container = container;
    this.imageUrl = imageUrl;
    this.inputName = inputName;
    this.canvas = null;
    this.ctx = null;
    this.isDrawing = false;
    this.lastX = 0;
    this.lastY = 0;
    this.fileInput = null;
    this.resizeObserver = null;
    this.intersectionObserver = null;
    this.resetButton = null;
    this.boundHandlers = {};
    this.debouncedSave = debounce(() => this.saveSignature(), 300);
  }
  init() {
    this.canvas = this.container.appendChild(document.createElement("canvas"));
    this.canvas.className = `touch-none select-none cursor-crosshair`;
    this.fileInput = this.container.appendChild(
      document.createElement("input")
    );
    this.fileInput.type = "file";
    this.fileInput.name = this.inputName;
    this.fileInput.accept = "image/png";
    this.fileInput.style.display = "none";
    this.ctx = this.canvas.getContext("2d", { willReadFrequently: false });
    this.setupCanvas();
    this.attachEventListeners();
    if (this.imageUrl) {
      this.loadSignature(this.imageUrl);
    }
  }
  setupCanvas() {
    this.intersectionObserver = new IntersectionObserver(
      (entries, observer) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            this.resizeCanvas();
            observer.disconnect();
          }
        }
      },
      { threshold: 0.1 }
    );
    this.intersectionObserver.observe(this.container);
    this.resizeObserver = new ResizeObserver(() => {
      this.resizeCanvas();
    });
    this.resizeObserver.observe(this.container);
    this.boundHandlers.resize = () => this.resizeCanvas();
    window.addEventListener("resize", this.boundHandlers.resize);
  }
  resizeCanvas() {
    const { canvas, ctx, fileInput } = this;
    if (!canvas || !ctx || !fileInput) return;
    const rect = this.container.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const tempCanvas = document.createElement("canvas");
    const tempCtx = tempCanvas.getContext("2d");
    tempCanvas.width = canvas.width;
    tempCanvas.height = canvas.height;
    if (canvas.width > 0 && canvas.height > 0) {
      tempCtx?.drawImage(canvas, 0, 0);
    }
    canvas.width = rect.width;
    canvas.height = rect.height;
    const file = fileInput.files?.[0];
    if (file) {
      this.loadSignatureFromFile(file);
    } else if (tempCanvas.width > 0 && tempCanvas.height > 0) {
      ctx.drawImage(tempCanvas, 0, 0);
    }
  }
  attachEventListeners() {
    if (!this.canvas) return;
    this.boundHandlers.pointerDown = this.handlePointerDown.bind(this);
    this.boundHandlers.pointerMove = this.handlePointerMove.bind(this);
    this.boundHandlers.pointerUp = this.handlePointerUp.bind(this);
    this.boundHandlers.pointerLeave = this.handlePointerLeave.bind(this);
    this.canvas.addEventListener("pointerdown", this.boundHandlers.pointerDown);
    this.canvas.addEventListener("pointermove", this.boundHandlers.pointerMove);
    this.canvas.addEventListener("pointerup", this.boundHandlers.pointerUp);
    this.canvas.addEventListener(
      "pointerleave",
      this.boundHandlers.pointerLeave
    );
  }
  handlePointerDown(e) {
    if (!this.canvas || !this.ctx) return;
    e.preventDefault();
    this.isDrawing = true;
    const rect = this.canvas.getBoundingClientRect();
    this.lastX = e.clientX - rect.left;
    this.lastY = e.clientY - rect.top;
    this.ctx.strokeStyle = "#000000";
    this.ctx.lineWidth = 2;
    this.ctx.lineCap = "round";
    this.ctx.lineJoin = "round";
  }
  handlePointerMove(e) {
    if (!this.isDrawing || !this.canvas || !this.ctx) return;
    e.preventDefault();
    const rect = this.canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    this.ctx.beginPath();
    this.ctx.moveTo(this.lastX, this.lastY);
    this.ctx.lineTo(x, y);
    this.ctx.stroke();
    this.lastX = x;
    this.lastY = y;
  }
  handlePointerUp() {
    if (!this.isDrawing) return;
    this.isDrawing = false;
    this.debouncedSave();
  }
  handlePointerLeave() {
    if (!this.isDrawing) return;
    this.isDrawing = false;
    this.debouncedSave();
  }
  async saveSignature() {
    const { canvas, fileInput } = this;
    if (!canvas || !fileInput) return;
    const blob = await new Promise((resolve) => {
      canvas.toBlob(resolve, "image/png", 1);
    });
    if (!blob) return;
    const file = new File([blob], "signature.png", {
      type: "image/png",
      lastModified: Date.now()
    });
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);
    fileInput.files = dataTransfer.files;
    this.container.dispatchEvent(new CustomEvent("updated", { bubbles: true }));
  }
  async loadSignature(url) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        this._drawImage(img);
        resolve();
      };
      img.onerror = (error) => {
        console.error("Failed to load signature image:", error);
        reject(error);
      };
      img.src = url;
    });
  }
  loadSignatureFromFile(file) {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result !== "string") return;
      const img = new Image();
      img.onload = () => this._drawImage(img);
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  }
  _drawImage(image) {
    if (!this.canvas || !this.ctx) return;
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    this.ctx.drawImage(image, 0, 0, this.canvas.width, this.canvas.height);
  }
  clear() {
    if (this.canvas)
      this.ctx?.clearRect(0, 0, this.canvas.width, this.canvas.height);
    if (this.fileInput) this.fileInput.value = "";
  }
  destroy() {
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
    }
    if (this.intersectionObserver) {
      this.intersectionObserver.disconnect();
    }
    if (this.boundHandlers.resize) {
      window.removeEventListener("resize", this.boundHandlers.resize);
    }
    if (this.canvas) {
      const { pointerDown, pointerMove, pointerUp, pointerLeave } = this.boundHandlers;
      if (pointerDown)
        this.canvas.removeEventListener("pointerdown", pointerDown);
      if (pointerMove)
        this.canvas.removeEventListener("pointermove", pointerMove);
      if (pointerUp) this.canvas.removeEventListener("pointerup", pointerUp);
      if (pointerLeave)
        this.canvas.removeEventListener("pointerleave", pointerLeave);
    }
  }
}

var signature = /*#__PURE__*/Object.freeze({
	__proto__: null,
	Signature: Signature,
	SignatureElement: SignatureElement
});

function isTodoItem(value) {
  return Boolean(
    value && typeof value === "object" && "text" in value && typeof value.text === "string"
  );
}
const normalizeTodoValue = (value, { resetChecked = false } = {}) => {
  if (!value || typeof value !== "object" || !("items" in value) || !Array.isArray(value.items))
    return null;
  const items = value.items.filter(isTodoItem).map((item) => ({
    text: item.text.trim(),
    checked: resetChecked ? false : item.checked === true
  })).filter((item) => item.text);
  return items.length > 0 ? { items } : null;
};
class TodoElement extends BaseElement {
  constructor(renderer, schema, submission) {
    super(renderer, schema, normalizeTodoValue(submission));
    this._input = null;
    this._editing = false;
    this._draftVisible = false;
    this._draft = "";
    this._renamingIndex = null;
    this._renameValue = "";
    this._historyValue = null;
    this._click = this._click.bind(this);
    this._change = this._change.bind(this);
    this._inputEvent = this._inputEvent.bind(this);
    this._keydown = this._keydown.bind(this);
  }
  get value() {
    return normalizeTodoValue({ items: this._payloadItems() });
  }
  get mode() {
    return this._editing ? "edit" : "read";
  }
  changed(value) {
    return !areEqual(this.value, normalizeTodoValue(value));
  }
  _items() {
    return normalizeTodoValue(this.submission)?.items ?? [];
  }
  _payloadItems() {
    const items = this._items();
    if (this._renamingIndex !== null && items[this._renamingIndex]) {
      const text = this._renameValue.trim();
      if (text) items[this._renamingIndex].text = text;
    }
    if (this._editing && this._draftVisible) {
      const text = this._draft.trim();
      if (text) items.push({ text, checked: false });
    }
    return items;
  }
  _setSubmission(value) {
    this.submission = normalizeTodoValue(value);
    this._syncInput();
  }
  _syncInput() {
    if (!this._input) return;
    const value = this.value;
    this._input.value = value ? JSON.stringify(value) : "";
  }
  _notifyChange() {
    this._input?.dispatchEvent(new Event("change", { bubbles: true }));
  }
  _commitItems(items, { notify = true, render = true } = {}) {
    this._setSubmission({ items });
    if (render) this._render();
    if (notify) this._notifyChange();
  }
  _focus(role, { select = false } = {}) {
    queueMicrotask(() => {
      const input = this._elt?.querySelector(
        `[data-role='${role}']`
      );
      if (!input) return;
      input.focus();
      if (select) input.select();
    });
  }
  _button({
    role,
    icon,
    label,
    text = null,
    kind = null,
    header = false
  }) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.role = role;
    if (kind) button.dataset.kind = kind;
    button.ariaLabel = label;
    button.title = label;
    button.className = header ? STYLES.form.icon : STYLES.form.table.actionButton;
    setIcon(
      button.appendChild(document.createElement("span")),
      icon,
      header ? "icon-xs" : "icon-sm"
    );
    if (header && text) {
      const span = button.appendChild(document.createElement("span"));
      span.textContent = text;
    }
    return button;
  }
  _checkbox(item, index, { disabled = false } = {}) {
    const checkbox = primitives.checkbox({
      checked: item.checked,
      disabled
    });
    const input = checkbox.querySelector("input");
    if (!input) return checkbox;
    input.dataset.role = "todo-check";
    input.dataset.index = String(index);
    input.ariaLabel = `${item.checked ? "Uncheck" : "Check"} ${item.text}`;
    return checkbox;
  }
  _itemRow(item, index) {
    const row = document.createElement("li");
    row.className = STYLES.form.todo.row;
    row.dataset.index = String(index);
    row.appendChild(
      this._checkbox(item, index, {
        disabled: this.readonly || this._editing
      })
    );
    if (this._editing && this._renamingIndex === index) {
      const input = row.appendChild(document.createElement("input"));
      input.type = "text";
      input.autocomplete = "off";
      input.dataset.role = "todo-rename-input";
      input.dataset.index = String(index);
      input.value = this._renameValue;
      input.className = STYLES.form.todo.inlineInput;
      input.ariaLabel = `Rename ${item.text}`;
    } else if (this._editing) {
      const text = row.appendChild(document.createElement("button"));
      text.type = "button";
      text.dataset.role = "todo-rename";
      text.dataset.index = String(index);
      text.textContent = item.text;
      text.className = STYLES.form.todo.text;
      text.ariaLabel = `Rename ${item.text}`;
    } else {
      const text = row.appendChild(document.createElement("span"));
      text.textContent = item.text;
      text.className = `${STYLES.form.todo.text} ${item.checked ? STYLES.form.todo.completeText : ""}`.trim();
    }
    if (this._editing) {
      const actions = row.appendChild(document.createElement("div"));
      actions.className = STYLES.form.todo.actions;
      actions.appendChild(
        this._button({
          role: "todo-remove",
          icon: "remove",
          label: `Remove ${item.text}`,
          kind: "delete"
        })
      );
    }
    return row;
  }
  _draftRow() {
    const row = document.createElement("li");
    row.className = STYLES.form.todo.row;
    row.dataset.role = "todo-draft-row";
    row.appendChild(
      this._checkbox({ text: "new todo", checked: false }, "draft", {
        disabled: true
      })
    );
    const input = row.appendChild(document.createElement("input"));
    input.type = "text";
    input.autocomplete = "off";
    input.dataset.role = "todo-draft";
    input.value = this._draft;
    input.className = STYLES.form.todo.inlineInput;
    input.placeholder = "Add a todo\u2026";
    input.ariaLabel = `Add item to ${this.label}`;
    const actions = row.appendChild(document.createElement("div"));
    actions.className = STYLES.form.todo.actions;
    actions.append(
      this._button({
        role: "todo-dismiss-draft",
        icon: "remove",
        label: "Dismiss new todo",
        kind: "delete"
      }),
      this._button({
        role: "todo-commit-draft",
        icon: "success",
        label: "Add todo"
      })
    );
    return row;
  }
  _render() {
    if (!this._elt || !this._input) return;
    this._elt.dataset.mode = this.mode;
    this._elt.replaceChildren(this._input);
    const label = this._elt.appendChild(
      primitives.label({
        label: this.label,
        tag: "h3",
        styles: { label: STYLES.label.row }
      })
    );
    if (!this.readonly) {
      const controls = label;
      if (this._editing) {
        controls.appendChild(
          this._button({
            role: "todo-done",
            icon: "success",
            label: `Done editing ${this.label}`,
            text: "Done",
            kind: "success",
            header: true
          })
        );
      } else {
        const historyButton = super.historyFillButton(this._historyValue);
        if (historyButton) controls.appendChild(historyButton);
        controls.appendChild(
          this._button({
            role: "todo-edit",
            icon: this.hasSubmission ? "edit" : "addRow",
            label: this.hasSubmission ? `Edit ${this.label}` : `Add to ${this.label}`,
            text: this.hasSubmission ? "Edit" : "Add",
            kind: this.hasSubmission ? null : "add",
            header: true
          })
        );
      }
    }
    const items = this._items();
    if (items.length > 0 || this._editing && this._draftVisible) {
      const list = this._elt.appendChild(document.createElement("ul"));
      list.className = STYLES.form.todo.list;
      items.forEach((item, index) => {
        list.appendChild(this._itemRow(item, index));
      });
      if (this._editing && this._draftVisible) {
        list.appendChild(this._draftRow());
      }
    } else if (this.readonly && this.showEmptyFields) {
      this._elt.appendChild(this.readonlyPlaceholder());
    }
    this._syncInput();
  }
  _enterEdit() {
    this._editing = true;
    this._draftVisible = true;
    this._draft = "";
    this._renamingIndex = null;
    this._render();
    this._focus("todo-draft");
  }
  _commitDraft({ continueEditing = true } = {}) {
    this._commitRename({ render: false });
    const text = this._draft.trim();
    const items = this._items();
    if (text) items.push({ text, checked: false });
    this._draft = "";
    this._draftVisible = continueEditing;
    this._renamingIndex = null;
    this._commitItems(items, { notify: Boolean(text) });
    if (continueEditing) this._focus("todo-draft");
    return Boolean(text);
  }
  _commitRename({ render = true } = {}) {
    if (this._renamingIndex === null) return false;
    const items = this._items();
    const item = items[this._renamingIndex];
    const text = this._renameValue.trim();
    const changed = Boolean(item && text && text !== item.text);
    if (changed) item.text = text;
    this._renamingIndex = null;
    this._renameValue = "";
    this._commitItems(items, { notify: changed, render });
    return changed;
  }
  _done() {
    this._commitRename({ render: false });
    const text = this._draftVisible ? this._draft.trim() : "";
    if (text) {
      const items = this._items();
      items.push({ text, checked: false });
      this._setSubmission({ items });
      this._notifyChange();
    }
    this._draft = "";
    this._draftVisible = false;
    this._editing = false;
    this._render();
  }
  _click(event) {
    const target = event.target instanceof Element ? event.target.closest("[data-role]") : null;
    if (!target || !this._elt?.contains(target)) return;
    const role = target.dataset.role;
    const handled = /* @__PURE__ */ new Set([
      "todo-edit",
      "todo-done",
      "todo-commit-draft",
      "todo-dismiss-draft",
      "todo-remove",
      "todo-rename"
    ]);
    if (!role || !handled.has(role)) return;
    event.preventDefault();
    event.stopPropagation();
    if (role === "todo-edit") {
      this._enterEdit();
    } else if (role === "todo-done") {
      this._done();
    } else if (role === "todo-commit-draft") {
      this._commitDraft();
    } else if (role === "todo-dismiss-draft") {
      const hadDraft = Boolean(this._draft.trim());
      this._draft = "";
      this._draftVisible = false;
      this._syncInput();
      this._render();
      if (hadDraft) this._notifyChange();
    } else if (role === "todo-remove") {
      this._commitRename({ render: false });
      const index = Number.parseInt(
        target.closest("[data-index]")?.dataset.index ?? "",
        10
      );
      if (Number.isNaN(index)) return;
      const items = this._items().filter((_, itemIndex) => itemIndex !== index);
      this._renamingIndex = null;
      this._commitItems(items);
    } else if (role === "todo-rename") {
      this._commitRename({ render: false });
      const index = Number.parseInt(target.dataset.index ?? "", 10);
      const item = this._items()[index];
      if (!item) return;
      this._renamingIndex = index;
      this._renameValue = item.text;
      this._render();
      this._focus("todo-rename-input", { select: true });
    }
  }
  _change(event) {
    const checkbox = event.target instanceof Element ? event.target.closest("[data-role='todo-check']") : null;
    if (!checkbox || this._editing || this.readonly) return;
    const index = Number.parseInt(checkbox.dataset.index ?? "", 10);
    const items = this._items();
    if (Number.isNaN(index) || !items[index]) return;
    items[index].checked = checkbox.checked;
    this._setSubmission({ items });
  }
  _inputEvent(event) {
    const { target } = event;
    if (!(target instanceof HTMLInputElement)) return;
    if (target.dataset.role === "todo-draft") {
      this._draft = target.value;
      this._syncInput();
    } else if (target.dataset.role === "todo-rename-input") {
      this._renameValue = target.value;
      this._syncInput();
    }
  }
  _keydown(event) {
    const { target } = event;
    const dataset = target && "dataset" in target ? target.dataset : null;
    const role = dataset && typeof dataset === "object" && "role" in dataset ? dataset.role : null;
    if (role === "todo-draft") {
      if (event.key === "Enter" || event.key === "Tab" && !event.shiftKey) {
        event.preventDefault();
        this._commitDraft();
      } else if (event.key === "Escape") {
        event.preventDefault();
        this._draft = "";
        this._draftVisible = false;
        this._render();
      }
    } else if (role === "todo-rename-input") {
      if (event.key === "Enter" || event.key === "Tab" && !event.shiftKey) {
        event.preventDefault();
        this._commitRename();
        this._focus("todo-draft");
      } else if (event.key === "Escape") {
        event.preventDefault();
        this._renamingIndex = null;
        this._renameValue = "";
        this._render();
      }
    }
  }
  fillFromHistory(value) {
    const restored = normalizeTodoValue(value, { resetChecked: true });
    if (!restored) return false;
    this._editing = false;
    this._draftVisible = false;
    this._draft = "";
    this._renamingIndex = null;
    this._setSubmission(restored);
    this._render();
    this._notifyChange();
    return true;
  }
  addHistoryFill(value) {
    this._historyValue = typeof value === "function" ? value : normalizeTodoValue(value, { resetChecked: true });
    this._render();
    return Boolean(this._elt?.querySelector("[data-role='history-fill']"));
  }
  updateSubmission(value) {
    this._editing = false;
    this._draftVisible = false;
    this._draft = "";
    this._renamingIndex = null;
    this._setSubmission(value);
    this._render();
  }
  create() {
    const elt = document.createElement("div");
    elt.id = this.id;
    elt.className = `${STYLES.form.todo.container} form-element group/element`;
    elt.dataset.kind = String(this.renderer.kind);
    elt._lp_element = this;
    this._elt = elt;
    this._input = document.createElement("input");
    this._input.type = "hidden";
    this._input.name = this.schema.id;
    elt.addEventListener("click", this._click);
    elt.addEventListener("change", this._change);
    elt.addEventListener("input", this._inputEvent);
    elt.addEventListener("keydown", this._keydown);
    this._render();
    return elt;
  }
  destroy() {
    if (this._elt) {
      this._elt.removeEventListener("click", this._click);
      this._elt.removeEventListener("change", this._change);
      this._elt.removeEventListener("input", this._inputEvent);
      this._elt.removeEventListener("keydown", this._keydown);
    }
    this._input = null;
    super.destroy();
  }
}

var todo = /*#__PURE__*/Object.freeze({
	__proto__: null,
	TodoElement: TodoElement,
	normalizeTodoValue: normalizeTodoValue
});

export { TableElement as T, todo as a, signature as s, table as t };
