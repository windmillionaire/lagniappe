import { STYLES } from "styles";
import { loadRevisionPreview } from "../widgets/loader";
import { ENDPOINTS } from "./endpoints";
import { captureError } from "./errors";
import { Modal } from "./modal";
import { request } from "./request";
import { areEqual, withTransition } from "./utilities";

const POLL_INTERVAL = 15_000;
const MAX_EDITED_ENTITIES = 32;

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010d_form_state_split.py::test_form_submission_reconciliation_uses_latest_schema
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_offline_submission_conflict_keeps_queue_until_choice
 * @features forms
 * @dimensions readonly-preview submission-choice latest-schema queued-conflict
 */
class FormRevisionModal extends Modal {
	constructor(watcher, marker, widget, state) {
		super(watcher.view, marker.querySelector("[data-role='edited-reset']"));
		this.watcher = watcher;
		this.marker = marker;
		this.widget = widget;
		this.state = state;
		this.selections = new Map();
	}

	/**
	 * @testable false
	 * @covered-by src/script/shared/editWatcher.mjs::FormRevisionModal
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
	 * @covered-by src/script/shared/editWatcher.mjs::FormRevisionModal
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
	 * @covered-by src/script/shared/editWatcher.mjs::FormRevisionModal
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
	 * @covered-by src/script/shared/editWatcher.mjs::FormRevisionModal
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
			this.watcher.view.kind ||
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
			await this.watcher.resolveRevision(this.marker, {
				localResponse: local.response,
				selections: Object.fromEntries(this.selections),
			});
			await this.remove();
		});

		super.attach(modal, this.widget.component);
		update.focus();
		return true;
	}
}

/**
 * @testable false
 * @covered-by src/script/shared/editWatcher.mjs::EditWatcher
 * @reason private whole-form conflict UI is selected by capability-aware watcher state
 */
class WholeFormRevisionModal extends Modal {
	constructor(watcher, marker, widget) {
		super(watcher.view, marker.querySelector("[data-role='edited-reset']"));
		this.watcher = watcher;
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
			this.watcher.view.kind ||
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
			await this.watcher.resolveRevision(this.marker, "local");
			await this.remove();
		});
		saved.addEventListener("click", async () => {
			await this.watcher.resolveRevision(this.marker, "server");
			await this.remove();
		});

		super.attach(modal, this.widget.component);
		saved.focus();
	}
}

/**
 * View-scoped detector for committed edits to forms represented by
 * lp-edited-marker descendants.
 *
 * @testable true
 * @tests tests_js/test_024_edit_watcher.py::test_edit_watcher_compares_and_resets_each_form_independently
 * @tests tests_js/test_028_form_state_split.py::test_edit_watcher_separates_schema_and_renderer_value_changes
 * @tests tests_js/test_028_form_state_split.py::test_edit_watcher_reconciles_independent_field_selections
 * @tests tests_e2e/004_projects/test_004b_info.py::test_project_revision_notice_only_resets_changed_form
 * @tests tests_e2e/010_sync/test_010d_form_state_split.py::test_form_submission_reconciliation_uses_latest_schema
 * @features edited-entity-notice
 * @dimensions entity-ancestor batching per-form comparison acknowledgement acknowledgement-no-probe targeted-reset reload-fallback timestamp-only formdata staged-reset no-reload dirty-state focused-state replacement info-form side-effect-free overlap-follow-up renderer-capability latest-schema schema-only submission-choice per-field-selection whole-form-selection clean-state transition
 * @pairs edited-entity-notice:submission-choice reconnect-refresh:dirty-form-preservation form-schema:notice
 */
export class EditWatcher {
	constructor(view) {
		this.view = view;
		this._timer = null;
		this._checkPromise = null;
		this._checkQueued = false;
		this._checkAllQueued = false;
		this._invalidatedKeys = new Set();
		this._destroyed = false;

		this._click = this._click.bind(this);
		this._entityUpdated = this._entityUpdated.bind(this);
		this.check = this.check.bind(this);
	}

	init() {
		this.view.elt.addEventListener("click", this._click);
		window.addEventListener("entity-updated", this._entityUpdated);
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
		const entities = new Map();
		const markers = this.view.elt.querySelectorAll("[lp-edited-marker]");

		for (const marker of markers) {
			const anchor = marker.closest("[lp-entity]");
			const key = anchor?.dataset.key;
			const fingerprint = anchor?.dataset.fingerprint;
			if (!anchor || !key || !fingerprint) {
				captureError(
					new Error("Edited marker has no fingerprinted entity anchor"),
					marker,
				);
				continue;
			}

			const entity = entities.get(key) ?? {
				key,
				fingerprint,
				anchors: new Set(),
				markers: new Set(),
			};
			entity.anchors.add(anchor);
			entity.markers.add(marker);
			entities.set(key, entity);
		}

		return entities;
	}

	_descriptors(entities) {
		return Array.from(entities.values(), ({ key, fingerprint }) => ({
			key,
			fingerprint,
		}));
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
		};
		return marker._lp_edited_state;
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

	_fallback(marker, error = null) {
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
			this._fallback(marker);
			return;
		}
		const remoteSnapshot = remotePreview.revisionSnapshot();
		remotePreview.destroy?.();

		const queued = Boolean(record || widget.form?._queued === true);
		const focused = Boolean(
			typeof document !== "undefined" &&
				widget.target?.contains?.(document.activeElement),
		);
		const dirty = widget.unsavedState === true || queued || focused;
		if (!dirty) {
			await withTransition(async () => {
				await widget.applyRevision(response);
				this._hide(
					widget.target?.querySelector("[lp-edited-marker]") ?? marker,
				);
			});
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
			this._fallback(marker);
			return;
		}
		const localSnapshot = localPreview.revisionSnapshot();
		localPreview.destroy?.();
		const rendererValuesDiffer =
			rendererCapable && this._rendererValuesDiffer(response, local.response);

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
			await withTransition(async () => {
				await widget.applyLocalRevision(response, { remoteSnapshot });
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
			});
			return;
		}

		if (rendererCapable && remoteSnapshot === widget.revisionBaseline) {
			await withTransition(async () => {
				await widget.applyLocalRevision(response, { remoteSnapshot });
				marker = widget.target.querySelector("[lp-edited-marker]") ?? marker;
			});
			if (record) {
				const rebased = await this.view.offlineQueue?.rebaseSubmit(
					record,
					widget,
					{ fingerprint, modified },
				);
				if (rebased) await this.view.offlineQueue?.replay();
			}
			this._hide(marker);
			return;
		}

		if (localSnapshot === remoteSnapshot || current === remoteSnapshot) {
			if (record) await this.view.offlineQueue?.cancel(record.id);
			await withTransition(async () => {
				await widget.applyRevision(response);
				this._hide(
					widget.target?.querySelector("[lp-edited-marker]") ?? marker,
				);
			});
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

	_schedule() {
		if (this._timer) clearTimeout(this._timer);
		this._timer = null;
		if (this._destroyed || !this.view.online || this.view.hidden) return;
		this._timer = setTimeout(this.check, POLL_INTERVAL);
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

	async _probe(marker, fingerprint, modified = null) {
		if (!marker?.isConnected && marker?.isConnected !== undefined) return;
		const state = this._state(marker);
		const token = {};
		state.token = token;
		const route = marker.dataset.editedRoute;
		if (!route) {
			this._fallback(
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
			if (response?.unchanged) {
				this._hide(marker);
				return;
			}
			if (!response?.ok) {
				this._fallback(marker);
				return;
			}

			const form = marker.closest("form[data-widget]");
			const widget = form?._lp_widget;
			if (!widget) {
				if (await this._installUninitialized(marker, response)) return;
				this._fallback(marker, new Error("Replacement response has no form"));
				return;
			}

			if (widget.revisionBaseline === null) widget.commitRevisionBaseline();
			await this._stageRevision(marker, widget, response, {
				fingerprint,
				modified,
			});
		} catch (error) {
			if (state.token === token) this._fallback(marker, error);
		}
	}

	async _probeEntity(key, fingerprint, modified = null) {
		const entity = this.entities.get(key);
		if (!entity) return;
		await Promise.all(
			Array.from(entity.markers, (marker) =>
				this._probe(marker, fingerprint, modified),
			),
		);
		for (const anchor of entity.anchors) {
			anchor.dataset.fingerprint = fingerprint;
			if (modified) anchor.dataset.modified = modified;
		}
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_edit_watcher_restores_active_autofill_without_form_sync
	 * @tests tests_e2e/005_pages/test_005h_page_autofill.py::test_page_autofill_runs_deferred_with_attached_file_context
	 * @features edited-entity-notice deferred-jobs
	 * @dimensions active-operation reload form-lock
	 */
	_lockEntity(entity, descriptor) {
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
				form.dataset.operationRevision = String(
					Number(descriptor.revision) || 0,
				);
				form.dataset.deferredLock = "form";
			}
			this.view.DeferredOperations?.track(descriptor.operation, {
				revision: Number(descriptor.revision) || 0,
				node: widget?.target ?? form,
			});
		}
	}

	async _checkNow(keys = null) {
		if (this._timer) clearTimeout(this._timer);
		this._timer = null;
		if (this._destroyed || !this.view.online || this.view.hidden) return;

		const mounted = this.entities;
		const entities = keys
			? new Map(
					Array.from(keys)
						.map((key) => [key, mounted.get(key)])
						.filter(([, entity]) => Boolean(entity)),
				)
			: mounted;
		const descriptors = this._descriptors(entities);
		if (!descriptors.length) return;

		for (
			let offset = 0;
			offset < descriptors.length;
			offset += MAX_EDITED_ENTITIES
		) {
			const response = await request.post(ENDPOINTS.edited, {
				entities: descriptors.slice(offset, offset + MAX_EDITED_ENTITIES),
			});
			if (!response?.ok || !Array.isArray(response.edited)) return;

			for (const operation of response.operations ?? []) {
				this._lockEntity(entities.get(operation.key), operation);
			}

			for (const edited of response.edited) {
				const entity = entities.get(edited.key);
				if (!entity) continue;
				if (edited.unavailable || !edited.fingerprint) {
					for (const marker of entity.markers) this._fallback(marker);
					continue;
				}
				await this._probeEntity(
					edited.key,
					edited.fingerprint,
					edited.modified ?? null,
				);
			}
		}
	}

	check(keys = null) {
		if (keys === null) {
			this._checkAllQueued = true;
		} else {
			for (const key of keys) this._invalidatedKeys.add(key);
		}
		if (this._checkPromise) {
			this._checkQueued = true;
			return this._checkPromise;
		}

		this._checkPromise = (async () => {
			try {
				do {
					this._checkQueued = false;
					const checkAll = this._checkAllQueued;
					this._checkAllQueued = false;
					const invalidated = new Set(this._invalidatedKeys);
					this._invalidatedKeys.clear();
					await this._checkNow(checkAll ? null : invalidated);
				} while (this._checkQueued);
			} finally {
				this._checkPromise = null;
				this._schedule();
			}
		})();
		return this._checkPromise;
	}

	invalidate(keys) {
		if (!keys) return this.check();
		const requested = Array.isArray(keys) ? keys : [keys];
		return this.check(requested.filter(Boolean));
	}

	acknowledge({ key, fingerprint, modified = null } = {}) {
		if (!key || !fingerprint) return;
		if (this.view.key === key) {
			this.view.elt.dataset.fingerprint = fingerprint;
			if (modified) this.view.elt.dataset.modified = modified;
		}

		const entity = this.entities.get(key);
		if (!entity) return;
		for (const anchor of entity.anchors) {
			anchor.dataset.fingerprint = fingerprint;
			if (modified) anchor.dataset.modified = modified;
		}
	}

	pause() {
		if (this._timer) clearTimeout(this._timer);
		this._timer = null;
	}

	resume() {
		if (this._destroyed || !this.view.online || this.view.hidden) return;
		return this.check();
	}

	async stageConflict(widget, { record, response } = {}) {
		const marker = widget?.target?.querySelector?.("[lp-edited-marker]");
		if (!marker || !record || !response) return false;
		const revision = (response.entities || []).find(
			(entity) => entity.key === record.target_key,
		);
		const state = this._state(marker);
		state.token = {};
		if (widget.revisionBaseline === null) widget.commitRevisionBaseline();
		await this._stageRevision(marker, widget, response, {
			fingerprint: revision?.fingerprint ?? null,
			modified: revision?.modified ?? null,
			record,
		});
		delete widget._offlineConflict;
		return true;
	}

	async resolveRevision(marker, choice) {
		const state = this._state(marker);
		const widget = marker.closest("form[data-widget]")?._lp_widget;
		if (!widget || !state.response) {
			this._fallback(marker);
			return false;
		}

		const fieldSelection =
			choice && typeof choice === "object" ? (choice.selections ?? {}) : null;
		const localSelected = fieldSelection
			? Object.values(fieldSelection).some((source) => source === "local")
			: choice === "local";

		if (!localSelected) {
			if (state.record) await this.view.offlineQueue?.cancel(state.record.id);
			await withTransition(() => widget.applyRevision(state.response));
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
			await withTransition(() =>
				widget.applyLocalRevision(state.response, {
					remoteSnapshot: state.remoteSnapshot,
					markUnsaved: !state.record,
					selectedSubmission,
				}),
			);
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

	async _click(event) {
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
			this._fallback(marker);
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
			this._fallback(
				widget.target?.querySelector("[lp-edited-marker]") ?? marker,
				error,
			);
		} finally {
			button.disabled = false;
		}
	}

	_entityUpdated(event) {
		this.acknowledge(event.detail);
	}

	destroy() {
		this._destroyed = true;
		this.pause();
		this._invalidatedKeys.clear();
		this.view.elt.removeEventListener("click", this._click);
		window.removeEventListener("entity-updated", this._entityUpdated);
	}
}
