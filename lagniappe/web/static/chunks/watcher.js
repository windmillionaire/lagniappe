/*! Third-party licenses: /third-party-licenses.txt */
import { f as areEqual, r as request, c as captureError, w as withTransition } from './foundation.js?v=b14914a4';
import { e as compatibleField, r as renderReviewBar, f as currentReviewOperation, h as incompatibleSchema } from './forms.js?v=b14914a4';
import { b as buttons } from './ui-controls.js?v=b14914a4';
import { S as STYLES } from './ui-resources.js?v=b14914a4';
import { Modal } from './modal.js?v=b14914a4';
import { l as loadWidget } from './core-foundation.js?v=b14914a4';
import './upstreamUnavailable.js?v=b14914a4';
import './connectivity.js?v=b14914a4';
import './combobox.js?v=b14914a4';

async function loadRevisionPreview(liveWidget, response, { readonly = liveWidget.readonly } = {}) {
  const html = response.html;
  if (!html) return null;
  const responseTarget = html.querySelector(
    `[data-widget='${liveWidget.name}']`
  );
  if (!responseTarget) return null;
  const container = document.createElement("div");
  container.appendChild(responseTarget.cloneNode(true));
  const view = {
    key: liveWidget.key,
    kind: liveWidget.kind,
    readonly,
    online: true,
    hidden: false,
    showExtractReloadNotice() {
    }
  };
  const component = {
    elt: container,
    view,
    key: liveWidget.key,
    kind: liveWidget.kind,
    widgets: {},
    get readonly() {
      return readonly;
    }
  };
  const preview = await loadWidget(component, liveWidget.name, {
    revisionPreview: true,
    schema: response.schema ?? null,
    submission: response.submission ?? null
  });
  const previewResponse = {
    ...response,
    html: html.cloneNode(true)
  };
  if (preview.updated) await preview.updated(previewResponse);
  if (preview.prereconcile) await preview.prereconcile();
  if (preview.postreconcile) preview.postreconcile();
  return preview;
}

class FormRevisionModal extends Modal {
  constructor(reconciler, marker, widget, state, { blockedAction = null } = {}) {
    super(
      reconciler.view,
      marker.querySelector("[data-role='edited-reset']")
    );
    this.reconciler = reconciler;
    this.marker = marker;
    this.widget = widget;
    this.state = state;
    this.blockedAction = blockedAction;
    this.selections = /* @__PURE__ */ new Map();
    this.openReview = this._reviewSnapshot();
    this.openSnapshot = widget.revisionSnapshot();
  }
  _reviewSnapshot() {
    const response = this.state.response;
    if (!response) return null;
    const review = response.form_state ?? {};
    return structuredClone({
      schema: response.schema,
      submission: response.submission,
      revision: review.revision,
      reviews: review.reviews,
      queued: this.state.record?.id
    });
  }
  async _isCurrent() {
    await Promise.all([this.state.probePromise, this.state.conflictPromise]);
    return areEqual(this.openReview, this._reviewSnapshot()) && this.widget.revisionSnapshot() === this.openSnapshot;
  }
  _schemaSummary() {
    const before = new Map(
      (this.state.record?.renderer_schema ?? this.widget.schema ?? []).map(
        (field) => [field?.id, field]
      )
    );
    const after = new Map(
      (this.state.response?.schema ?? []).map((field) => [field?.id, field])
    );
    const added = [...after.keys()].filter((id) => id && !before.has(id));
    const removed = [...before.keys()].filter((id) => id && !after.has(id));
    const changed = [...after.keys()].filter(
      (id) => id && before.has(id) && !areEqual(before.get(id), after.get(id))
    );
    const parts = [];
    if (added.length) parts.push(`${added.length} added`);
    if (removed.length) parts.push(`${removed.length} removed`);
    if (changed.length) parts.push(`${changed.length} changed`);
    return parts.length ? `Schema update: ${parts.join(", ")}.` : null;
  }
  _value(element) {
    const rendered = element?.elt?.cloneNode(true);
    if (!rendered || element?.hasSubmission === false) {
      const empty = document.createElement("p");
      empty.className = "text-sm italic text-base-medium";
      empty.textContent = "Empty";
      return empty;
    }
    const label = rendered.matches?.("[data-role='label']") ? rendered : rendered.querySelector?.("[data-role='label']");
    label?.remove();
    rendered.removeAttribute?.("id");
    rendered.querySelectorAll?.("[id]").forEach((node) => {
      node.removeAttribute("id");
    });
    rendered.querySelectorAll?.("button").forEach((button) => {
      button.remove();
    });
    for (const node of [
      rendered,
      ...rendered.querySelectorAll("[data-visible]")
    ]) {
      node.dataset.visible = "true";
    }
    return rendered;
  }
  async _differences(localResponse) {
    const response = this.state.response;
    if (!response) return [];
    const localSnapshot = this.state.record ? this.state.record.renderer_submission ?? {} : this.widget.captureFormState().renderer_submission ?? {};
    const localSubmission = {
      ...localResponse.submission,
      ...localSnapshot
    };
    const state = response.form_state ?? {};
    this.sources = [
      {
        id: "local",
        label: this.state.record ? "Queued value" : "Value in this tab",
        schema: this.state.record?.renderer_schema ?? this.widget.schema,
        submission: localSubmission
      },
      {
        id: "server",
        label: "Latest saved value",
        schema: response.schema,
        submission: response.submission ?? {}
      },
      ...(state.reviews ?? []).map(
        (review) => ({
          id: `ai:${review.operation}`,
          label: review.private ? "Revised suggestion" : "Autofill suggestion",
          ...review
        })
      )
    ];
    const previews = await Promise.all(
      this.sources.map(
        (source) => loadRevisionPreview(
          this.widget,
          {
            ...response,
            schema: source.schema,
            submission: source.submission
          },
          { readonly: true }
        )
      )
    );
    try {
      const rendered = previews.map((preview) => {
        if (!preview) throw new Error("Could not render form review values");
        return new Map(
          Array.from(preview.form?.renderer?.elements?.values?.() ?? []).map(
            (element) => [element.schema?.id, element]
          )
        );
      });
      const fields = [
        ...new Map(
          this.sources.flatMap((source) => source.schema ?? []).map((field) => [field.id, field])
        ).values()
      ];
      const reviews = state.reviews ?? [];
      const savedChangedSinceLaunch = (field) => reviews.some(
        (review) => review.saved_baseline && !this._sameValue(
          this.sources[1].submission[field.id],
          review.saved_baseline[field.id],
          field
        )
      );
      return fields.filter((field) => {
        if (!field?.id) return false;
        const suggestedChange = reviews.some(
          (review) => review.fields?.includes(field.id) && !this._sameValue(
            review.baseline?.[field.id],
            review.submission?.[field.id],
            field
          )
        );
        if (suggestedChange) return true;
        if (reviews.length && !this.state.record) {
          const localField = this.sources[0].schema?.find(
            (item) => item.id === field.id
          );
          const savedField = this.sources[1].schema?.find(
            (item) => item.id === field.id
          );
          return savedChangedSinceLaunch(field) || !compatibleField(localField, savedField);
        }
        return this.sources.some(
          (source) => (!source.fields || source.fields.includes(field.id)) && source.schema?.some((item) => item.id === field.id) && (!this._sameValue(
            source.submission[field.id],
            this.sources[1].submission[field.id],
            field
          ) || !compatibleField(
            source.schema.find((item) => item.id === field.id),
            this.sources[1].schema?.find((item) => item.id === field.id)
          ))
        );
      }).map((field) => ({
        id: field.id,
        label: field.title || field.label || "Untitled field",
        choices: this.sources.flatMap((source, index) => {
          if (source.fields && !source.fields.includes(field.id)) return [];
          if (source.id === "server" && (reviews.length && !this.state.record && !savedChangedSinceLaunch(field) && compatibleField(
            this.sources[0].schema?.find(
              (item) => item.id === field.id
            ),
            source.schema?.find((item) => item.id === field.id)
          ) || this._sameValue(
            source.submission[field.id],
            this.sources[0].submission[field.id],
            field
          ) && compatibleField(
            this.sources[0].schema?.find(
              (item) => item.id === field.id
            ),
            source.schema?.find((item) => item.id === field.id)
          ) || !savedChangedSinceLaunch(field) && this.sources.some(
            (candidate) => candidate.id.startsWith("ai:") && candidate.fields?.includes(field.id) && this._sameValue(
              source.submission[field.id],
              candidate.submission[field.id],
              field
            ) && compatibleField(
              candidate.schema?.find(
                (item) => item.id === field.id
              ),
              source.schema?.find((item) => item.id === field.id)
            )
          )))
            return [];
          const definition = source.schema?.find(
            (item) => item.id === field.id
          );
          if (!definition) return [];
          if (source.id.startsWith("ai:") && savedChangedSinceLaunch(field) && this._sameValue(
            source.submission[field.id],
            this.sources[1].submission[field.id],
            field
          ) && compatibleField(
            definition,
            this.sources[1].schema?.find((item) => item.id === field.id)
          ))
            return [];
          if (source.id.startsWith("ai:") && this._sameValue(
            source.baseline?.[field.id],
            source.submission[field.id],
            field
          ) && this._sameValue(
            source.submission[field.id],
            this.sources[0].submission[field.id],
            field
          ) && compatibleField(
            definition,
            this.sources[0].schema?.find((item) => item.id === field.id)
          ))
            return [];
          return [
            {
              source: source.id,
              label: source.label,
              compatible: source.id === "server" || compatibleField(
                definition,
                this.sources[1].schema?.find(
                  (item) => item.id === field.id
                )
              ),
              value: this._value(rendered[index].get(field.id))
            }
          ];
        }).sort((left, right) => {
          const rank = (source) => {
            if (source === "local") return 0;
            if (source.startsWith("ai:")) return 1;
            if (source === "server") return 2;
            return 3;
          };
          return rank(left.source) - rank(right.source);
        })
      }));
    } finally {
      previews.forEach((preview) => {
        preview?.destroy?.();
      });
    }
  }
  _sameValue(left, right, field = null) {
    const comparable = (value) => {
      if (value == null || value === "" || Array.isArray(value) && !value.length)
        return null;
      if (typeof value === "object" && Object.keys(value).length === 1 && ("rows" in value && Array.isArray(value.rows) && !value.rows.length || "items" in value && Array.isArray(value.items) && !value.items.length))
        return null;
      if (field?.type === "input" && field.input === "number" && (typeof value === "string" || typeof value === "number") && Number.isFinite(Number(value)))
        return Number(value);
      return value;
    };
    return areEqual(comparable(left), comparable(right));
  }
  _choice(field, { source, label, compatible, value }) {
    const button = document.createElement(compatible ? "button" : "div");
    if (compatible) {
      button.setAttribute("type", "button");
      button.setAttribute("role", "radio");
      button.setAttribute(
        "aria-checked",
        (source === this.selections.get(field.id)).toString()
      );
    } else button.dataset.role = "incompatible-value";
    button.setAttribute("aria-label", `${label} for ${field.label}`);
    button.dataset.revisionSource = source;
    button.className = "min-w-0 rounded-md border border-base-light/50 bg-white p-3 text-left transition-colors hover:bg-base-bg aria-checked:bg-kind-bg aria-checked:outline-2 aria-checked:outline-kind-default";
    const heading = button.appendChild(document.createElement("span"));
    heading.className = "mb-2 block text-xs font-semibold text-base-medium";
    heading.textContent = label;
    button.appendChild(value);
    if (!compatible) {
      const explanation = button.appendChild(document.createElement("p"));
      explanation.className = "mt-2 text-xs text-base-medium";
      explanation.textContent = "This field changed type or was removed. Keep this earlier value for reference and re-enter it in the updated form if needed.";
      return button;
    }
    button.addEventListener("click", () => {
      const group = button.closest("[role='radiogroup']");
      group?.querySelectorAll("[role='radio']").forEach((choice) => {
        choice.setAttribute("aria-checked", (choice === button).toString());
      });
      this.selections.set(field.id, source);
    });
    return button;
  }
  async init() {
    const response = this.state.response;
    if (!response) return false;
    const local = this.state.record ? this.widget.buildLocalRevision(response, this.state.record) : this.widget.buildLocalRevision(response);
    const differences = await this._differences(local.response);
    if (!differences.length && !this.state.response?.form_state) return false;
    const noNewAutofillValues = !differences.length && !this.blockedAction && !this.state.record && !!this.state.response?.form_state?.reviews?.length;
    const saved = this.sources[1];
    const savedContextChanged = this.state.response?.form_state?.reviews?.some((review) => {
      const savedBaseline = review.saved_baseline;
      if (!savedBaseline) return false;
      const fields2 = new Map(
        [...review.schema ?? [], ...saved.schema ?? []].filter((field) => field?.id).map((field) => [field.id, field])
      );
      return [...fields2.values()].some(
        (field) => !this._sameValue(
          saved.submission[field.id],
          savedBaseline[field.id],
          field
        )
      );
    }) ?? false;
    for (const field of differences) {
      const localChoice = field.choices.find(
        (choice) => choice.source === "local" && choice.compatible
      );
      const serverChoice = field.choices.find(
        (choice) => choice.source === "server" && choice.compatible
      );
      const aiChoice = field.choices.findLast(
        (choice) => choice.compatible && choice.source.startsWith("ai:")
      );
      const baseline = this.widget._baselineSubmission;
      const changedLocally = this.state.record || baseline && !this._sameValue(
        this.sources[0].submission[field.id] ?? null,
        baseline[field.id] ?? null
      );
      let defaultSource = aiChoice?.source ?? serverChoice?.source ?? localChoice?.source;
      if (savedContextChanged)
        defaultSource = serverChoice?.source ?? (localChoice?.compatible ? "local" : defaultSource);
      if (localChoice?.compatible && changedLocally) defaultSource = "local";
      if (defaultSource) this.selections.set(field.id, defaultSource);
    }
    const modal = document.createElement("div");
    modal.id = "modal";
    modal.className = STYLES.modal.wrapper;
    modal.dataset.kind = this.widget.kind || this.widget.component?.kind || this.reconciler.view.kind || "default";
    const content = modal.appendChild(document.createElement("div"));
    content.id = "modal-content";
    content.className = `${STYLES.modal.content} w-full sm:max-w-3xl`;
    const header = content.appendChild(document.createElement("header"));
    header.className = STYLES.modal.header;
    const title = header.appendChild(document.createElement("h2"));
    title.className = "text-lg font-bold text-base-dark";
    title.textContent = this.blockedAction === "autofill" ? "Review changes before autofill" : noNewAutofillValues ? "Autofill is complete" : "Choose form values";
    const close = header.appendChild(document.createElement("button"));
    close.type = "button";
    close.setAttribute("lp-control", "close");
    close.className = STYLES.button.close;
    close.textContent = "Close";
    const body = content.appendChild(document.createElement("div"));
    body.className = "space-y-4 p-4 sm:p-6";
    const intro = body.appendChild(document.createElement("p"));
    intro.className = "text-sm text-base-medium";
    intro.textContent = this.blockedAction === "autofill" ? "Autofill did not start because the saved form changed. Choose which values to keep, then select Use selected values and start Autofill again. Use Update first if you want to save your choices." : noNewAutofillValues ? "No new form values were suggested. Keep your current values or revise the result below. Use Update afterward to acknowledge this review." : "Choose the values to keep. This updates your open form only; use Update afterward to save. Earlier values whose field type changed are shown for reference.";
    if (differences.some(
      (field) => field.choices.some((choice) => !choice.compatible)
    ))
      intro.textContent += " Applying these choices drops incompatible draft values from the updated form. Copy any earlier values you need before continuing.";
    const schemaSummary = this._schemaSummary();
    if (schemaSummary) {
      const schema = body.appendChild(document.createElement("p"));
      schema.className = STYLES.message;
      schema.textContent = schemaSummary;
    }
    const fields = body.appendChild(document.createElement("div"));
    fields.className = "space-y-4";
    for (const field of differences) {
      const row = fields.appendChild(document.createElement("section"));
      row.className = "rounded-md border border-base-light/50 bg-base-bg p-3";
      const label = row.appendChild(document.createElement("h3"));
      label.className = "mb-2 font-semibold text-base-dark";
      label.textContent = field.label;
      const choices = row.appendChild(document.createElement("div"));
      if (field.choices.some((choice) => choice.compatible))
        choices.setAttribute("role", "radiogroup");
      choices.setAttribute("aria-label", field.label);
      choices.className = "grid gap-2 sm:grid-cols-2";
      choices.append(
        ...field.choices.map((choice) => this._choice(field, choice))
      );
    }
    if (!differences.length && !noNewAutofillValues) {
      const noChanges = fields.appendChild(document.createElement("p"));
      noChanges.textContent = "The available values already match. You can revise them with a prompt below.";
    }
    this._refinement(body);
    const actions = body.appendChild(document.createElement("div"));
    actions.className = "flex w-full";
    const updateAction = buttons.active({
      type: "button",
      text: noNewAutofillValues ? "Keep current values" : "Use selected values",
      processingText: "Applying values\u2026"
    });
    const update = actions.appendChild(updateAction.element);
    update.addEventListener("click", async () => {
      updateAction.activate();
      try {
        if (!await this._isCurrent()) {
          intro.textContent = "The form changed while this review was open. Close and reopen Review to compare the latest values.";
          return;
        }
        await this.reconciler.resolveRevision(this.marker, {
          localResponse: local.response,
          selections: Object.fromEntries(this.selections),
          selectedSubmission: this._selectedSubmission()
        });
        await this.remove();
      } finally {
        updateAction.deactivate();
      }
    });
    await super.attach(modal, this.widget.component);
    update.focus();
    return true;
  }
  _selectedSubmission() {
    const response = this.state.response;
    if (!response) return {};
    const review = response.form_state ?? {};
    const preserveTabDraft = !this.state.record && review.reviews?.length;
    const submission = structuredClone(
      preserveTabDraft ? this.sources[0].submission : response.submission ?? {}
    );
    for (const [id, sourceId] of this.selections) {
      const source = this.sources.find(
        (candidate) => candidate.id === sourceId
      );
      if (!source || !compatibleField(
        source.schema?.find((field) => field.id === id),
        response.schema?.find((field) => field.id === id)
      ))
        continue;
      if (Object.hasOwn(source.submission, id))
        submission[id] = structuredClone(source.submission[id]);
      else delete submission[id];
    }
    const currentIds = new Set(
      (response.schema ?? []).map((field) => field.id)
    );
    return Object.fromEntries(
      Object.entries(submission).filter(([id]) => currentIds.has(id))
    );
  }
  _refinement(body) {
    const review = this.state.response?.form_state;
    const url = review?.refine_url;
    if (!url || this.state.record || !review.reviews?.length) return;
    const section = body.appendChild(document.createElement("section"));
    section.className = "space-y-2";
    const label = section.appendChild(document.createElement("label"));
    label.className = "block text-sm font-semibold";
    label.append("Revise these values");
    const prompt = label.appendChild(document.createElement("textarea"));
    prompt.setAttribute("aria-label", "Revise these values with AI");
    prompt.className = "mt-2 block w-full rounded-md border border-base-light p-2 text-sm";
    prompt.placeholder = "Describe what to add, correct, or reorganize\u2026";
    const reviseAction = buttons.active({
      type: "button",
      icon: "generate",
      text: "Revise suggestions",
      processingText: "Revising suggestions\u2026",
      style: `${STYLES.button.submit} review-revise-action`
    });
    const button = section.appendChild(reviseAction.element);
    button.setAttribute("aria-label", "Revise suggestions with AI");
    const message = section.appendChild(document.createElement("p"));
    message.setAttribute("role", "status");
    message.className = "text-sm text-base-medium";
    message.textContent = "Suggestions stay private to you until you save the form. No file is required.";
    button.addEventListener("click", async () => {
      if (!prompt.value.trim()) return;
      if (!await this._isCurrent()) {
        message.textContent = "The form changed. Close and reopen Review before revising.";
        return;
      }
      reviseAction.activate();
      try {
        const operationId = this.widget.view?.operationId?.();
        if (!operationId)
          throw new Error("Could not identify the review operation");
        const data = new FormData();
        data.set("autofill-description", prompt.value);
        data.set(
          "form-revision",
          String(this.state.response?.form_state?.revision)
        );
        data.set("operation-id", operationId);
        data.set("submission", JSON.stringify(this._selectedSubmission()));
        const response = await request.post(
          url,
          data
        );
        if (!response?.ok) {
          message.textContent = response?.message || response?.error || "The form changed or suggestions could not be started. Your choices were kept.";
          return;
        }
        const status = typeof response.status === "object" ? response.status : void 0;
        this.widget.lockDeferredOperation({ ...response, status });
        renderReviewBar(this.widget, status);
        const manager = await this.widget.view?.ensureDeferredOperations?.();
        if (response.operation)
          manager?.track(response.operation, {
            node: this.widget.target,
            status,
            revision: response.revision
          });
        await this.remove();
      } catch {
        message.textContent = "Suggestions could not be started. Your choices were kept; please try again.";
      } finally {
        reviseAction.deactivate();
      }
    });
  }
}
class WholeFormRevisionModal extends Modal {
  constructor(reconciler, marker, widget) {
    super(
      reconciler.view,
      marker.querySelector("[data-role='edited-reset']")
    );
    this.reconciler = reconciler;
    this.marker = marker;
    this.widget = widget;
  }
  async init() {
    const modal = document.createElement("div");
    modal.id = "modal";
    modal.className = STYLES.modal.wrapper;
    modal.dataset.kind = this.widget.kind || this.widget.component?.kind || this.reconciler.view.kind || "default";
    const content = modal.appendChild(document.createElement("div"));
    content.id = "modal-content";
    content.className = `${STYLES.modal.content} w-full sm:max-w-lg`;
    const header = content.appendChild(document.createElement("header"));
    header.className = STYLES.modal.header;
    const title = header.appendChild(document.createElement("h2"));
    title.className = "text-lg font-bold text-base-dark";
    title.textContent = "Choose form version";
    const close = header.appendChild(document.createElement("button"));
    close.type = "button";
    close.setAttribute("lp-control", "close");
    close.className = STYLES.button.close;
    close.textContent = "Close";
    const body = content.appendChild(document.createElement("div"));
    body.className = "space-y-4 p-4 sm:p-6";
    const copy = body.appendChild(document.createElement("p"));
    copy.className = "text-sm text-base-medium";
    copy.textContent = "This form cannot be compared field by field. Use the saved version or retry the complete queued version.";
    const actions = body.appendChild(document.createElement("div"));
    actions.className = "flex flex-col-reverse gap-2 sm:flex-row sm:justify-end";
    const retry = actions.appendChild(document.createElement("button"));
    retry.type = "button";
    retry.className = STYLES.button.cancel;
    retry.textContent = "Retry queued version";
    const saved = actions.appendChild(document.createElement("button"));
    saved.type = "button";
    saved.className = STYLES.button.submit;
    saved.textContent = "Use saved version";
    retry.addEventListener("click", async () => {
      await this.reconciler.resolveRevision(this.marker, "local");
      await this.remove();
    });
    saved.addEventListener("click", async () => {
      await this.reconciler.resolveRevision(this.marker, "server");
      await this.remove();
    });
    await super.attach(modal, this.widget.component);
    saved.focus();
  }
}

const ACTION_LABELS = {
  reset: "Reset form",
  reload: "Reload page",
  review: "Review values",
  "whole-review": "Review versions",
  apply: "Continue",
  dismiss: "Dismiss"
};
class EditReconciler {
  constructor(view, {
    recordMarkerRevision = () => {
    },
    ownedDeferredCompletion = () => null,
    forgetDeferredCompletion = () => {
    }
  } = {}) {
    this.view = view;
    this.recordMarkerRevision = recordMarkerRevision;
    this.ownedDeferredCompletion = ownedDeferredCompletion;
    this.forgetDeferredCompletion = forgetDeferredCompletion;
  }
  _state(marker) {
    marker._lp_edited_state ??= {
      mode: "reset",
      response: null,
      fingerprint: null,
      modified: null,
      record: null,
      remoteSnapshot: null,
      schemaChanged: false,
      submissionChoice: false,
      token: null,
      probePromise: null,
      probeRevision: null,
      pendingProbe: null,
      conflictPromise: null
    };
    return marker._lp_edited_state;
  }
  async _prepareRevision(widget, response) {
    if (widget.prepareRevision) return await widget.prepareRevision(response);
    return () => {
      const result = widget.applyRevision(response);
      if (typeof result?.then === "function") void result.catch(captureError);
    };
  }
  async _prepareLocalRevision(widget, response, options) {
    if (widget.prepareLocalRevision) {
      return await widget.prepareLocalRevision(response, options);
    }
    return () => {
      const result = widget.applyLocalRevision(response, options);
      if (typeof result?.then === "function") void result.catch(captureError);
    };
  }
  _setAction(marker, mode, message = null) {
    const state = this._state(marker);
    state.mode = mode;
    const button = marker.querySelector(
      "[data-role='edited-reset']"
    );
    if (button && !button.dataset?.reviewPending)
      button.textContent = ACTION_LABELS[mode] ?? "Review update";
    const copy = marker.querySelector("[data-role='edited-message']");
    if (copy && message) copy.textContent = message;
    if (button) button.hidden = false;
  }
  _hide(marker) {
    if (!marker) return;
    marker.dataset.visible = "false";
    const state = this._state(marker);
    state.response = null;
    state.fingerprint = null;
    state.modified = null;
    state.record = null;
    state.remoteSnapshot = null;
    state.schemaChanged = false;
    state.submissionChoice = false;
    this._setAction(marker, "reset");
    const widget = marker.closest?.("form[data-widget]")?._lp_widget;
    if (widget?.target?.dataset?.formState) renderReviewBar(widget);
  }
  _show(marker) {
    const wasVisible = marker.dataset.visible === "true";
    marker.dataset.visible = "true";
    if (!wasVisible) this.view.addFlash?.(marker);
  }
  fallback(marker, error = null) {
    const state = this._state(marker);
    state.response = null;
    this._setAction(marker, "reload");
    this._show(marker);
    if (error) captureError(error, marker);
  }
  _rendererCapable(widget, response) {
    const objectSubmission = (submission) => Boolean(submission) && typeof submission === "object" && !Array.isArray(submission);
    return Boolean(
      widget.form?.renderer && Array.isArray(widget.schema) && widget.schema.length && objectSubmission(widget.submission) && Array.isArray(response.schema) && response.schema.length && objectSubmission(response.submission)
    );
  }
  _rendererValuesDiffer(response, localResponse) {
    const saved = response.submission ?? {};
    const local = localResponse.submission ?? {};
    return (response.schema ?? []).some(
      (field) => field?.id && !areEqual(local[field.id] ?? null, saved[field.id] ?? null)
    );
  }
  _storeRevision(marker, response, {
    fingerprint,
    modified,
    record,
    remoteSnapshot,
    schemaChanged,
    submissionChoice
  }) {
    const next = this._state(marker);
    next.response = response;
    next.fingerprint = fingerprint;
    next.modified = modified;
    next.record = record;
    next.remoteSnapshot = remoteSnapshot;
    next.schemaChanged = schemaChanged;
    next.submissionChoice = submissionChoice;
    return next;
  }
  async _stageRevision(marker, widget, response, {
    fingerprint = null,
    modified = null,
    record: incomingRecord = null
  } = {}) {
    const state = this._state(marker);
    const record = incomingRecord ?? state.record;
    if (response.form_state) {
      const operation = currentReviewOperation(
        widget,
        response.form_state.operation
      );
      widget.reviewState = {
        ...response.form_state,
        operation,
        revision: widget.reviewState?.revision ?? response.form_state.revision
      };
      if (operation?.key) {
        widget.lockDeferredOperation?.({
          operation: operation.key,
          revision: operation.revision,
          scope: operation.scope,
          blocks_edit: operation.blocks_edit,
          status: operation
        });
        const operations = this.view.DeferredOperations || await this.view.ensureDeferredOperations?.();
        operations?.track(operation.key, {
          node: widget.target,
          revision: operation.revision,
          status: operation
        });
      }
      renderReviewBar(widget);
    }
    const explicitReview = Boolean(
      response.form_state?.reviews?.some(
        (review) => !widget._reviewedOperations?.has(review.operation)
      )
    );
    const token = state.token;
    const anchor = marker.closest?.("[lp-entity]");
    const baselineFingerprint = record?.fingerprint ?? anchor?.dataset?.fingerprint ?? null;
    const baselineModified = record?.modified ?? anchor?.dataset?.modified ?? null;
    const fingerprintChanged = Boolean(
      fingerprint && baselineFingerprint && baselineFingerprint !== fingerprint
    );
    const schemaOnlyRevision = Boolean(
      fingerprintChanged && modified && baselineModified && baselineModified === modified
    );
    const observedSchemaChanged = !areEqual(
      widget.schema ?? null,
      response.schema ?? null
    );
    const schemaChanged = observedSchemaChanged || schemaOnlyRevision;
    if (observedSchemaChanged) {
      widget._reviewedOperations?.clear();
      widget._usedAutofillOperations?.clear();
    }
    const remotePreview = await loadRevisionPreview(widget, response);
    if (token && state.token !== token) {
      remotePreview?.destroy?.();
      return;
    }
    if (!remotePreview || !widget.revisionCanReset(remotePreview)) {
      remotePreview?.destroy?.();
      this.fallback(marker);
      return;
    }
    const remoteSnapshot = remotePreview.revisionSnapshot();
    remotePreview.destroy?.();
    const queued = Boolean(record || widget.form?._queued === true);
    const unsaved = widget.unsavedState === true;
    const focused = Boolean(
      typeof document !== "undefined" && widget.target?.contains?.(document.activeElement)
    );
    const active = widget.component?.active === widget && widget.visible === true;
    const ownedDeferredCompletion = !unsaved && !queued && widget.reviewState?.operation?.type !== "autofill" ? this.ownedDeferredCompletion(marker, widget) : null;
    if (!queued && !explicitReview && !ownedDeferredCompletion && !schemaChanged && remoteSnapshot === widget.revisionBaseline) {
      this._hide(marker);
      return;
    }
    const protectedRevision = explicitReview || unsaved || queued || !schemaChanged && !ownedDeferredCompletion && (active || focused);
    if (!protectedRevision) {
      const commitRevision = await this._prepareRevision(widget, response);
      await withTransition(
        () => {
          commitRevision();
          this._hide(
            widget.target?.querySelector(
              "[lp-edited-marker]"
            ) ?? marker
          );
        },
        { label: "edit-reconcile:apply-remote" }
      );
      return;
    }
    const current = widget.revisionSnapshot();
    const rendererCapable = this._rendererCapable(widget, response);
    const local = record ? widget.buildLocalRevision(response, record) : widget.buildLocalRevision(response);
    const localPreview = await loadRevisionPreview(widget, local.response);
    if (token && state.token !== token) {
      localPreview?.destroy?.();
      return;
    }
    if (!localPreview || !widget.revisionCanReset(localPreview)) {
      localPreview?.destroy?.();
      this.fallback(marker);
      return;
    }
    const localSnapshot = localPreview.revisionSnapshot();
    localPreview.destroy?.();
    const rendererValuesDiffer = rendererCapable && this._rendererValuesDiffer(response, local.response);
    const incompatible = incompatibleSchema(
      record?.renderer_schema ?? widget.schema ?? [],
      response.schema ?? []
    );
    const requiresReview = explicitReview || (unsaved || queued) && incompatible;
    if (!requiresReview && (localSnapshot === remoteSnapshot || !record && current === remoteSnapshot)) {
      if (record) await this.view.offlineQueue?.cancel(record.id);
      const commitRevision = await this._prepareRevision(widget, response);
      await withTransition(
        () => {
          commitRevision();
          this._hide(
            widget.target?.querySelector(
              "[lp-edited-marker]"
            ) ?? marker
          );
        },
        { label: "edit-reconcile:accept-matching" }
      );
      return;
    }
    if (explicitReview && rendererCapable || rendererValuesDiffer && !schemaOnlyRevision || rendererCapable && incompatible) {
      this._storeRevision(marker, response, {
        fingerprint,
        modified,
        record,
        remoteSnapshot,
        schemaChanged,
        submissionChoice: true
      });
      this._setAction(
        marker,
        "review",
        schemaChanged ? "The form fields and saved values changed elsewhere." : "Another user has edited this form."
      );
      this._show(marker);
      if (widget.target?.dataset?.formState) renderReviewBar(widget);
      return;
    }
    if (rendererCapable && schemaChanged) {
      const commitRevision = await this._prepareLocalRevision(
        widget,
        response,
        {
          remoteSnapshot
        }
      );
      await withTransition(
        () => {
          commitRevision();
          marker = widget.target.querySelector("[lp-edited-marker]") ?? marker;
          this._hide(marker);
        },
        { label: "edit-reconcile:rebase-schema" }
      );
      if (record) {
        const rebased = await this.view.offlineQueue?.rebaseSubmit(
          record,
          widget,
          { fingerprint, modified }
        );
        if (rebased) await this.view.offlineQueue?.replay();
      }
      return;
    }
    if (rendererCapable && remoteSnapshot === widget.revisionBaseline) {
      const commitRevision = await this._prepareLocalRevision(
        widget,
        response,
        {
          remoteSnapshot
        }
      );
      await withTransition(
        () => {
          commitRevision();
          marker = widget.target.querySelector("[lp-edited-marker]") ?? marker;
          this._hide(marker);
        },
        { label: "edit-reconcile:rebase-values" }
      );
      if (record) {
        const rebased = await this.view.offlineQueue?.rebaseSubmit(
          record,
          widget,
          { fingerprint, modified }
        );
        if (rebased) await this.view.offlineQueue?.replay();
      }
      return;
    }
    this._storeRevision(marker, response, {
      fingerprint,
      modified,
      record,
      remoteSnapshot,
      schemaChanged,
      submissionChoice: queued
    });
    this._setAction(
      marker,
      queued ? "whole-review" : "reset",
      queued ? "The saved form changed while this update was queued." : "This form changed elsewhere. Reset it to load the saved version."
    );
    this._show(marker);
  }
  async _installUninitialized(marker, response) {
    const form = marker.closest("form[data-widget]");
    const name = form?.dataset.widget;
    const replacement = name && response.html ? response.html.querySelector(`[data-widget='${name}']`) : null;
    if (!form || !replacement) return false;
    const visible = form.dataset.visible;
    const fresh = replacement.cloneNode(true);
    if (visible !== void 0) fresh.dataset.visible = visible;
    await withTransition(() => form.replaceWith(fresh));
    return true;
  }
  _sameProbeRevision(left, right) {
    return Boolean(
      left && right && left.fingerprint === right.fingerprint && left.modified === right.modified
    );
  }
  probe(marker, fingerprint, modified = null) {
    const state = this._state(marker);
    const requested = { fingerprint, modified };
    if (state.conflictPromise) {
      state.pendingProbe = requested;
      return state.conflictPromise.then(() => {
        const pending = state.pendingProbe;
        if (!pending) return;
        state.pendingProbe = null;
        return this.probe(marker, pending.fingerprint, pending.modified);
      });
    }
    if (state.probePromise && this._sameProbeRevision(state.probeRevision, requested)) {
      return state.probePromise;
    }
    if (!this._sameProbeRevision(state.pendingProbe, requested)) {
      state.pendingProbe = requested;
    }
    if (state.probePromise) return state.probePromise;
    const drain = async () => {
      let processed = null;
      while (state.pendingProbe) {
        const next = state.pendingProbe;
        state.pendingProbe = null;
        if (this._sameProbeRevision(processed, next)) continue;
        state.probeRevision = next;
        await this._runProbe(marker, next.fingerprint, next.modified);
        processed = next;
      }
    };
    const promise = drain().finally(() => {
      if (state.probePromise !== promise) return;
      state.probePromise = null;
      state.probeRevision = null;
    });
    state.probePromise = promise;
    return promise;
  }
  async _runProbe(marker, fingerprint, modified = null) {
    if (!marker?.isConnected && marker?.isConnected !== void 0) return;
    const state = this._state(marker);
    const token = {};
    state.token = token;
    const route = marker.dataset.editedRoute;
    if (!route) {
      this.fallback(
        marker,
        new Error("Edited marker has no replacement route")
      );
      return;
    }
    try {
      const response = await request.get(route, null, {
        acknowledgeEntities: false,
        replaceErrorPage: false
      });
      if (state.token !== token) return;
      const form = marker.closest("form[data-widget]");
      const widget = form?._lp_widget;
      const completion = this.ownedDeferredCompletion(marker, widget);
      if (response?.unchanged) {
        if (!state.response) this._hide(marker);
        this.recordMarkerRevision(marker, { fingerprint, modified });
        this.forgetDeferredCompletion(completion);
        return;
      }
      if (!response?.ok) {
        this.fallback(marker);
        this.forgetDeferredCompletion(completion);
        return;
      }
      if (!widget) {
        if (await this._installUninitialized(marker, response)) return;
        this.fallback(marker, new Error("Replacement response has no form"));
        return;
      }
      if (widget.revisionBaseline === null) widget.commitRevisionBaseline();
      await this._stageRevision(marker, widget, response, {
        fingerprint,
        modified
      });
      this.recordMarkerRevision(marker, { fingerprint, modified });
      this.forgetDeferredCompletion(completion);
    } catch (error) {
      if (state.token === token) this.fallback(marker, error);
    }
  }
  async stageConflict(widget, { record, response } = {}) {
    const marker = widget?.target?.querySelector?.("[lp-edited-marker]");
    if (!marker || !response) return false;
    const revision = (response.entities || []).find(
      (entity) => entity.key === (record?.target_key ?? widget.key)
    );
    const state = this._state(marker);
    const reconcile = (async () => {
      if (state.probePromise) await state.probePromise;
      state.token = {};
      if (widget.revisionBaseline === null) widget.commitRevisionBaseline();
      await this._stageRevision(marker, widget, response, {
        fingerprint: revision?.fingerprint ?? null,
        modified: revision?.modified ?? null,
        record
      });
      delete widget._offlineConflict;
      return true;
    })();
    state.conflictPromise = reconcile;
    try {
      return await reconcile;
    } catch (error) {
      this.fallback(marker, error);
      return false;
    } finally {
      if (state.conflictPromise === reconcile) {
        state.conflictPromise = null;
      }
    }
  }
  async openConflictReview(widget, { blockedAction = null } = {}) {
    const marker = widget?.target?.querySelector?.("[lp-edited-marker]");
    if (!marker || !["review", "whole-review"].includes(this._state(marker).mode))
      return false;
    const button = marker.querySelector(
      "[data-role='edited-reset']"
    );
    if (!button || button.disabled) return false;
    await this._activateAction(marker, button, {
      refresh: true,
      blockedAction
    });
    return true;
  }
  async resolveRevision(marker, choice) {
    const state = this._state(marker);
    const widget = marker.closest("form[data-widget]")?._lp_widget;
    if (!widget || !state.response) {
      this.fallback(marker);
      return false;
    }
    const fieldChoice = choice && typeof choice === "object" ? choice : null;
    const fieldSelection = fieldChoice ? fieldChoice.selections ?? {} : null;
    const localSelected = fieldSelection ? Object.values(fieldSelection).some((source) => source !== "server") || !!fieldChoice?.selectedSubmission && !state.record : choice === "local";
    if (!localSelected) {
      if (state.record) await this.view.offlineQueue?.cancel(state.record.id);
      const commitRevision = await this._prepareRevision(
        widget,
        state.response
      );
      await withTransition(() => commitRevision(), {
        label: "edit-reconcile:resolve-server"
      });
    } else {
      let selectedSubmission = fieldChoice?.selectedSubmission;
      if (fieldSelection && selectedSubmission === void 0) {
        selectedSubmission = structuredClone(state.response.submission ?? {});
        const localSubmission = fieldChoice?.localResponse?.submission ?? {};
        for (const [id, source] of Object.entries(fieldSelection)) {
          if (source !== "local") continue;
          if (Object.hasOwn(localSubmission, id)) {
            selectedSubmission[id] = structuredClone(localSubmission[id]);
          } else {
            delete selectedSubmission[id];
          }
        }
      }
      const commitRevision = await this._prepareLocalRevision(
        widget,
        state.response,
        {
          remoteSnapshot: state.remoteSnapshot,
          markUnsaved: !state.record,
          selectedSubmission
        }
      );
      await withTransition(() => commitRevision(), {
        label: "edit-reconcile:resolve-local"
      });
      if (state.record) {
        const rebased = await this.view.offlineQueue?.rebaseSubmit(
          state.record,
          widget,
          {
            fingerprint: state.fingerprint,
            modified: state.modified
          }
        );
        if (rebased) await this.view.offlineQueue?.replay();
      }
    }
    const currentMarker = widget.target?.querySelector("[lp-edited-marker]") ?? marker;
    if (!state.record && state.response.form_state?.reviews?.length) {
      widget._reviewedOperations ??= /* @__PURE__ */ new Set();
      widget._usedAutofillOperations ??= /* @__PURE__ */ new Set();
      for (const review of state.response.form_state?.reviews ?? [])
        widget._reviewedOperations.add(review.operation);
      for (const source of Object.values(fieldSelection ?? {})) {
        if (source.startsWith("ai:"))
          widget._usedAutofillOperations.add(source.slice(3));
      }
      widget.markUnsavedState?.();
    }
    this._hide(currentMarker);
    return true;
  }
  async handleClick(event) {
    const button = event.target?.closest?.("[data-role='edited-reset']");
    if (!button) return;
    const marker = button.closest("[lp-edited-marker]");
    if (!marker) return;
    await this._activateAction(marker, button);
  }
  async _activateAction(marker, button, {
    refresh = false,
    blockedAction = null
  } = {}) {
    const state = marker ? this._state(marker) : null;
    if (!state) return;
    if (state.mode === "reload") {
      window.location.reload();
      return;
    }
    if (state.mode === "dismiss") {
      this._hide(marker);
      return;
    }
    if (button.disabled) return;
    const widget = marker.closest("form[data-widget]")?._lp_widget;
    const reviewPending = ["review", "whole-review"].includes(state.mode);
    const originalLabel = button.textContent;
    button.disabled = true;
    if (reviewPending) {
      button.dataset.reviewPending = "true";
      button.textContent = "Opening review\u2026";
      button.setAttribute("aria-busy", "true");
    }
    try {
      await state.probePromise;
      await state.conflictPromise;
      if ((refresh || widget?.target?.dataset?.formState) && !state.record) {
        const route = marker.dataset.editedRoute;
        const response = route ? await request.get(route, null, {
          acknowledgeEntities: false,
          replaceErrorPage: false
        }) : null;
        if (!response?.ok)
          throw new Error(
            "Could not load the latest form values. Please try Review again."
          );
        if (!response.unchanged) {
          if (!widget) {
            this.fallback(marker);
            return;
          }
          state.token = {};
          await this._stageRevision(marker, widget, response);
        }
      }
      if (!state.response && marker.dataset.visible === "false") return;
      if (!widget || !state.response) {
        this.fallback(marker);
        return;
      }
      if (state.mode === "review") {
        const modal = new FormRevisionModal(this, marker, widget, state, {
          blockedAction
        });
        const shown = await modal.init();
        if (!shown && state.record) {
          await new WholeFormRevisionModal(this, marker, widget).init();
        } else if (!shown) {
          this._setAction(
            marker,
            "reset",
            "This form changed elsewhere. Reset it to load the saved version."
          );
        }
      } else if (state.mode === "whole-review") {
        await new WholeFormRevisionModal(this, marker, widget).init();
      } else if (state.mode === "apply" && state.record) {
        await this.resolveRevision(marker, "local");
      } else {
        await this.resolveRevision(marker, "server");
      }
    } catch (error) {
      this.fallback(
        widget?.target?.querySelector("[lp-edited-marker]") ?? marker,
        error
      );
    } finally {
      if (reviewPending) {
        delete button.dataset.reviewPending;
        button.removeAttribute("aria-busy");
        button.textContent = ACTION_LABELS[state.mode] ?? originalLabel;
      }
      button.disabled = false;
    }
  }
}

class EditWatcher {
  constructor(view) {
    this.view = view;
    this._unsubscribers = /* @__PURE__ */ new Map();
    this._markerRevisions = /* @__PURE__ */ new WeakMap();
    this._latestRevisions = /* @__PURE__ */ new Map();
    this._deferredCompletions = /* @__PURE__ */ new Map();
    this._destroyed = false;
    this._reconciler = new EditReconciler(view, {
      recordMarkerRevision: (marker, revision) => {
        this._markerRevisions.set(marker, revision);
      },
      ownedDeferredCompletion: (marker, widget) => this._ownedDeferredCompletion(marker, widget),
      forgetDeferredCompletion: (completion) => this._forgetDeferredCompletion(completion)
    });
    this._click = (event) => this._reconciler.handleClick(event);
    this._entityUpdated = this._entityUpdated.bind(this);
    this.check = this.check.bind(this);
  }
  init() {
    this.view.elt.addEventListener("click", this._click);
    window.addEventListener("entity-updated", this._entityUpdated);
    if (this.view.key && this.view.elt.dataset.fingerprint) {
      this._latestRevisions.set(this.view.key, {
        fingerprint: this.view.elt.dataset.fingerprint,
        modified: this.view.elt.dataset.modified ?? null
      });
    }
    for (const component of Object.values(this.view.components ?? {})) {
      for (const widget of Object.values(component.widgets ?? {})) {
        if (widget && typeof widget === "object" && "_offlineConflict" in widget && widget._offlineConflict) {
          const form = widget;
          void this.stageConflict(form, form._offlineConflict);
        }
      }
    }
    this.resume();
  }
  get entities() {
    return this._entities();
  }
  _componentVisible(component) {
    if (component?.visible !== true) return false;
    let ancestor = component.elt?.parentElement?.closest?.("[lp-component]");
    while (ancestor) {
      if (ancestor.dataset.visible === "false") return false;
      ancestor = ancestor.parentElement?.closest?.("[lp-component]");
    }
    return true;
  }
  _markerActive(marker) {
    const widget = marker.closest?.("form[data-widget]")?._lp_widget;
    return Boolean(
      widget && widget.component?.active === widget && this._componentVisible(widget.component) && widget.visible === true
    );
  }
  _markerRevision(marker, anchor) {
    let revision = this._markerRevisions.get(marker);
    if (!revision) {
      revision = {
        fingerprint: anchor.dataset.fingerprint ?? null,
        modified: anchor.dataset.modified ?? null
      };
      this._markerRevisions.set(marker, revision);
    }
    return revision;
  }
  _entities({ activeOnly = true } = {}) {
    const entities = /* @__PURE__ */ new Map();
    const markers = this.view.elt.querySelectorAll("[lp-edited-marker]");
    for (const marker of markers) {
      const anchor = marker.closest("[lp-entity]");
      const key = anchor?.dataset.key;
      const revision = anchor ? this._markerRevision(marker, anchor) : null;
      const fingerprint = revision?.fingerprint;
      if (!anchor || !key || !revision || !fingerprint) {
        captureError(
          new Error("Edited marker has no fingerprinted entity anchor"),
          marker
        );
        continue;
      }
      if (activeOnly && !this._markerActive(marker)) continue;
      const entity = entities.get(key) ?? {
        key,
        fingerprint,
        modified: revision.modified,
        anchors: /* @__PURE__ */ new Set(),
        markers: /* @__PURE__ */ new Set()
      };
      entity.anchors.add(anchor);
      entity.markers.add(marker);
      entities.set(key, entity);
    }
    return entities;
  }
  expectDeferredCompletion(key, operation) {
    if (!key || !operation) return false;
    const operations = this._deferredCompletions.get(key) ?? /* @__PURE__ */ new Set();
    operations.add(operation);
    this._deferredCompletions.set(key, operations);
    return true;
  }
  _ownedDeferredCompletion(marker, widget) {
    const key = marker.closest?.("[lp-entity]")?.dataset?.key;
    const operation = widget?._deferredOperation;
    if (!key || !operation) return null;
    if (this._deferredCompletions.get(key)?.has(operation)) {
      return { key, operation };
    }
    for (const [ownerKey, operations] of this._deferredCompletions) {
      if (operations.has(operation)) return { key: ownerKey, operation };
    }
    return null;
  }
  _forgetDeferredCompletion(completion) {
    if (!completion) return;
    const operations = this._deferredCompletions.get(completion.key);
    operations?.delete(completion.operation);
    if (!operations?.size) this._deferredCompletions.delete(completion.key);
  }
  async _probeEntity(key, fingerprint, modified = null) {
    const entity = this.entities.get(key);
    if (!entity) return;
    const revision = { fingerprint, modified };
    const stale = Array.from(entity.markers).filter((marker) => {
      const current = this._markerRevisions.get(marker);
      return current?.fingerprint !== fingerprint || Boolean(modified) && current?.modified !== modified || Boolean(
        this._ownedDeferredCompletion(
          marker,
          marker.closest?.("form[data-widget]")?._lp_widget
        )
      );
    });
    await Promise.all(
      stale.map(
        (marker) => this._reconciler.probe(marker, fingerprint, modified)
      )
    );
    const latest = this._latestRevisions.get(key);
    const anchorRevision = latest?.fingerprint ? latest : revision;
    for (const anchor of entity.anchors) {
      anchor.dataset.fingerprint = anchorRevision.fingerprint;
      if (anchorRevision.modified) {
        anchor.dataset.modified = anchorRevision.modified;
      }
    }
  }
  async receiveEntityResult(key, result) {
    if (!key || !result) return;
    if (result.status === "unavailable") {
      for (const marker of this.entities.get(key)?.markers ?? []) {
        this._reconciler.fallback(marker);
      }
      return;
    }
    if (result.status === "unchanged" && this._deferredCompletions.size) {
      const revision2 = this._latestRevisions.get(key) ?? {
        fingerprint: result.revision ?? null,
        modified: null
      };
      if (revision2.fingerprint) {
        await this._probeEntity(key, revision2.fingerprint, revision2.modified);
      }
      return;
    }
    if (result.status !== "changed" || !result.payload?.fingerprint) return;
    const revision = {
      fingerprint: result.payload.fingerprint,
      modified: result.payload.modified ?? null
    };
    this._latestRevisions.set(key, revision);
    await this._probeEntity(key, revision.fingerprint, revision.modified);
  }
  async _lockEntity(entity, descriptor) {
    if (!entity || !descriptor?.operation) return;
    const forms = /* @__PURE__ */ new Set();
    for (const marker of entity.markers ?? []) {
      const form = marker.closest("form[data-widget]");
      if (form) forms.add(form);
    }
    for (const anchor of entity.anchors ?? []) {
      for (const form of anchor.querySelectorAll?.(
        "form[data-widget='PageInfo'], form[data-widget='TaskForm']"
      ) ?? []) {
        forms.add(form);
      }
    }
    const tracked = [];
    for (const form of forms) {
      if (form.dataset.deferredLock !== "form" && !["PageInfo", "TaskForm"].includes(form.dataset.widget ?? ""))
        continue;
      const widget = form._lp_widget;
      if (widget?._deferredOperation !== descriptor.operation) {
        widget?.lockDeferredOperation?.(descriptor);
      }
      if (!widget) {
        form.dataset.operation = descriptor.operation;
        form.dataset.operationRevision = String(descriptor.revision ?? 0);
        form.dataset.operationScope = descriptor.scope || "";
        if (descriptor.blocks_edit === true || descriptor.scope === "form-change")
          form.dataset.deferredLock = "form";
        else delete form.dataset.deferredLock;
      }
      tracked.push({
        revision: descriptor.revision ?? 0,
        node: widget?.target ?? form
      });
    }
    if (!tracked.length) return;
    const operations = this.view.DeferredOperations || await this.view.ensureDeferredOperations?.();
    for (const options of tracked) {
      operations?.track(descriptor.operation, options);
    }
  }
  _syncSubscriptions() {
    const mounted = this.entities;
    const active = /* @__PURE__ */ new Set();
    for (const entity of mounted.values()) {
      const entityId = `edit:${entity.key}`;
      const lockId = `lock:${entity.key}`;
      active.add(lockId);
      if (entity.key !== this.view.key) active.add(entityId);
      if (entity.key !== this.view.key && !this._unsubscribers.has(entityId)) {
        this._unsubscribers.set(
          entityId,
          this.view.PollingCoordinator?.subscribe(
            {
              id: entityId,
              type: "entity",
              key: entity.key,
              revision: entity.fingerprint
            },
            {
              mode: "periodic",
              initial: "scheduled",
              onResult: (result) => this.receiveEntityResult(entity.key, result)
            }
          ) ?? (() => {
          })
        );
      }
      if (!this._unsubscribers.has(lockId)) {
        this._unsubscribers.set(
          lockId,
          this.view.PollingCoordinator?.subscribe(
            {
              id: lockId,
              type: "form-lock",
              key: entity.key,
              revision: "unlocked"
            },
            {
              mode: "periodic",
              initial: "scheduled",
              onResult: async (result) => {
                if (result.status !== "changed") return;
                if (result.payload?.locked) {
                  await this._lockEntity(
                    this.entities.get(entity.key),
                    result.payload
                  );
                } else if (Array.from(this.entities.get(entity.key)?.markers ?? []).some(
                  (marker) => marker.closest?.("form[data-widget]")?.hasAttribute("data-deferred-lock")
                )) {
                  await this.view.reconcileChange?.({
                    type: "poll",
                    key: entity.key
                  });
                }
              }
            }
          ) ?? (() => {
          })
        );
      }
    }
    for (const [id, unsubscribe] of this._unsubscribers) {
      if (active.has(id)) continue;
      unsubscribe();
      this._unsubscribers.delete(id);
    }
    return mounted;
  }
  async reconcileSubscriptions() {
    const mounted = this._syncSubscriptions();
    await Promise.all(
      Array.from(mounted.values(), async (entity) => {
        const latest = this._latestRevisions.get(entity.key);
        if (!latest) return;
        await this._probeEntity(
          entity.key,
          latest.fingerprint,
          latest.modified
        );
      })
    );
    return mounted;
  }
  check(keys = null, options = {}) {
    const mounted = this._syncSubscriptions();
    const requested = keys === null ? [...mounted.keys()] : Array.from(keys);
    const ids = requested.flatMap((key) => [
      key === this.view.key ? `view:entity:${key}` : `edit:${key}`,
      `lock:${key}`
    ]);
    return this.view.PollingCoordinator?.trigger(ids, options);
  }
  enqueue(keys = null) {
    const mounted = this._syncSubscriptions();
    const requested = keys === null ? [...mounted.keys()] : Array.from(keys);
    const ids = requested.flatMap((key) => [
      key === this.view.key ? `view:entity:${key}` : `edit:${key}`,
      `lock:${key}`
    ]);
    this.view.PollingCoordinator?.enqueue(ids);
  }
  invalidate(keys) {
    const requested = keys ? (Array.isArray(keys) ? keys : [keys]).filter(Boolean) : null;
    return this.check(requested, { fresh: true });
  }
  acknowledge({
    key,
    fingerprint,
    modified = null
  } = {}) {
    if (!key || !fingerprint) return;
    this._latestRevisions.set(key, { fingerprint, modified });
    if (this.view.key === key) {
      this.view.elt.dataset.fingerprint = fingerprint;
      if (modified) this.view.elt.dataset.modified = modified;
    }
    this.view.PollingCoordinator?.acknowledge(`edit:${key}`, fingerprint);
    this.view.PollingCoordinator?.acknowledge(
      `view:entity:${key}`,
      fingerprint
    );
    const entity = this.entities.get(key);
    if (!entity) return;
    for (const anchor of entity.anchors) {
      anchor.dataset.fingerprint = fingerprint;
      if (modified) anchor.dataset.modified = modified;
    }
    for (const marker of entity.markers) {
      this._markerRevisions.set(marker, { fingerprint, modified });
    }
  }
  pause() {
  }
  resume() {
    if (this._destroyed || !this.view.online || this.view.hidden) return;
    return this.reconcileSubscriptions();
  }
  stageConflict(widget, conflict = {}) {
    return this._reconciler.stageConflict(widget, conflict);
  }
  openConflictReview(widget, options = {}) {
    return this._reconciler.openConflictReview(widget, options);
  }
  resolveRevision(marker, choice) {
    return this._reconciler.resolveRevision(marker, choice);
  }
  _entityUpdated(event) {
    this.acknowledge(event.detail);
  }
  destroy() {
    this._destroyed = true;
    for (const unsubscribe of this._unsubscribers.values()) unsubscribe();
    this._unsubscribers.clear();
    this._deferredCompletions.clear();
    this.view.elt.removeEventListener("click", this._click);
    window.removeEventListener("entity-updated", this._entityUpdated);
  }
}

export { EditWatcher };
