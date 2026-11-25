import type { DeferredOperationManager } from "../../shared/deferredOperations.ts";
import { captureError } from "../../shared/errors.ts";
import type {
	OfflineMutationRecord,
	OfflineQueue,
} from "../../shared/offlineQueue.ts";
import { request } from "../../shared/request.ts";
import { withTransition } from "../../shared/transitions.ts";
import { areEqual } from "../../shared/utilities.ts";
import type {
	FormRevisionChoice,
	FormRevisionConflict,
	FormRevisionFields,
	FormRevisionResponse,
	FormRevisionReviewOptions,
} from "../../types/forms";
import type {
	FormWidget,
	LocalRevisionOptions,
} from "../../widgets/base/formWidget.ts";
import { incompatibleSchema } from "../representation.ts";
import { currentReviewOperation, renderReviewBar } from "../reviewBar.ts";
import { FormRevisionModal, WholeFormRevisionModal } from "./modals.ts";
import { loadRevisionPreview } from "./preview.ts";

const ACTION_LABELS = {
	reset: "Reset form",
	reload: "Reload page",
	review: "Review values",
	"whole-review": "Review versions",
	apply: "Continue",
	dismiss: "Dismiss",
};

type RevisionMode = keyof typeof ACTION_LABELS;

export interface MarkerRevision {
	fingerprint: string | null;
	modified: string | null;
}

type ProbedRevision = MarkerRevision & { fingerprint: string };

type QueuedRevision = OfflineMutationRecord &
	NonNullable<Parameters<FormWidget["buildLocalRevision"]>[1]>;

interface StagedRevision extends MarkerRevision {
	record: QueuedRevision | null;
	remoteSnapshot: string | null;
	schemaChanged: boolean;
	submissionChoice: boolean;
}

export interface FormRevisionState extends StagedRevision {
	mode: RevisionMode;
	response: FormRevisionResponse | null;
	token: object | null;
	probePromise: Promise<void> | null;
	probeRevision: ProbedRevision | null;
	pendingProbe: ProbedRevision | null;
	conflictPromise: Promise<boolean> | null;
}

export type RevisionMarker = HTMLElement & {
	_lp_edited_state?: FormRevisionState;
};

export type RevisionForm = HTMLFormElement & {
	_lp_widget?: FormWidget;
};

export interface DeferredCompletion {
	key: string;
	operation: string;
}

type DeferredOperations = Pick<DeferredOperationManager, "track">;

export interface ReconcilerView {
	_destroyed?: boolean;
	dataset?: DOMStringMap;
	kind?: string | null;
	addFlash?(marker: RevisionMarker): void;
	reconcileChange?(change: {
		type: "poll" | "delete";
		key: string | null;
	}): unknown;
	offlineQueue?: Pick<
		OfflineQueue,
		"cancel" | "rebaseSubmit" | "replay"
	> | null;
	DeferredOperations?: DeferredOperations | null;
	ensureDeferredOperations?(): Promise<DeferredOperations | null | undefined>;
}

interface ReconcilerCallbacks {
	recordMarkerRevision(marker: RevisionMarker, revision: MarkerRevision): void;
	ownedDeferredCompletion(
		marker: RevisionMarker,
		widget?: FormWidget,
	): DeferredCompletion | null;
	forgetDeferredCompletion(completion: DeferredCompletion | null): void;
}

/**
 * Per-marker authoritative revision probing, comparison, and resolution for
 * forms discovered by EditWatcher.
 *
 */
export class EditReconciler {
	declare readonly view: ReconcilerView;
	declare readonly recordMarkerRevision: ReconcilerCallbacks["recordMarkerRevision"];
	declare readonly ownedDeferredCompletion: ReconcilerCallbacks["ownedDeferredCompletion"];
	declare readonly forgetDeferredCompletion: ReconcilerCallbacks["forgetDeferredCompletion"];

	constructor(
		view: ReconcilerView,
		{
			recordMarkerRevision = () => {},
			ownedDeferredCompletion = () => null,
			forgetDeferredCompletion = () => {},
		}: Partial<ReconcilerCallbacks> = {},
	) {
		this.view = view;
		this.recordMarkerRevision = recordMarkerRevision;
		this.ownedDeferredCompletion = ownedDeferredCompletion;
		this.forgetDeferredCompletion = forgetDeferredCompletion;
	}

	_state(marker: RevisionMarker) {
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

	async _prepareRevision(widget: FormWidget, response: FormRevisionResponse) {
		if (widget.prepareRevision) return await widget.prepareRevision(response);
		return () => {
			const result = widget.applyRevision(response);
			if (typeof result?.then === "function") void result.catch(captureError);
		};
	}

	async _prepareLocalRevision(
		widget: FormWidget,
		response: FormRevisionResponse,
		options: LocalRevisionOptions,
	) {
		if (widget.prepareLocalRevision) {
			return await widget.prepareLocalRevision(response, options);
		}
		return () => {
			const result = widget.applyLocalRevision(response, options);
			if (typeof result?.then === "function") void result.catch(captureError);
		};
	}

	_setAction(
		marker: RevisionMarker,
		mode: RevisionMode,
		message: string | null = null,
	) {
		const state = this._state(marker);
		state.mode = mode;
		const button = marker.querySelector<HTMLButtonElement>(
			"[data-role='edited-reset']",
		);
		if (button && !button.dataset?.reviewPending)
			button.textContent = ACTION_LABELS[mode] ?? "Review update";
		const copy = marker.querySelector("[data-role='edited-message']");
		if (copy && message) copy.textContent = message;
		if (button) button.hidden = false;
	}

	_hide(marker: RevisionMarker | null | undefined) {
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
		const widget =
			marker.closest?.<RevisionForm>("form[data-widget]")?._lp_widget;
		if (widget?.target?.dataset?.formState) renderReviewBar(widget);
	}

	_show(marker: RevisionMarker) {
		const wasVisible = marker.dataset.visible === "true";
		marker.dataset.visible = "true";
		if (!wasVisible) this.view.addFlash?.(marker);
	}

	fallback(marker: RevisionMarker, error: unknown = null) {
		const state = this._state(marker);
		state.response = null;
		this._setAction(marker, "reload");
		this._show(marker);
		if (error) captureError(error, marker);
	}

	_rendererCapable(widget: FormWidget, response: FormRevisionResponse) {
		const objectSubmission = (submission: unknown) =>
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

	_rendererValuesDiffer(
		response: FormRevisionResponse,
		localResponse: FormRevisionResponse,
	) {
		const saved = response.submission ?? {};
		const local = localResponse.submission ?? {};
		return (response.schema ?? []).some(
			(field) =>
				field?.id &&
				!areEqual(local[field.id] ?? null, saved[field.id] ?? null),
		);
	}

	_storeRevision(
		marker: RevisionMarker,
		response: FormRevisionResponse,
		{
			fingerprint,
			modified,
			record,
			remoteSnapshot,
			schemaChanged,
			submissionChoice,
		}: StagedRevision,
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
		marker: RevisionMarker,
		widget: FormWidget,
		response: FormRevisionResponse,
		{
			fingerprint = null,
			modified = null,
			record: incomingRecord = null,
		}: Partial<MarkerRevision> & { record?: OfflineMutationRecord | null } = {},
	) {
		const state = this._state(marker);
		// The queue keeps its optional renderer data opaque. Form projection uses
		// the schema, submission and combobox selections captured when it was queued.
		const record = (incomingRecord ?? state.record) as QueuedRevision | null;
		if (response.form_state) {
			const operation = currentReviewOperation(
				widget,
				response.form_state.operation,
			);
			// A new candidate is not acknowledgement of a new answer baseline.
			widget.reviewState = {
				...response.form_state,
				operation,
				revision: widget.reviewState?.revision ?? response.form_state.revision,
			};
			if (operation?.key) {
				widget.lockDeferredOperation?.({
					operation: operation.key,
					revision: operation.revision,
					scope: operation.scope,
					blocks_edit: operation.blocks_edit,
					status: operation,
				});
				const operations =
					this.view.DeferredOperations ||
					(await this.view.ensureDeferredOperations?.());
				operations?.track(operation.key, {
					node: widget.target,
					revision: operation.revision,
					status: operation,
				});
			}
			renderReviewBar(widget);
		}
		const explicitReview = Boolean(
			response.form_state?.reviews?.some(
				(review) => !widget._reviewedOperations?.has(review.operation),
			),
		);
		const token = state.token;
		const anchor = marker.closest?.<HTMLElement>("[lp-entity]");
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
			typeof document !== "undefined" &&
				widget.target?.contains?.(document.activeElement),
		);
		const active =
			widget.component?.active === widget && widget.visible === true;
		const ownedDeferredCompletion =
			!unsaved && !queued && widget.reviewState?.operation?.type !== "autofill"
				? this.ownedDeferredCompletion(marker, widget)
				: null;
		// A page image (or other metadata) can advance the entity revision without
		// changing this form. Keep its DOM, focus, and draft; the probe still records
		// the checked revision, and real value/schema changes follow normal review.
		if (
			!queued &&
			!explicitReview &&
			!ownedDeferredCompletion &&
			!schemaChanged &&
			remoteSnapshot === widget.revisionBaseline
		) {
			this._hide(marker);
			return;
		}
		const protectedRevision =
			explicitReview ||
			unsaved ||
			queued ||
			(!schemaChanged && !ownedDeferredCompletion && (active || focused));
		if (!protectedRevision) {
			const commitRevision = await this._prepareRevision(widget, response);
			await withTransition(
				() => {
					commitRevision();
					this._hide(
						widget.target?.querySelector<RevisionMarker>(
							"[lp-edited-marker]",
						) ?? marker,
					);
				},
				{ label: "edit-reconcile:apply-remote" },
			);
			return;
		}

		const current = widget.revisionSnapshot();
		const rendererCapable = this._rendererCapable(widget, response);
		// A freshly rendered form starts from saved values after reload. The
		// queued command, not that form, is the local side of this conflict.
		const local = record
			? widget.buildLocalRevision(response, record)
			: widget.buildLocalRevision(response);
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
		const incompatible = incompatibleSchema(
			record?.renderer_schema ?? widget.schema ?? [],
			response.schema ?? [],
		);
		// Projection drops incompatible local values. A matching projection cannot
		// acknowledge their loss while an unsaved or queued draft still owns them.
		const requiresReview =
			explicitReview || ((unsaved || queued) && incompatible);

		if (
			!requiresReview &&
			(localSnapshot === remoteSnapshot ||
				(!record && current === remoteSnapshot))
		) {
			if (record) await this.view.offlineQueue?.cancel(record.id);
			const commitRevision = await this._prepareRevision(widget, response);
			await withTransition(
				() => {
					commitRevision();
					this._hide(
						widget.target?.querySelector<RevisionMarker>(
							"[lp-edited-marker]",
						) ?? marker,
					);
				},
				{ label: "edit-reconcile:accept-matching" },
			);
			return;
		}

		if (
			(explicitReview && rendererCapable) ||
			(rendererValuesDiffer && !schemaOnlyRevision) ||
			(rendererCapable && incompatible)
		) {
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
					: "Another user has edited this form.",
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
					remoteSnapshot,
				},
			);
			await withTransition(
				() => {
					commitRevision();
					marker =
						widget.target.querySelector<RevisionMarker>("[lp-edited-marker]") ??
						marker;
					this._hide(marker);
				},
				{ label: "edit-reconcile:rebase-schema" },
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
					marker =
						widget.target.querySelector<RevisionMarker>("[lp-edited-marker]") ??
						marker;
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

	async _installUninitialized(
		marker: RevisionMarker,
		response: FormRevisionResponse,
	) {
		const form = marker.closest<RevisionForm>("form[data-widget]");
		const name = form?.dataset.widget;
		const replacement =
			name && response.html
				? response.html.querySelector<HTMLElement>(`[data-widget='${name}']`)
				: null;
		if (!form || !replacement) return false;

		const visible = form.dataset.visible;
		const fresh = replacement.cloneNode(true) as HTMLElement;
		if (visible !== undefined) fresh.dataset.visible = visible;
		await withTransition(() => form.replaceWith(fresh));
		return true;
	}

	_sameProbeRevision(
		left: ProbedRevision | null,
		right: ProbedRevision | null,
	) {
		return Boolean(
			left &&
				right &&
				left.fingerprint === right.fingerprint &&
				left.modified === right.modified,
		);
	}

	probe(
		marker: RevisionMarker,
		fingerprint: string,
		modified: string | null = null,
	): Promise<void> {
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
			let processed: ProbedRevision | null = null;
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

	async _runProbe(
		marker: RevisionMarker,
		fingerprint: string,
		modified: string | null = null,
	) {
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
			const response = await request.get<FormRevisionFields>(route, null, {
				acknowledgeEntities: false,
				replaceErrorPage: false,
			});
			if (state.token !== token) return;
			const form = marker.closest<RevisionForm>("form[data-widget]");
			const widget = form?._lp_widget;
			const completion = this.ownedDeferredCompletion(marker, widget);
			if (response?.unchanged) {
				// A conditional response does not dismiss a still-unresolved review.
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
				modified,
			});
			this.recordMarkerRevision(marker, { fingerprint, modified });
			this.forgetDeferredCompletion(completion);
		} catch (error) {
			if (state.token === token) this.fallback(marker, error);
		}
	}

	async stageConflict(
		widget: FormWidget,
		{ record, response }: FormRevisionConflict = {},
	) {
		const marker =
			widget?.target?.querySelector?.<RevisionMarker>("[lp-edited-marker]");
		if (!marker || !response) return false;
		const revision = (response.entities || []).find(
			(entity) => entity.key === (record?.target_key ?? widget.key),
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
		} catch (error) {
			this.fallback(marker, error);
			return false;
		} finally {
			if (state.conflictPromise === reconcile) {
				state.conflictPromise = null;
			}
		}
	}

	async openConflictReview(
		widget: FormWidget,
		{ blockedAction = null }: FormRevisionReviewOptions = {},
	) {
		const marker =
			widget?.target?.querySelector?.<RevisionMarker>("[lp-edited-marker]");
		if (
			!marker ||
			!["review", "whole-review"].includes(this._state(marker).mode)
		)
			return false;
		const button = marker.querySelector<HTMLButtonElement>(
			"[data-role='edited-reset']",
		);
		if (!button || button.disabled) return false;
		await this._activateAction(marker, button, {
			refresh: true,
			blockedAction,
		});
		return true;
	}

	async resolveRevision(marker: RevisionMarker, choice: FormRevisionChoice) {
		const state = this._state(marker);
		const widget =
			marker.closest<RevisionForm>("form[data-widget]")?._lp_widget;
		if (!widget || !state.response) {
			this.fallback(marker);
			return false;
		}

		const fieldChoice = choice && typeof choice === "object" ? choice : null;
		const fieldSelection = fieldChoice ? (fieldChoice.selections ?? {}) : null;
		const localSelected = fieldSelection
			? Object.values(fieldSelection).some((source) => source !== "server") ||
				(!!fieldChoice?.selectedSubmission && !state.record)
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
			let selectedSubmission = fieldChoice?.selectedSubmission;
			if (fieldSelection && selectedSubmission === undefined) {
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
			widget.target?.querySelector<RevisionMarker>("[lp-edited-marker]") ??
			marker;
		if (!state.record && state.response.form_state?.reviews?.length) {
			widget._reviewedOperations ??= new Set();
			widget._usedAutofillOperations ??= new Set();
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

	async handleClick(event: MouseEvent) {
		const button = (
			event.target as Element | null
		)?.closest?.<HTMLButtonElement>("[data-role='edited-reset']");
		if (!button) return;
		const marker = button.closest<RevisionMarker>("[lp-edited-marker]");
		if (!marker) return;
		await this._activateAction(marker, button);
	}

	async _activateAction(
		marker: RevisionMarker,
		button: HTMLButtonElement,
		{
			refresh = false,
			blockedAction = null,
		}: FormRevisionReviewOptions & { refresh?: boolean } = {},
	) {
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
		const widget =
			marker.closest<RevisionForm>("form[data-widget]")?._lp_widget;
		const reviewPending = ["review", "whole-review"].includes(state.mode);
		const originalLabel = button.textContent;
		button.disabled = true;
		if (reviewPending) {
			button.dataset.reviewPending = "true";
			button.textContent = "Opening review…";
			button.setAttribute("aria-busy", "true");
		}
		try {
			await state.probePromise;
			await state.conflictPromise;
			if ((refresh || widget?.target?.dataset?.formState) && !state.record) {
				// Completion can arrive before the revision probe finishes. Refresh on
				// opening, including cold loads with no staged response yet.
				const route = marker.dataset.editedRoute;
				const response = route
					? await request.get<FormRevisionFields>(route, null, {
							acknowledgeEntities: false,
							replaceErrorPage: false,
						})
					: null;
				if (!response?.ok)
					throw new Error(
						"Could not load the latest form values. Please try Review again.",
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
					blockedAction,
				});
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
				widget?.target?.querySelector<RevisionMarker>("[lp-edited-marker]") ??
					marker,
				error,
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
