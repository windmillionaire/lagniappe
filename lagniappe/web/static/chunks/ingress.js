/*! Third-party licenses: /third-party-licenses.txt */
import { b as buttons, p as primitives } from './ui-controls.js?v=b6ea3fe0';
import { r as request, c as captureError, w as withTransition } from './foundation.js?v=b6ea3fe0';
import { a as FacetsBox, S as SelectBox } from './forms.js?v=b6ea3fe0';
import './connectivity.js?v=b6ea3fe0';
import { Modal } from './modal.js?v=b6ea3fe0';
import './ui-resources.js?v=b6ea3fe0';
import './upstreamUnavailable.js?v=b6ea3fe0';
import './combobox.js?v=b6ea3fe0';

class ImportData {
  constructor(attributes) {
    Object.assign(this, attributes);
    this._destroyed = false;
    this._stageActionPromise = null;
    const stageElt = this.target.querySelector(
      "[data-role='stage']"
    );
    const progressElt = this.target.querySelector(
      "[data-role='progress']"
    );
    if (!stageElt || !progressElt) {
      throw new Error(
        "Import widget is missing its stage or progress element."
      );
    }
    this.stageElt = stageElt;
    this.progressElt = progressElt;
    this.stage = this.target.dataset.stage;
    this.stageSettings = null;
    this.error = null;
    this.stopButton = null;
    this.stopped = false;
    this.actions = /* @__PURE__ */ new Set();
    this.runStatus = "idle";
    this.pollAfterMs = null;
    this.importRequestStarted = false;
    this._unsubscribeImport = null;
    this._stageUpdate = Promise.resolve(void 0);
    this._parser = new DOMParser();
    this._refreshProgress = this._refreshProgress.bind(this);
    this._updateVisibility = this._updateVisibility.bind(this);
    this._click = this._click.bind(this);
    this._change = this._change.bind(this);
    this._next = this._next.bind(this);
    this._deleteImported = this._deleteImported.bind(this);
  }
  init() {
    request.get(this.endpoints.get(this.key)).then((resp) => {
      if (!this._destroyed) this._setStage(resp);
    }).catch((error) => {
      captureError(error, this.target, { context: "ingress-initial-stage" });
    });
    this.target.addEventListener("click", this._click);
    this.progressElt.addEventListener("change", this._change);
    this.progressElt.addEventListener("input", this._updateVisibility);
  }
  async _click(e) {
    if (this._destroyed || !(e.target instanceof Element)) return;
    const button = e.target.closest("button");
    if (!button) return;
    if (button.dataset.role === "next") {
      await this._runStageAction(button, {
        pendingText: "Processing...",
        fallback: "Could not continue. Try again.",
        operation: () => this._next()
      });
    } else if (button.dataset.role === "import") {
      await this._runStageAction(button, {
        pendingText: "Starting Import...",
        fallback: "Import could not be started. Please try again.",
        operation: () => this._startImport()
      });
    } else if (button.dataset.role === "set-stage") {
      const stage = button.dataset.stage;
      this._setStage(
        await request.put(
          this.endpoints.setStage(this.key),
          { stage }
        )
      );
    } else if (button.dataset.role === "delete-imported") {
      await this._deleteImported(button);
    } else if (button.dataset.role === "stop" && this.actions.has("stop")) {
      await this._runStageAction(button, {
        pendingText: "Stopping...",
        pendingKind: "delete",
        fallback: "Import could not be stopped. Please try again.",
        pausePolling: true,
        operation: () => request.post(this.endpoints.stop(this.key))
      });
    } else if (button.dataset.role === "stop" && this.actions.has("restart")) {
      await this._runStageAction(button, {
        pendingText: "Restarting...",
        pendingKind: "project",
        fallback: "Import could not be restarted. Please try again.",
        operation: () => this._startImport()
      });
    }
  }
  _runStageAction(button, {
    pendingText,
    pendingKind = null,
    fallback,
    operation,
    pausePolling = false
  }) {
    if (this._stageActionPromise) return this._stageActionPromise;
    if (this._destroyed || !button) return Promise.resolve(false);
    const originalText = (button.textContent ?? "").trim();
    const originalKind = button.dataset.kind;
    const hadFocus = document.activeElement === button;
    const wasPolling = this.importRequestStarted;
    const action = buttons.active({
      existingButton: button,
      defaultText: originalText,
      completedText: originalText
    });
    this._clearError();
    action.activate(pendingText, pendingKind);
    button.setAttribute("aria-disabled", "true");
    button.setAttribute("aria-busy", "true");
    if (pausePolling) this._setImportStopped();
    let committed = false;
    const pending = (async () => {
      try {
        const response = await operation();
        if (this._destroyed) return false;
        if (response?.ok !== true) {
          this._showError(response?.error || fallback);
          return false;
        }
        committed = response.stage ? this._setStage(response) : await this._refreshProgress();
        if (!committed && !this._destroyed) this._showError(fallback);
        return committed;
      } catch (error) {
        captureError(error, button, { context: "ingress-stage-action" });
        if (!this._destroyed) this._showError(fallback);
        return false;
      } finally {
        if (!committed && pausePolling && wasPolling && !this._destroyed) {
          Promise.resolve().then(() => this._startImportPolling()).catch((error) => {
            captureError(error, this.target, {
              context: "ingress-polling-recovery"
            });
          });
        }
        if (!committed && !this._destroyed && button.isConnected !== false) {
          action.deactivate(originalText, originalKind);
          button.setAttribute("aria-disabled", "false");
          button.removeAttribute("aria-busy");
          if (hadFocus && (!document.activeElement || document.activeElement === document.body || document.activeElement === button)) {
            button.focus({ preventScroll: true });
          }
        }
      }
    })();
    this._stageActionPromise = pending;
    const clearPending = () => {
      if (this._stageActionPromise === pending) {
        this._stageActionPromise = null;
      }
    };
    pending.then(clearPending, clearPending);
    return pending;
  }
  async _change(e) {
    const target = e.target;
    const form = target instanceof Element ? target.closest("form") : null;
    if (!form) return;
    this.stageElt.querySelectorAll("[data-process]").forEach((processButton) => {
      if (processButton.dataset.process === this.stage) {
        processButton.dataset.visible = "true";
      } else {
        processButton.dataset.visible = "false";
      }
    });
    const updates = new FormData(form);
    const submit = () => request.patch(this.endpoints.update(this.key), updates);
    this._stageUpdate = this._stageUpdate.then(submit, submit);
    return this._stageUpdate;
  }
  _setStage(resp) {
    if (this._destroyed || !resp) return false;
    const {
      stage,
      error,
      progress,
      status,
      stopped = false,
      actions = [],
      run_status: runStatus = "idle",
      poll_after_ms: pollAfterMs = null
    } = resp;
    if (!stage) return false;
    withTransition(() => {
      this.stageElt.innerHTML = progress;
      this.progressElt.innerHTML = status;
      this.stage = stage;
      this.stopped = stopped === true || stopped === "true";
      this.actions = new Set(actions);
      this.runStatus = runStatus;
      this.pollAfterMs = pollAfterMs;
      if (this.stageSettings) {
        this._destroyStage();
      }
      this.stageSettings = {
        target: this.progressElt.querySelector("form"),
        destroyables: []
      };
      if (stage === "CHOOSE_FORM") {
        this._setChooseForm();
      } else if (stage === "CHOOSE_PARENT") {
        this._setChooseParent();
      } else if (stage === "ASSIGN_COLUMNS") {
        this._setAssignColumns();
      } else if (stage === "VERIFY_IMPORT") {
        this._setVerifyImport();
      } else if (stage === "IMPORTING") {
        this._setImportControls();
        if (this.actions.has("restart")) {
          this._setImportStopped();
        } else if (["queued", "running", "stop_requested"].includes(this.runStatus)) {
          this._startImportPolling();
        }
      } else {
        this._setImportStopped();
      }
      if (error) {
        if (stage === "IMPORTING") {
          this._setImportStopped();
        }
        this._showError(error);
      } else {
        this._clearError();
      }
    });
    return true;
  }
  _updateVisibility(e) {
    const target = e.target;
    if (!(target instanceof HTMLInputElement) || target.dataset.optionToggle !== "true")
      return;
    const option = target.type === "checkbox" ? target.name : target.value;
    const section = target.closest("[data-section]");
    section?.querySelectorAll("[data-option]").forEach((section2) => {
      if (target.checked && section2.dataset.option === option) {
        section2.dataset.visible = "true";
      } else {
        section2.dataset.visible = "false";
      }
      const visible = section2.dataset.visible === "true";
      if (!visible) {
        this.stageSettings?.destroyables.forEach((destroyable) => {
          if (destroyable.clear) destroyable.clear();
        });
        section2.querySelectorAll("input").forEach((input) => {
          input.checked = false;
          input.value = "";
        });
      }
    });
  }
  _showError(message) {
    this._clearError();
    this.error = primitives.error(message);
    this.error.setAttribute("role", "status");
    this.error.setAttribute("aria-live", "polite");
    this.error.setAttribute("aria-atomic", "true");
    this.error.dataset.visible = "true";
    this.progressElt.prepend(this.error);
  }
  _clearError() {
    if (!this.error) return;
    this.error.remove();
    this.error = null;
  }
  _destroyStage() {
    if (this.stageSettings) {
      this.stageSettings.destroyables.forEach((destroyable) => {
        destroyable.destroy();
      });
    }
    this.stageSettings = null;
  }
  _setVerifyImport() {
    const settings = this.stageSettings;
    const target = settings?.target;
    const initialSection = target?.querySelector(
      "[data-section='page-form-index']"
    );
    if (!settings || !target || !initialSection) return;
    let section = initialSection;
    const setupSelects = () => {
      const pageSelect = section.querySelector(
        "[data-option='page-form']"
      );
      const indexFrom = section.querySelector(
        "[data-role='index-from']"
      );
      const indexTo = section.querySelector(
        "[data-role='index-to']"
      );
      if (pageSelect) {
        const selectPageForm = new FacetsBox(pageSelect);
        selectPageForm.init();
        settings.destroyables.push(selectPageForm);
      }
      if (indexFrom) {
        const selectIndexFrom = new SelectBox(indexFrom);
        selectIndexFrom.init();
        settings.destroyables.push(selectIndexFrom);
      }
      if (indexTo?.hasAttribute("lp-select")) {
        const selectIndexTo = new SelectBox(indexTo);
        selectIndexTo.init();
        settings.destroyables.push(selectIndexTo);
      }
    };
    setupSelects();
    target.addEventListener("change", async (e) => {
      const input = e.target;
      if (!input || !["page-form-id", "index-field-choice"].includes(input.name)) {
        return;
      } else if (input.name === "index-field-choice" && input.value === "page-form") {
        return;
      }
      e.stopPropagation();
      section.classList.add("opacity-50", "pointer-events-none");
      const params = new URLSearchParams();
      params.set("update-form-index", input.value);
      const resp = await request.get(
        this.endpoints.getPageForm(this.key),
        params
      );
      if (!resp) return;
      const html = resp.html instanceof Document ? resp.html : this._parser.parseFromString(resp.html, "text/html");
      const newSection = html.querySelector(
        "[data-section='page-form-index']"
      );
      if (!newSection) return;
      withTransition(() => {
        settings.destroyables.forEach((destroyable) => {
          destroyable.destroy();
        });
        settings.destroyables = [];
        section.replaceWith(newSection);
        section = newSection;
        setupSelects();
      });
    });
  }
  _setChooseForm() {
    const settings = this.stageSettings;
    const selectButton = settings?.target?.querySelector(
      "[data-option='existing-form']"
    );
    if (!settings || !selectButton) return;
    const selectForm = new FacetsBox(selectButton);
    selectForm.init();
    settings.destroyables.push(selectForm);
  }
  _setChooseParent() {
    const settings = this.stageSettings;
    const parentElt = settings?.target;
    if (!settings || !parentElt) return;
    const selectButton = parentElt.querySelector(
      "[data-option='existing-parent']"
    );
    if (!selectButton) return;
    const selectParent = new FacetsBox(selectButton);
    selectParent.init();
    settings.destroyables.push(selectParent);
    const createModel = parentElt.querySelector(
      "[data-section='create-model']"
    );
    if (!createModel) return;
    if (createModel.dataset.parentKind === "project") {
      createModel.dataset.visible = "true";
    } else {
      createModel.dataset.visible = "false";
    }
    parentElt.addEventListener("updated", (e) => {
      const { options } = e.detail;
      Object.values(options).forEach((option) => {
        if (option.kind === "project") {
          createModel.dataset.visible = "true";
          createModel.dataset.parentKind = "project";
        } else if (option.kind === "model") {
          createModel.dataset.parentKind = "model";
          createModel.dataset.visible = "false";
        }
      });
    });
  }
  _setAssignColumns() {
    const settings = this.stageSettings;
    const target = settings?.target;
    if (!settings || !target) return;
    const columns = target.querySelectorAll("[lp-select]");
    columns.forEach((column) => {
      const select = new SelectBox(column);
      select.init();
      settings.destroyables.push(select);
    });
    const _setOpacity = (checkbox) => {
      const select = checkbox.closest("tr")?.querySelector(
        "[lp-select]"
      );
      if (!select) return;
      if (checkbox.checked) {
        select.classList.add("opacity-50", "pointer-events-none");
        select._lp_combobox?.clear();
      } else {
        select.classList.remove("opacity-50", "pointer-events-none");
      }
    };
    target.querySelectorAll("input[type='checkbox']").forEach((checkbox) => {
      if (checkbox.checked) {
        _setOpacity(checkbox);
      }
    });
    target.addEventListener("change", (e) => {
      if (e.target instanceof HTMLInputElement && e.target.type === "checkbox") {
        _setOpacity(e.target);
      }
    });
  }
  async _next() {
    await this._stageUpdate;
    if (this._destroyed) return null;
    const form = this.stageSettings?.target;
    const updates = form ? new FormData(form) : new FormData();
    updates.append("stage", this.stage);
    return request.put(
      this.endpoints.next(this.key),
      updates
    );
  }
  _setImportControls() {
    const button = this.stageElt.querySelector("[data-role='stop']");
    if (!button) return;
    this.stopButton = buttons.active({ existingButton: button });
  }
  _setImportStopped() {
    this.importRequestStarted = false;
    this._stopImportPolling();
  }
  async _refreshProgress() {
    if (this._destroyed) return false;
    const response = await request.get(
      this.endpoints.get(this.key)
    );
    if (this._destroyed || response?.ok !== true) return false;
    return this._setStage(response);
  }
  _startImportPolling() {
    if (this._destroyed) return;
    this.importRequestStarted = true;
    return this.syncPollingSubscription();
  }
  _pollingVisible() {
    if (this.component?.active !== this || this.component?.visible !== true || this.visible !== true)
      return false;
    let ancestor = this.component?.elt?.parentElement?.closest?.(
      "[lp-component]"
    );
    while (ancestor) {
      if (ancestor.dataset.visible === "false") return false;
      ancestor = ancestor.parentElement?.closest?.("[lp-component]");
    }
    return true;
  }
  /**
   * Import progress is only useful while its wizard is the active visible
   * widget. A running import is remembered and catches up when reopened.
   *
   */
  async syncPollingSubscription() {
    if (this._destroyed) return;
    if (!this.importRequestStarted || !this._pollingVisible()) {
      this._stopImportPolling();
      return;
    }
    if (!this.view.PollingCoordinator) {
      await this.view.ensurePollingCoordinator?.();
      if (!this.importRequestStarted || !this._pollingVisible()) return;
    }
    if (this._unsubscribeImport) return;
    this._unsubscribeImport = this.view.PollingCoordinator?.subscribe(
      {
        id: `ingress:${this.key}`,
        type: "ingress",
        key: this.key,
        revision: this.target.dataset.fingerprint ?? null
      },
      {
        mode: "periodic",
        initial: "immediate",
        onResult: (result) => {
          if (!this._pollingVisible()) return false;
          if (result.status === "changed") return this._refreshProgress();
        }
      }
    );
  }
  _stopImportPolling() {
    this._unsubscribeImport?.();
    this._unsubscribeImport = null;
  }
  async _deleteImported(button) {
    const modal = new Modal(this.view, button);
    await modal.load(this.endpoints.deleteImported(this.key));
    const deleteButton = modal.modal?.querySelector(
      "[data-role='delete-imported']"
    );
    if (!deleteButton) return;
    deleteButton.addEventListener(
      "click",
      async () => {
        deleteButton.disabled = true;
        const spinner = deleteButton.querySelector("#spinner");
        if (spinner) spinner.dataset.visible = "true";
        const response = await request.delete(
          deleteButton.dataset.route
        );
        if (!response?.ok) {
          deleteButton.disabled = false;
          if (spinner) spinner.dataset.visible = "false";
          return;
        }
        await modal.remove();
        this._setStage(response);
      },
      { once: true }
    );
    deleteButton.focus();
  }
  _startImport() {
    return request.post(
      this.endpoints.import(this.key),
      {}
    );
  }
  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;
    this.target.removeEventListener("click", this._click);
    this.progressElt.removeEventListener("change", this._change);
    this.progressElt.removeEventListener("input", this._updateVisibility);
    this._destroyStage();
    this._stopImportPolling();
  }
}

export { ImportData };
