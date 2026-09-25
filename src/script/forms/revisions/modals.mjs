import { buttons } from "../../elements/buttons.mjs";
import { STYLES } from "../../generated/styles.mjs";
import { Modal } from "../../shared/modal.mjs";
import { request } from "../../shared/request.mjs";
import { areEqual } from "../../shared/utilities.mjs";
import { compatibleField } from "../representation.mjs";
import { renderReviewBar } from "../reviewBar.mjs";
import { loadRevisionPreview } from "./preview.mjs";

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010d_form_state_split.py::test_form_submission_reconciliation_uses_latest_schema
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_offline_submission_conflict_keeps_queue_until_choice
 * @matrix forms : latest-schema queued-conflict readonly-preview submission-choice
 * @pair forms:autofill-review
 */
export class FormRevisionModal extends Modal {
	constructor(
		reconciler,
		marker,
		widget,
		state,
		{ blockedAction = null } = {},
	) {
		super(reconciler.view, marker.querySelector("[data-role='edited-reset']"));
		this.reconciler = reconciler;
		this.marker = marker;
		this.widget = widget;
		this.state = state;
		this.blockedAction = blockedAction;
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
			(this.state.record?.renderer_schema ?? this.widget.schema ?? []).map(
				(field) => [field?.id, field],
			),
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
		if (!rendered || element.hasSubmission === false) {
			const empty = document.createElement("p");
			empty.className = "text-sm italic text-base-medium";
			empty.textContent = "Empty";
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
		const localSnapshot = this.state.record
			? (this.state.record.renderer_submission ?? {})
			: (this.widget.captureFormState().renderer_submission ?? {});
		const localSubmission = {
			...localResponse.submission,
			...localSnapshot,
		};
		const state = this.state.response.form_state ?? {};
		this.sources = [
			{
				id: "local",
				label: this.state.record ? "Queued value" : "Value in this tab",
				schema: this.state.record?.renderer_schema ?? this.widget.schema,
				submission: localSubmission,
			},
			{
				id: "server",
				label: "Latest saved value",
				schema: this.state.response.schema,
				submission: this.state.response.submission ?? {},
			},
			...(state.reviews ?? []).map((review) => ({
				id: `ai:${review.operation}`,
				label: review.private ? "Revised suggestion" : "Autofill suggestion",
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
			const reviews = state.reviews ?? [];
			const savedChangedSinceLaunch = (field) =>
				reviews.some(
					(review) =>
						review.saved_baseline &&
						!this._sameValue(
							this.sources[1].submission[field.id],
							review.saved_baseline[field.id],
							field,
						),
				);
			return fields
				.filter((field) => {
					if (!field?.id) return false;
					const suggestedChange = reviews.some(
						(review) =>
							review.fields?.includes(field.id) &&
							!this._sameValue(
								review.baseline?.[field.id],
								review.submission?.[field.id],
								field,
							),
					);
					if (suggestedChange) return true;
					if (reviews.length && !this.state.record) {
						// An existing local draft is context, not a new AI or remote value.
						const localField = this.sources[0].schema?.find(
							(item) => item.id === field.id,
						);
						const savedField = this.sources[1].schema?.find(
							(item) => item.id === field.id,
						);
						return (
							savedChangedSinceLaunch(field) ||
							!compatibleField(localField, savedField)
						);
					}
					return this.sources.some(
						(source) =>
							(!source.fields || source.fields.includes(field.id)) &&
							source.schema?.some((item) => item.id === field.id) &&
							(!this._sameValue(
								source.submission[field.id],
								this.sources[1].submission[field.id],
								field,
							) ||
								!compatibleField(
									source.schema.find((item) => item.id === field.id),
									this.sources[1].schema?.find((item) => item.id === field.id),
								)),
					);
				})
				.map((field) => ({
					id: field.id,
					label: field.title || field.label || "Untitled field",
					choices: this.sources
						.flatMap((source, index) => {
							if (source.fields && !source.fields.includes(field.id)) return [];
							if (
								source.id === "server" &&
								((reviews.length &&
									!this.state.record &&
									!savedChangedSinceLaunch(field) &&
									compatibleField(
										this.sources[0].schema?.find(
											(item) => item.id === field.id,
										),
										source.schema?.find((item) => item.id === field.id),
									)) ||
									(this._sameValue(
										source.submission[field.id],
										this.sources[0].submission[field.id],
										field,
									) &&
										compatibleField(
											this.sources[0].schema?.find(
												(item) => item.id === field.id,
											),
											source.schema?.find((item) => item.id === field.id),
										)) ||
									(!savedChangedSinceLaunch(field) &&
										this.sources.some(
											(candidate) =>
												candidate.id.startsWith("ai:") &&
												candidate.fields?.includes(field.id) &&
												this._sameValue(
													source.submission[field.id],
													candidate.submission[field.id],
													field,
												) &&
												compatibleField(
													candidate.schema?.find(
														(item) => item.id === field.id,
													),
													source.schema?.find((item) => item.id === field.id),
												),
										)))
							)
								return [];
							const definition = source.schema?.find(
								(item) => item.id === field.id,
							);
							if (!definition) return [];
							if (
								source.id.startsWith("ai:") &&
								savedChangedSinceLaunch(field) &&
								this._sameValue(
									source.submission[field.id],
									this.sources[1].submission[field.id],
									field,
								) &&
								compatibleField(
									definition,
									this.sources[1].schema?.find((item) => item.id === field.id),
								)
							)
								return [];
							if (
								source.id.startsWith("ai:") &&
								this._sameValue(
									source.baseline?.[field.id],
									source.submission[field.id],
									field,
								) &&
								this._sameValue(
									source.submission[field.id],
									this.sources[0].submission[field.id],
									field,
								) &&
								compatibleField(
									definition,
									this.sources[0].schema?.find((item) => item.id === field.id),
								)
							)
								return [];
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
								},
							];
						})
						.sort((left, right) => {
							const rank = (source) => {
								if (source === "local") return 0;
								if (source.startsWith("ai:")) return 1;
								if (source === "server") return 2;
								return 3;
							};
							return rank(left.source) - rank(right.source);
						}),
				}));
		} finally {
			previews.forEach((preview) => {
				preview?.destroy?.();
			});
		}
	}

	/**
	 * @testable false
	 * @covered-by src/script/forms/revisions/modals.mjs::FormRevisionModal
	 * @reason empty controls and absent saved values have the same displayed meaning
	 */
	_sameValue(left, right, field = null) {
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
			if (
				field?.type === "input" &&
				field.input === "number" &&
				(typeof value === "string" || typeof value === "number") &&
				Number.isFinite(Number(value))
			)
				return Number(value);
			return value;
		};
		return areEqual(comparable(left), comparable(right));
	}

	/**
	 * @testable false
	 * @covered-by src/script/forms/revisions/modals.mjs::FormRevisionModal
	 * @reason private per-field choice composition is part of the reconciliation modal
	 */
	_choice(field, { source, label, compatible, value }) {
		const button = document.createElement(compatible ? "button" : "div");
		if (compatible) {
			button.type = "button";
			button.setAttribute("role", "radio");
			button.setAttribute(
				"aria-checked",
				(source === this.selections.get(field.id)).toString(),
			);
		} else button.dataset.role = "incompatible-value";
		button.setAttribute("aria-label", `${label} for ${field.label}`);
		button.dataset.revisionSource = source;
		button.className =
			"min-w-0 rounded-md border border-base-light/50 bg-white p-3 text-left transition-colors hover:bg-base-bg aria-checked:bg-kind-bg aria-checked:outline-2 aria-checked:outline-kind-default";

		const heading = button.appendChild(document.createElement("span"));
		heading.className = "mb-2 block text-xs font-semibold text-base-medium";
		heading.textContent = label;
		button.appendChild(value);
		if (!compatible) {
			const explanation = button.appendChild(document.createElement("p"));
			explanation.className = "mt-2 text-xs text-base-medium";
			explanation.textContent =
				"This field changed type or was removed. Keep this earlier value for reference and re-enter it in the updated form if needed.";
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
		const local = this.state.record
			? this.widget.buildLocalRevision(this.state.response, this.state.record)
			: this.widget.buildLocalRevision(this.state.response);
		const differences = await this._differences(local.response);
		if (!differences.length && !this.state.response.form_state) return false;
		const noNewAutofillValues =
			!differences.length &&
			!this.blockedAction &&
			!this.state.record &&
			!!this.state.response.form_state?.reviews?.length;
		const saved = this.sources[1];
		// An AI value can depend on a different saved field, so a post-launch
		// context edit makes every proposal opt-in, not only the edited field.
		const savedContextChanged =
			this.state.response.form_state?.reviews?.some((review) => {
				if (!review.saved_baseline) return false;
				const fields = new Map(
					[...(review.schema ?? []), ...(saved.schema ?? [])]
						.filter((field) => field?.id)
						.map((field) => [field.id, field]),
				);
				return [...fields.values()].some(
					(field) =>
						!this._sameValue(
							saved.submission[field.id],
							review.saved_baseline[field.id],
							field,
						),
				);
			}) ?? false;
		for (const field of differences) {
			const localChoice = field.choices.find(
				(choice) => choice.source === "local" && choice.compatible,
			);
			const serverChoice = field.choices.find(
				(choice) => choice.source === "server" && choice.compatible,
			);
			const aiChoice = field.choices.findLast(
				(choice) => choice.compatible && choice.source.startsWith("ai:"),
			);
			const baseline = this.widget._baselineSubmission;
			const changedLocally =
				this.state.record ||
				(baseline &&
					!this._sameValue(
						this.sources[0].submission[field.id] ?? null,
						baseline[field.id] ?? null,
						field,
					));
			let defaultSource =
				aiChoice?.source ?? serverChoice?.source ?? localChoice?.source;
			if (savedContextChanged)
				defaultSource =
					serverChoice?.source ??
					(localChoice?.compatible ? "local" : defaultSource);
			if (localChoice?.compatible && changedLocally) defaultSource = "local";
			if (defaultSource) this.selections.set(field.id, defaultSource);
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
		title.textContent =
			this.blockedAction === "autofill"
				? "Review changes before autofill"
				: noNewAutofillValues
					? "Autofill is complete"
					: "Choose form values";
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
			this.blockedAction === "autofill"
				? "Autofill did not start because the saved form changed. Choose which values to keep, then select Use selected values and start Autofill again. Use Update first if you want to save your choices."
				: noNewAutofillValues
					? "No new form values were suggested. Keep your current values or revise the result below. Use Update afterward to acknowledge this review."
					: "Choose the values to keep. This updates your open form only; use Update afterward to save. Earlier values whose field type changed are shown for reference.";
		if (
			differences.some((field) =>
				field.choices.some((choice) => !choice.compatible),
			)
		)
			intro.textContent +=
				" Applying these choices drops incompatible draft values from the updated form. Copy any earlier values you need before continuing.";
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
				...field.choices.map((choice) => this._choice(field, choice)),
			);
		}
		if (!differences.length && !noNewAutofillValues) {
			const noChanges = fields.appendChild(document.createElement("p"));
			noChanges.textContent =
				"The available values already match. You can revise them with a prompt below.";
		}
		this._refinement(body);
		const actions = body.appendChild(document.createElement("div"));
		actions.className = "flex w-full";
		const updateAction = buttons.active({
			type: "button",
			text: noNewAutofillValues ? "Keep current values" : "Use selected values",
			processingText: "Applying values…",
		});
		const update = actions.appendChild(updateAction.element);

		update.addEventListener("click", async () => {
			updateAction.activate();
			try {
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
			} finally {
				updateAction.deactivate();
			}
		});

		await super.attach(modal, this.widget.component);
		update.focus();
		return true;
	}

	/** @testable infrastructure */
	_selectedSubmission() {
		const review = this.state.response.form_state ?? {};
		const preserveTabDraft = !this.state.record && review.reviews?.length;
		const submission = structuredClone(
			preserveTabDraft
				? this.sources[0].submission
				: (this.state.response.submission ?? {}),
		);
		for (const [id, sourceId] of this.selections) {
			const source = this.sources.find(
				(candidate) => candidate.id === sourceId,
			);
			if (
				!compatibleField(
					source?.schema?.find((field) => field.id === id),
					this.state.response.schema?.find((field) => field.id === id),
				)
			)
				continue;
			if (Object.hasOwn(source?.submission ?? {}, id))
				submission[id] = structuredClone(source.submission[id]);
			else delete submission[id];
		}
		const currentIds = new Set(
			(this.state.response.schema ?? []).map((field) => field.id),
		);
		return Object.fromEntries(
			Object.entries(submission).filter(([id]) => currentIds.has(id)),
		);
	}

	/** @testable infrastructure */
	_refinement(body) {
		const url = this.state.response.form_state?.refine_url;
		if (
			!url ||
			this.state.record ||
			!this.state.response.form_state?.reviews?.length
		)
			return;
		const section = body.appendChild(document.createElement("section"));
		section.className = "space-y-2";
		const label = section.appendChild(document.createElement("label"));
		label.className = "block text-sm font-semibold";
		label.append("Revise these values");
		const prompt = label.appendChild(document.createElement("textarea"));
		prompt.setAttribute("aria-label", "Revise these values with AI");
		prompt.className =
			"mt-2 block w-full rounded-md border border-base-light p-2 text-sm";
		prompt.placeholder = "Describe what to add, correct, or reorganize…";
		const reviseAction = buttons.active({
			type: "button",
			icon: "generate",
			text: "Revise suggestions",
			processingText: "Revising suggestions…",
			style: `${STYLES.button.submit} review-revise-action`,
		});
		const button = section.appendChild(reviseAction.element);
		button.setAttribute("aria-label", "Revise suggestions with AI");
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
			reviseAction.activate();
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
				await this.remove();
			} catch {
				message.textContent =
					"Suggestions could not be started. Your choices were kept; please try again.";
			} finally {
				reviseAction.deactivate();
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
