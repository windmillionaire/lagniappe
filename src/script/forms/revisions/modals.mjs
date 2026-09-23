import { STYLES } from "../../generated/styles.mjs";
import { Modal } from "../../shared/modal.mjs";
import { areEqual } from "../../shared/utilities.mjs";
import { compatibleField } from "../representation.mjs";
import { loadRevisionPreview } from "./preview.mjs";
import { request } from "../../shared/request.mjs";
import { renderReviewBar } from "../reviewBar.mjs";

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010d_form_state_split.py::test_form_submission_reconciliation_uses_latest_schema
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_offline_submission_conflict_keeps_queue_until_choice
 * @matrix forms : latest-schema queued-conflict readonly-preview submission-choice
 * @pair form-migration:readonly-modal
 */
export class FormRevisionModal extends Modal {
	constructor(reconciler, marker, widget, state) {
		super(reconciler.view, marker.querySelector("[data-role='edited-reset']"));
		this.reconciler = reconciler;
		this.marker = marker;
		this.widget = widget;
		this.state = state;
		this.selections = new Map();
		this.openReview = this._reviewSnapshot();
		this.openSnapshot = widget.revisionSnapshot();
	}

	/**
	 * @testable false
	 * @covered-by src/script/forms/revisions/modals.mjs::FormRevisionModal
	 * @reason capture selectable values without poll identities or progress ticks
	 */
	_reviewSnapshot() {
		const response = this.state.response;
		if (!response) return null;
		const review = response.form_state ?? {};
		return structuredClone({
			schema: response.schema,
			submission: response.submission,
			revision: review.revision,
			migration: review.migration,
			reviews: review.reviews,
			queued: this.state.record?.id,
		});
	}

	/**
	 * @testable false
	 * @covered-by src/script/forms/revisions/modals.mjs::FormRevisionModal
	 * @reason revalidate modal choices after any in-flight revision comparison
	 */
	async _isCurrent() {
		await Promise.all([this.state.probePromise, this.state.conflictPromise]);
		return (
			areEqual(this.openReview, this._reviewSnapshot()) &&
			this.widget.revisionSnapshot() === this.openSnapshot
		);
	}

	/**
	 * @testable false
	 * @covered-by src/script/forms/revisions/modals.mjs::FormRevisionModal
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
	 * @covered-by src/script/forms/revisions/modals.mjs::FormRevisionModal
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
	 * @covered-by src/script/forms/revisions/modals.mjs::FormRevisionModal
	 * @reason private changed-field projection is part of the reconciliation modal
	 */
	async _differences(localResponse) {
		const localSubmission = {
			...localResponse.submission,
			...this.widget.captureFormState().renderer_submission,
		};
		const state = this.state.response.form_state ?? {};
		this.sources = [
			{
				id: "local",
				label: this.state.record ? "Queued value" : "Value in this tab",
				schema: this.widget.schema,
				submission: localSubmission,
			},
			{
				id: "server",
				label: "Latest saved value",
				schema: this.state.response.schema,
				submission: this.state.response.submission ?? {},
			},
			...(state.migration
				? [
						{
							id: "before",
							label: "Before the schema change",
							...state.migration,
						},
					]
				: []),
			...(state.reviews ?? []).map((review) => ({
				id: `ai:${review.operation}`,
				label: review.private
					? "Your revised suggestion"
					: "Autofill suggestion",
				...review,
			})),
		];
		const previews = await Promise.all(
			this.sources.map((source) =>
				loadRevisionPreview(
					this.widget,
					{
						...this.state.response,
						schema: source.schema,
						submission: source.submission,
					},
					{ readonly: true },
				),
			),
		);
		try {
			if (previews.some((preview) => !preview))
				throw new Error("Could not render form review values");
			const elements = (preview) =>
				new Map(
					Array.from(preview.form?.renderer?.elements?.values?.() ?? []).map(
						(element) => [element.schema?.id, element],
					),
				);
			const rendered = previews.map(elements);
			const fields = [
				...new Map(
					this.sources
						.flatMap((source) => source.schema ?? [])
						.map((field) => [field.id, field]),
				).values(),
			];
			return fields
				.filter(
					(field) =>
						field?.id &&
						this.sources.some(
							(source) =>
								(!source.fields || source.fields.includes(field.id)) &&
								source.schema?.some((item) => item.id === field.id) &&
								(!this._sameValue(
									source.submission[field.id],
									this.sources[1].submission[field.id],
								) ||
									!compatibleField(
										source.schema.find((item) => item.id === field.id),
										this.sources[1].schema?.find(
											(item) => item.id === field.id,
										),
									)),
						),
				)
				.map((field) => ({
					id: field.id,
					label: field.title || field.label || "Untitled field",
					choices: this.sources.flatMap((source, index) => {
						if (source.fields && !source.fields.includes(field.id)) return [];
						const definition = source.schema?.find(
							(item) => item.id === field.id,
						);
						if (!definition && source.id !== "server") return [];
						return [
							{
								source: source.id,
								label: source.label,
								compatible:
									source.id === "server" ||
									compatibleField(
										definition,
										this.sources[1].schema?.find(
											(item) => item.id === field.id,
										),
									),
								value: this._value(rendered[index].get(field.id)),
								conversionFailed:
									source.id === "server" &&
									definition &&
									source.submission[field.id] == null &&
									state.migration?.submission?.[field.id] != null,
							},
						];
					}),
				}));
		} finally {
			previews.forEach((preview) => preview?.destroy?.());
		}
	}

	/**
	 * @testable false
	 * @covered-by src/script/forms/revisions/modals.mjs::FormRevisionModal
	 * @reason empty controls and absent saved values have the same displayed meaning
	 */
	_sameValue(left, right) {
		/** @testable infrastructure */
		const comparable = (value) => {
			if (
				value == null ||
				value === "" ||
				(Array.isArray(value) && !value.length)
			)
				return null;
			if (
				typeof value === "object" &&
				Object.keys(value).length === 1 &&
				["rows", "items"].some(
					(key) => Array.isArray(value[key]) && !value[key].length,
				)
			)
				return null;
			return value;
		};
		return areEqual(comparable(left), comparable(right));
	}

	/**
	 * @testable false
	 * @covered-by src/script/forms/revisions/modals.mjs::FormRevisionModal
	 * @reason private per-field choice composition is part of the reconciliation modal
	 */
	_choice(field, { source, label, compatible, value, conversionFailed }) {
		const button = document.createElement("button");
		button.type = "button";
		button.setAttribute("role", "radio");
		button.setAttribute(
			"aria-checked",
			(source === this.selections.get(field.id)).toString(),
		);
		button.setAttribute("aria-label", `${label} for ${field.label}`);
		button.dataset.revisionSource = source;
		button.className =
			"min-w-0 rounded-md border border-base-light/50 bg-white p-3 text-left transition-colors hover:bg-base-bg aria-checked:bg-kind-bg aria-checked:outline-2 aria-checked:outline-kind-default";

		const heading = button.appendChild(document.createElement("span"));
		heading.className = "mb-2 block text-xs font-semibold text-base-medium";
		heading.textContent = label;
		button.appendChild(value);
		if (conversionFailed) {
			const warning = button.appendChild(document.createElement("p"));
			warning.dataset.kind = "error";
			warning.className = "mt-2 text-sm italic text-kind-default";
			warning.textContent = "Value not able to be converted";
		}
		if (!compatible) {
			button.disabled = true;
			const explanation = button.appendChild(document.createElement("p"));
			explanation.className = "mt-2 text-xs text-base-medium";
			explanation.textContent =
				"This field changed type or was removed. Keep this earlier value for reference and re-enter it in the updated form if needed.";
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
		const local = this.widget.buildLocalRevision(this.state.response);
		const differences = await this._differences(local.response);
		if (!differences.length && !this.state.response.form_state) return false;
		for (const field of differences) {
			const localChoice = field.choices.find(
				(choice) => choice.source === "local",
			);
			const baseline = this.widget._baselineSubmission;
			const changedLocally =
				!this.state.record &&
				baseline &&
				!this._sameValue(
					this.sources[0].submission[field.id] ?? null,
					baseline[field.id] ?? null,
				);
			this.selections.set(
				field.id,
				localChoice?.compatible && changedLocally ? "local" : "server",
			);
		}

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
			"Choose the values to keep. This updates your open form only; use Update afterward to save. Earlier values whose field type changed are shown for reference.";
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
				...field.choices.map((choice) => this._choice(field, choice)),
			);
		}
		if (!differences.length) {
			const noChanges = fields.appendChild(document.createElement("p"));
			noChanges.textContent =
				"The available values already match. You can revise them with a prompt below.";
		}
		this._refinement(body);
		const actions = body.appendChild(document.createElement("div"));
		actions.className = "ml-auto flex w-fit";
		const update = actions.appendChild(document.createElement("button"));
		update.type = "button";
		update.className = STYLES.button.submit;
		update.textContent = "Use selected values";

		update.addEventListener("click", async () => {
			if (!(await this._isCurrent())) {
				intro.textContent =
					"The form changed while this review was open. Close and reopen Review to compare the latest values.";
				return;
			}
			await this.reconciler.resolveRevision(this.marker, {
				localResponse: local.response,
				selections: Object.fromEntries(this.selections),
				selectedSubmission: this._selectedSubmission(),
			});
			await this.remove();
		});

		await super.attach(modal, this.widget.component);
		update.focus();
		return true;
	}

	/** @testable infrastructure */
	_selectedSubmission() {
		const submission = structuredClone(this.state.response.submission ?? {});
		for (const [id, sourceId] of this.selections) {
			const source = this.sources.find(
				(candidate) => candidate.id === sourceId,
			);
			if (Object.hasOwn(source?.submission ?? {}, id))
				submission[id] = structuredClone(source.submission[id]);
			else delete submission[id];
		}
		return submission;
	}

	/** @testable infrastructure */
	_refinement(body) {
		const url = this.state.response.form_state?.refine_url;
		if (!url || this.state.record) return;
		const section = body.appendChild(document.createElement("section"));
		section.className = "space-y-2";
		const label = section.appendChild(document.createElement("label"));
		label.className = "block text-sm font-semibold";
		label.textContent = "Revise these values with AI";
		const prompt = label.appendChild(document.createElement("textarea"));
		prompt.className =
			"mt-2 block w-full rounded-md border border-base-light p-2 text-sm";
		prompt.placeholder = "Describe what to add, correct, or reorganize…";
		const button = section.appendChild(document.createElement("button"));
		button.type = "button";
		button.className =
			"rounded-md bg-kind-bg px-3 py-2 text-sm font-semibold text-kind-dark outline-1 outline-kind-light hover:outline-kind-default focus-visible:outline-2 disabled:opacity-50";
		button.textContent = "Revise suggestions";
		const message = section.appendChild(document.createElement("p"));
		message.setAttribute("role", "status");
		message.className = "text-sm text-base-medium";
		message.textContent =
			"Suggestions stay private to you until you save the form. No file is required.";
		button.addEventListener("click", async () => {
			if (!prompt.value.trim()) return;
			if (!(await this._isCurrent())) {
				message.textContent =
					"The form changed. Close and reopen Review before revising.";
				return;
			}
			button.disabled = true;
			try {
				const data = new FormData();
				data.set("autofill-description", prompt.value);
				data.set("form-revision", this.state.response.form_state.revision);
				data.set("operation-id", this.widget.view.operationId());
				data.set("submission", JSON.stringify(this._selectedSubmission()));
				const response = await request.post(url, data);
				if (!response?.ok) {
					message.textContent =
						response?.message ||
						response?.error ||
						"The form changed or suggestions could not be started. Your choices were kept.";
					return;
				}
				this.widget.lockDeferredOperation(response);
				renderReviewBar(this.widget, response.status);
				const manager = await this.widget.view.ensureDeferredOperations?.();
				manager?.track(response.operation, {
					node: this.widget.target,
					status: response.status,
					revision: response.revision,
				});
				message.textContent =
					"Autofill is running. You can close this review and keep editing; the bar has Cancel and will show when suggestions are ready.";
			} catch {
				message.textContent =
					"Suggestions could not be started. Your choices were kept; please try again.";
			} finally {
				button.disabled = false;
			}
		});
	}
}

/**
 * @testable false
 * @covered-by src/script/forms/revisions/reconciler.mjs::EditReconciler
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
