import { STYLES } from "styles";
import { loadRevisionPreview } from "../widgets/loader";
import { Modal } from "./modal";
import { areEqual } from "./utilities";

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010d_form_state_split.py::test_form_submission_reconciliation_uses_latest_schema
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_offline_submission_conflict_keeps_queue_until_choice
 * @matrix forms : latest-schema queued-conflict readonly-preview submission-choice
 */
export class FormRevisionModal extends Modal {
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
export class WholeFormRevisionModal extends Modal {
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
