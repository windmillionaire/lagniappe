import { loadRevisionPreview } from "../widgets/loader";
import { FormRevisionModal, WholeFormRevisionModal } from "./editRevisionModal";
import { captureError } from "./errors";
import { request } from "./request";
import { areEqual, withTransition } from "./utilities";

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
 * @matrix edited-entity-notice : active-state clean-state coalescing comparison dirty-state focused-state latest-schema local-values mixed-submission overlap-follow-up owned-deferred-completion per-field-selection reload-fallback renderer-capability saved-default schema-only submission-choice targeted-reset transition whole-form-selection
 * @matrix forms : latest-schema mixed-submission per-field-selection saved-default submission-choice
 * @pairs form-schema:notice reconnect-refresh:dirty-form-preservation
 */
export class EditReconciler {
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
