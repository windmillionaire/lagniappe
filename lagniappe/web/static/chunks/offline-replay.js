/*! Third-party licenses: /third-party-licenses.txt */
import { getOfflineMutations, deleteOfflineMutations, setOfflineMutation } from './offline.js?v=b74a2211';
import { r as request } from './foundation.js?v=b74a2211';

const REPLAY_RESULT = Object.freeze({
  BLOCKED: "blocked",
  COMPLETED: "completed",
  REBASED: "rebased"
});
function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function isOptionalText(value) {
  return value === void 0 || value === null || typeof value === "string";
}
function isMutationFile(value) {
  return isRecord(value) && typeof value.name === "string" && value.file instanceof Blob && typeof value.filename === "string" && (value.type === void 0 || typeof value.type === "string");
}
function isOfflineMutation(record) {
  return isOptionalText(record.action) && isOptionalText(record.method) && typeof record.route === "string" && (record.created_at == null || typeof record.created_at === "number") && isOptionalText(record.kind) && isOptionalText(record.client_key) && isOptionalText(record.target_key) && isOptionalText(record.fingerprint) && isOptionalText(record.modified) && (record.fields == null || Array.isArray(record.fields) && record.fields.every(
    (value) => Array.isArray(value) && typeof value[0] === "string" && typeof value[1] === "string"
  )) && (record.files == null || Array.isArray(record.files) && record.files.every(isMutationFile)) && record.conflictResponse === void 0;
}
function selectedFormControl(control) {
  if (control.closest?.(".form-element") || !("_lp_combobox" in control)) {
    return null;
  }
  const combobox = control._lp_combobox;
  if (!isRecord(combobox) || typeof combobox.name !== "string" || !combobox.name) {
    return null;
  }
  const { name, values } = combobox;
  const options = Array.isArray(combobox.options) ? combobox.options : [];
  return {
    name,
    options: options.filter(
      (option) => isRecord(option) && values instanceof Set && values.has(option.id)
    )
  };
}
function createId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `offline-mutation-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
function elementResponse(element) {
  const html = document.implementation.createHTMLDocument("");
  if (element) html.body.appendChild(element);
  return {
    ok: true,
    html
  };
}
function serializeFormData(data) {
  const fields = [];
  const files = [];
  for (const [name, value] of data.entries()) {
    if (value instanceof File) {
      if (value.size > 0 && value.name) {
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
  return { fields, files };
}
function formDataFromRecord(record) {
  const data = new FormData();
  for (const [name, value] of record.fields || []) {
    data.append(name, value);
  }
  for (const file of record.files || []) {
    data.append(file.name, file.file, file.filename);
  }
  if (record.method !== "DELETE") {
    data.set("offline", "True");
    if (record.fingerprint) {
      data.set("offline-fingerprint", record.fingerprint);
    }
  }
  return data;
}
function field(record, name) {
  return (record.fields || []).find(([key]) => key === name)?.[1] || "";
}
class OfflineQueue {
  constructor(view) {
    this.view = view;
    this.records = [];
    this._replaying = false;
  }
  async init() {
    this.records = (await getOfflineMutations()).filter(isOfflineMutation);
  }
  get widgets() {
    return Object.values(this.view.components).flatMap((component) => {
      return Object.values(component.widgets).filter(
        (widget) => widget !== void 0
      );
    });
  }
  get targets() {
    return this.widgets.filter(
      (widget) => typeof widget?.handleOfflineQueue === "function"
    );
  }
  async _dispatch(context, targets = this.targets) {
    return Promise.all(
      [...new Set(targets)].filter(Boolean).map(async (target) => {
        if (typeof target === "function") return target(context);
        return target.handleOfflineQueue?.(context);
      })
    );
  }
  /**
   * A task form can mount after the first reconnect replay found its conflict.
   * Give that form the retained record instead of requiring another replay.
   *
   */
  async presentFor(target) {
    if (!target?.key || typeof target.handleOfflineQueue !== "function") return;
    const record = this._sortedRecords().find(
      (candidate) => candidate.target_key === target.key
    );
    if (!record) return;
    await this._dispatch(
      {
        phase: record.conflictResponse ? "conflict" : "queued",
        queue: this,
        record,
        response: record.conflictResponse
      },
      [target]
    );
  }
  _responseFromResults(results) {
    return results.find(
      (result) => isRecord(result) && typeof result.ok === "boolean" && (result.html === void 0 || result.html instanceof Document) && (result.removed === void 0 || typeof result.removed === "boolean")
    );
  }
  async queueSubmit(component, data, route, method = "POST") {
    const widget = component.active;
    const target = widget?.target;
    if (!widget || "standalone" in widget || !target?.hasAttribute("lp-offline"))
      return null;
    if (typeof widget.offline !== "function") return null;
    await this._destinationWidget(component);
    const action = method === "POST" ? "create" : "update";
    const partial = await widget.offline({
      action,
      queue: this,
      component,
      data,
      method,
      route,
      widget
    });
    if (!partial) return null;
    const fingerprint = partial.fingerprint ?? target.closest?.("[lp-entity]")?.dataset?.fingerprint ?? this.view.elt?.dataset?.fingerprint ?? null;
    const modified = partial.modified ?? target.closest?.("[lp-entity]")?.dataset?.modified ?? this.view.elt?.dataset?.modified ?? null;
    const rendererSubmission = partial.renderer_submission ?? widget.form?.renderer?._packageSubmission?.() ?? null;
    const formControls = Array.from(
      target.querySelectorAll?.("[data-combobox-id]") || []
    ).map(selectedFormControl).filter((control) => control !== null);
    const result = await this.queue({
      action,
      method,
      route,
      data,
      ...partial,
      fingerprint,
      modified,
      renderer_submission: rendererSubmission,
      renderer_schema: partial.renderer_schema ?? widget.schema ?? null,
      form_controls: formControls
    });
    return result.response ? { ...result.response, queued: true } : { ok: true, queued: true };
  }
  async _destinationWidget(component) {
    const destination = component.active?.target?.dataset.destination;
    if (!destination) return null;
    const [componentId, widgetName] = destination.split(":");
    if (!widgetName) return null;
    const componentElt = componentId === component.name ? component.elt : document.getElementById(componentId);
    const destinationComponent = this.view.getComponent(componentElt);
    if (!destinationComponent) return null;
    return destinationComponent.widgets[widgetName] || await destinationComponent.loadWidget(widgetName);
  }
  async replay() {
    if (!this.view.online || this._replaying) return 0;
    this._replaying = true;
    let completed = 0;
    try {
      for (const record of this._sortedRecords()) {
        let current = record;
        while (current) {
          const result = await this._replayRecord(current);
          if (result.state === REPLAY_RESULT.REBASED) {
            current = result.record;
            continue;
          }
          if (result.state === REPLAY_RESULT.BLOCKED) return completed;
          if (result.state === REPLAY_RESULT.COMPLETED) {
            completed += 1;
            break;
          }
          throw new TypeError(`Unknown replay result: ${result.state}`);
        }
      }
    } finally {
      this._replaying = false;
    }
    return completed;
  }
  async _replayRecord(record) {
    const response = await this._send(record);
    if (response?.conflict) {
      const attemptedFingerprint = record.fingerprint;
      record.conflictResponse = response;
      await this._dispatch({
        phase: "conflict",
        queue: this,
        record,
        response
      });
      const rebased = this.records.find((queued) => queued.id === record.id);
      if (!rebased || rebased.fingerprint === attemptedFingerprint) {
        return { state: REPLAY_RESULT.BLOCKED };
      }
      return { state: REPLAY_RESULT.REBASED, record: rebased };
    }
    if (!response?.ok || response.error) {
      return { state: REPLAY_RESULT.BLOCKED };
    }
    await deleteOfflineMutations([record.id]);
    this.records = this.records.filter((queued) => queued.id !== record.id);
    const targets = this.targets;
    const mountedUpdateTargets = record.method === "PUT" ? this._mountedUpdateTargets(record, targets) : [];
    this._finalize(record, response);
    await this._dispatch(
      {
        phase: "replayed",
        queue: this,
        record,
        response
      },
      targets.filter((target) => !mountedUpdateTargets.includes(target))
    );
    if (record.method === "PUT") {
      await this._pollMountedUpdate(record, mountedUpdateTargets);
    }
    return { state: REPLAY_RESULT.COMPLETED };
  }
  _mountedUpdateTargets(record, targets = this.targets) {
    return targets.filter(
      (target) => target?.key === record.target_key && target.target?.matches?.("form[data-widget]")
    );
  }
  async _pollMountedUpdate(record, targets = this._mountedUpdateTargets(record)) {
    if (!targets.length) return;
    const watcher = this.view.EditWatcher || await this.view.ensureEditWatcher?.();
    await watcher?.invalidate?.(record.target_key);
  }
  async rebaseSubmit(record, widget, {
    fingerprint,
    modified
  } = {}) {
    if (!record?.id || !widget) return null;
    const data = widget.component?.formData ?? widget.formData;
    if (!(data instanceof FormData)) return null;
    const serialized = serializeFormData(data);
    const currentFileNames = new Set(serialized.files.map((file) => file.name));
    serialized.files.push(
      ...(record.files || []).filter(
        (file) => !currentFileNames.has(file.name)
      )
    );
    const rebased = {
      ...record,
      fingerprint: fingerprint || record.fingerprint || null,
      modified: modified || record.modified || null,
      renderer_submission: widget.form?.renderer?._packageSubmission?.() ?? record.renderer_submission ?? null,
      renderer_schema: widget.schema ?? record.renderer_schema ?? null,
      fields: serialized.fields,
      files: serialized.files
    };
    delete rebased.conflictResponse;
    await this._store(rebased);
    await this._dispatch({
      phase: "queued",
      queue: this,
      record: rebased
    });
    return rebased;
  }
  async queue(record) {
    const queued = this._queuedRecord(record);
    await this._store(queued);
    const results = await this._dispatch({
      phase: "queued",
      queue: this,
      record: queued
    });
    return {
      record: queued,
      response: this._responseFromResults(results)
    };
  }
  _queuedRecord(record) {
    const id = record.id || createId();
    const serialized = record.data ? serializeFormData(record.data) : {
      fields: record.fields || [],
      files: record.files || []
    };
    return {
      id,
      action: record.action || (record.method === "DELETE" ? "delete" : "submit"),
      kind: record.kind,
      method: record.method || "POST",
      route: record.route,
      client_key: record.client_key || (record.action === "create" ? `offline:${id}` : null),
      target_key: record.target_key,
      fingerprint: record.fingerprint || null,
      modified: record.modified || null,
      renderer_submission: record.renderer_submission ?? null,
      renderer_schema: record.renderer_schema ?? null,
      form_controls: record.form_controls || [],
      fields: serialized.fields,
      files: serialized.files,
      created_at: record.created_at || Date.now()
    };
  }
  response(element) {
    return elementResponse(element);
  }
  field(record, name) {
    return field(record, name);
  }
  recordsFor({
    kind = null,
    action = null
  } = {}) {
    return this._sortedRecords().filter((record) => {
      if (kind && record.kind !== kind) return false;
      if (action && record.action !== action) return false;
      return true;
    });
  }
  async cancel(match) {
    const records = this.records.filter((record) => {
      return this._recordMatches(record, match);
    });
    if (records.length === 0) return [];
    await deleteOfflineMutations(records.map((record) => record.id));
    const ids = new Set(records.map((record) => record.id));
    this.records = this.records.filter((record) => !ids.has(record.id));
    await Promise.all(
      records.map((record) => {
        return this._dispatch({
          phase: "cancelled",
          queue: this,
          record
        });
      })
    );
    return records;
  }
  _recordMatches(record, match) {
    if (typeof match === "function") return match(record);
    if (typeof match === "string") {
      return [record.id, record.client_key, record.target_key].includes(match);
    }
    if (!match || typeof match !== "object") return false;
    return Object.entries(match).every(([key, value]) => record[key] === value);
  }
  async _store(record) {
    await setOfflineMutation(record);
    this.records = [
      ...this.records.filter((existing) => existing.id !== record.id),
      record
    ];
  }
  _sortedRecords() {
    return [...this.records].sort(
      (a, b) => Number(a.created_at) - Number(b.created_at)
    );
  }
  async _send(record) {
    if (record.method === "DELETE") return request.delete(record.route);
    const data = formDataFromRecord(record);
    if (record.method === "PUT") {
      return request.put(record.route, data, { acknowledgeEntities: false });
    }
    return request.post(record.route, data);
  }
  _finalize(record, response) {
    const key = record.action === "create" ? record.client_key : record.target_key;
    if (!key) return;
    const current = document.querySelector(`[data-key="${key}"]`);
    if (record.action === "create") {
      const html = response.html || void 0;
      const replacement = html?.querySelector("li,[lp-entity]");
      if (current && replacement) current.replaceWith(replacement);
      else if (current && response.removed) current.remove();
      return;
    }
    if ((record.action === "complete" || record.action === "delete") && current) {
      current.remove();
    }
  }
}

var offlineQueue = /*#__PURE__*/Object.freeze({
	__proto__: null,
	OfflineQueue: OfflineQueue
});

const replayOfflineQueue = async (view, existingQueue = null) => {
  try {
    if (view._destroyed) return 0;
    const queue = existingQueue || await view.ensureOfflineQueue();
    if (!queue || view._destroyed || !view.online) return 0;
    const replayed = await queue.replay() || 0;
    if (replayed && !view._destroyed) await view.refresh();
    return replayed;
  } catch (error) {
    view.reportStartupError(error, view.elt, "offline-replay");
    return 0;
  }
};

var offlineReplay = /*#__PURE__*/Object.freeze({
	__proto__: null,
	replayOfflineQueue: replayOfflineQueue
});

export { offlineReplay as a, offlineQueue as o };
