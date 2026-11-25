/*! Third-party licenses: /third-party-licenses.txt */
import { r as renderReviewBar } from './forms.js?v=b14914a4';
import { w as withTransition, c as captureError } from './foundation.js?v=b14914a4';
import { c as createIcon } from './ui-resources.js?v=b14914a4';
import './ui-controls.js?v=b14914a4';
import './modal.js?v=b14914a4';
import './upstreamUnavailable.js?v=b14914a4';
import './connectivity.js?v=b14914a4';
import './combobox.js?v=b14914a4';

function operationRevision(value) {
  if (typeof value === "number") return value;
  if (typeof value === "string" && /^(0|[1-9][0-9]*)$/.test(value)) {
    return Number(value);
  }
  return value;
}
function isInteger(value) {
  return Number.isInteger(value);
}
function elapsedLabel(value) {
  const seconds = Math.max(Number(value) || 0, 0);
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${Math.floor(seconds)} seconds`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} hr ${minutes % 60} min`;
}
function operationNodes(key) {
  return Array.from(
    document.querySelectorAll("[data-operation]")
  ).filter((node) => node.dataset.operation === key);
}
function operationNodeVisible(node) {
  if (!node || node.isConnected === false) return false;
  if (node.closest?.("[hidden], .hidden, [data-visible='false']")) return false;
  const rects = node.getClientRects?.();
  return rects ? rects.length > 0 : true;
}
function completedAutofillInMarkup(node, status) {
  if (node.dataset.widget !== "TaskForm" || !node.dataset.operationBootstrap || !node.dataset.formState || status?.type !== "autofill" || !status.terminal)
    return false;
  try {
    const state = JSON.parse(node.dataset.formState);
    return state.operation?.key === status.key && state.operation?.revision === status.revision && (status.status !== "succeeded" || state.reviews?.some((review) => review.operation === status.key));
  } catch {
    return false;
  }
}
class DeferredOperationManager {
  constructor(view) {
    this.view = view;
    this.operations = /* @__PURE__ */ new Map();
    this.destroyed = false;
    this.ignored = /* @__PURE__ */ new Set();
    this.unsubscribers = /* @__PURE__ */ new Map();
  }
  init() {
    this.scan();
    return this;
  }
  scan(root = document) {
    const nodes = Array.from(
      root.querySelectorAll?.("[data-operation]") || []
    );
    if ("matches" in root && root.matches?.("[data-operation]"))
      nodes.unshift(root);
    const terminalKeys = /* @__PURE__ */ new Set();
    const scannedKeys = /* @__PURE__ */ new Set();
    for (const node of nodes) {
      if (root === document && node.dataset.widget === "TaskForm" && node._lp_widget?.visible !== true)
        continue;
      const key = node.dataset.operation;
      if (!key) continue;
      const revision = operationRevision(node.dataset.operationRevision);
      const status = node.dataset.operationBootstrap ? JSON.parse(node.dataset.operationBootstrap) : node.dataset.operationStatus ? {
        key,
        revision,
        status: node.dataset.operationStatus,
        phase: node.dataset.operationPhase || "unknown",
        phase_label: node.dataset.operationPhaseLabel || "Working",
        elapsed_seconds: Number(node.dataset.operationElapsed) || 0,
        recovering: node.dataset.operationRecovering === "true",
        terminal: node.dataset.operationTerminal === "true",
        ...node.dataset.operationError ? { error: node.dataset.operationError } : {}
      } : null;
      if (completedAutofillInMarkup(node, status)) continue;
      const tracked = this.track(key, {
        revision,
        node,
        immediate: false,
        status
      });
      if (tracked) {
        scannedKeys.add(key);
        if (status?.terminal) terminalKeys.add(status.key);
      }
    }
    this._refreshCachedStatuses(scannedKeys);
    if (terminalKeys.size) {
      this.view.PollingCoordinator?.trigger(
        Array.from(terminalKeys, (key) => `operation:${key}`)
      );
    }
  }
  resumeTaskForm(node) {
    if (node?.dataset.widget !== "TaskForm") return;
    this.scan(node);
    const key = node.dataset.operation;
    if (key && this.operations.has(key) && node.dataset.operationTerminal !== "true") {
      this.view.PollingCoordinator?.trigger(`operation:${key}`);
    }
  }
  suspendTaskForm(node) {
    if (node?.dataset.widget !== "TaskForm") return;
    const key = node.dataset.operation;
    if (!key || operationNodes(key).some(
      (other) => other !== node && other._lp_widget?.visible === true
    ))
      return;
    this.operations.delete(key);
    this.unsubscribers.get(key)?.();
    this.unsubscribers.delete(key);
  }
  track(key, {
    revision = 0,
    node = null,
    immediate = true,
    status = null
  } = {}) {
    if (this.destroyed || !key || this.ignored.has(key)) return false;
    const decorationNode = node?.dataset?.deferredStatus === "false" ? null : node;
    const previous = decorationNode?.dataset?.operation;
    if (previous && previous !== key && !operationNodes(previous).some((node2) => node2 !== decorationNode)) {
      this.operations.delete(previous);
      this.unsubscribers.get(previous)?.();
      this.unsubscribers.delete(previous);
      this._ignore(previous);
    }
    if (decorationNode) decorationNode.dataset.operation = key;
    if (decorationNode && decorationNode.dataset.pending !== "false" && !status?.terminal) {
      void withTransition(() => this.decorate(decorationNode, key), {
        label: "deferred-operation:decorate"
      });
    }
    const current = this.operations.get(key);
    const incomingRevision = operationRevision(
      revision ?? current?.revision ?? 0
    );
    const resolvedRevision = isInteger(incomingRevision) ? Math.max(
      isInteger(current?.revision) ? current.revision : 0,
      incomingRevision
    ) : incomingRevision;
    const latest = status && (!current?.status || incomingRevision > current.revision) ? { status: { ...status }, receivedAt: Date.now() } : current;
    this.operations.set(key, { ...latest, revision: resolvedRevision });
    const polling = this.view.PollingCoordinator;
    if (this.view.hidden && this.view.blurred) {
      polling?.blur(this.view.blurredAt ?? Date.now());
    }
    let subscribed = false;
    if (!this.unsubscribers.has(key)) {
      const unsubscribe = polling?.subscribe(
        {
          id: `operation:${key}`,
          type: "operation",
          key,
          // A terminal HTML seed is not an acknowledgement of destination
          // reconciliation. Keep its cursor behind until receive succeeds.
          revision: status?.terminal ? Math.max(Number(resolvedRevision) - 1, 0) : typeof resolvedRevision === "number" ? resolvedRevision : NaN
        },
        {
          mode: "periodic",
          initial: "scheduled",
          whileBlurred: () => this.visible(key),
          onResult: async (result) => {
            if (result.status === "changed" && result.payload) {
              return await this.receive(result.payload);
            } else if (result.status === "error" || result.status === "unavailable") {
              this._renderStatusDelay([key]);
            } else {
              this._refreshCachedStatuses([key]);
            }
          }
        }
      );
      if (unsubscribe) {
        this.unsubscribers.set(key, unsubscribe);
        subscribed = true;
      }
    }
    if (immediate && subscribed) {
      polling?.trigger(`operation:${key}`);
    }
    if (!subscribed) polling?.reschedule?.();
    return true;
  }
  visible(key) {
    return this.operations.has(key) && operationNodes(key).some(operationNodeVisible);
  }
  decorate(node, key) {
    if (!node || !key) return;
    node.dataset.operation = key;
    if (node.dataset.formState && node.dataset.operationScope !== "form-change") {
      if (node._lp_widget) renderReviewBar(node._lp_widget);
      return;
    }
    const formLocked = node.dataset.deferredLock === "form";
    if (formLocked) {
      node.setAttribute("aria-busy", "true");
      for (const control of node.querySelectorAll("input, textarea, select, button")) {
        control.disabled = true;
      }
    }
    if (node.querySelector("[data-role='deferred-phase']")) return;
    const autofill = node.querySelector("[data-role='autofill']");
    const submitGroup = node.querySelector("[data-role='submit-group']");
    const autofillSubmitGroup = node.querySelector(
      "[data-role='autofill-submit-group']"
    );
    const autofillTarget = autofill && submitGroup || autofillSubmitGroup;
    const progress = document.createElement("p");
    progress.dataset.role = "deferred-progress";
    progress.className = autofillTarget ? "flex min-h-10 items-center justify-center gap-2 rounded-md bg-kind-default px-4 py-2 text-sm font-semibold text-white shadow-sm" : "mt-2 text-sm text-base-medium";
    progress.setAttribute("aria-live", "polite");
    const icon = createIcon("spinner");
    icon.setAttribute("aria-hidden", "true");
    const phase = document.createElement("span");
    phase.dataset.role = "deferred-phase";
    phase.textContent = node.dataset.operationPhaseLabel || (node.dataset.operationScope === "form-change" ? "Schema migration in progress" : autofillTarget ? "Autofill queued" : "Waiting to start");
    const separator = document.createElement("span");
    separator.setAttribute("aria-hidden", "true");
    separator.textContent = " \xB7 ";
    const elapsed = document.createElement("span");
    elapsed.dataset.role = "deferred-elapsed";
    elapsed.textContent = "just now";
    if (autofillTarget) {
      progress.append(icon, phase, separator, elapsed);
      autofillTarget.replaceWith(progress);
      if (autofill && autofill !== autofillTarget) autofill.remove();
    } else {
      progress.append(phase, separator, elapsed);
      node.append(progress);
    }
  }
  nudge(key, revision = null) {
    const current = key ? this.operations.get(key) : null;
    const incomingRevision = revision === null || revision === void 0 ? revision : operationRevision(revision);
    if (current && isInteger(incomingRevision) && isInteger(current.revision) && incomingRevision < current.revision)
      return false;
    if (key && !this.track(key, { revision: incomingRevision })) return false;
    this.view.PollingCoordinator?.trigger(key ? `operation:${key}` : null);
    return true;
  }
  async poll() {
    return this.view.PollingCoordinator?.trigger(
      Array.from(this.operations.keys(), (key) => `operation:${key}`)
    );
  }
  async receive(status) {
    if (this.destroyed || !status?.key || !this.operations.has(status.key))
      return false;
    const current = this.operations.get(status.key);
    const revision = operationRevision(status.revision);
    if (!isInteger(revision) || revision < 0) {
      captureError(
        new TypeError("Invalid deferred operation revision."),
        this.view.elt,
        {
          context: "polling-operation-payload"
        }
      );
      return false;
    }
    const previousRevision = current?.revision;
    if (!isInteger(previousRevision) || previousRevision < 0) return false;
    if (revision < previousRevision) return false;
    this.operations.set(status.key, {
      revision,
      status: { ...status },
      receivedAt: Date.now()
    });
    this._render(status);
    window.dispatchEvent(
      new CustomEvent("deferred-operation", { detail: { ...status } })
    );
    if (status.terminal) {
      let reconciled = true;
      try {
        const editWatcher = this.view.EditWatcher || await this.view.ensureEditWatcher?.();
        editWatcher?.expectDeferredCompletion?.(status.entity_key, status.key);
        await this.view.reconcileChange?.({
          type: "deferred-complete",
          key: status.entity_key,
          source_widget: status.source_widget,
          destination: status.destination,
          deferred_revision: `${status.key}:${revision}`
        });
        if (status.type === "autofill" && status.status === "succeeded") {
          reconciled = !operationNodes(status.key).some((node) => {
            const widget = node._lp_widget;
            return widget?.visible === true && widget.component?.active === widget && !widget._reviewedOperations?.has(status.key) && !widget.reviewState?.stale_autofill && !widget.reviewState?.reviews?.some(
              (review) => review.operation === status.key
            );
          });
        }
      } catch {
        reconciled = false;
      }
      if (reconciled) {
        this.operations.delete(status.key);
        this.unsubscribers.get(status.key)?.();
        this.unsubscribers.delete(status.key);
        this._ignore(status.key);
      } else {
        this._renderStatusDelay([status.key]);
      }
      return reconciled;
    }
    return true;
  }
  _render(status, elapsedSeconds = status.elapsed_seconds) {
    for (const node of operationNodes(status.key)) {
      if (status.type === "autofill" && node._lp_widget) {
        renderReviewBar(node._lp_widget, {
          ...status,
          elapsed_seconds: elapsedSeconds
        });
      }
      delete node.dataset.operationBootstrap;
      node.dataset.operationRevision = String(status.revision);
      node.dataset.operationStatus = status.status || "unknown";
      node.dataset.operationPhase = status.phase || "unknown";
      node.dataset.operationPhaseLabel = status.phase_label || "Working";
      node.dataset.operationElapsed = String(elapsedSeconds || 0);
      node.dataset.operationRecovering = status.recovering ? "true" : "false";
      if (status.error) node.dataset.operationError = status.error;
      else delete node.dataset.operationError;
      node.dataset.operationTerminal = status.terminal ? "true" : "false";
      const phase = node.querySelector("[data-role='deferred-phase']");
      if (phase) {
        phase.textContent = status.error ? `${status.phase_label}: ${status.error}` : status.recovering ? `${status.phase_label}. Taking longer than expected.` : status.phase_label ?? null;
      }
      const elapsed = node.querySelector("[data-role='deferred-elapsed']");
      if (elapsed) elapsed.textContent = elapsedLabel(elapsedSeconds);
    }
  }
  _refreshCachedStatuses(keys = Array.from(this.operations.keys())) {
    for (const key of keys) {
      const operation = this.operations.get(key);
      if (!operation?.status) continue;
      const elapsed = (Number(operation.status.elapsed_seconds) || 0) + Math.max(Math.floor((Date.now() - operation.receivedAt) / 1e3), 0);
      this._render(operation.status, elapsed);
    }
  }
  _renderStatusDelay(keys = Array.from(this.operations.keys())) {
    for (const key of keys) {
      for (const node of operationNodes(key)) {
        const phase = node.querySelector("[data-role='deferred-phase']");
        if (phase) phase.textContent = "Status check delayed. Retrying.";
      }
    }
  }
  _ignore(key) {
    if (!key) return;
    this.ignored.add(key);
    if (this.ignored.size > 100) {
      const oldest = this.ignored.values().next();
      if (!oldest.done) this.ignored.delete(oldest.value);
    }
  }
  destroy() {
    this.destroyed = true;
    for (const unsubscribe of this.unsubscribers.values()) unsubscribe();
    this.unsubscribers.clear();
    this.operations.clear();
    this.ignored.clear();
  }
}

export { DeferredOperationManager };
