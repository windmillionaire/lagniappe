/*! Third-party licenses: /third-party-licenses.txt */
import { a as loadRevisionPreview } from './core-foundation.js?v=b4b0f2eb';
import { STYLES } from './styles.js?v=b4b0f2eb';
import { Modal } from './modal.js?v=b4b0f2eb';
import { j as areEqual, c as captureError, w as withTransition, r as request } from './foundation.js?v=b4b0f2eb';
import './connectivity.js?v=b4b0f2eb';

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010d_form_state_split.py::test_form_submission_reconciliation_uses_latest_schema
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_offline_submission_conflict_keeps_queue_until_choice
 * @features forms
 * @dimensions readonly-preview submission-choice latest-schema queued-conflict
 */
class FormRevisionModal extends Modal {
	constructor(reconciler, marker, widget, state) {
		super(reconciler.view, marker.querySelector("[data-role='edited-reset']"));
		this.reconciler = reconciler;
		this.marker = marker;
		this.widget = widget;
		this.state = state;
		this.selections = new Map();
	}

	/**
	 * @testable false
	 * @covered-by src/script/shared/editRevisionModal.mjs::FormRevisionModal
	 * @reason private schema-summary copy is part of the reconciliation modal
	 */
	_schemaSummary() {
		const before = new Map(
			(this.widget.schema ?? []).map((field) => [field?.id, field]),
		);
		const after = new Map(
			(this.state.response?.schema ?? []).map((field) => [field?.id, field]),
		);
		const added = [...after.keys()].filter((id) => id && !before.has(id));
		const removed = [...before.keys()].filter((id) => id && !after.has(id));
		const changed = [...after.keys()].filter(
			(id) => id && before.has(id) && !areEqual(before.get(id), after.get(id)),
		);
		const parts = [];
		if (added.length) parts.push(`${added.length} added`);
		if (removed.length) parts.push(`${removed.length} removed`);
		if (changed.length) parts.push(`${changed.length} changed`);
		return parts.length ? `Schema update: ${parts.join(", ")}.` : null;
	}

	/**
	 * @testable false
	 * @covered-by src/script/shared/editRevisionModal.mjs::FormRevisionModal
	 * @reason private readonly value extraction is part of the reconciliation modal
	 */
	_value(element) {
		const rendered = element?.elt?.cloneNode(true);
		if (!rendered) {
			const empty = document.createElement("p");
			empty.className = "text-sm italic text-base-medium";
			empty.textContent = "Not provided";
			return empty;
		}

		const label = rendered.matches?.("[data-role='label']")
			? rendered
			: rendered.querySelector?.("[data-role='label']");
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
			...rendered.querySelectorAll("[data-visible]"),
		]) {
			node.dataset.visible = "true";
		}
		return rendered;
	}

	/**
	 * @testable false
	 * @covered-by src/script/shared/editRevisionModal.mjs::FormRevisionModal
	 * @reason private changed-field projection is part of the reconciliation modal
	 */
	async _differences(localResponse) {
		const [localPreview, savedPreview] = await Promise.all([
			loadRevisionPreview(this.widget, localResponse, { readonly: true }),
			loadRevisionPreview(this.widget, this.state.response, { readonly: true }),
		]);
		if (!localPreview || !savedPreview) {
			localPreview?.destroy?.();
			savedPreview?.destroy?.();
			throw new Error("Could not render form revision values");
		}

		try {
			const elements = (preview) =>
				new Map(
					Array.from(preview.form?.renderer?.elements?.values?.() ?? []).map(
						(element) => [element.schema?.id, element],
					),
				);
			const localElements = elements(localPreview);
			const savedElements = elements(savedPreview);
			const localSubmission = localResponse.submission ?? {};
			const savedSubmission = this.state.response.submission ?? {};

			return (this.state.response.schema ?? [])
				.filter(
					(field) =>
						field?.id &&
						!areEqual(
							localSubmission[field.id] ?? null,
							savedSubmission[field.id] ?? null,
						),
				)
				.map((field) => ({
					id: field.id,
					label: field.title || field.label || "Untitled field",
					local: this._value(localElements.get(field.id)),
					saved: this._value(savedElements.get(field.id)),
				}));
		} finally {
			localPreview.destroy?.();
			savedPreview.destroy?.();
		}
	}

	/**
	 * @testable false
	 * @covered-by src/script/shared/editRevisionModal.mjs::FormRevisionModal
	 * @reason private per-field choice composition is part of the reconciliation modal
	 */
	_choice(field, source, value) {
		const button = document.createElement("button");
		button.type = "button";
		button.setAttribute("role", "radio");
		button.setAttribute("aria-checked", (source === "server").toString());
		button.setAttribute(
			"aria-label",
			`${source === "server" ? "Saved" : this.state.record ? "Queued" : "Current"} value for ${field.label}`,
		);
		button.dataset.revisionSource = source;
		button.className =
			"min-w-0 rounded-md border border-base-light/50 bg-white p-3 text-left transition-colors hover:bg-base-bg aria-checked:bg-kind-bg aria-checked:outline-2 aria-checked:outline-kind-default";

		const heading = button.appendChild(document.createElement("span"));
		heading.className = "mb-2 block text-xs font-semibold text-base-medium";
		heading.textContent =
			source === "server"
				? "Saved value"
				: this.state.record
					? "Queued value"
					: "Value in this tab";
		button.appendChild(value);

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
		const local = this.widget.buildLocalRevision(this.state.response);
		const differences = await this._differences(local.response);
		if (!differences.length) return false;
		for (const field of differences) this.selections.set(field.id, "server");

		const modal = document.createElement("div");
		modal.id = "modal";
		modal.className = STYLES.modal.wrapper;
		modal.dataset.kind =
			this.widget.kind ||
			this.widget.component?.kind ||
			this.reconciler.view.kind ||
			"default";
		const content = modal.appendChild(document.createElement("div"));
		content.id = "modal-content";
		content.className = `${STYLES.modal.content} w-full sm:max-w-3xl`;

		const header = content.appendChild(document.createElement("header"));
		header.className = STYLES.modal.header;
		const title = header.appendChild(document.createElement("h2"));
		title.className = "text-lg font-bold text-base-dark";
		title.textContent = "Choose form values";
		const close = header.appendChild(document.createElement("button"));
		close.type = "button";
		close.setAttribute("lp-control", "close");
		close.className = STYLES.button.close;
		close.textContent = "Close";

		const body = content.appendChild(document.createElement("div"));
		body.className = "space-y-4 p-4 sm:p-6";
		const intro = body.appendChild(document.createElement("p"));
		intro.className = "text-sm text-base-medium";
		intro.textContent =
			"Choose a value for each changed field. Saved values are selected by default.";
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
			choices.setAttribute("role", "radiogroup");
			choices.setAttribute("aria-label", field.label);
			choices.className = "grid gap-2 sm:grid-cols-2";
			choices.append(
				this._choice(field, "local", field.local),
				this._choice(field, "server", field.saved),
			);
		}
		const actions = body.appendChild(document.createElement("div"));
		actions.className = "ml-auto flex w-fit";
		const update = actions.appendChild(document.createElement("button"));
		update.type = "button";
		update.className = STYLES.button.submit;
		update.textContent = "Update values";

		update.addEventListener("click", async () => {
			await this.reconciler.resolveRevision(this.marker, {
				localResponse: local.response,
				selections: Object.fromEntries(this.selections),
			});
			await this.remove();
		});

		await super.attach(modal, this.widget.component);
		update.focus();
		return true;
	}
}

/**
 * @testable false
 * @covered-by src/script/shared/editReconciler.mjs::EditReconciler
 * @reason private whole-form conflict UI is selected by capability-aware reconciliation state
 */
class WholeFormRevisionModal extends Modal {
	constructor(reconciler, marker, widget) {
		super(reconciler.view, marker.querySelector("[data-role='edited-reset']"));
		this.reconciler = reconciler;
		this.marker = marker;
		this.widget = widget;
	}

	async init() {
		const modal = document.createElement("div");
		modal.id = "modal";
		modal.className = STYLES.modal.wrapper;
		modal.dataset.kind =
			this.widget.kind ||
			this.widget.component?.kind ||
			this.reconciler.view.kind ||
			"default";
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
		copy.textContent =
			"This form cannot be compared field by field. Use the saved version or retry the complete queued version.";

		const actions = body.appendChild(document.createElement("div"));
		actions.className =
			"flex flex-col-reverse gap-2 sm:flex-row sm:justify-end";
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

/**
 * Per-marker authoritative revision probing, comparison, and resolution for
 * forms discovered by EditWatcher.
 *
 * @testable true
 * @tests tests_js/test_024_edit_watcher.py::test_edit_watcher_compares_and_resets_each_form_independently
 * @tests tests_js/test_024_edit_watcher.py::test_edit_watcher_coalesces_overlapping_revision_probes
 * @tests tests_js/test_028_form_state_split.py::test_edit_watcher_separates_schema_and_renderer_value_changes
 * @tests tests_js/test_028_form_state_split.py::test_edit_watcher_reconciles_independent_field_selections
 * @tests tests_js/test_028_form_state_split.py::test_owned_deferred_completion_replaces_clean_active_form
 * @tests tests_e2e/010_sync/test_010d_form_state_split.py::test_form_submission_reconciliation_uses_latest_schema
 * @pairs edited-entity-notice:targeted-reset edited-entity-notice:reload-fallback
 * @pairs edited-entity-notice:dirty-state edited-entity-notice:active-state
 * @pairs edited-entity-notice:focused-state edited-entity-notice:comparison
 * @pairs edited-entity-notice:overlap-follow-up edited-entity-notice:coalescing
 * @pairs edited-entity-notice:renderer-capability edited-entity-notice:latest-schema
 * @pairs edited-entity-notice:schema-only edited-entity-notice:local-values
 * @pairs edited-entity-notice:submission-choice edited-entity-notice:per-field-selection
 * @pairs edited-entity-notice:whole-form-selection edited-entity-notice:clean-state
 * @pairs edited-entity-notice:transition edited-entity-notice:owned-deferred-completion
 * @pairs forms:latest-schema forms:submission-choice forms:per-field-selection
 * @pairs reconnect-refresh:dirty-form-preservation form-schema:notice
 */
class EditReconciler {
	constructor(
		view,
		{
			recordMarkerRevision = () => {},
			ownedDeferredCompletion = () => null,
			forgetDeferredCompletion = () => {},
		} = {},
	) {
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
			conflictPromise: null,
		};
		return marker._lp_edited_state;
	}

	async _prepareRevision(widget, response) {
		if (widget.prepareRevision) return await widget.prepareRevision(response);
		return () => {
			const result = widget.applyRevision(response);
			if (result?.then) void result.catch(captureError);
		};
	}

	async _prepareLocalRevision(widget, response, options) {
		if (widget.prepareLocalRevision) {
			return await widget.prepareLocalRevision(response, options);
		}
		return () => {
			const result = widget.applyLocalRevision(response, options);
			if (result?.then) void result.catch(captureError);
		};
	}

	_setAction(marker, mode, message = null) {
		const state = this._state(marker);
		state.mode = mode;
		const button = marker.querySelector("[data-role='edited-reset']");
		if (button) {
			button.textContent =
				{
					reset: "Reset form",
					reload: "Reload page",
					review: "Review values",
					"whole-review": "Review versions",
					apply: "Continue",
					dismiss: "Dismiss",
				}[mode] ?? "Review update";
		}
		const copy = marker.querySelector("[data-role='edited-message']");
		if (copy && message) copy.textContent = message;
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
		const objectSubmission = (submission) =>
			Boolean(submission) &&
			typeof submission === "object" &&
			!Array.isArray(submission);
		return Boolean(
			widget.form?.renderer &&
				Array.isArray(widget.schema) &&
				widget.schema.length &&
				objectSubmission(widget.submission) &&
				Array.isArray(response.schema) &&
				response.schema.length &&
				objectSubmission(response.submission),
		);
	}

	_rendererValuesDiffer(response, localResponse) {
		const saved = response.submission ?? {};
		const local = localResponse.submission ?? {};
		return (response.schema ?? []).some(
			(field) =>
				field?.id &&
				!areEqual(local[field.id] ?? null, saved[field.id] ?? null),
		);
	}

	_storeRevision(
		marker,
		response,
		{
			fingerprint,
			modified,
			record,
			remoteSnapshot,
			schemaChanged,
			submissionChoice,
		},
	) {
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

	async _stageRevision(
		marker,
		widget,
		response,
		{ fingerprint = null, modified = null, record = null } = {},
	) {
		const state = this._state(marker);
		record ??= state.record;
		const token = state.token;
		const anchor = marker.closest?.("[lp-entity]");
		const baselineFingerprint =
			record?.fingerprint ?? anchor?.dataset?.fingerprint ?? null;
		const baselineModified =
			record?.modified ?? anchor?.dataset?.modified ?? null;
		const fingerprintChanged = Boolean(
			fingerprint && baselineFingerprint && baselineFingerprint !== fingerprint,
		);
		const schemaOnlyRevision = Boolean(
			fingerprintChanged &&
				modified &&
				baselineModified &&
				baselineModified === modified,
		);
		const observedSchemaChanged = !areEqual(
			widget.schema ?? null,
			response.schema ?? null,
		);
		const schemaChanged = observedSchemaChanged || schemaOnlyRevision;

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
			typeof document !== "undefined" &&
				widget.target?.contains?.(document.activeElement),
		);
		const active =
			widget.component?.active === widget && widget.visible === true;
		const ownedDeferredCompletion =
			!unsaved && !queued ? this.ownedDeferredCompletion(marker, widget) : null;
		const protectedRevision =
			unsaved || queued || (!ownedDeferredCompletion && (active || focused));
		if (!protectedRevision) {
			const commitRevision = await this._prepareRevision(widget, response);
			await withTransition(
				() => {
					commitRevision();
					this._hide(
						widget.target?.querySelector("[lp-edited-marker]") ?? marker,
					);
				},
				{ label: "edit-reconcile:apply-remote" },
			);
			return;
		}

		const current = widget.revisionSnapshot();
		const rendererCapable = this._rendererCapable(widget, response);
		const local = widget.buildLocalRevision(response);
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
		const rendererValuesDiffer =
			rendererCapable && this._rendererValuesDiffer(response, local.response);

		if (localSnapshot === remoteSnapshot || current === remoteSnapshot) {
			if (record) await this.view.offlineQueue?.cancel(record.id);
			const commitRevision = await this._prepareRevision(widget, response);
			await withTransition(
				() => {
					commitRevision();
					this._hide(
						widget.target?.querySelector("[lp-edited-marker]") ?? marker,
					);
				},
				{ label: "edit-reconcile:accept-matching" },
			);
			return;
		}

		if (rendererValuesDiffer && !schemaOnlyRevision) {
			this._storeRevision(marker, response, {
				fingerprint,
				modified,
				record,
				remoteSnapshot,
				schemaChanged,
				submissionChoice: true,
			});
			this._setAction(
				marker,
				"review",
				schemaChanged
					? "The form fields and saved values changed elsewhere."
					: "Saved values changed elsewhere.",
			);
			this._show(marker);
			return;
		}

		if (rendererCapable && schemaChanged) {
			const commitRevision = await this._prepareLocalRevision(
				widget,
				response,
				{
					remoteSnapshot,
				},
			);
			await withTransition(
				() => {
					commitRevision();
					marker = widget.target.querySelector("[lp-edited-marker]") ?? marker;
					this._storeRevision(marker, response, {
						fingerprint,
						modified,
						record,
						remoteSnapshot,
						schemaChanged,
						submissionChoice: false,
					});
					this._setAction(
						marker,
						record ? "apply" : "dismiss",
						"This form's fields have changed. It has been updated to reflect the latest schema.",
					);
					this._show(marker);
				},
				{ label: "edit-reconcile:rebase-schema" },
			);
			return;
		}

		if (rendererCapable && remoteSnapshot === widget.revisionBaseline) {
			const commitRevision = await this._prepareLocalRevision(
				widget,
				response,
				{
					remoteSnapshot,
				},
			);
			await withTransition(
				() => {
					commitRevision();
					marker = widget.target.querySelector("[lp-edited-marker]") ?? marker;
					this._hide(marker);
				},
				{ label: "edit-reconcile:rebase-values" },
			);
			if (record) {
				const rebased = await this.view.offlineQueue?.rebaseSubmit(
					record,
					widget,
					{ fingerprint, modified },
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
			submissionChoice: queued,
		});
		this._setAction(
			marker,
			queued ? "whole-review" : "reset",
			queued
				? "The saved form changed while this update was queued."
				: "This form changed elsewhere. Reset it to load the saved version.",
		);
		this._show(marker);
	}

	async _installUninitialized(marker, response) {
		const form = marker.closest("form[data-widget]");
		const name = form?.dataset.widget;
		const replacement = name
			? response.html?.querySelector(`[data-widget='${name}']`)
			: null;
		if (!form || !replacement) return false;

		const visible = form.dataset.visible;
		const fresh = replacement.cloneNode(true);
		if (visible !== undefined) fresh.dataset.visible = visible;
		await withTransition(() => form.replaceWith(fresh));
		return true;
	}

	_sameProbeRevision(left, right) {
		return Boolean(
			left &&
				right &&
				left.fingerprint === right.fingerprint &&
				left.modified === right.modified,
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
		if (
			state.probePromise &&
			this._sameProbeRevision(state.probeRevision, requested)
		) {
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
		if (!marker?.isConnected && marker?.isConnected !== undefined) return;
		const state = this._state(marker);
		const token = {};
		state.token = token;
		const route = marker.dataset.editedRoute;
		if (!route) {
			this.fallback(
				marker,
				new Error("Edited marker has no replacement route"),
			);
			return;
		}

		try {
			const response = await request.get(route, null, {
				acknowledgeEntities: false,
				replaceErrorPage: false,
			});
			if (state.token !== token) return;
			const form = marker.closest("form[data-widget]");
			const widget = form?._lp_widget;
			const completion = this.ownedDeferredCompletion(marker, widget);
			if (response?.unchanged) {
				this._hide(marker);
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
				modified,
			});
			this.recordMarkerRevision(marker, { fingerprint, modified });
			this.forgetDeferredCompletion(completion);
		} catch (error) {
			if (state.token === token) this.fallback(marker, error);
		}
	}

	async stageConflict(widget, { record, response } = {}) {
		const marker = widget?.target?.querySelector?.("[lp-edited-marker]");
		if (!marker || !record || !response) return false;
		const revision = (response.entities || []).find(
			(entity) => entity.key === record.target_key,
		);
		const state = this._state(marker);
		const reconcile = (async () => {
			if (state.probePromise) await state.probePromise;
			state.token = {};
			if (widget.revisionBaseline === null) widget.commitRevisionBaseline();
			await this._stageRevision(marker, widget, response, {
				fingerprint: revision?.fingerprint ?? null,
				modified: revision?.modified ?? null,
				record,
			});
			delete widget._offlineConflict;
			return true;
		})();
		state.conflictPromise = reconcile;
		try {
			return await reconcile;
		} finally {
			if (state.conflictPromise === reconcile) {
				state.conflictPromise = null;
			}
		}
	}

	async resolveRevision(marker, choice) {
		const state = this._state(marker);
		const widget = marker.closest("form[data-widget]")?._lp_widget;
		if (!widget || !state.response) {
			this.fallback(marker);
			return false;
		}

		const fieldSelection =
			choice && typeof choice === "object" ? (choice.selections ?? {}) : null;
		const localSelected = fieldSelection
			? Object.values(fieldSelection).some((source) => source === "local")
			: choice === "local";

		if (!localSelected) {
			if (state.record) await this.view.offlineQueue?.cancel(state.record.id);
			const commitRevision = await this._prepareRevision(
				widget,
				state.response,
			);
			await withTransition(() => commitRevision(), {
				label: "edit-reconcile:resolve-server",
			});
		} else {
			let selectedSubmission;
			if (fieldSelection) {
				selectedSubmission = structuredClone(state.response.submission ?? {});
				const localSubmission = choice.localResponse?.submission ?? {};
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
					selectedSubmission,
				},
			);
			await withTransition(() => commitRevision(), {
				label: "edit-reconcile:resolve-local",
			});
			if (state.record) {
				const rebased = await this.view.offlineQueue?.rebaseSubmit(
					state.record,
					widget,
					{
						fingerprint: state.fingerprint,
						modified: state.modified,
					},
				);
				if (rebased) await this.view.offlineQueue?.replay();
			}
		}

		const currentMarker =
			widget.target?.querySelector("[lp-edited-marker]") ?? marker;
		this._hide(currentMarker);
		return true;
	}

	async handleClick(event) {
		const button = event.target.closest("[data-role='edited-reset']");
		if (!button) return;
		const marker = button.closest("[lp-edited-marker]");
		const state = marker ? this._state(marker) : null;
		if (!marker || !state) return;

		if (state.mode === "reload") {
			window.location.reload();
			return;
		}
		if (state.mode === "dismiss") {
			this._hide(marker);
			return;
		}
		const widget = marker.closest("form[data-widget]")?._lp_widget;
		if (!widget || !state.response) {
			this.fallback(marker);
			return;
		}

		button.disabled = true;
		try {
			if (state.mode === "review") {
				const modal = new FormRevisionModal(this, marker, widget, state);
				const shown = await modal.init();
				if (!shown && state.record) {
					await new WholeFormRevisionModal(this, marker, widget).init();
				} else if (!shown) {
					this._setAction(
						marker,
						"reset",
						"This form changed elsewhere. Reset it to load the saved version.",
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
				widget.target?.querySelector("[lp-edited-marker]") ?? marker,
				error,
			);
		} finally {
			button.disabled = false;
		}
	}
}

/**
 * View-scoped detector for committed edits to forms represented by
 * lp-edited-marker descendants.
 *
 * @testable true
 * @tests tests_js/test_024_edit_watcher.py::test_edit_watcher_compares_and_resets_each_form_independently
 * @tests tests_js/test_028_form_state_split.py::test_owned_deferred_completion_replaces_clean_active_form
 * @tests tests_e2e/004_projects/test_004b_info.py::test_project_revision_notice_only_resets_changed_form
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_replay_reconciles_after_reload
 * @features edited-entity-notice deferred-jobs polling
 * @dimensions entity-ancestor batching per-form acknowledgement acknowledgement-no-probe active-state visibility subscription-lifecycle owned-deferred-completion freshness
 * @pairs edited-entity-notice:entity-ancestor edited-entity-notice:batching
 * @pairs edited-entity-notice:per-form edited-entity-notice:acknowledgement
 * @pairs edited-entity-notice:acknowledgement-no-probe
 * @pairs edited-entity-notice:active-state
 * @pairs edited-entity-notice:visibility edited-entity-notice:subscription-lifecycle
 * @pairs edited-entity-notice:owned-deferred-completion deferred-jobs:owned-deferred-completion
 * @pairs polling:freshness
 */
class EditWatcher {
	constructor(view) {
		this.view = view;
		this._unsubscribers = new Map();
		this._markerRevisions = new WeakMap();
		this._latestRevisions = new Map();
		this._deferredCompletions = new Map();
		this._destroyed = false;
		this._reconciler = new EditReconciler(view, {
			recordMarkerRevision: (marker, revision) => {
				this._markerRevisions.set(marker, revision);
			},
			ownedDeferredCompletion: (marker, widget) =>
				this._ownedDeferredCompletion(marker, widget),
			forgetDeferredCompletion: (completion) =>
				this._forgetDeferredCompletion(completion),
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
				modified: this.view.elt.dataset.modified ?? null,
			});
		}
		for (const component of Object.values(this.view.components ?? {})) {
			for (const widget of Object.values(component.widgets ?? {})) {
				if (widget._offlineConflict) {
					this.stageConflict(widget, widget._offlineConflict);
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
			widget &&
				widget.component?.active === widget &&
				this._componentVisible(widget.component) &&
				widget.visible === true,
		);
	}

	_markerRevision(marker, anchor) {
		let revision = this._markerRevisions.get(marker);
		if (!revision) {
			revision = {
				fingerprint: anchor.dataset.fingerprint ?? null,
				modified: anchor.dataset.modified ?? null,
			};
			this._markerRevisions.set(marker, revision);
		}
		return revision;
	}

	_entities({ activeOnly = true } = {}) {
		const entities = new Map();
		const markers = this.view.elt.querySelectorAll("[lp-edited-marker]");

		for (const marker of markers) {
			const anchor = marker.closest("[lp-entity]");
			const key = anchor?.dataset.key;
			const revision = anchor ? this._markerRevision(marker, anchor) : null;
			const fingerprint = revision?.fingerprint;
			if (!anchor || !key || !fingerprint) {
				captureError(
					new Error("Edited marker has no fingerprinted entity anchor"),
					marker,
				);
				continue;
			}
			if (activeOnly && !this._markerActive(marker)) continue;

			const entity = entities.get(key) ?? {
				key,
				fingerprint,
				modified: revision.modified,
				anchors: new Set(),
				markers: new Set(),
			};
			entity.anchors.add(anchor);
			entity.markers.add(marker);
			entities.set(key, entity);
		}

		return entities;
	}

	expectDeferredCompletion(key, operation) {
		if (!key || !operation) return false;
		const operations = this._deferredCompletions.get(key) ?? new Set();
		operations.add(operation);
		this._deferredCompletions.set(key, operations);
		return true;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_owned_deferred_completion_replaces_clean_active_form
	 * @pair deferred-jobs:owned-deferred-completion
	 * @pair edited-entity-notice:owned-deferred-completion
	 */
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
			return (
				current?.fingerprint !== fingerprint ||
				(Boolean(modified) && current?.modified !== modified) ||
				Boolean(
					this._ownedDeferredCompletion(
						marker,
						marker.closest?.("form[data-widget]")?._lp_widget,
					),
				)
			);
		});
		await Promise.all(
			stale.map((marker) =>
				this._reconciler.probe(marker, fingerprint, modified),
			),
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
		if (result.status === "unchanged" && this._deferredCompletions.has(key)) {
			const revision = this._latestRevisions.get(key) ?? {
				fingerprint: result.revision ?? null,
				modified: null,
			};
			if (revision.fingerprint) {
				await this._probeEntity(key, revision.fingerprint, revision.modified);
			}
			return;
		}
		if (result.status !== "changed" || !result.payload?.fingerprint) return;
		const revision = {
			fingerprint: result.payload.fingerprint,
			modified: result.payload.modified ?? null,
		};
		this._latestRevisions.set(key, revision);
		await this._probeEntity(key, revision.fingerprint, revision.modified);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_edit_watcher_restores_active_autofill_without_form_sync
	 * @tests tests_e2e/005_pages/test_005h_page_autofill.py::test_page_autofill_runs_deferred_with_attached_file_context
	 * @features edited-entity-notice deferred-jobs
	 * @dimensions active-operation reload form-lock
	 */
	async _lockEntity(entity, descriptor) {
		if (!entity || !descriptor?.operation) return;
		const forms = new Set();
		for (const marker of entity.markers ?? []) {
			const form = marker.closest("form[data-widget]");
			if (form) forms.add(form);
		}
		for (const anchor of entity.anchors ?? []) {
			for (const form of anchor.querySelectorAll?.(
				"form[data-widget='PageInfo'], form[data-widget='TaskForm']",
			) ?? []) {
				forms.add(form);
			}
		}

		const tracked = [];
		for (const form of forms) {
			if (
				form.dataset.deferredLock !== "form" &&
				!["PageInfo", "TaskForm"].includes(form.dataset.widget)
			)
				continue;

			const widget = form._lp_widget;
			if (widget?._deferredOperation !== descriptor.operation) {
				widget?.lockDeferredOperation?.(descriptor);
			}
			if (!widget) {
				form.dataset.operation = descriptor.operation;
				form.dataset.operationRevision = String(descriptor.revision ?? 0);
				form.dataset.deferredLock = "form";
			}
			tracked.push({
				revision: descriptor.revision ?? 0,
				node: widget?.target ?? form,
			});
		}

		if (!tracked.length) return;
		const operations =
			this.view.DeferredOperations ||
			(await this.view.ensureDeferredOperations?.());
		for (const options of tracked) {
			operations?.track(descriptor.operation, options);
		}
	}

	_syncSubscriptions() {
		const mounted = this.entities;
		const active = new Set();
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
							revision: entity.fingerprint,
						},
						{
							mode: "periodic",
							initial: "scheduled",
							onResult: (result) =>
								this.receiveEntityResult(entity.key, result),
						},
					) ?? (() => {}),
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
							revision: "unlocked",
						},
						{
							mode: "periodic",
							initial: "scheduled",
							onResult: async (result) => {
								if (result.status !== "changed") return;
								if (result.payload?.locked) {
									await this._lockEntity(
										this.entities.get(entity.key),
										result.payload,
									);
								} else if (
									Array.from(this.entities.get(entity.key)?.markers ?? []).some(
										(marker) =>
											marker
												.closest?.("form[data-widget]")
												?.hasAttribute("data-deferred-lock"),
									)
								) {
									await this.view.reconcileChange?.({
										type: "poll",
										key: entity.key,
									});
								}
							},
						},
					) ?? (() => {}),
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
					latest.modified,
				);
			}),
		);
		return mounted;
	}

	check(keys = null, options = {}) {
		const mounted = this._syncSubscriptions();
		const requested = keys === null ? [...mounted.keys()] : Array.from(keys);
		const ids = requested.flatMap((key) => [
			key === this.view.key ? `view:entity:${key}` : `edit:${key}`,
			`lock:${key}`,
		]);
		return this.view.PollingCoordinator?.trigger(ids, options);
	}

	enqueue(keys = null) {
		const mounted = this._syncSubscriptions();
		const requested = keys === null ? [...mounted.keys()] : Array.from(keys);
		const ids = requested.flatMap((key) => [
			key === this.view.key ? `view:entity:${key}` : `edit:${key}`,
			`lock:${key}`,
		]);
		this.view.PollingCoordinator?.enqueue(ids);
	}

	invalidate(keys) {
		const requested = keys
			? (Array.isArray(keys) ? keys : [keys]).filter(Boolean)
			: null;
		return this.check(requested, { fresh: true });
	}

	acknowledge({ key, fingerprint, modified = null } = {}) {
		if (!key || !fingerprint) return;
		this._latestRevisions.set(key, { fingerprint, modified });
		if (this.view.key === key) {
			this.view.elt.dataset.fingerprint = fingerprint;
			if (modified) this.view.elt.dataset.modified = modified;
		}
		this.view.PollingCoordinator?.acknowledge(`edit:${key}`, fingerprint);
		this.view.PollingCoordinator?.acknowledge(
			`view:entity:${key}`,
			fingerprint,
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

	pause() {}

	resume() {
		if (this._destroyed || !this.view.online || this.view.hidden) return;
		return this.reconcileSubscriptions();
	}

	stageConflict(widget, conflict = {}) {
		return this._reconciler.stageConflict(widget, conflict);
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
